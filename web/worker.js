// Worker Umnia : sert l'application (fichiers statiques) et l'API /api/*
// (connexion, tâches partagées par agence, administration). Données : base D1 « DB ».
// Le moteur d'analyse reste dans le navigateur ; ne sont stockés ici que les comptes
// et les tâches (paramètres + plan classé par l'agent).

import {HttpError, adserverStatus, client} from "./adserver.js";
import {evaluate, mergeAlerts, mailText} from "./quality.js";
import {ASSISTANT_RULES, ASSISTANT_GUIDE} from "./assistant_guide.js";

const SESSION_HOURS = 12;
const PBKDF2_ITERATIONS = 10000;      // offre gratuite : ~10 ms de CPU par requête
const MAX_FAILURES = 5, FAILURE_WINDOW = 300;   // anti-force brute : 5 essais / 5 min / IP
const MAX_TASK_BYTES = 900_000;

const SCHEMA = [
  `CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL,
     name TEXT NOT NULL, agency_id TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user',
     pw_hash TEXT NOT NULL, pw_salt TEXT NOT NULL, created REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS login_failures (ip TEXT NOT NULL, ts REAL NOT NULL)`,
  `CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, mode TEXT NOT NULL, name TEXT NOT NULL,
     advertiser TEXT, adserver TEXT, campaign TEXT, agency_id TEXT NOT NULL, owner_id INTEGER NOT NULL,
     owner_name TEXT, status TEXT NOT NULL DEFAULT 'brouillon', data TEXT, created REAL NOT NULL,
     updated REAL NOT NULL)`,
  `CREATE INDEX IF NOT EXISTS tasks_agency ON tasks (agency_id, updated)`,
  // Carnet d'adresses des régies (proposé lors de la programmation des reports)
  `CREATE TABLE IF NOT EXISTS contacts (agency_id TEXT NOT NULL, site TEXT NOT NULL, email TEXT NOT NULL,
     updated REAL NOT NULL, PRIMARY KEY (agency_id, site, email))`,
  // Réglages partagés par l'agence (correspondance des régies, vues enregistrées du tableau croisé)
  `CREATE TABLE IF NOT EXISTS agency_settings (agency_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
     updated REAL NOT NULL, PRIMARY KEY (agency_id, key))`,
  // Assistant d'aide : nombre de questions et jetons par utilisateur et par jour (plafond, suivi du coût)
  `CREATE TABLE IF NOT EXISTS assistant_usage (user_id INTEGER NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL,
     tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, PRIMARY KEY (user_id, day))`,
];
const SETTING_KEYS = new Set(["site_map", "pivot_views", "advertisers", "report_templates", "requests", "corrections", "client_rules",
                              "monitors", "alerts", "alert_thresholds"]);
// Réglages que seul un administrateur modifie (demandes d'ajout et corrections retenues : ouvertes à tous)
const ADMIN_SETTING_KEYS = new Set(["advertisers", "report_templates", "client_rules", "alert_thresholds"]);
const MAX_SETTING_BYTES = 200_000;
const BIG_SETTINGS = {monitors: 900_000, alerts: 400_000};   // instantanés des campagnes surveillées
const MONITOR_EVERY = 5 * 3600;                               // une vérification toutes les ~6 h (déclencheur)
const EMAIL = /^[^\s@<>,;]+@[^\s@<>,;]+\.[a-z]{2,}$/i;
let schemaReady = false;

async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

const now = () => Date.now() / 1000;
const today = () => new Date().toISOString().slice(0, 10);
const dailyQuota = (env) => Number(env.ASSISTANT_DAILY_LIMIT) || 60;
const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), {status, headers: {"content-type": "application/json; charset=utf-8",
    "cache-control": "no-store", ...headers}});
const fail = (message, status = 400) => json({error: message}, status);

function b64(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s);
}
function randomToken(n = 32) {
  return b64(crypto.getRandomValues(new Uint8Array(n))).replace(/[+/=]/g, "").slice(0, 43);
}
async function hashPassword(password, saltB64) {
  const salt = saltB64 ? Uint8Array.from(atob(saltB64), (c) => c.charCodeAt(0)) : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({name: "PBKDF2", hash: "SHA-256", salt, iterations: PBKDF2_ITERATIONS}, key, 256);
  return {hash: b64(bits), salt: b64(salt)};
}
function sameString(a, b) {           // comparaison en temps constant
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
function cookie(token, maxAge) {
  return `trf_session=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}
function readCookie(request) {
  const m = (request.headers.get("cookie") || "").match(/(?:^|;\s*)trf_session=([A-Za-z0-9]+)/);
  return m ? m[1] : "";
}
const publicUser = (u) => u && {id: u.id, email: u.email, name: u.name, agency_id: u.agency_id, role: u.role};
const clean = (v, max = 200) => String(v ?? "").trim().slice(0, max);

async function currentUser(db, request) {
  const token = readCookie(request);
  if (!token) return null;
  return db.prepare(`SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                     WHERE s.token = ? AND s.expires > ?`).bind(token, now()).first();
}

async function body(request) {
  try { return await request.json(); } catch { return {}; }
}

// --- Routes ---------------------------------------------------------------------------

async function api(request, env, url) {
  const db = env.DB;
  if (!db) return fail("Base de données non configurée (liaison D1 « DB »).", 503);
  await ensureSchema(db);
  const path = url.pathname.replace(/\/+$/, "");
  const method = request.method;
  const ip = request.headers.get("CF-Connecting-IP") || "local";

  // Premier lancement : création du compte administrateur
  if (path === "/api/setup" && method === "POST") {
    const count = await db.prepare("SELECT COUNT(*) AS n FROM users").first();
    if (count.n > 0) return fail("Déjà configuré.", 403);
    const b = await body(request);
    // Clé d'installation : le secret TRAFFICKER_PASSWORD du Worker (personne d'autre ne
    // peut créer le premier administrateur sur le site en ligne)
    if (env.TRAFFICKER_PASSWORD && !sameString(String(b.setup_key || ""), env.TRAFFICKER_PASSWORD))
      return fail("Clé d'installation incorrecte.", 403);
    if (!b.email || !b.password || String(b.password).length < 10) return fail("E-mail et mot de passe (10 caractères min.) requis.");
    const {hash, salt} = await hashPassword(String(b.password));
    await db.prepare(`INSERT INTO users (email, name, agency_id, role, pw_hash, pw_salt, created)
                      VALUES (?, ?, ?, 'admin', ?, ?, ?)`)
      .bind(clean(b.email).toLowerCase(), clean(b.name) || clean(b.email), clean(b.agency_id) || "agence", hash, salt, now()).run();
    return json({ok: true});
  }

  if (path === "/api/login" && method === "POST") {
    const fails = await db.prepare("SELECT COUNT(*) AS n FROM login_failures WHERE ip = ? AND ts > ?")
      .bind(ip, now() - FAILURE_WINDOW).first();
    if (fails.n >= MAX_FAILURES) return fail("Trop d'essais, réessayez dans 5 minutes.", 429);
    const b = await body(request);
    const user = await db.prepare("SELECT * FROM users WHERE email = ?").bind(clean(b.email).toLowerCase()).first();
    const ok = user && sameString((await hashPassword(String(b.password || ""), user.pw_salt)).hash, user.pw_hash);
    if (!ok) {
      await db.prepare("INSERT INTO login_failures (ip, ts) VALUES (?, ?)").bind(ip, now()).run();
      return fail("Identifiants incorrects.", 401);
    }
    const token = randomToken();
    await db.batch([
      db.prepare("DELETE FROM sessions WHERE expires < ?").bind(now()),
      db.prepare("DELETE FROM login_failures WHERE ip = ? OR ts < ?").bind(ip, now() - 3600),
      db.prepare("INSERT INTO sessions (token, user_id, expires) VALUES (?, ?, ?)")
        .bind(token, user.id, now() + SESSION_HOURS * 3600),
    ]);
    return json({user: publicUser(user)}, 200, {"set-cookie": cookie(token, SESSION_HOURS * 3600)});
  }

  if (path === "/api/logout" && method === "POST") {
    const token = readCookie(request);
    if (token) await db.prepare("DELETE FROM sessions WHERE token = ?").bind(token).run();
    return json({ok: true}, 200, {"set-cookie": cookie("x", 0)});
  }

  const user = await currentUser(db, request);
  if (path === "/api/me") {
    if (user) return json({user: publicUser(user)});
    const count = await db.prepare("SELECT COUNT(*) AS n FROM users").first();
    return json({user: null, setup: count.n === 0}, 401);
  }
  if (!user) return fail("Authentification requise.", 401);

  // --- Tâches : visibles par les membres de la même agence ---
  if (path === "/api/tasks" && method === "GET") {
    const scope = url.searchParams.get("scope") === "agency" ? "agency" : "mine";
    const mode = url.searchParams.get("mode") === "reporting" ? "reporting" : "trafficking";
    const q = `%${clean(url.searchParams.get("q"), 100)}%`;
    const where = scope === "mine" ? "owner_id = ?" : "agency_id = ?";
    const rows = await db.prepare(`SELECT id, mode, name, advertiser, adserver, campaign, agency_id, owner_name,
                                   status, created, updated FROM tasks WHERE ${where} AND mode = ?
                                   AND (name LIKE ? OR advertiser LIKE ? OR campaign LIKE ?)
                                   ORDER BY updated DESC LIMIT 100`)
      .bind(scope === "mine" ? user.id : user.agency_id, mode, q, q, q).all();
    return json({tasks: rows.results});
  }
  if (path === "/api/tasks" && method === "POST") {
    const b = await body(request);
    if (!clean(b.name)) return fail("Nom de la tâche requis.");
    const id = randomToken(12);
    const t = now();
    await db.prepare(`INSERT INTO tasks (id, mode, name, advertiser, adserver, campaign, agency_id, owner_id,
                      owner_name, status, data, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'brouillon', '{}', ?, ?)`)
      .bind(id, b.mode === "reporting" ? "reporting" : "trafficking", clean(b.name), clean(b.advertiser),
            b.adserver === "adform" ? "adform" : "cm360", clean(b.campaign),
            user.role === "admin" && clean(b.agency_id) ? clean(b.agency_id) : user.agency_id,
            user.id, user.name, t, t).run();
    return json({id});
  }
  const m = path.match(/^\/api\/tasks\/([A-Za-z0-9]+)$/);
  if (m) {
    const task = await db.prepare("SELECT * FROM tasks WHERE id = ?").bind(m[1]).first();
    if (!task || (task.agency_id !== user.agency_id && task.owner_id !== user.id)) return fail("Tâche introuvable.", 404);
    if (method === "GET") return json({task: {...task, data: JSON.parse(task.data || "{}")}});
    if (method === "PUT") {
      const b = await body(request);
      const data = JSON.stringify(b.data ?? JSON.parse(task.data || "{}"));
      if (data.length > MAX_TASK_BYTES) return fail("Tâche trop volumineuse.", 413);
      await db.prepare(`UPDATE tasks SET name = ?, advertiser = ?, adserver = ?, campaign = ?, status = ?,
                        data = ?, updated = ? WHERE id = ?`)
        .bind(clean(b.name ?? task.name), clean(b.advertiser ?? task.advertiser),
              (b.adserver ?? task.adserver) === "adform" ? "adform" : "cm360", clean(b.campaign ?? task.campaign),
              clean(b.status ?? task.status, 40), data, now(), task.id).run();
      return json({ok: true});
    }
    if (method === "DELETE") {
      if (task.owner_id !== user.id && user.role !== "admin") return fail("Seul l'auteur peut supprimer.", 403);
      await db.prepare("DELETE FROM tasks WHERE id = ?").bind(task.id).run();
      return json({ok: true});
    }
  }

  // --- Ad servers (CM360 / Adform) : les clés restent dans les secrets du Worker ---
  if (path.startsWith("/api/adserver/")) {
    const q = url.searchParams;
    const b = method === "POST" || method === "PUT" ? await body(request) : {};
    const adserver = (b.adserver || q.get("adserver")) === "adform" ? "adform" : "cm360";
    const route = path.slice("/api/adserver/".length);
    try {
      if (route === "status") return json({...adserverStatus(env), mail: !!(env.RESEND_API_KEY && env.MAIL_FROM)});
      // Diagnostic de connexion (administrateurs) : jeton puis lecture des annonceurs
      if (route === "diagnostic") {
        if (user.role !== "admin") return fail("Réservé aux administrateurs.", 403);
        const t0 = Date.now();
        try {
          const list = await client(adserver, env).advertisers("");
          return json({ok: true, adserver, advertisers: list.length, sample: list.slice(0, 5).map((a) => a.name), ms: Date.now() - t0});
        } catch (e) {
          return json({ok: false, adserver, error: e.message, ms: Date.now() - t0});
        }
      }
      const c = client(adserver, env);
      if (route === "advertisers") return json({advertisers: await c.advertisers(clean(q.get("q"), 100))});
      if (route === "sites") return json({adserver, sites: await c.sites(clean(q.get("q"), 100))});
      if (route === "campaigns") return json({campaigns: await c.campaigns(clean(q.get("advertiser_id"), 40), clean(q.get("q"), 100))});
      if (route === "placements") return json(await c.placements(clean(q.get("campaign_id"), 40)));
      if (route === "delivery" && method === "POST") return json(await c.delivery(clean(b.campaign_id, 40)));
      if (route === "delivery" && method === "GET") return json(await c.deliveryFile(clean(q.get("report_id"), 40), clean(q.get("file_id"), 40)));
      const sm = route.match(/^schedule(?:\/([A-Za-z0-9_-]+))?$/);
      if (sm && method === "DELETE" && sm[1]) return json(await c.deleteSchedule(sm[1]));
      if (sm && (method === "POST" || method === "PUT")) {
        const emails = [].concat(b.emails || []).map((e) => clean(e, 120).toLowerCase()).filter(Boolean);
        if (!emails.length || emails.length > 20 || !emails.every((e) => EMAIL.test(e))) return fail("E-mail(s) de la régie invalide(s).");
        const sc = b.schedule || {};
        if (!/^\d{4}-\d{2}-\d{2}$/.test(sc.start || "") || !/^\d{4}-\d{2}-\d{2}$/.test(sc.end || "") || sc.start > sc.end)
          return fail("Dates du calendrier invalides.");
        const site = {id: clean(b.site && b.site.id, 40), name: clean(b.site && b.site.name, 200)};
        const sched = {
          frequency: ["daily", "weekly", "monthly"].includes(sc.frequency) ? sc.frequency : "weekly",
          weekdays: [].concat(sc.weekdays || []).filter((d) => /^[A-Z]+DAY$/.test(d)), range: sc.range === "period" ? "period" : "cumul",
          start: sc.start, end: sc.end, message: clean(sc.message, 1000)};
        if (method === "POST" && !sm[1]) return json(await c.schedule(clean(b.campaign_id, 40), site, emails, sched));
        if (method === "PUT" && sm[1])
          return json(await c.updateSchedule(sm[1], clean(b.campaign_id, 40), site, emails, sched, b.active !== false));
      }
    } catch (e) {
      if (e instanceof HttpError) return fail(e.message, e.status);
      throw e;
    }
    return fail("Route inconnue.", 404);
  }

  // --- Carnet d'adresses des régies (par agence) ---
  const sk = path.match(/^\/api\/settings\/([a-z_]+)$/);
  if (sk) {
    if (!SETTING_KEYS.has(sk[1])) return fail("Réglage inconnu.", 404);
    if (method === "GET") {
      const row = await db.prepare("SELECT value FROM agency_settings WHERE agency_id = ? AND key = ?").bind(user.agency_id, sk[1]).first();
      return json({value: row ? JSON.parse(row.value) : null});
    }
    if (method === "PUT") {
      if (ADMIN_SETTING_KEYS.has(sk[1]) && user.role !== "admin") return fail("Réservé aux administrateurs.", 403);
      const b = await body(request);
      const value = JSON.stringify(b.value ?? null);
      if (value.length > (BIG_SETTINGS[sk[1]] || MAX_SETTING_BYTES)) return fail("Réglage trop volumineux.", 413);
      await db.prepare(`INSERT INTO agency_settings (agency_id, key, value, updated) VALUES (?, ?, ?, ?)
        ON CONFLICT (agency_id, key) DO UPDATE SET value = excluded.value, updated = excluded.updated`)
        .bind(user.agency_id, sk[1], value, now()).run();
      return json({ok: true});
    }
  }

  // --- Contrôles avant mise en ligne : les URL de destination répondent-elles ? ---
  if (path === "/api/urlcheck" && method === "POST") {
    const b = await body(request);
    const urls = [...new Set([].concat(b.urls || []).map((u) => String(u || "").trim()).filter((u) => u && u.length <= 2000))].slice(0, 60);
    const out = [];
    for (let i = 0; i < urls.length; i += 6) out.push(...await Promise.all(urls.slice(i, i + 6).map((u) => checkUrl(u, env))));
    return json({results: out});
  }

  // --- Surveillance : e-mail des nouvelles alertes (destinataires : comptes de l'agence) ---
  if (path === "/api/alerts/notify" && method === "POST") {
    const b = await body(request);
    const monitors = (await getSetting(db, user.agency_id, "monitors")) || [];
    const alerts = (await getSetting(db, user.agency_id, "alerts")) || [];
    const m = monitors.find((x) => x.id === String(b.monitor_id || ""));
    if (!m) return fail("Surveillance introuvable.", 404);
    const ids = new Set([].concat(b.alert_ids || []).map(String));
    const fresh = alerts.filter((a) => ids.has(a.id) && a.monitor_id === m.id && a.status === "open" && !a.emailed);
    if (!fresh.length) return json({sent: false, reason: "Rien de nouveau."});
    const res = await mailAlerts(env, db, user.agency_id, m, fresh);
    if (res.sent) {
      for (const a of fresh) a.emailed = now();
      await putSetting(db, user.agency_id, "alerts", alerts);
    }
    return json(res);
  }

  // --- Assistant d'aide (Claude, clé Umnia) : guide l'utilisateur, sans accès aux tâches ni aux données ---
  if (path === "/api/assistant/status" && method === "GET") {
    const used = await db.prepare("SELECT n FROM assistant_usage WHERE user_id = ? AND day = ?").bind(user.id, today()).first();
    return json({enabled: !!env.ANTHROPIC_API_KEY, remaining: Math.max(0, dailyQuota(env) - (used ? used.n : 0))});
  }
  if (path === "/api/assistant" && method === "POST") {
    if (!env.ANTHROPIC_API_KEY) return fail("Assistant non configuré (secret ANTHROPIC_API_KEY du Worker).", 503);
    const b = await body(request);
    const msgs = Array.isArray(b.messages) ? b.messages.slice(-20) : [];
    const ok = msgs.length && msgs.every((m, i) => ["user", "assistant"].includes(m.role) && typeof m.content === "string"
      && m.content.trim() && m.content.length <= 4000 && (i === msgs.length - 1 ? m.role === "user" : true))
      && msgs[0].role === "user" && msgs.every((m, i) => i === 0 || m.role !== msgs[i - 1].role);
    if (!ok) return fail("Conversation invalide.");
    const used = await db.prepare("SELECT n FROM assistant_usage WHERE user_id = ? AND day = ?").bind(user.id, today()).first();
    if ((used ? used.n : 0) >= dailyQuota(env)) return fail("Limite de questions atteinte pour aujourd'hui.", 429);
    const screen = clean(b.screen, 120);
    const messages = msgs.map((m, i) => ({role: m.role, content: i === msgs.length - 1 && screen ? `[Écran : ${screen}]\n${m.content}` : m.content}));
    let r;
    try {
      r = await fetch((env.ANTHROPIC_BASE_URL || "https://api.anthropic.com") + "/v1/messages", {method: "POST",
        headers: {"x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                  "anthropic-beta": "server-side-fallback-2026-07-01", "content-type": "application/json"},
        body: JSON.stringify({model: env.ASSISTANT_MODEL || "claude-opus-5-5", max_tokens: 4000,
          output_config: {effort: "low"}, fallbacks: "default",
          system: [{type: "text", text: ASSISTANT_RULES + "\n\n" + ASSISTANT_GUIDE, cache_control: {type: "ephemeral"}}],
          messages})});
    } catch (e) {
      return fail("Assistant injoignable, réessayez dans un instant.", 502);
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = r.status === 401 || r.status === 403 ? "Clé de l'assistant refusée : prévenez l'administrateur."
        : r.status === 429 || r.status === 529 || r.status >= 500 ? "Assistant surchargé, réessayez dans un instant."
        : "Question refusée par l'assistant.";
      return fail(msg, r.status === 429 || r.status >= 500 ? 503 : 502);
    }
    const u = d.usage || {};
    const tin = (u.input_tokens || 0) + (u.cache_creation_input_tokens || 0) + (u.cache_read_input_tokens || 0);
    await db.prepare(`INSERT INTO assistant_usage (user_id, day, n, tokens_in, tokens_out) VALUES (?, ?, 1, ?, ?)
      ON CONFLICT (user_id, day) DO UPDATE SET n = n + 1, tokens_in = tokens_in + excluded.tokens_in, tokens_out = tokens_out + excluded.tokens_out`)
      .bind(user.id, today(), tin, u.output_tokens || 0).run();
    if (d.stop_reason === "refusal") return json({answer: "Je ne peux pas répondre à cette demande. Posez-moi une question sur l'utilisation d'Umnia."});
    const answer = (d.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n").trim();
    return json({answer: answer || "Je n'ai pas de réponse : reformulez votre question.",
                 truncated: d.stop_reason === "max_tokens"});
  }

  // Vérification immédiate des campagnes surveillées (administrateurs ; sinon toutes les ~6 h)
  if (path === "/api/monitors/run" && method === "POST") {
    if (user.role !== "admin") return fail("Réservé aux administrateurs.", 403);
    return json({runs: (await runMonitors(env, true)).filter((r) => r.agency === user.agency_id)});
  }

  if (path === "/api/contacts" && method === "GET") {
    const rows = await db.prepare("SELECT site, email FROM contacts WHERE agency_id = ? ORDER BY site, updated DESC")
      .bind(user.agency_id).all();
    return json({contacts: rows.results});
  }
  if (path === "/api/contacts" && method === "POST") {
    const b = await body(request);
    const site = clean(b.site, 200);
    const emails = [].concat(b.emails || []).map((e) => clean(e, 120).toLowerCase()).filter((e) => EMAIL.test(e)).slice(0, 20);
    if (!site || !emails.length) return fail("Régie et e-mail requis.");
    await db.batch(emails.map((e) => db.prepare(`INSERT INTO contacts (agency_id, site, email, updated) VALUES (?, ?, ?, ?)
      ON CONFLICT (agency_id, site, email) DO UPDATE SET updated = excluded.updated`).bind(user.agency_id, site, e, now())));
    return json({ok: true});
  }

  // --- Administration (rôle admin) ---
  if (path === "/api/users") {
    if (user.role !== "admin") return fail("Réservé aux administrateurs.", 403);
    if (method === "GET") {
      const rows = await db.prepare("SELECT id, email, name, agency_id, role, created FROM users ORDER BY agency_id, name").all();
      return json({users: rows.results});
    }
    if (method === "POST") {
      const b = await body(request);
      if (!b.email || !b.password || String(b.password).length < 10) return fail("E-mail et mot de passe (10 caractères min.) requis.");
      const {hash, salt} = await hashPassword(String(b.password));
      try {
        await db.prepare(`INSERT INTO users (email, name, agency_id, role, pw_hash, pw_salt, created) VALUES (?, ?, ?, ?, ?, ?, ?)`)
          .bind(clean(b.email).toLowerCase(), clean(b.name) || clean(b.email), clean(b.agency_id) || user.agency_id,
                b.role === "admin" ? "admin" : "user", hash, salt, now()).run();
      } catch {
        return fail("Cet e-mail existe déjà.", 409);
      }
      return json({ok: true});
    }
  }
  const um = path.match(/^\/api\/users\/(\d+)$/);
  if (um && method === "DELETE") {
    if (user.role !== "admin") return fail("Réservé aux administrateurs.", 403);
    if (Number(um[1]) === user.id) return fail("Impossible de supprimer son propre compte.");
    await db.batch([db.prepare("DELETE FROM sessions WHERE user_id = ?").bind(Number(um[1])),
                    db.prepare("DELETE FROM users WHERE id = ?").bind(Number(um[1]))]);
    return json({ok: true});
  }
  if (path === "/api/password" && method === "POST") {
    const b = await body(request);
    const ok = sameString((await hashPassword(String(b.current || ""), user.pw_salt)).hash, user.pw_hash);
    if (!ok) return fail("Mot de passe actuel incorrect.", 403);
    if (String(b.password || "").length < 10) return fail("10 caractères minimum.");
    const {hash, salt} = await hashPassword(String(b.password));
    await db.prepare("UPDATE users SET pw_hash = ?, pw_salt = ? WHERE id = ?").bind(hash, salt, user.id).run();
    return json({ok: true});
  }
  return fail("Route inconnue.", 404);
}

// --- Outils : réglages d'agence, e-mail, vérification d'URL, surveillance programmée ---
async function getSetting(db, agency, key) {
  const row = await db.prepare("SELECT value FROM agency_settings WHERE agency_id = ? AND key = ?").bind(agency, key).first();
  return row ? JSON.parse(row.value) : null;
}
async function putSetting(db, agency, key, value) {
  await db.prepare(`INSERT INTO agency_settings (agency_id, key, value, updated) VALUES (?, ?, ?, ?)
    ON CONFLICT (agency_id, key) DO UPDATE SET value = excluded.value, updated = excluded.updated`)
    .bind(agency, key, JSON.stringify(value), now()).run();
}

// E-mail via Resend (secrets RESEND_API_KEY et MAIL_FROM) ; sans secret : alertes dans la cloche seulement
export async function sendMail(env, to, subject, text) {
  if (!env.RESEND_API_KEY || !env.MAIL_FROM) return {sent: false, reason: "E-mail non configuré (secrets RESEND_API_KEY / MAIL_FROM)."};
  const r = await fetch(env.RESEND_URL || "https://api.resend.com/emails", {method: "POST",
    headers: {authorization: "Bearer " + env.RESEND_API_KEY, "content-type": "application/json"},
    body: JSON.stringify({from: env.MAIL_FROM, to, subject, text})});
  return r.ok ? {sent: true, to} : {sent: false, reason: `Envoi refusé (${r.status}).`};
}
// Destinataires limités aux comptes de l'agence (pas d'envoi vers une adresse extérieure)
async function mailAlerts(env, db, agency, monitor, alerts) {
  const users = (await db.prepare("SELECT email FROM users WHERE agency_id = ?").bind(agency).all()).results.map((u) => u.email.toLowerCase());
  const to = [...new Set([].concat(monitor.emails || []).map((e) => String(e).toLowerCase()))].filter((e) => users.includes(e)).slice(0, 20);
  if (!to.length) return {sent: false, reason: "Aucun destinataire de l'agence."};
  const c = monitor.campaign || {};
  return sendMail(env, to, `Umnia · ${alerts.length} alerte(s) · ${c.name || "campagne"}`, mailText(monitor, alerts));
}

const PRIVATE_HOST = /^(localhost|.*\.local|.*\.localhost|.*\.internal|0\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|127\.\d+\.\d+\.\d+|169\.254\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+|\[.*\])$/i;
async function checkUrl(raw, env) {
  const t0 = Date.now();
  let url = raw, hops = 0;
  try {
    for (;;) {
      const u = new URL(url);
      if (!/^https?:$/.test(u.protocol) || u.username || u.password) return {url: raw, error: "Adresse non autorisée."};
      if (PRIVATE_HOST.test(u.hostname) && env.URLCHECK_ALLOW_LOCAL !== "1") return {url: raw, error: "Adresse interne refusée."};
      const ctl = new AbortController(), timer = setTimeout(() => ctl.abort(), 8000);
      let r;
      try {
        r = await fetch(u.toString(), {method: "GET", redirect: "manual", signal: ctl.signal,
                                       headers: {"user-agent": "Umnia-URL-check/1.0", accept: "text/html,*/*"}});
      } finally { clearTimeout(timer); }
      try { await r.body?.cancel(); } catch { /* corps déjà lu */ }
      const loc = r.headers.get("location");
      if (r.status >= 300 && r.status < 400 && loc && hops < 5) { url = new URL(loc, u).toString(); hops++; continue; }
      return {url: raw, status: r.status, final: url, hops, ms: Date.now() - t0};
    }
  } catch (e) {
    return {url: raw, error: e.name === "AbortError" ? "Pas de réponse en 8 s." : "Injoignable (" + (e.message || e) + ")", ms: Date.now() - t0};
  }
}

// Déclencheur (cron) : campagnes surveillées connectées à un ad server, toutes les ~6 h
export async function runMonitors(env, force = false) {
  const db = env.DB;
  await ensureSchema(db);
  const rows = (await db.prepare("SELECT agency_id, value FROM agency_settings WHERE key = 'monitors'").all()).results;
  const done = [];
  for (const row of rows) {
    const monitors = JSON.parse(row.value || "[]");
    let alerts = (await getSetting(db, row.agency_id, "alerts")) || [];
    const thresholds = (await getSetting(db, row.agency_id, "alert_thresholds")) || {};
    let changed = false;
    for (const m of monitors) {
      if (!m.active || !m.live || (!force && now() - (m.last_run || 0) < MONITOR_EVERY)) continue;
      changed = true;
      try {
        const c = client(m.adserver, env);
        const {campaign, placements} = await c.placements(m.campaign.id);
        const r = m.pending ? await c.deliveryFile(m.pending.report_id, m.pending.file_id) : await c.delivery(m.campaign.id);
        if (r.pending) { m.pending = r.pending; continue; }       // rapport CM360 en cours : repris au prochain passage
        delete m.pending;
        m.campaign = {...m.campaign, ...campaign};
        m.placements = placements;
        const {alerts: found, stats} = evaluate({campaign: m.campaign, placements, delivery: r.delivery, targets: m.targets,
                                                regie: m.regie, thresholds});
        const merged = mergeAlerts(alerts, m, found);
        alerts = merged.list;
        Object.assign(m, {last_run: now(), last_error: "", stats});
        if (merged.fresh.length) {
          const res = await mailAlerts(env, db, row.agency_id, m, merged.fresh);
          if (res.sent) for (const a of merged.fresh) a.emailed = now();
          m.last_mail = res.sent ? now() : m.last_mail;
        }
        done.push({agency: row.agency_id, monitor: m.id, alerts: found.length, fresh: merged.fresh.length});
      } catch (e) {
        Object.assign(m, {last_run: now(), last_error: String(e.message || e).slice(0, 300)});
      }
    }
    if (changed) {
      await putSetting(db, row.agency_id, "monitors", monitors);
      await putSetting(db, row.agency_id, "alerts", alerts);
    }
  }
  return done;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(runMonitors(env));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      // Requêtes d'écriture : même origine uniquement (protection CSRF)
      const origin = request.headers.get("origin");
      if (request.method !== "GET" && origin && origin !== url.origin) return fail("Origine refusée.", 403);
      try {
        return await api(request, env, url);
      } catch (e) {
        return fail("Erreur serveur : " + (e && e.message || e), 500);
      }
    }
    return env.ASSETS.fetch(request);
  },
};

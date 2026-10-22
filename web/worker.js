// Worker Trafficker : sert l'application (fichiers statiques) et l'API /api/*
// (connexion, tâches partagées par agence, administration). Données : base D1 « DB ».
// Le moteur d'analyse reste dans le navigateur ; ne sont stockés ici que les comptes
// et les tâches (paramètres + plan classé par l'agent).

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
];
let schemaReady = false;

async function ensureSchema(db) {
  if (schemaReady) return;
  await db.batch(SCHEMA.map((s) => db.prepare(s)));
  schemaReady = true;
}

const now = () => Date.now() / 1000;
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

export default {
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

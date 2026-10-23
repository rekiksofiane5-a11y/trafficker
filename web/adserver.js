// Accès aux ad servers depuis le Worker (les clés restent côté serveur, jamais dans la page).
// CM360 : compte de service Google (secret CM360_SA_JSON) + profil utilisateur (CM360_PROFILE_ID).
// Adform : client API (ADFORM_CLIENT_ID / ADFORM_CLIENT_SECRET) — endpoints à valider avec un accès réel.
// Sans clé configurée, la page utilise les données de démonstration (demo_adserver.json).

export class HttpError extends Error {
  constructor(message, status = 502) { super(message); this.status = status; }
}

const tokens = new Map();               // jetons OAuth en cache dans l'isolate

export function adserverStatus(env) {
  return {cm360: !!(env.CM360_SA_JSON && env.CM360_PROFILE_ID),
          adform: !!(env.ADFORM_CLIENT_ID && env.ADFORM_CLIENT_SECRET)};
}

const b64url = (bytes) => {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
const b64urlText = (text) => b64url(new TextEncoder().encode(text));
const isoDay = (d) => d.toISOString().slice(0, 10);

async function cached(key, make) {
  const t = tokens.get(key);
  if (t && t.exp > Date.now() + 60_000) return t.token;
  const {token, ttl} = await make();
  tokens.set(key, {token, exp: Date.now() + ttl * 1000});
  return token;
}

async function readJson(r, what) {
  let d = {};
  try { d = await r.json(); } catch { /* corps vide */ }
  if (!r.ok) {
    const msg = (d.error && (d.error.message || d.error_description || d.error)) || d.message || r.statusText;
    throw new HttpError(`${what} : ${typeof msg === "string" ? msg : JSON.stringify(msg)} (HTTP ${r.status})`, r.status === 404 ? 404 : 502);
  }
  return d;
}

// --- CM360 (Campaign Manager 360 API v5) ---------------------------------------------------

function cm360(env) {
  const base = env.CM360_API_BASE || "https://dfareporting.googleapis.com/dfareporting/v5";
  const tokenUrl = env.GOOGLE_TOKEN_URL || "https://oauth2.googleapis.com/token";
  const profile = env.CM360_PROFILE_ID;
  let sa;
  try { sa = JSON.parse(env.CM360_SA_JSON); } catch { throw new HttpError("Secret CM360_SA_JSON illisible (JSON du compte de service).", 500); }

  const token = () => cached("cm360", async () => {
    const pem = String(sa.private_key || "").replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
    const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
    const key = await crypto.subtle.importKey("pkcs8", der, {name: "RSASSA-PKCS1-v1_5", hash: "SHA-256"}, false, ["sign"]);
    const iat = Math.floor(Date.now() / 1000);
    const unsigned = b64urlText(JSON.stringify({alg: "RS256", typ: "JWT"})) + "." + b64urlText(JSON.stringify({
      iss: sa.client_email, aud: tokenUrl, iat, exp: iat + 3600,
      scope: "https://www.googleapis.com/auth/dfareporting https://www.googleapis.com/auth/dfatrafficking"}));
    const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
    const r = await fetch(tokenUrl, {method: "POST", headers: {"content-type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer", assertion: unsigned + "." + b64url(sig)})});
    const d = await readJson(r, "Connexion Google (compte de service)");
    return {token: d.access_token, ttl: d.expires_in || 3600};
  });

  const call = async (path, {method = "GET", params, body, raw} = {}) => {
    const u = new URL(path.startsWith("http") ? path : `${base}/userprofiles/${profile}${path}`);
    for (const [k, v] of Object.entries(params || {})) {
      for (const x of [].concat(v)) if (x !== undefined && x !== "") u.searchParams.append(k, x);
    }
    const r = await fetch(u, {method, headers: {authorization: "Bearer " + await token(),
      ...(body ? {"content-type": "application/json"} : {})}, body: body ? JSON.stringify(body) : undefined});
    if (raw) {
      if (!r.ok) throw new HttpError(`CM360 : téléchargement du rapport refusé (HTTP ${r.status})`);
      return r.text();
    }
    return readJson(r, "CM360");
  };

  const pages = async (path, params, key, max = 5) => {
    const out = [];
    let pageToken;
    for (let i = 0; i < max; i++) {
      const d = await call(path, {params: {...params, pageToken}});
      out.push(...(d[key] || []));
      pageToken = d.nextPageToken;
      if (!pageToken) break;
    }
    return out;
  };

  const campaignOf = async (id) => {
    const c = await call(`/campaigns/${encodeURIComponent(id)}`);
    const adv = await call(`/advertisers/${encodeURIComponent(c.advertiserId)}`).catch(() => ({}));
    return {id: String(c.id), name: c.name, advertiser_id: String(c.advertiserId || ""), advertiser: adv.name || "",
            start: c.startDate || "", end: c.endDate || ""};
  };

  // Diffusion jour x emplacement d'une campagne (rapport CSV éphémère)
  const reportBody = (campaign, extra = {}) => ({
    name: `Umnia - ${campaign.name}`.slice(0, 250), type: "STANDARD", format: "CSV",
    criteria: {dateRange: {startDate: campaign.start, endDate: minDay(campaign.end, isoDay(new Date()))},
               dimensions: [{name: "date"}, {name: "placementId"}], metricNames: ["impressions", "clicks"],
               dimensionFilters: [{dimensionName: "campaign", id: String(campaign.id), kind: "dfareporting#dimensionValue"}]},
    ...extra});

  const fileResult = async (reportId, file) => {
    if (file.status === "REPORT_AVAILABLE") {
      const csv = await call(file.urls && file.urls.apiUrl ? file.urls.apiUrl : `/reports/${reportId}/files/${file.id}?alt=media`, {raw: true});
      await call(`/reports/${reportId}`, {method: "DELETE"}).catch(() => null);
      return {delivery: parseCm360Csv(csv)};
    }
    if (file.status === "FAILED" || file.status === "CANCELLED") throw new HttpError("CM360 : le rapport a échoué.");
    return {pending: {report_id: String(reportId), file_id: String(file.id)}};
  };

  return {
    async advertisers(q) {
      const d = await call("/advertisers", {params: {searchString: q || undefined, maxResults: 50, sortField: "NAME"}});
      return (d.advertisers || []).map((a) => ({id: String(a.id), name: a.name}));
    },
    // Répertoire des sites CM360 du compte : noms exacts à reprendre dans le trafficking
    async sites(q) {
      const items = await pages("/sites", {searchString: q || undefined, maxResults: 1000, sortField: "NAME"}, "sites", 10);
      return items.map((s) => ({id: String(s.id), name: s.name, directory_site_id: s.directorySiteId ? String(s.directorySiteId) : ""}));
    },
    async campaigns(advertiserId, q) {
      const d = await call("/campaigns", {params: {advertiserIds: advertiserId || undefined, searchString: q || undefined,
                                                   maxResults: 100, sortField: "NAME", archived: false}});
      return (d.campaigns || []).map((c) => ({id: String(c.id), name: c.name, advertiser_id: String(c.advertiserId || ""),
                                               start: c.startDate || "", end: c.endDate || ""}));
    },
    async placements(campaignId) {
      const campaign = await campaignOf(campaignId);
      const items = await pages("/placements", {campaignIds: campaignId, maxResults: 1000}, "placements");
      const siteIds = [...new Set(items.map((p) => String(p.siteId)).filter(Boolean))];
      const names = {};
      for (let i = 0; i < siteIds.length; i += 100) {
        const d = await call("/sites", {params: {ids: siteIds.slice(i, i + 100), maxResults: 100}});
        for (const s of d.sites || []) names[String(s.id)] = s.name;
      }
      const placements = items.map((p) => ({
        id: String(p.id), name: p.name, site_id: String(p.siteId || ""), site: names[String(p.siteId)] || `Site ${p.siteId}`,
        size: p.size ? `${p.size.width}x${p.size.height}` : "",
        start: (p.pricingSchedule && p.pricingSchedule.startDate) || "", end: (p.pricingSchedule && p.pricingSchedule.endDate) || ""}));
      return {campaign, placements};
    },
    async delivery(campaignId) {
      const campaign = await campaignOf(campaignId);
      if (!campaign.start || campaign.start > isoDay(new Date())) return {delivery: []};
      const rep = await call("/reports", {method: "POST", body: reportBody(campaign)});
      let file = await call(`/reports/${rep.id}/run`, {method: "POST", params: {synchronous: true}});
      for (let i = 0; i < 6 && file.status === "PROCESSING"; i++) {      // ~15 s au plus, puis la page relance
        await new Promise((ok) => setTimeout(ok, 2500));
        file = await call(`/reports/${rep.id}/files/${file.id}`);
      }
      return fileResult(rep.id, file);
    },
    async deliveryFile(reportId, fileId) {
      return fileResult(reportId, await call(`/reports/${encodeURIComponent(reportId)}/files/${encodeURIComponent(fileId)}`));
    },
    // Report régie programmé : CM360 génère et envoie lui-même le fichier par e-mail
    async schedule(campaignId, site, emails, sched) {
      const rep = await call("/reports", {method: "POST", body: scheduleBody(await campaignOf(campaignId), site, emails, sched, true)});
      return {report_id: String(rep.id), sent_by: "cm360"};
    },
    // Pause / reprise / modification : le rapport CM360 est réécrit (reports.update)
    async updateSchedule(reportId, campaignId, site, emails, sched, active) {
      const old = await call(`/reports/${encodeURIComponent(reportId)}`);
      const body = {...scheduleBody(await campaignOf(campaignId), site, emails, sched, active), id: old.id};
      await call(`/reports/${encodeURIComponent(reportId)}`, {method: "PUT", body});
      return {report_id: String(old.id), active};
    },
    async deleteSchedule(reportId) {
      await call(`/reports/${encodeURIComponent(reportId)}`, {method: "DELETE"});
      return {ok: true};
    },
  };

  function scheduleBody(campaign, site, emails, sched, active) {
    const relative = {daily: "YESTERDAY", weekly: "LAST_7_DAYS", monthly: "PREVIOUS_MONTH"}[sched.frequency];
    const dateRange = sched.range === "period" && relative ? {relativeDateRange: relative}
      : {startDate: campaign.start, endDate: campaign.end};
    const body = {
      name: `Umnia - ${campaign.name} - ${site.name}`.slice(0, 250), type: "STANDARD", format: "EXCEL",
      criteria: {dateRange, dimensions: [{name: "date"}, {name: "site"}, {name: "placement"}, {name: "placementId"}],
                 metricNames: ["impressions", "clicks"],
                 dimensionFilters: [{dimensionName: "campaign", id: String(campaign.id), kind: "dfareporting#dimensionValue"},
                                    {dimensionName: "site", id: String(site.id), kind: "dfareporting#dimensionValue"}]},
      schedule: {active: !!active, every: 1, repeats: {daily: "DAILY", weekly: "WEEKLY", monthly: "MONTHLY"}[sched.frequency] || "WEEKLY",
                 ...(sched.frequency === "weekly" ? {repeatsOnWeekDays: sched.weekdays && sched.weekdays.length ? sched.weekdays : ["MONDAY"]} : {}),
                 ...(sched.frequency === "monthly" ? {runsOnDayOfMonth: "DAY_OF_MONTH"} : {}),
                 startDate: sched.start, expirationDate: sched.end},
      delivery: {emailOwner: false, emailOwnerDeliveryType: "ATTACHMENT", message: sched.message || "",
                 recipients: emails.map((email) => ({email, deliveryType: "ATTACHMENT", kind: "dfareporting#recipient"}))},
    };
    return body;
  }
}

function minDay(a, b) { return !a ? b : a < b ? a : b; }

// Export CSV CM360 : en-têtes de rapport, ligne « Report Fields », colonnes, données, « Grand Total »
export function parseCm360Csv(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  let i = lines.findIndex((l) => /^report fields/i.test(l.trim()));
  i = i >= 0 ? i + 1 : 0;
  const split = (l) => {
    const out = []; let cur = "", q = false;
    for (let k = 0; k < l.length; k++) {
      const c = l[k];
      if (q) { if (c === '"' && l[k + 1] === '"') { cur += '"'; k++; } else if (c === '"') q = false; else cur += c; }
      else if (c === '"') q = true; else if (c === ",") { out.push(cur); cur = ""; } else cur += c;
    }
    out.push(cur);
    return out;
  };
  const head = split(lines[i] || "").map((h) => h.trim().toLowerCase());
  const col = (re) => head.findIndex((h) => re.test(h));
  const cDate = col(/^date$/), cPl = col(/placement id/), cImp = col(/^impressions$/), cClk = col(/^clicks$/);
  if (cPl < 0 || cImp < 0) throw new HttpError("CM360 : colonnes inattendues dans le rapport (" + head.join(", ") + ").");
  const out = [];
  for (const l of lines.slice(i + 1)) {
    if (!l.trim() || /^grand total/i.test(l)) continue;
    const v = split(l);
    out.push({date: cDate >= 0 ? v[cDate] : "", placement_id: v[cPl], impressions: Number(v[cImp]) || 0,
              clicks: cClk >= 0 ? Number(v[cClk]) || 0 : 0});
  }
  return out;
}

// --- Adform (API Buyer) : à valider avec un accès réel ---------------------------------------

function adform(env) {
  const base = env.ADFORM_API_BASE || "https://api.adform.com";
  const token = () => cached("adform", async () => {
    const r = await fetch(env.ADFORM_TOKEN_URL || "https://id.adform.com/sts/connect/token", {method: "POST",
      headers: {"content-type": "application/x-www-form-urlencoded"},
      body: new URLSearchParams({grant_type: "client_credentials", client_id: env.ADFORM_CLIENT_ID,
        client_secret: env.ADFORM_CLIENT_SECRET,
        scope: "https://api.adform.com/scope/buyer.campaigns.api.readonly https://api.adform.com/scope/buyer.stats"})});
    const d = await readJson(r, "Connexion Adform");
    return {token: d.access_token, ttl: d.expires_in || 3600};
  });
  const call = async (path, {method = "GET", body} = {}) => {
    const r = await fetch(base + path, {method, headers: {authorization: "Bearer " + await token(),
      ...(body ? {"content-type": "application/json"} : {})}, body: body ? JSON.stringify(body) : undefined});
    return readJson(r, "Adform");
  };
  const list = (d) => Array.isArray(d) ? d : (d.items || d.data || []);
  const campaignOf = async (id) => {
    const c = await call(`/v1/buyer/campaigns/${encodeURIComponent(id)}`);
    return {id: String(c.id), name: c.name, advertiser_id: String(c.advertiserId || ""), advertiser: c.advertiserName || "",
            start: (c.startDate || "").slice(0, 10), end: (c.endDate || "").slice(0, 10)};
  };
  return {
    // Médias Adform (équivalent des sites) : au mieux, selon les droits de l'API
    async sites(q) {
      const s = (q || "").toLowerCase();
      return list(await call("/v1/buyer/medias")).filter((m) => !s || String(m.name).toLowerCase().includes(s))
        .map((m) => ({id: String(m.id), name: m.name}));
    },
    async advertisers(q) {
      const s = (q || "").toLowerCase();
      return list(await call("/v1/buyer/advertisers")).filter((a) => !s || String(a.name).toLowerCase().includes(s))
        .slice(0, 50).map((a) => ({id: String(a.id), name: a.name}));
    },
    async campaigns(advertiserId, q) {
      const s = (q || "").toLowerCase();
      return list(await call(`/v1/buyer/campaigns?advertiserIds=${encodeURIComponent(advertiserId)}`))
        .filter((c) => !s || String(c.name).toLowerCase().includes(s))
        .map((c) => ({id: String(c.id), name: c.name, advertiser_id: String(advertiserId),
                      start: (c.startDate || "").slice(0, 10), end: (c.endDate || "").slice(0, 10)}));
    },
    async placements(campaignId) {
      const campaign = await campaignOf(campaignId);
      const items = list(await call(`/v1/buyer/campaigns/${encodeURIComponent(campaignId)}/placements`));
      return {campaign, placements: items.map((p) => ({id: String(p.id), name: p.name,
        site: (p.media && p.media.name) || p.mediaName || "Média inconnu", site_id: String((p.media && p.media.id) || p.mediaId || ""),
        size: p.size || "", start: (p.startDate || "").slice(0, 10), end: (p.endDate || "").slice(0, 10)}))};
    },
    async delivery(campaignId) {
      const campaign = await campaignOf(campaignId);
      const d = await call("/v1/buyer/stats/data", {method: "POST", body: {
        dimensions: ["date", "placement"], metrics: ["impressions", "clicks"],
        filter: {date: {from: campaign.start, to: minDay(campaign.end, isoDay(new Date()))}, campaign: {id: [Number(campaignId)]}}}});
      const rd = d.reportData || {};
      const h = (rd.columnHeaders || []).map((x) => String(x).toLowerCase());
      return {delivery: (rd.rows || []).map((r) => ({date: String(r[h.indexOf("date")] || "").slice(0, 10),
        placement_id: String(r[h.findIndex((x) => x.startsWith("placement"))]),
        impressions: Number(r[h.indexOf("impressions")]) || 0, clicks: Number(r[h.indexOf("clicks")]) || 0}))};
    },
    async deliveryFile() { throw new HttpError("Adform : pas de rapport asynchrone.", 400); },
    async schedule() {
      // Pas de création de rapport programmé par l'API Adform : le calendrier est enregistré
      // dans Umnia et le rapport est à programmer dans Adform (Excel prêt à télécharger).
      return {report_id: "", sent_by: "manual"};
    },
    async updateSchedule() { throw new HttpError("Adform : rapport programmé à modifier dans Adform.", 400); },
    async deleteSchedule() { throw new HttpError("Adform : rapport programmé à supprimer dans Adform.", 400); },
  };
}

export function client(adserver, env) {
  const st = adserverStatus(env);
  if (adserver === "adform") {
    if (!st.adform) throw new HttpError("Adform non connecté (secrets ADFORM_CLIENT_ID / ADFORM_CLIENT_SECRET).", 409);
    return adform(env);
  }
  if (!st.cm360) throw new HttpError("CM360 non connecté (secrets CM360_SA_JSON / CM360_PROFILE_ID).", 409);
  return cm360(env);
}

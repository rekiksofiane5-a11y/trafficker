// Worker + faux CM360 : vérifie l'API /api/adserver/* de bout en bout sans compte Google.
// Lance un faux serveur Google (jeton OAuth + API CM360 v5), puis `wrangler dev` avec un compte
// de service généré pour l'occasion. Contrôles : JWT signé RS256 vérifiable, lecture annonceurs /
// campagnes / emplacements, rapport CSV de diffusion (asynchrone), programmation d'un report régie.
// Usage : node tests/worker_cm360.mjs   (prérequis : npm ci)
import {spawn} from "node:child_process";
import {generateKeyPairSync, createVerify} from "node:crypto";
import {createServer} from "node:http";
import {rmSync, writeFileSync} from "node:fs";
import assert from "node:assert/strict";

const ROOT = new URL("..", import.meta.url).pathname;
const {privateKey, publicKey} = generateKeyPairSync("rsa", {modulusLength: 2048});
const SA = {client_email: "umnia@test.iam.gserviceaccount.com",
            private_key: privateKey.export({type: "pkcs8", format: "pem"})};
const seen = [];
let fileReads = 0;

const fake = createServer(async (req, res) => {
  let raw = "";
  for await (const c of req) raw += c;
  const url = new URL(req.url, "http://x");
  seen.push({method: req.method, path: url.pathname, query: url.search, body: raw, auth: req.headers.authorization});
  const send = (d, s = 200) => { res.writeHead(s, {"content-type": "application/json"}); res.end(JSON.stringify(d)); };
  if (url.pathname === "/token") {
    const jwt = new URLSearchParams(raw).get("assertion").split(".");
    const ok = createVerify("RSA-SHA256").update(jwt[0] + "." + jwt[1]).verify(publicKey, Buffer.from(jwt[2], "base64url"));
    const claims = JSON.parse(Buffer.from(jwt[1], "base64url"));
    if (!ok || claims.iss !== SA.client_email || !claims.scope.includes("dfareporting")) return send({error: "invalid_grant"}, 400);
    return send({access_token: "tok-123", expires_in: 3600});
  }
  if (req.headers.authorization !== "Bearer tok-123") return send({error: {message: "unauthenticated"}}, 401);
  const p = url.pathname.replace("/dfareporting/v5/userprofiles/777", "");
  if (p === "/advertisers") return send({advertisers: [{id: "9001", name: "UPSA"}, {id: "9002", name: "UPSA Pharma"}]});
  if (p === "/advertisers/9001") return send({id: "9001", name: "UPSA"});
  if (p === "/campaigns") return send({campaigns: [{id: "3417", name: "Citrate 2026", advertiserId: "9001", startDate: "2026-10-01", endDate: "2026-12-31"}]});
  if (p === "/campaigns/3417") return send({id: "3417", name: "Citrate 2026", advertiserId: "9001", startDate: "2026-10-01", endDate: "2026-12-31"});
  if (p === "/placements") {
    if (!url.searchParams.get("pageToken")) return send({nextPageToken: "p2", placements: [
      {id: "11", name: "PAVE", siteId: "5", size: {width: 300, height: 250}, pricingSchedule: {startDate: "2026-10-01", endDate: "2026-12-31"}}]});
    return send({placements: [{id: "21", name: "VIDEO", siteId: "6", size: {width: 640, height: 360}}]});
  }
  if (p === "/sites") return send({sites: [{id: "5", name: "Le Monde", directorySiteId: "105"}, {id: "6", name: "Teads"}]});
  if (p === "/reports" && req.method === "POST") return send({id: "r1", ...JSON.parse(raw)});
  if (p === "/reports/r1/run") return send({id: "f1", status: "PROCESSING"});
  if (p === "/reports/r1/files/f1") {
    fileReads++;
    return send(fileReads < 2 ? {id: "f1", status: "PROCESSING"}
      : {id: "f1", status: "REPORT_AVAILABLE", urls: {apiUrl: `http://127.0.0.1:${fake.address().port}/download/f1`}});
  }
  if (p === "/download/f1" || url.pathname === "/download/f1") {
    res.writeHead(200, {"content-type": "text/csv"});
    return res.end("Umnia\nDate Range,x\n\nReport Fields\nDate,Placement ID,Impressions,Clicks\n2026-10-01,11,1000,4\n2026-10-02,11,1500,2\nGrand Total:,,2500,6\n");
  }
  if (p === "/reports/r1" && req.method === "DELETE") { res.writeHead(204); return res.end(); }
  if (p === "/reports/r1" && req.method === "GET") return send({id: "r1", name: "Umnia - Citrate 2026 - Le Monde"});
  if (p === "/reports/r1" && req.method === "PUT") return send(JSON.parse(raw));
  send({error: {message: "inconnu " + p}}, 404);
});
await new Promise((ok) => fake.listen(0, "127.0.0.1", ok));
const F = `http://127.0.0.1:${fake.address().port}`;

writeFileSync(ROOT + ".dev.vars", [
  `CM360_SA_JSON='${JSON.stringify(SA)}'`, "CM360_PROFILE_ID=777",
  `CM360_API_BASE=${F}/dfareporting/v5`, `GOOGLE_TOKEN_URL=${F}/token`, "TRAFFICKER_PASSWORD=cle-test-123"].join("\n"));
rmSync(ROOT + ".wrangler/state", {recursive: true, force: true});
const port = 8800 + Math.floor(Math.random() * 100);
const wd = spawn("npx", ["wrangler", "dev", "--port", String(port)], {cwd: ROOT, stdio: ["ignore", "pipe", "pipe"], detached: true});
let log = "";
wd.stdout.on("data", (d) => { log += d; });
wd.stderr.on("data", (d) => { log += d; });
const U = `http://127.0.0.1:${port}`;
let cookie = "";
const api = async (method, path, body) => {
  const r = await fetch(U + "/api/" + path, {method, headers: {"content-type": "application/json", cookie, origin: U},
                                             body: body ? JSON.stringify(body) : undefined});
  const sc = r.headers.get("set-cookie");
  if (sc) cookie = sc.split(";")[0];
  return {status: r.status, data: await r.json()};
};

try {
  for (let i = 0; i < 90; i++) {
    try { if ((await fetch(U + "/api/me")).status) break; } catch { /* démarrage */ }
    await new Promise((ok) => setTimeout(ok, 1000));
  }
  assert.equal((await api("POST", "setup", {name: "A", email: "a@ag.fr", agency_id: "AG", password: "motdepasse1", setup_key: "cle-test-123"})).status, 200);
  assert.equal((await api("POST", "login", {email: "a@ag.fr", password: "motdepasse1"})).status, 200);
  assert.deepEqual((await api("GET", "adserver/status")).data, {cm360: true, adform: false});
  const diag = (await api("GET", "adserver/diagnostic?adserver=cm360")).data;
  assert.equal(diag.ok, true);
  assert.deepEqual(diag.sample, ["UPSA", "UPSA Pharma"]);
  const diagAf = (await api("GET", "adserver/diagnostic?adserver=adform")).data;
  assert.equal(diagAf.ok, false);
  assert.match(diagAf.error, /Adform non connecté/);
  assert.equal((await api("GET", "adserver/advertisers?adserver=adform")).status, 409);         // Adform non connecté
  const adv = (await api("GET", "adserver/advertisers?q=UPSA")).data.advertisers;
  assert.equal(adv.length, 2);
  assert.ok(seen.some((s) => s.path.endsWith("/advertisers") && s.query.includes("searchString=UPSA")));
  const sites = (await api("GET", "adserver/sites")).data;                                       // répertoire des sites CM360
  assert.deepEqual(sites.sites[0], {id: "5", name: "Le Monde", directory_site_id: "105"});
  assert.ok(seen.some((s) => s.path.endsWith("/sites") && s.query.includes("maxResults=1000")));
  const camps = (await api("GET", "adserver/campaigns?advertiser_id=9001")).data.campaigns;
  assert.deepEqual(camps[0], {id: "3417", name: "Citrate 2026", advertiser_id: "9001", start: "2026-10-01", end: "2026-12-31"});
  const pl = (await api("GET", "adserver/placements?campaign_id=3417")).data;
  assert.equal(pl.campaign.advertiser, "UPSA");
  assert.deepEqual(pl.placements.map((p) => [p.id, p.site, p.size]), [["11", "Le Monde", "300x250"], ["21", "Teads", "640x360"]]);
  const del = (await api("POST", "adserver/delivery", {campaign_id: "3417"})).data;
  assert.deepEqual(del.delivery, [{date: "2026-10-01", placement_id: "11", impressions: 1000, clicks: 4},
                                  {date: "2026-10-02", placement_id: "11", impressions: 1500, clicks: 2}]);
  const rep = JSON.parse(seen.find((s) => s.path.endsWith("/reports") && s.method === "POST").body);
  assert.deepEqual(rep.criteria.dimensionFilters[0].id, "3417");
  assert.ok(seen.some((s) => s.method === "DELETE"));                                            // rapport éphémère supprimé
  const bad = await api("POST", "adserver/schedule", {campaign_id: "3417", site: {id: "5", name: "Le Monde"}, emails: ["x"],
                                                     schedule: {frequency: "weekly", start: "2026-10-23", end: "2026-12-31"}});
  assert.equal(bad.status, 400);
  seen.length = 0;
  const ok = await api("POST", "adserver/schedule", {campaign_id: "3417", site: {id: "5", name: "Le Monde"},
    emails: ["Trafic@LeMonde.fr"], schedule: {frequency: "weekly", weekdays: ["MONDAY", "THURSDAY"], range: "cumul",
                                              start: "2026-10-23", end: "2026-12-31", message: "Bonjour"}});
  assert.equal(ok.status, 200);
  assert.deepEqual(ok.data, {report_id: "r1", sent_by: "cm360"});
  const sch = JSON.parse(seen.find((s) => s.path.endsWith("/reports") && s.method === "POST").body);
  assert.equal(sch.format, "EXCEL");
  assert.deepEqual(sch.schedule, {active: true, every: 1, repeats: "WEEKLY", repeatsOnWeekDays: ["MONDAY", "THURSDAY"],
                                  startDate: "2026-10-23", expirationDate: "2026-12-31"});
  assert.deepEqual(sch.delivery.recipients, [{email: "trafic@lemonde.fr", deliveryType: "ATTACHMENT", kind: "dfareporting#recipient"}]);
  assert.deepEqual(sch.criteria.dimensionFilters.map((f) => [f.dimensionName, f.id]), [["campaign", "3417"], ["site", "5"]]);
  // Pause puis modification (reports.update) et suppression du report programmé
  seen.length = 0;
  const paused = await api("PUT", "adserver/schedule/r1", {campaign_id: "3417", site: {id: "5", name: "Le Monde"},
    emails: ["trafic@lemonde.fr", "ops@lemonde.fr"], active: false,
    schedule: {frequency: "daily", range: "period", start: "2026-10-23", end: "2026-12-31"}});
  assert.deepEqual(paused.data, {report_id: "r1", active: false});
  const put = JSON.parse(seen.find((x) => x.method === "PUT").body);
  assert.equal(put.id, "r1");
  assert.equal(put.schedule.active, false);
  assert.equal(put.schedule.repeats, "DAILY");
  assert.deepEqual(put.criteria.dateRange, {relativeDateRange: "YESTERDAY"});
  assert.equal(put.delivery.recipients.length, 2);
  assert.equal((await api("PUT", "adserver/schedule/r1", {campaign_id: "3417", emails: ["x"], schedule: {}})).status, 400);
  seen.length = 0;
  assert.deepEqual((await api("DELETE", "adserver/schedule/r1")).data, {ok: true});
  assert.ok(seen.some((x) => x.method === "DELETE" && x.path.endsWith("/reports/r1")));
  assert.equal((await api("PUT", "adserver/schedule/r1?adserver=adform", {adserver: "adform"})).status, 409);
  assert.equal((await api("POST", "contacts", {site: "Le Monde", emails: ["trafic@lemonde.fr", "pas-un-mail"]})).status, 200);
  assert.deepEqual((await api("GET", "contacts")).data.contacts, [{site: "Le Monde", email: "trafic@lemonde.fr"}]);
  // Réglages partagés par l'agence
  assert.deepEqual((await api("GET", "settings/site_map")).data, {value: null});
  assert.equal((await api("PUT", "settings/site_map", {value: {"Facebook FR": "Meta"}})).status, 200);
  assert.deepEqual((await api("GET", "settings/site_map")).data, {value: {"Facebook FR": "Meta"}});
  assert.equal((await api("GET", "settings/inconnu")).status, 404);
  cookie = "";
  assert.equal((await api("GET", "adserver/status")).status, 401);                                // connexion requise
  console.log("OK : Worker + faux CM360 (jeton RS256, lecture, rapport asynchrone, programmation, pause / modification / suppression, carnet).");
} catch (e) {
  console.error(log.slice(-3000));
  throw e;
} finally {
  try { process.kill(-wd.pid, "SIGTERM"); } catch { /* déjà arrêté */ }
  fake.close();
  rmSync(ROOT + ".dev.vars", {force: true});
}

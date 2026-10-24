// Contrôles qualité (UTM, budgets) et alertes de surveillance : node tests/quality.test.mjs
import assert from "node:assert/strict";
import {utmIssues, budgetIssues, evaluate, mergeAlerts, matchTargets, num} from "../web/quality.js";

const texts = (l) => l.map((x) => x.text).join(" | ");

// --- UTM ---
{
  const u = (src, camp = "noel", extra = "") => `https://www.marque.fr/?utm_source=${src}&utm_medium=display&utm_campaign=${camp}${extra}`;
  const rows = [
    {site_name: "Le Monde", landing_page_url: u("lemonde")},
    {site_name: "Le Monde", landing_page_url: u("LeMonde")},
    {site_name: "Le Monde", landing_page_url: u("lm")},
    {site_name: "Teads", landing_page_url: u("lemonde")},
    {site_name: "Prisma", landing_page_url: "https://www.marque.fr/promo"},
    {site_name: "Prisma", landing_page_url: u("prisma", "noel2")},
    {site_name: "Prisma", landing_page_url: "http://www.marque.fr/?utm_source=prisma&utm_source=x&utm_content={{creative}}"},
    {site_name: "Teads", landing_page_url: "pas une url"},
  ];
  const t = texts(utmIssues(rows));
  for (const want of ["URL de destination invalide (1)", "http au lieu de https", "UTM absentes sur 1 ligne", "UTM incomplètes",
                      "Paramètre UTM répété", "non renseigné", "utm_campaign différent", "utm_source écrit de plusieurs façons",
                      "Le Monde : plusieurs utm_source", "utm_source « lemonde » identique pour 2 régies"])
    assert.ok(t.includes(want), `UTM : « ${want} » attendu dans ${t}`);
  assert.equal(utmIssues([{site_name: "A", landing_page_url: u("a")}, {site_name: "B", landing_page_url: u("b")}]).length, 0);
}

// --- Budgets / volumes ---
{
  const r = (b, v, n) => ({placement_name: n, site_name: "S", budget_eur: b, objective_impressions: v, pricing_type: "CPM"});
  const t = texts(budgetIssues([r("1 000 €", "200 000", "a"), r("1 200", "240000", "b"), r("900", "180000", "c"),
                               r("9 000", "100000", "d"), r("500", "", "e")], {budget_eur: "20000"}));
  assert.ok(t.includes("CPM implicite atypique"), t);
  assert.ok(t.includes("Budget sans volume sur 1 ligne"), t);
  assert.ok(t.includes("≠ budget de la campagne"), t);
  assert.equal(num("4 000,50 €"), 4000.5);
  assert.equal(budgetIssues([r("1000", "200000", "a"), r("1000", "200000", "a")], {budget_eur: "1000"}).length, 0);   // lignes de créas répétées
  // PM extrait : total de campagne sur chaque ligne, budget de la ligne dans line_budget_eur / line_volume
  const x = (lb, lv, n) => ({placement_name: n, site_name: "S", budget_eur: "43500", objective_impressions: "6050000",
                              line_budget_eur: lb, line_volume: lv, pricing_type: "CPM"});
  const ex = texts(budgetIssues([x("6000", "1500000", "a"), x("4500", "900000", "b"), x("3000", "1000000", "c"),
                                 x("30000", "2650000", "d")], {budget_eur: "43500"}));
  assert.ok(!ex.includes("≠ budget de la campagne"), ex);                  // 6 000 + 4 500 + 3 000 + 30 000 = 43 500
  assert.equal(budgetIssues([x("6000", "1500000", "a"), x("4500", "900000", "b"), x("3000", "1000000", "c")], {budget_eur: "13500"}).length, 0);
}

// --- Surveillance ---
const now = new Date("2026-10-24T10:00:00Z");
const campaign = {id: "1", name: "Noël", start: "2026-10-14", end: "2026-11-02"};   // 20 jours, 10 écoulés au 23
const placements = [
  {id: "p1", name: "LM-Pave", site: "Le Monde", start: "2026-10-14", end: "2026-11-02"},
  {id: "p2", name: "LM-Banniere", site: "Le Monde"},
  {id: "p3", name: "Teads-Video", site: "Teads"},
  {id: "p4", name: "Prisma-Pave", site: "Prisma", start: "2026-10-22"},
];
const delivery = [];
for (let d = 14; d <= 23; d++) {
  const date = `2026-10-${d}`;
  delivery.push({date, placement_id: "p1", impressions: 5000, clicks: 5});
  if (d <= 20) delivery.push({date, placement_id: "p2", impressions: 8000, clicks: 8});     // à l'arrêt depuis le 21
}
const targets = {placements: [
  {name: "LM-Pave", site: "Le Monde", impressions: "200000", budget: "2000"},
  {name: "LM-Banniere", site: "Le Monde", impressions: "160000", budget: "1600"},
  {name: "Teads-Video", site: "Teads", impressions: "100000", budget: "3000"},
]};
{
  const {alerts} = evaluate({campaign, placements, delivery, targets, regie: {"Le Monde": {impressions: "130000", through: "2026-10-20"}}, now});
  const by = (k) => alerts.filter((a) => a.kind === k);
  assert.deepEqual(by("no_delivery").map((a) => a.key).sort(), ["no_delivery:prisma", "no_delivery:teads"]);   // Prisma : démarré le 22
  assert.ok(by("pacing").some((a) => a.key === "pacing:campaign"), texts(alerts));                          // 106k / 230k prévus
  assert.ok(by("pacing").some((a) => a.key === "pacing:teads"));
  assert.equal(by("mid_budget").length, 1);
  assert.equal(by("paused").map((a) => a.key).join(), "paused:p2");
  assert.equal(by("regie_gap").length, 1);                                       // 130 000 déclarées vs 91 000
  assert.match(by("regie_gap")[0].text, /\+43 %/);
  // seuils : 48 h sans impression -> Prisma (démarré il y a ~58 h) reste en alerte, rythme toléré à 40 %
  const loose = evaluate({campaign, placements, delivery, targets, thresholds: {no_delivery_hours: 72, pacing_low: 40, paused_days: 4}, now}).alerts;
  assert.ok(!loose.some((a) => a.key === "no_delivery:prisma") && !loose.some((a) => a.key === "paused:p2"), texts(loose));
  // campagne terminée : plus d'alerte de diffusion
  assert.equal(evaluate({campaign: {...campaign, end: "2026-10-20"}, placements, delivery, targets, now}).alerts.length, 0);
  // fusion : nouvelles, puis rien de neuf, puis fermeture
  const m = {id: "m1", task_id: "t1", campaign};
  const a1 = mergeAlerts([], m, alerts, 100);
  assert.equal(a1.fresh.length, alerts.length);
  const a2 = mergeAlerts(a1.list, m, alerts, 200);
  assert.equal(a2.fresh.length, 0);
  const a3 = mergeAlerts(a2.list, m, alerts.filter((a) => a.kind !== "paused"), 300);
  assert.equal(a3.list.find((a) => a.key === "paused:p2").status, "closed");
  const a4 = mergeAlerts(a3.list, m, alerts, 400);
  assert.deepEqual(a4.fresh.map((a) => a.key), ["paused:p2"]);                   // rouverte = de nouveau notifiée
  assert.equal(matchTargets([{id: "x", name: "lm pave", site: "Le Monde"}], targets).get("x").name, "LM-Pave");
}
console.log("OK : contrôles qualité (UTM, budgets) et alertes de surveillance.");

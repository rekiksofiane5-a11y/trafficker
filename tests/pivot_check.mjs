// Tableau croisé (web/pivot.js) : sommes, taux recalculés, colonnes, tri, préréglages (node tests/pivot_check.mjs)
import assert from "node:assert/strict";
import "../web/pivot.js";
const P = globalThis.Pivot;
const t = {columns: [
  {label: "Date", kind: "dimension"}, {label: "Site (CM360)", kind: "dimension"}, {label: "Placement", kind: "dimension"},
  {label: "Placement ID", kind: "dimension"}, {label: "Impressions", kind: "metric"}, {label: "Clicks", kind: "metric"},
  {label: "Click Rate", kind: "metric", rate: true}, {label: "Active View: % Viewable Impressions", kind: "metric", rate: true},
  {label: "Semaine", kind: "dimension", derived: true}],
  rows: [
    ["2026-10-01", "Le Monde", "LM-PAVE", "1", 1000, 10, 1.0, 50, "S40"],
    ["2026-10-02", "Le Monde", "LM-PAVE", "1", 3000, 15, 0.5, 70, "S40"],
    ["2026-10-02", "Teads", "TEADS-VID", "2", 2000, 2, 0.1, 90, "S40"],
    ["2026-10-06", "Teads", "TEADS-VID", "2", 0, 4, 0, 0, "S41"],                      // click tracker : clics seuls
  ]};
let r = P.compute(t, {rows: ["Site (CM360)"], col: "", values: ["Impressions", "Clicks", "Click Rate", "Active View: % Viewable Impressions"]});
assert.deepEqual(r.header, ["Site (CM360)", "Impressions", "Clicks", "Click Rate", "Active View: % Viewable Impressions"]);
assert.deepEqual(r.rows[0].slice(0, 3), ["Le Monde", 4000, 25]);                         // trié par impressions décroissantes
assert.equal(r.rows[0][3], 25 / 4000 * 100);                                            // CTR recalculé, pas additionné
assert.equal(r.rows[0][4], (50 * 1000 + 70 * 3000) / 4000);                              // visibilité pondérée par les impressions
assert.deepEqual(r.total.slice(0, 3), ["Total", 6000, 31]);
assert.equal(r.total[3], 31 / 6000 * 100);
r = P.compute(t, {rows: ["Site (CM360)"], col: "Semaine", values: ["Clicks", "Impressions"]});
assert.deepEqual(r.header, ["Site (CM360)", "S40", "S41", "Total"]);                     // une seule valeur avec des colonnes
assert.deepEqual(r.rows.find((x) => x[0] === "Teads"), ["Teads", 2, 4, 6]);
r = P.compute(t, {rows: ["Site (CM360)", "Placement"], col: "", values: ["Impressions"], sort: {by: "Placement", dir: 1}});
assert.deepEqual(r.rows.map((x) => x[1]), ["LM-PAVE", "TEADS-VID"]);
assert.deepEqual(r.total, ["Total", "", 6000]);
const names = P.presets(t).map((p) => p.name);
assert.deepEqual(names, ["Par régie", "Par emplacement", "Par jour", "Par semaine", "Régie × semaine", "Emplacement × jour"]);
console.log("OK : tableau croisé (sommes, taux recalculés, colonnes, tri, préréglages).");

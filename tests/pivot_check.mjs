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
// Filtres : exclure / garder des valeurs avant le croisement
r = P.compute(t, {rows: ["Site (CM360)"], values: ["Impressions"], filters: [{col: "Site (CM360)", mode: "exclude", values: ["Teads"]}]});
assert.deepEqual(r.rows.map((x) => x[0]), ["Le Monde"]);
assert.deepEqual(r.total, ["Total", 4000]);
r = P.compute(t, {rows: ["Date"], values: ["Clicks"], filters: [{col: "Semaine", mode: "include", values: ["S41"]}]});
assert.deepEqual(r.rows, [["2026-10-06", 4]]);
assert.deepEqual(P.dimValues(t, "Site (CM360)").map((v) => v.value), ["Le Monde", "Teads"]);    // les plus lourdes d'abord
console.log("OK : tableau croisé (sommes, taux recalculés, colonnes, tri, préréglages).");

// Comparaison de périodes : dernier jour 2026-10-06 (mardi) -> semaine du 05/10 contre celle du 28/09
let per = P.periods(t, "week");
assert.deepEqual([per.a, per.b], [["2026-10-05", "2026-10-11"], ["2026-09-28", "2026-10-04"]]);
assert.deepEqual(P.periods(t, "7d").a, ["2026-09-30", "2026-10-06"]);
assert.deepEqual(P.periods(t, "month").b, ["2026-09-01", "2026-09-30"]);
assert.equal(P.periods(t, "custom", {a: ["2026-10-05", "2026-10-01"], b: ["2026-10-01", "2026-10-02"]}), null);   // dates à l'envers
let c = P.compare(t, {rows: ["Site (CM360)"], values: ["Impressions", "Clicks", "Click Rate"],
                      compare: {mode: "custom", a: ["2026-10-02", "2026-10-06"], b: ["2026-10-01", "2026-10-01"]}});
assert.deepEqual(c.header.slice(0, 4), ["Site (CM360)", "Impressions · A", "Impressions · B", "Δ Impressions (%)"]);
assert.equal(c.header[9], "Δ Click Rate (pts)");
const lm = c.rows.find((x) => x[0] === "Le Monde"), td = c.rows.find((x) => x[0] === "Teads");
assert.deepEqual(lm.slice(1, 4), [3000, 1000, 200]);                                    // +200 %
assert.equal(lm[9], 15 / 3000 * 100 - 10 / 1000 * 100);                                  // écart de CTR en points
assert.deepEqual(td.slice(1, 4), [2000, 0, null]);                                      // absent en B : variation non calculable
assert.deepEqual(c.total.slice(0, 4), ["Total", 5000, 1000, 400]);
assert.equal(P.compare({columns: t.columns.slice(1), rows: []}, {rows: ["Placement"], compare: {mode: "week"}}), null);  // sans colonne Date
console.log("pivot compare ok");

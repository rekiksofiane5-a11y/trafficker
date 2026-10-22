// Assistant « Prompt CM360 » : demandes types -> prompt, réglages, questions (node tests/cm_prompt_check.mjs)
import assert from "node:assert/strict";
import "../web/cm_prompt.js";
const P = globalThis.CMPrompt;
const ctx = {today: "2026-10-22", sites: ["DV360 Open Market", "Le Monde"],
             campaign: {name: "Citrate 2026", advertiser: "UPSA", start: "2026-10-16", end: "2026-10-30"}};

// Demande complète : aucune question, période de campagne bornée à aujourd'hui, filtre régie, programmation
let a = P.analyze("impressions et clics par jour et par emplacement depuis le début de la campagne, à envoyer chaque lundi à Trafic@LeMonde.fr pour Le Monde", ctx);
assert.deepEqual(a.questions, []);
let b = P.build(a.spec);
assert.match(b.prompt, /^Create a flat table report for the campaign "Citrate 2026" \(advertiser "UPSA"\), from October 16, 2026 to October 22, 2026\./);
assert.match(b.prompt, /Rows \(dimensions\): Date, Site \(CM360\), Placement and Placement ID\./);
assert.match(b.prompt, /Columns \(metrics\): Impressions, Clicks and Click Rate\./);
assert.match(b.prompt, /Only include the site "Le Monde"\./);
assert.ok(b.notes.some((n) => n.includes("Last 7 days") && n.includes("trafic@lemonde.fr") && n.includes("minuit")));
assert.ok(b.notes.some((n) => n.includes("60 jours")));
assert.ok(b.notes.some((n) => n.includes("jamais un filtre")));

// « semaine dernière » = période, pas la dimension Semaine
a = P.analyze("clics par régie la semaine dernière", ctx);
assert.equal(a.spec.range.kind, "LAST_WEEK");
assert.deepEqual(a.spec.dimensions, ["site"]);
assert.deepEqual(a.spec.metrics, ["clicks"]);

// Demande vague sans contexte : campagne, période et découpage demandés ; métriques par défaut
a = P.analyze("visibilité", {today: "2026-10-22"});
assert.deepEqual(a.questions.map((q) => q.id), ["campaign", "range", "dimensions"]);
let s = P.answer(a.spec, {campaign: "Noël 2026", range: "CUSTOM", start: "2026-12-01", end: "2026-12-24", dimensions: ["placement"]}, {today: "2026-10-22"});
assert.deepEqual(P.missing(s), []);
b = P.build(s);
assert.match(b.prompt, /campaign "Noël 2026".*from December 1, 2026 to December 24, 2026/);
assert.match(b.prompt, /Site \(CM360\), Placement and Placement ID/);               // site ajouté avec l'emplacement
assert.match(b.prompt, /Active View: % Viewable Impressions/);

// Dates explicites, N derniers jours, pas de campagne = toutes les campagnes de l'annonceur
assert.equal(P.analyze("conversions par site du 01/10 au 15/10/2026", ctx).spec.range.en, "from October 1, 2026 to October 15, 2026");
assert.equal(P.analyze("clics par device les 14 derniers jours", ctx).spec.range.en, "for the last 14 days");
b = P.build(P.answer(P.analyze("impressions par campagne hier", {today: "2026-10-22", campaign: {advertiser: "UPSA"}}).spec, {campaign: ""}, {}));
assert.match(b.prompt, /for all campaigns of the advertiser "UPSA", for yesterday/);
console.log("OK : prompt CM360 (questions, période, dimensions, filtres, programmation).");

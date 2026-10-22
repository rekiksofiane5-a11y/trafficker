// Assistant « Prompt CM360 » : une demande en français, même sommaire (« clics par régie la
// semaine dernière »), devient un prompt complet pour « Generate report » de CM360 (Report
// Builder), plus les réglages manuels équivalents. Ce qui manque (campagne, période,
// découpage) est demandé à l'utilisateur. Sans API ni IA : règles déterministes, testables.
(function (root) {
  "use strict";

  const norm = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

  // Métriques et dimensions : nom affiché dans CM360 + mots qui les désignent (FR / EN)
  const METRICS = {
    impressions: {cm: "Impressions", fr: "Impressions", re: /impr|\bimps?\b|volume|diffusion|livr/},
    clicks: {cm: "Clicks", fr: "Clics", re: /\bclics?\b|\bclicks?\b/},
    ctr: {cm: "Click Rate", fr: "CTR", re: /\bctr\b|taux de clic|click rate/},
    conversions: {cm: "Total Conversions", fr: "Conversions", re: /conver|\bventes?\b|\bleads?\b/},
    cost: {cm: "Media Cost", fr: "Coût média", re: /\bcouts?\b|depense|\bspend\b|\bcost\b|budget/},
    viewability: {cm: "Active View: % Viewable Impressions", fr: "Visibilité (% impressions visibles)", re: /visibil|viewab|active view|mesurab/},
    video: {cm: "Video Completions", fr: "Vidéos vues en entier", re: /completion|\bvtr\b|quartile|video vue|vues? completes?/},
    reach: {cm: "Unique Reach: Impression Reach", fr: "Couverture (reach)", re: /\breach\b|couverture|\buniques?\b/},
    frequency: {cm: "Unique Reach: Average Impression Frequency", fr: "Fréquence moyenne", re: /frequence|frequency|repetition/},
  };
  const DIMENSIONS = {
    date: {cm: "Date", fr: "Jour", re: /\bjours?\b|quotidien|\bdaily\b|par date|journalier|jour par jour/},
    week: {cm: "Week", fr: "Semaine", re: /par semaine|hebdo|\bweekly\b/},
    month: {cm: "Month", fr: "Mois", re: /par mois|mensuel|\bmonthly\b/},
    campaign: {cm: "Campaign", fr: "Campagne", re: /par campagne|by campaign|toutes les campagnes|chaque campagne/},
    site: {cm: "Site (CM360)", fr: "Régie / site", re: /regie|\bsites?\b|publisher|editeur|\bsupports?\b|\bmedias?\b/},
    placement: {cm: "Placement", fr: "Emplacement", re: /emplacement|placement/},
    ad: {cm: "Ad", fr: "Annonce", re: /\bannonces?\b|par ad\b/},
    creative: {cm: "Creative", fr: "Créative", re: /\bcreas?\b|creative|creatif|visuel/},
    size: {cm: "Placement Size", fr: "Format", re: /\bformats?\b|taille|\bsize\b|dimension/},
    device: {cm: "Platform Type", fr: "Device", re: /device|appareil|mobile|desktop|tablette|plateforme/},
    country: {cm: "Country", fr: "Pays", re: /\bpays\b|country|\bgeo\b/},
    city: {cm: "City", fr: "Ville", re: /\bvilles?\b|\bcity\b|par region/},
  };
  const DIM_ORDER = ["date", "week", "month", "campaign", "site", "placement", "ad", "creative", "size", "device", "country", "city"];
  const RANGES = [
    {kind: "YESTERDAY", fr: "Hier", en: "for yesterday", re: /\bhier\b|yesterday/},
    {kind: "TODAY", fr: "Aujourd'hui", en: "for today", re: /aujourd.?hui|\btoday\b/},
    {kind: "LAST_WEEK", fr: "Semaine dernière", en: "for last week", re: /semaine (derniere|precedente)|derniere semaine|last week/},
    {kind: "LAST_MONTH", fr: "Mois dernier", en: "for last month", re: /mois (dernier|precedent)|dernier mois|last month/},
    {kind: "MONTH_TO_DATE", fr: "Mois en cours", en: "for the month to date", re: /ce mois|mois en cours|month to date/},
    {kind: "CAMPAIGN", fr: "Depuis le début de la campagne", en: "", re: /depuis le debut|debut de (la )?campagne|toute la campagne|since (the )?start|campaign to date|cumul/},
  ];
  const MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

  const iso = (d) => d.toISOString().slice(0, 10);
  const en = (isoDay) => { const [y, m, d] = isoDay.split("-").map(Number); return `${MONTHS_EN[m - 1]} ${d}, ${y}`; };
  const fr = (isoDay) => isoDay ? isoDay.split("-").reverse().join("/") : "";

  function parseDate(tok, year) {
    const m = tok.match(/^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?$/);
    if (!m) return "";
    let y = m[3] ? Number(m[3]) : year;
    if (y && y < 100) y += 2000;
    if (!y) return "";
    const d = new Date(Date.UTC(y, Number(m[2]) - 1, Number(m[1])));
    return d.getUTCMonth() === Number(m[2]) - 1 ? iso(d) : "";
  }

  function findRange(t, today) {
    const n = t.match(/(\d{1,3}) (derniers? jours|last days|days)/) || t.match(/last (\d{1,3}) days/);
    if (n) return {kind: "LAST_N", days: Number(n[1]), fr: `${n[1]} derniers jours`, en: `for the last ${n[1]} days`};
    const toks = t.match(/\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?/g);
    if (toks && toks.length >= 2) {
      const year = Number((toks[1].match(/[/.-](\d{4})$/) || toks[0].match(/[/.-](\d{4})$/) || [])[1]) || Number(today.slice(0, 4));
      const a = parseDate(toks[0], year), b = parseDate(toks[1], year);
      if (a && b && a <= b) return {kind: "CUSTOM", start: a, end: b, fr: `du ${fr(a)} au ${fr(b)}`, en: `from ${en(a)} to ${en(b)}`};
    }
    for (const r of RANGES) if (r.re.test(t)) return {kind: r.kind, fr: r.fr, en: r.en};
    return null;
  }

  // Demande -> spécification + questions sur ce qui manque
  function analyze(text, ctx = {}) {
    const t = norm(text);
    const today = ctx.today || iso(new Date());
    const camp = ctx.campaign || {};
    const spec = {metrics: [], dimensions: [], range: null, campaign: camp.name || "", advertiser: camp.advertiser || "",
                  sites: [], schedule: null, emails: [], defaults: []};
    // Période d'abord (« semaine dernière » ne doit pas devenir la dimension Semaine)
    spec.range = findRange(t, today);
    const rest = t.replace(/semaine (derniere|precedente)|derniere semaine|mois (dernier|precedent)|dernier mois|ce mois|mois en cours/g, " ");
    for (const [k, m] of Object.entries(METRICS)) if (m.re.test(rest)) spec.metrics.push(k);
    for (const k of DIM_ORDER) if (DIMENSIONS[k].re.test(rest)) spec.dimensions.push(k);
    if (spec.range && spec.range.kind === "CAMPAIGN") {
      if (camp.start && camp.end) {
        const end = camp.end < today ? camp.end : today;
        spec.range = {kind: "CUSTOM", start: camp.start, end, fr: `depuis le début de la campagne (${fr(camp.start)} → ${fr(end)})`,
                      en: `from ${en(camp.start)} to ${en(end)}`};
      } else spec.range = null;                                   // dates de campagne inconnues : à demander
    }
    // Campagne citée entre guillemets
    const q = String(text || "").match(/[«"“]\s*([^»"”]{3,120}?)\s*[»"”]/);
    if (q) spec.campaign = q[1];
    // Régies citées par leur nom (régies de la campagne choisie)
    for (const s of ctx.sites || []) if (s && norm(s).length > 2 && t.includes(norm(s))) spec.sites.push(s);
    // Programmation et destinataires (« à envoyer chaque lundi à x@y.fr »)
    spec.emails = (String(text || "").match(/[^\s@<>,;]+@[^\s@<>,;]+\.[a-z]{2,}/gi) || []).map((e) => e.toLowerCase());
    const day = (t.match(/(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)/) || [])[1];
    if (/chaque jour|tous les jours|quotidien/.test(t) && /envo|program|schedul|mail/.test(t)) spec.schedule = {fr: "tous les jours", en: "daily"};
    else if (day || /hebdo|chaque semaine/.test(t)) spec.schedule = {fr: day ? `chaque ${day}` : "chaque semaine", en: day ? `weekly on ${{lundi: "Monday", mardi: "Tuesday", mercredi: "Wednesday", jeudi: "Thursday", vendredi: "Friday", samedi: "Saturday", dimanche: "Sunday"}[day]}` : "weekly"};
    else if (/chaque mois|mensuel/.test(t) && /envo|program|mail/.test(t)) spec.schedule = {fr: "chaque mois", en: "monthly"};
    if (spec.schedule && spec.dimensions.includes("date") === false && /envo|program/.test(t)) spec.dimensions.unshift("date");
    if (!spec.metrics.length) { spec.metrics = ["impressions", "clicks", "ctr"]; spec.defaults.push("Métriques non précisées : impressions, clics et CTR par défaut."); }
    if (spec.metrics.includes("clicks") && spec.metrics.includes("impressions") && !spec.metrics.includes("ctr")) spec.metrics.push("ctr");
    if (spec.dimensions.includes("placement") && !spec.dimensions.includes("site")) spec.dimensions.splice(spec.dimensions.indexOf("placement"), 0, "site");
    const questions = [];
    if (!spec.campaign) questions.push({id: "campaign", label: "Sur quelle campagne ? (nom exact dans CM360)", type: "text",
                                        hint: "Laissez vide pour toutes les campagnes de l'annonceur."});
    if (!spec.range) questions.push({id: "range", label: "Sur quelle période ?", type: "choice",
      options: [...RANGES.filter((r) => r.kind !== "CAMPAIGN" || (camp.start && camp.end)).map((r) => [r.kind, r.fr]),
                ["LAST_N:30", "30 derniers jours"], ["CUSTOM", "Dates précises…"]]});
    if (!spec.dimensions.length) questions.push({id: "dimensions", label: "Découper par…", type: "multi",
      options: DIM_ORDER.map((k) => [k, DIMENSIONS[k].fr]), preset: ["site", "placement"]});
    return {spec, questions};
  }

  // Réponses aux questions -> spécification complète
  function answer(spec, answers, ctx = {}) {
    const s = {...spec, dimensions: [...spec.dimensions]};
    const camp = ctx.campaign || {};
    const today = ctx.today || iso(new Date());
    if (answers.campaign !== undefined) s.campaign = String(answers.campaign).trim();
    if (answers.dimensions) s.dimensions = DIM_ORDER.filter((k) => answers.dimensions.includes(k));
    if (s.dimensions.includes("placement") && !s.dimensions.includes("site")) s.dimensions.splice(s.dimensions.indexOf("placement"), 0, "site");
    const r = answers.range;
    if (r === "CUSTOM" && answers.start && answers.end && answers.start <= answers.end) {
      s.range = {kind: "CUSTOM", start: answers.start, end: answers.end, fr: `du ${fr(answers.start)} au ${fr(answers.end)}`,
                 en: `from ${en(answers.start)} to ${en(answers.end)}`};
    } else if (r && r.startsWith("LAST_N:")) {
      const n = r.split(":")[1];
      s.range = {kind: "LAST_N", days: Number(n), fr: `${n} derniers jours`, en: `for the last ${n} days`};
    } else if (r === "CAMPAIGN" && camp.start && camp.end) {
      const end = camp.end < today ? camp.end : today;
      s.range = {kind: "CUSTOM", start: camp.start, end, fr: `depuis le début de la campagne (${fr(camp.start)} → ${fr(end)})`,
                 en: `from ${en(camp.start)} to ${en(end)}`};
    } else if (r) {
      const def = RANGES.find((x) => x.kind === r);
      if (def) s.range = {kind: r, fr: def.fr, en: def.en};
    }
    return s;
  }

  function missing(spec) {
    return [!spec.range && "période", !spec.dimensions.length && "découpage"].filter(Boolean);
  }

  const list = (a) => a.length <= 1 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1];

  // Spécification -> prompt anglais pour CM360 + réglages manuels + remarques
  function build(spec) {
    const dims = spec.dimensions.map((k) => DIMENSIONS[k].cm);
    if (spec.dimensions.includes("placement")) dims.splice(dims.indexOf("Placement") + 1, 0, "Placement ID");
    const mets = spec.metrics.map((k) => METRICS[k].cm);
    const scope = spec.campaign ? `for the campaign "${spec.campaign}"${spec.advertiser ? ` (advertiser "${spec.advertiser}")` : ""}`
      : spec.advertiser ? `for all campaigns of the advertiser "${spec.advertiser}"` : "for all my campaigns";
    const parts = [`Create a flat table report ${scope}, ${spec.range.en}.`,
                   `Rows (dimensions): ${list(dims)}.`, `Columns (metrics): ${list(mets)}.`];
    if (spec.sites.length) parts.push(`Only include the site${spec.sites.length > 1 ? "s" : ""} ${list(spec.sites.map((s) => `"${s}"`))}.`);
    const time = ["date", "week", "month"].find((k) => spec.dimensions.includes(k));
    parts.push(time ? `Sort by ${DIMENSIONS[time].cm} ascending, then by ${mets[0]} descending.` : `Sort by ${mets[0]} descending.`);
    const prompt = parts.join(" ");
    const settings = [
      ["Type", "Flat table"],
      ["Date range", spec.range.kind === "CUSTOM" ? `${fr(spec.range.start)} → ${fr(spec.range.end)}` : spec.range.fr],
      ["Dimensions (ROW)", dims.join(", ")],
      ["Metrics (COLUMN)", mets.join(", ")],
      ["Filter", [spec.campaign && `Campaign = ${spec.campaign}`, spec.advertiser && !spec.campaign && `Advertiser = ${spec.advertiser}`,
                  spec.sites.length && `Site (CM360) = ${spec.sites.join(" | ")}`].filter(Boolean).join(" ; ") || "—"],
    ];
    // Règles de l'aide CM360 « Instant reporting » (support.google.com/campaignmanager/answer/7674615)
    const notes = [...(spec.defaults || [])];
    if (spec.schedule) {
      const rel = {daily: "Yesterday", monthly: "Previous month"}[spec.schedule.en] || (spec.schedule.en.startsWith("weekly") ? "Last 7 days" : "");
      notes.push(`Programmation (à régler à la main, pas par le prompt) : « Save », puis l'icône « Schedule and delivery » → `
        + `activer « Schedule status », fuseau horaire Europe/Paris, fréquence ${spec.schedule.fr}`
        + (rel ? `, plage de dates relative « ${rel} » (une plage fixe ne glisse pas d'un envoi à l'autre)` : "")
        + ` ; activer « Delivery » → « Attachment » (ou « Link to report » si le fichier dépasse 25 Mo), « Email owner »`
        + (spec.emails.length ? `, « Add people » : ${spec.emails.join(", ")}` : ", « Add people » : e-mails de la régie")
        + `. L'envoi part à minuit dans le fuseau choisi.`);
      notes.push("Un rapport programmé jamais téléchargé depuis 60 jours ou en échec depuis 30 jours est désactivé ; "
        + "il s'arrête aussi si son propriétaire devient inactif ou perd ses droits de reporting.");
    } else if (spec.emails.length) {
      notes.push(`Destinataires repérés (${spec.emails.join(", ")}) : à saisir dans « Schedule and delivery » → « Add people » après « Save ».`);
    }
    if (spec.dimensions.some((k) => ["date", "week", "month"].includes(k)))
      notes.push("La date est une colonne, jamais un filtre : la période se règle uniquement dans « Date range ».");
    notes.push("Rester en « Flat table » : un tableau croisé (pivot) n'est que téléchargeable et ne s'exécute pas avec plusieurs métriques pivotées.");
    if (spec.dimensions.length >= 3) notes.push("Si le rapport ne charge pas : réduire la période ou retirer une dimension, ou cliquer « Download » pour obtenir les données complètes.");
    if (spec.metrics.includes("viewability")) notes.push("Visibilité : nécessite la mesure Active View sur les emplacements.");
    if (spec.metrics.includes("reach") || spec.metrics.includes("frequency")) notes.push("Couverture / fréquence : métriques « Unique Reach », disponibles sur des périodes limitées selon le compte.");
    notes.push("Generate report est en bêta : vérifiez dimensions, métriques et filtres proposés par CM360 avant « Run report ».");
    return {prompt, settings, notes};
  }

  const api = {analyze, answer, build, missing, METRICS, DIMENSIONS};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.CMPrompt = api;
})(typeof self !== "undefined" ? self : globalThis);

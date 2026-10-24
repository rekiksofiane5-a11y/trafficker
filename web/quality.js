// Contrôles qualité Agopis, partagés par la page et le Worker (module ES sans dépendance) :
// - avant mise en ligne : UTM des URL de destination, cohérence budgets / volumes du PM ;
// - après lancement : alertes de surveillance (aucune impression, rythme, budget à mi-campagne,
//   écart régie / ad server, emplacement à l'arrêt), fusionnées avec les alertes déjà connues.

export const DEFAULT_THRESHOLDS = {
  no_delivery_hours: 24,   // heures après le démarrage sans aucune impression
  pacing_low: 80,          // % du prévu à date en dessous duquel le rythme est en alerte
  mid_budget_gap: 20,      // écart (%) budget consommé / attendu, vérifié à partir de la mi-campagne
  regie_gap: 10,           // écart (%) entre les chiffres déclarés par la régie et ceux de l'ad server
  paused_days: 2,          // jours consécutifs sans impression pour un emplacement qui diffusait
};
export const THRESHOLD_LABELS = {
  no_delivery_hours: "Aucune impression après (heures)",
  pacing_low: "Rythme en alerte sous (% du prévu)",
  mid_budget_gap: "Budget à mi-campagne : écart max (%)",
  regie_gap: "Écart régie / ad server max (%)",
  paused_days: "Emplacement à l'arrêt après (jours sans impression)",
};
export const ALERT_KINDS = {
  no_delivery: "Aucune impression", pacing: "Rythme", mid_budget: "Budget mi-campagne",
  regie_gap: "Écart régie", paused: "Emplacement à l'arrêt",
};

export const keyOf = (s) => String(s ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "");
export function num(v) {
  if (typeof v === "number") return v;
  const s = String(v ?? "").replace(/[\s  €]/g, "").replace(/[^\d,.-]/g, "");
  const n = Number(s.includes(",") && !s.includes(".") ? s.replace(",", ".") : s.replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}
const fmt = (n) => Math.round(n).toLocaleString("fr-FR");
const frDate = (iso) => (iso || "").slice(0, 10).split("-").reverse().join("/");
const lines = (idx) => `Ligne(s) ${idx.slice(0, 8).join(", ")}${idx.length > 8 ? " …" : ""}`;
const UTM = ["utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"];

// --- Avant mise en ligne : UTM ------------------------------------------------------------------
export function utmIssues(rows) {
  const out = [], seen = [];
  const bad = [], http = [], missing = [], partial = [], dup = [], holes = [];
  rows.forEach((r, i) => {
    const raw = String(r.landing_page_url || "").trim();
    if (!raw) return;
    let u;
    try { u = new URL(raw); } catch (e) { bad.push(i + 1); return; }
    if (!/^https?:$/.test(u.protocol)) { bad.push(i + 1); return; }
    if (u.protocol === "http:") http.push(i + 1);
    const p = u.searchParams, utm = {};
    for (const k of UTM) if (p.has(k)) utm[k] = p.get(k);
    if (UTM.some((k) => p.getAll(k).length > 1)) dup.push(i + 1);
    if (/\{\{|\}\}|\bxxx+\b|\btodo\b|\[[^\]]*\]/i.test(decodeURIComponent(u.search))) holes.push(i + 1);
    if (utm.utm_source && (!utm.utm_medium || !utm.utm_campaign)) partial.push(i + 1);
    seen.push({i: i + 1, site: r.site_name || "", utm});
  });
  if (bad.length) out.push({level: "block", text: `URL de destination invalide (${bad.length})`, sub: lines(bad)});
  if (http.length) out.push({level: "warn", text: `URL en http au lieu de https (${http.length})`, sub: lines(http)});
  const tagged = seen.filter((s) => s.utm.utm_source || s.utm.utm_campaign);
  if (tagged.length && tagged.length < seen.length) {
    for (const s of seen) if (!s.utm.utm_source && !s.utm.utm_campaign) missing.push(s.i);
    out.push({level: "warn", text: `UTM absentes sur ${missing.length} ligne(s) alors que les autres en ont`, sub: lines(missing)});
  }
  if (partial.length) out.push({level: "warn", text: "UTM incomplètes : utm_medium ou utm_campaign manquant", sub: lines(partial)});
  if (dup.length) out.push({level: "warn", text: "Paramètre UTM répété dans la même URL", sub: lines(dup)});
  if (holes.length) out.push({level: "warn", text: "Paramètre d'URL non renseigné ({{…}}, [ ], XXX)", sub: lines(holes)});
  const camps = [...new Set(tagged.map((s) => s.utm.utm_campaign).filter(Boolean))];
  if (camps.length > 1) out.push({level: "warn", text: `utm_campaign différent selon les lignes (${camps.length} valeurs)`,
                                  sub: camps.slice(0, 4).join(" · ") + (camps.length > 4 ? " …" : "")});
  // une même valeur écrite de plusieurs façons (GA4 distingue majuscules et espaces)
  for (const k of UTM) {
    const byNorm = new Map();
    for (const s of tagged) if (s.utm[k]) {
      const n = s.utm[k].toLowerCase().trim();
      if (!byNorm.has(n)) byNorm.set(n, new Set());
      byNorm.get(n).add(s.utm[k]);
    }
    const mixed = [...byNorm.values()].filter((v) => v.size > 1).map((v) => [...v].join(" / "));
    if (mixed.length) out.push({level: "warn", text: `${k} écrit de plusieurs façons (majuscules, espaces)`, sub: mixed.slice(0, 3).join(" · ")});
  }
  const spaced = tagged.filter((s) => Object.values(s.utm).some((v) => /\s/.test(v))).map((s) => s.i);
  if (spaced.length) out.push({level: "warn", text: "Espaces dans des valeurs UTM", sub: lines(spaced)});
  // utm_source : une valeur par régie, et pas la même pour deux régies
  const bySite = new Map(), bySource = new Map();
  for (const s of tagged) {
    if (!s.utm.utm_source || !s.site) continue;
    const site = keyOf(s.site), src = s.utm.utm_source.toLowerCase();
    if (!bySite.has(site)) bySite.set(site, {name: s.site, src: new Set()});
    bySite.get(site).src.add(src);
    if (!bySource.has(src)) bySource.set(src, new Map());
    bySource.get(src).set(site, s.site);
  }
  for (const v of bySite.values())
    if (v.src.size > 1) out.push({level: "warn", text: `${v.name} : plusieurs utm_source (${[...v.src].join(", ")})`});
  if (bySite.size > 1)
    for (const [src, sites] of bySource)
      if (sites.size > 1) out.push({level: "warn", text: `utm_source « ${src} » identique pour ${sites.size} régies`,
                                    sub: [...sites.values()].slice(0, 4).join(" · ")});
  return out;
}

// --- Avant mise en ligne : budgets et volumes du PM -----------------------------------------------
export function budgetIssues(rows, campaign = {}) {
  const out = [], cpms = [], noVol = [], noBudget = [], neg = [];
  // une ligne par emplacement (les lignes de créas répètent le budget de l'emplacement)
  const seen = new Set();
  let sum = 0, withBudget = 0, withVol = 0;
  rows.forEach((r, i) => {
    const id = [r.placement_final || r.placement_name, r.site_name, r.format_label || r.size].map(keyOf).join("|");
    if (seen.has(id)) return;
    seen.add(id);
    const b = num(r.budget_eur), v = num(r.objective_impressions);
    if (String(r.budget_eur || "").trim() && b <= 0) neg.push(i + 1);
    if (b > 0) { sum += b; withBudget++; }
    if (v > 0) withVol++;
    if (b > 0 && !(v > 0)) noVol.push(i + 1);
    if (v > 0 && !(b > 0)) noBudget.push(i + 1);
    const cpc = /cpc/i.test(r.pricing_type || "");
    if (b > 0 && v > 0 && !cpc) cpms.push({i: i + 1, cpm: b / v * 1000});
  });
  if (neg.length) out.push({level: "warn", text: "Budget nul ou négatif", sub: lines(neg)});
  if (withBudget && withVol) {
    if (noVol.length) out.push({level: "warn", text: `Budget sans volume sur ${noVol.length} ligne(s)`, sub: lines(noVol)});
    if (noBudget.length) out.push({level: "warn", text: `Volume sans budget sur ${noBudget.length} ligne(s)`, sub: lines(noBudget)});
  }
  if (cpms.length >= 3) {
    const sorted = cpms.map((c) => c.cpm).sort((a, b) => a - b), med = sorted[Math.floor(sorted.length / 2)];
    const odd = cpms.filter((c) => c.cpm > med * 3 || c.cpm < med / 3);
    if (odd.length) out.push({level: "warn", text: `CPM implicite atypique (médiane ${med.toFixed(2)} €)`,
                              sub: odd.slice(0, 6).map((c) => `ligne ${c.i} : ${c.cpm.toFixed(2)} €`).join(" · ")});
  }
  const total = num(campaign.budget_eur);
  if (total > 0 && sum > 0 && Math.abs(sum - total) / total > 0.01)
    out.push({level: "warn", text: `Somme des budgets des lignes (${fmt(sum)} €) ≠ budget de la campagne (${fmt(total)} €)`});
  return out;
}

// --- Après lancement : évaluation d'une campagne surveillée ---------------------------------------
const day = (iso) => new Date((iso || "").slice(0, 10) + "T00:00:00Z");
const addDays = (iso, n) => { const d = day(iso); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const span = (a, b) => (a && b && b >= a ? Math.round((day(b) - day(a)) / 864e5) + 1 : 0);

// Emplacement de l'ad server -> ligne prévue du plan (nom identique, sinon un nom contenu dans l'autre)
export function matchTargets(placements, targets) {
  const list = (targets && targets.placements) || [], byKey = new Map(list.map((t) => [keyOf(t.name), t]));
  const out = new Map(), used = new Set();
  for (const p of placements) {
    const t = byKey.get(keyOf(p.name));
    if (t && !used.has(t)) { out.set(String(p.id), t); used.add(t); }
  }
  for (const p of placements) {
    const k = keyOf(p.name);
    if (out.has(String(p.id)) || !k) continue;
    const c = list.filter((t) => !used.has(t) && keyOf(t.name) && (keyOf(t.name).includes(k) || k.includes(keyOf(t.name))))
      .sort((a, b) => (keyOf(a.site) !== keyOf(p.site)) - (keyOf(b.site) !== keyOf(p.site)));
    if (c.length) { out.set(String(p.id), c[0]); used.add(c[0]); }
  }
  return out;
}

export function evaluate({campaign = {}, placements = [], delivery = [], targets = null, regie = {}, thresholds = {}, now = new Date()}) {
  const th = {...DEFAULT_THRESHOLDS, ...thresholds};
  const today = new Date(now).toISOString().slice(0, 10), dataEnd = addDays(today, -1);
  const alerts = [];
  const cStart = (campaign.start || "").slice(0, 10), cEnd = (campaign.end || "").slice(0, 10);
  const running = cStart && cStart <= today && (!cEnd || cEnd >= today);
  const per = new Map();
  for (const d of delivery) {
    const id = String(d.placement_id);
    if (!per.has(id)) per.set(id, {total: 0, byDay: new Map()});
    const x = per.get(id), imp = Number(d.impressions) || 0;
    x.total += imp;
    x.byDay.set(d.date, (x.byDay.get(d.date) || 0) + imp);
  }
  const stats = {impressions: [...per.values()].reduce((a, x) => a + x.total, 0), placements: placements.length, running: !!running};

  // 1. aucune impression N heures après le démarrage (regroupé par régie)
  if (running) {
    const silent = new Map();
    for (const p of placements) {
      const s = (p.start || cStart).slice(0, 10), e = (p.end || cEnd).slice(0, 10);
      if (!s || (e && e < s)) continue;
      const hours = (new Date(now) - day(s)) / 36e5;
      if (hours >= th.no_delivery_hours && !((per.get(String(p.id)) || {}).total > 0)) {
        if (!silent.has(p.site)) silent.set(p.site, []);
        silent.get(p.site).push(p.name);
      }
    }
    for (const [site, names] of silent)
      alerts.push({key: "no_delivery:" + keyOf(site), kind: "no_delivery", level: "block",
        text: `${site || "Régie inconnue"} : ${names.length} emplacement(s) sans impression ${th.no_delivery_hours} h après le démarrage`,
        sub: names.slice(0, 3).join(" · ") + (names.length > 3 ? " …" : "")});
  }

  // 2. rythme sous le seuil et 3. budget à mi-campagne (plan lié requis)
  const matched = matchTargets(placements, targets);
  if (running && matched.size) {
    const camp = {planned: 0, expected: 0, delivered: 0, budget: 0, spent: 0, expSpend: 0}, sites = new Map();
    let elapsedC = 0, totalC = 0;
    for (const p of placements) {
      const t = matched.get(String(p.id));
      if (!t) continue;
      const planned = num(t.impressions), budget = num(t.budget);
      const s = (p.start || t.start || cStart).slice(0, 10), e = (p.end || t.end || cEnd).slice(0, 10);
      const total = span(s, e), elapsed = span(s, e && e < dataEnd ? e : dataEnd);
      totalC = Math.max(totalC, total); elapsedC = Math.max(elapsedC, elapsed);
      if (!planned || !total) continue;
      const delivered = (per.get(String(p.id)) || {}).total || 0, expected = planned * elapsed / total;
      const add = (o) => { o.planned += planned; o.expected += expected; o.delivered += delivered;
        if (budget) { o.budget += budget; o.spent += budget * delivered / planned; o.expSpend += budget * elapsed / total; } };
      add(camp);
      if (!sites.has(p.site)) sites.set(p.site, {planned: 0, expected: 0, delivered: 0, budget: 0, spent: 0, expSpend: 0});
      add(sites.get(p.site));
    }
    const pace = (o) => (o.expected ? o.delivered / o.expected * 100 : null);
    if (elapsedC >= 2) {
      const pc = pace(camp);
      if (pc !== null && pc < th.pacing_low)
        alerts.push({key: "pacing:campaign", kind: "pacing", level: "warn",
          text: `Rythme de la campagne : ${Math.round(pc)} % du prévu à date (seuil ${th.pacing_low} %)`,
          sub: `${fmt(camp.delivered)} impressions livrées pour ${fmt(camp.expected)} prévues au ${frDate(dataEnd)}`});
      for (const [site, o] of sites) {
        const ps = pace(o);
        if (ps !== null && ps < th.pacing_low)
          alerts.push({key: "pacing:" + keyOf(site), kind: "pacing", level: "warn",
            text: `${site} : rythme à ${Math.round(ps)} % du prévu à date`, sub: `${fmt(o.delivered)} / ${fmt(o.expected)} impressions`});
      }
    }
    if (totalC && elapsedC / totalC >= 0.5 && camp.expSpend > 0) {
      const gap = (camp.spent - camp.expSpend) / camp.expSpend * 100;
      if (Math.abs(gap) > th.mid_budget_gap)
        alerts.push({key: "mid_budget", kind: "mid_budget", level: "warn",
          text: `Mi-campagne : budget consommé estimé ${fmt(camp.spent)} € pour ${fmt(camp.expSpend)} € attendus (${gap > 0 ? "+" : ""}${Math.round(gap)} %)`,
          sub: `Budget prévu ${fmt(camp.budget)} € · ${elapsedC} / ${totalC} jours écoulés`});
    }
    stats.pacing = pace(camp);
  }

  // 4. écart entre les chiffres déclarés par la régie et ceux de l'ad server (même période)
  for (const [site, r] of Object.entries(regie || {})) {
    const declared = num(r && r.impressions), through = (r && r.through) || dataEnd;
    if (!declared) continue;
    const ids = new Set(placements.filter((p) => keyOf(p.site) === keyOf(site)).map((p) => String(p.id)));
    const ad = delivery.filter((d) => ids.has(String(d.placement_id)) && d.date <= through).reduce((a, d) => a + (Number(d.impressions) || 0), 0);
    if (!ad) continue;
    const gap = (declared - ad) / ad * 100;
    if (Math.abs(gap) > th.regie_gap)
      alerts.push({key: "regie_gap:" + keyOf(site), kind: "regie_gap", level: "warn",
        text: `${site} : écart de ${gap > 0 ? "+" : ""}${Math.round(gap)} % entre la régie et l'ad server`,
        sub: `Régie ${fmt(declared)} · ad server ${fmt(ad)} impressions au ${frDate(through)}`});
  }

  // 5. emplacement à l'arrêt : il diffusait, puis plus rien depuis N jours (ou statut en pause)
  if (running) {
    const n = Math.max(1, Math.round(th.paused_days)), from = addDays(dataEnd, -n + 1);
    for (const p of placements) {
      const e = (p.end || cEnd).slice(0, 10), s = (p.start || cStart).slice(0, 10);
      if (e && e < today) continue;
      const x = per.get(String(p.id));
      const status = String(p.status || "").toUpperCase();
      const off = p.active === false || ["PAUSED", "INACTIVE", "ARCHIVED"].includes(status);
      let stopped = false;
      if (x && x.total > 0 && s && s < from) {
        let recent = 0;
        for (let d = from; d <= dataEnd; d = addDays(d, 1)) recent += x.byDay.get(d) || 0;
        stopped = recent === 0;
      }
      if (off || stopped)
        alerts.push({key: "paused:" + p.id, kind: "paused", level: "block",
          text: `${p.name} : ${off ? "emplacement en pause dans l'ad server" : `aucune impression depuis ${n} jour(s)`} alors que la campagne tourne`,
          sub: `${p.site || ""} · fin prévue ${frDate(e) || "—"}`});
    }
  }
  return {alerts, stats};
}

// Fusion avec les alertes connues : nouvelles (ou rouvertes) à notifier, disparues fermées
export function mergeAlerts(existing, monitor, found, now = Date.now() / 1000) {
  const list = (existing || []).map((a) => ({...a}));
  const fresh = [], keys = new Set(found.map((a) => a.key));
  for (const a of found) {
    const old = list.find((x) => x.monitor_id === monitor.id && x.key === a.key);
    if (old) {
      if (old.status !== "open") { old.status = "open"; old.first = now; fresh.push(old); }
      Object.assign(old, {text: a.text, sub: a.sub || "", level: a.level, last: now});
    } else {
      const n = {id: `${monitor.id}:${a.key}:${Math.round(now)}`, monitor_id: monitor.id, task_id: monitor.task_id || "",
                 campaign: (monitor.campaign || {}).name || "", key: a.key, kind: a.kind, level: a.level, text: a.text,
                 sub: a.sub || "", first: now, last: now, status: "open"};
      list.push(n);
      fresh.push(n);
    }
  }
  for (const a of list) if (a.monitor_id === monitor.id && a.status === "open" && !keys.has(a.key)) { a.status = "closed"; a.closed = now; }
  // on garde les alertes ouvertes et les 300 plus récentes
  const keep = list.sort((a, b) => (b.last || 0) - (a.last || 0)).filter((a, i) => a.status === "open" || i < 300);
  return {list: keep, fresh};
}

export function mailText(monitor, alerts) {
  const c = monitor.campaign || {};
  return [`Agopis — ${alerts.length} nouvelle(s) alerte(s) sur la campagne « ${c.name || ""} »${c.advertiser ? ` (${c.advertiser})` : ""}.`, "",
    ...alerts.map((a) => `• ${a.text}${a.sub ? `\n  ${a.sub}` : ""}`), "",
    "Détail et réglages : onglet Reporting > Check de mise en ligne de la campagne."].join("\n");
}

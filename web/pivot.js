// Tableau croisé dynamique sur un export à plat : lignes (1 ou 2 dimensions), colonnes
// (une dimension, facultative), valeurs (métriques). Les sommes s'additionnent ; les taux sont
// recalculés (CTR = clics / impressions) ou moyennés au prorata des impressions.
(function (root) {
  "use strict";

  const norm = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const find = (cols, re, kind) => cols.findIndex((c) => (!kind || c.kind === kind) && re.test(norm(c.label)) && !/(^|\W)id($|\W)/.test(norm(c.label)));

  // Taux recalculable à partir de deux sommes de la table
  function rateRule(cols, j) {
    const l = norm(cols[j].label);
    const imp = find(cols, /^impressions?$|^impr/, "metric"), clk = find(cols, /^clicks?$|^clics?$/, "metric");
    if (/click rate|ctr|taux de clic/.test(l) && imp >= 0 && clk >= 0) return {num: clk, den: imp, factor: 100};
    return imp >= 0 ? {weight: imp} : {mean: true};
  }

  // Filtres : [{col, mode: "include" | "exclude", values: [...]}] appliqués avant le croisement
  function filterRows(table, filters) {
    const active = (filters || []).map((f) => ({i: table.columns.findIndex((c) => c.label === f.col), mode: f.mode,
                                               set: new Set((f.values || []).map(String))}))
      .filter((f) => f.i >= 0 && f.set.size);
    if (!active.length) return table.rows;
    return table.rows.filter((r) => active.every((f) => (f.mode === "exclude") !== f.set.has(String(r[f.i]))));
  }

  // Valeurs d'une dimension, les plus lourdes d'abord (pour choisir quoi filtrer)
  function dimValues(table, label, limit = 300) {
    const i = table.columns.findIndex((c) => c.label === label);
    const imp = table.columns.findIndex((c) => c.kind === "metric" && /^impressions?$|^impr/.test(norm(c.label)));
    if (i < 0) return [];
    const w = new Map();
    for (const r of table.rows) w.set(r[i], (w.get(r[i]) || 0) + (imp >= 0 ? Number(r[imp]) || 0 : 1));
    return [...w.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([v, n]) => ({value: v, weight: n}));
  }

  function compute(table, spec) {
    table = {columns: table.columns, rows: filterRows(table, spec.filters)};
    const cols = table.columns;
    const idx = (label) => cols.findIndex((c) => c.label === label);
    const rowIdx = (spec.rows || []).map(idx).filter((i) => i >= 0);
    const colIdx = spec.col ? idx(spec.col) : -1;
    let values = (spec.values || []).map(idx).filter((i) => i >= 0 && cols[i].kind === "metric");
    if (!values.length) values = cols.map((c, i) => (c.kind === "metric" ? i : -1)).filter((i) => i >= 0).slice(0, 3);
    if (colIdx >= 0) values = values.slice(0, 1);              // avec des colonnes : une seule valeur affichée
    const sumIdx = [...new Set(cols.map((c, i) => (c.kind === "metric" ? i : -1)).filter((i) => i >= 0))];
    const rules = {};
    for (const v of values) if (cols[v].rate) rules[v] = rateRule(cols, v);

    const newAcc = () => ({sums: Object.fromEntries(sumIdx.map((i) => [i, 0])), w: {}, n: 0});
    const add = (acc, r) => {
      acc.n++;
      for (const i of sumIdx) acc.sums[i] += Number(r[i]) || 0;
      for (const v of values) {
        const ru = rules[v];
        if (ru && ru.weight !== undefined) acc.w[v] = (acc.w[v] || 0) + (Number(r[v]) || 0) * (Number(r[ru.weight]) || 0);
      }
    };
    const val = (acc, v) => {
      if (!acc) return null;
      const ru = rules[v];
      if (!ru) return acc.sums[v];
      if (ru.num !== undefined) return acc.sums[ru.den] ? acc.sums[ru.num] / acc.sums[ru.den] * ru.factor : 0;
      if (ru.weight !== undefined) return acc.sums[ru.weight] ? acc.w[v] / acc.sums[ru.weight] : 0;
      return acc.n ? acc.sums[v] / acc.n : 0;
    };

    const groups = new Map(), colVals = new Map(), total = newAcc();
    for (const r of table.rows) {
      const key = rowIdx.map((i) => r[i]).join("\u0001");
      let g = groups.get(key);
      if (!g) { g = {keys: rowIdx.map((i) => r[i]), all: newAcc(), cells: new Map()}; groups.set(key, g); }
      add(g.all, r);
      add(total, r);
      if (colIdx >= 0) {
        const cv = r[colIdx];
        if (!colVals.has(cv)) colVals.set(cv, newAcc());
        add(colVals.get(cv), r);
        if (!g.cells.has(cv)) g.cells.set(cv, newAcc());
        add(g.cells.get(cv), r);
      }
    }
    const MAX_COLS = 40;
    let colKeys = [...colVals.keys()].sort((a, b) => String(a).localeCompare(String(b), "fr", {numeric: true}));
    const truncatedCols = colKeys.length > MAX_COLS;
    if (truncatedCols) colKeys = colKeys.slice(-MAX_COLS);

    const rowLabels = rowIdx.map((i) => cols[i].label);
    const header = colIdx >= 0 ? [...rowLabels, ...colKeys.map(String), "Total"] : [...rowLabels, ...values.map((v) => cols[v].label)];
    const metricOf = colIdx >= 0 ? () => values[0] : (k) => values[k];
    let rows = [...groups.values()].map((g) => colIdx >= 0
      ? [...g.keys, ...colKeys.map((ck) => val(g.cells.get(ck), values[0])), val(g.all, values[0])]
      : [...g.keys, ...values.map((v) => val(g.all, v))]);
    // Tri : par une colonne choisie, sinon par la première valeur (ou le total) décroissante
    const sortCol = spec.sort && header.includes(spec.sort.by) ? header.indexOf(spec.sort.by) : (colIdx >= 0 ? header.length - 1 : rowLabels.length);
    const dir = spec.sort && spec.sort.dir ? spec.sort.dir : (sortCol < rowLabels.length ? 1 : -1);
    rows.sort((a, b) => {
      const x = a[sortCol], y = b[sortCol];
      if (typeof x === "number" || typeof y === "number") return ((x || 0) - (y || 0)) * dir;
      return String(x).localeCompare(String(y), "fr", {numeric: true}) * dir;
    });
    const totalRow = colIdx >= 0
      ? ["Total", ...rowLabels.slice(1).map(() => ""), ...colKeys.map((ck) => val(colVals.get(ck), values[0])), val(total, values[0])]
      : ["Total", ...rowLabels.slice(1).map(() => ""), ...values.map((v) => val(total, v))];
    if (!rowLabels.length) { rows = []; }
    return {header, rows, total: totalRow, rowDims: rowLabels.length, values: values.map((v) => cols[v].label),
            rateCols: header.map((h, k) => k >= rowLabels.length && cols[metricOf(k - rowLabels.length)] && !!cols[metricOf(k - rowLabels.length)].rate),
            groups: groups.size, truncatedCols, sourceRows: table.rows.length};
  }

  // --- Comparaison de deux périodes (A = la plus récente, B = la précédente) ---
  const dateCol = (cols) => find(cols, /^date$|^jour$|^day$/, "dimension");
  const iso = (d) => d.toISOString().slice(0, 10);
  const shift = (s, days) => { const d = new Date(s + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + days); return iso(d); };

  // mode : "7d" (7 derniers jours vs 7 précédents), "week" (semaine lun.-dim. du dernier jour vs la précédente),
  // "month" (mois du dernier jour vs le précédent), "custom" ({a: [début, fin], b: [début, fin]})
  function periods(table, mode, custom) {
    const di = dateCol(table.columns);
    if (di < 0) return null;
    let last = "";
    for (const r of table.rows) { const v = String(r[di] || ""); if (/^\d{4}-\d{2}-\d{2}$/.test(v) && v > last) last = v; }
    if (!last) return null;
    if (mode === "custom") {
      const ok = (p) => Array.isArray(p) && p.length === 2 && p.every((x) => /^\d{4}-\d{2}-\d{2}$/.test(x || "")) && p[0] <= p[1];
      return custom && ok(custom.a) && ok(custom.b) ? {a: custom.a, b: custom.b, last} : null;
    }
    if (mode === "7d") return {a: [shift(last, -6), last], b: [shift(last, -13), shift(last, -7)], last};
    if (mode === "week") {
      const dow = (new Date(last + "T00:00:00Z").getUTCDay() + 6) % 7;          // 0 = lundi
      const mon = shift(last, -dow);
      return {a: [mon, shift(mon, 6)], b: [shift(mon, -7), shift(mon, -1)], last};
    }
    if (mode === "month") {
      const m0 = last.slice(0, 8) + "01";
      const prev = shift(m0, -1);
      return {a: [m0, shift(shift(m0, 32).slice(0, 8) + "01", -1)], b: [prev.slice(0, 8) + "01", prev], last};
    }
    return null;
  }

  function compare(table, spec) {
    const cols = table.columns, di = dateCol(cols);
    const per = periods(table, spec.compare && spec.compare.mode, spec.compare);
    if (di < 0 || !per) return null;
    const inRange = (p) => ({columns: cols, rows: table.rows.filter((r) => { const v = String(r[di] || ""); return v >= p[0] && v <= p[1]; })});
    const base = {...spec, col: "", sort: null};
    const A = compute(inRange(per.a), base), B = compute(inRange(per.b), base);
    const nd = A.rowDims, vals = A.values;
    const rate = vals.map((v) => !!(cols.find((c) => c.label === v) || {}).rate);
    const delta = (a, b, k) => (a === null || b === null ? null : rate[k] ? a - b : b ? (a - b) / b * 100 : null);
    const header = [...A.header.slice(0, nd)], rateCols = header.map(() => false), deltaCols = header.map(() => "");
    vals.forEach((v, k) => {
      header.push(v + " · A", v + " · B", "Δ " + v + (rate[k] ? " (pts)" : " (%)"));
      rateCols.push(rate[k], rate[k], true);
      deltaCols.push("", "", rate[k] ? "pts" : "%");
    });
    const keyOf = (row) => row.slice(0, nd).join("\u0001");
    const map = new Map();
    for (const row of A.rows) map.set(keyOf(row), {keys: row.slice(0, nd), a: row.slice(nd), b: null});
    for (const row of B.rows) {
      const g = map.get(keyOf(row));
      if (g) g.b = row.slice(nd); else map.set(keyOf(row), {keys: row.slice(0, nd), a: null, b: row.slice(nd)});
    }
    const line = (keys, a, b) => [...keys, ...vals.flatMap((_, k) => {
      const x = a ? a[k] : (rate[k] ? null : 0), y = b ? b[k] : (rate[k] ? null : 0);
      return [x, y, delta(x, y, k)];
    })];
    let rows = [...map.values()].map((g) => line(g.keys, g.a, g.b));
    const sortCol = spec.sort && header.includes(spec.sort.by) ? header.indexOf(spec.sort.by) : nd;
    const dir = spec.sort && spec.sort.dir ? spec.sort.dir : (sortCol < nd ? 1 : -1);
    rows.sort((p, q) => {
      const x = p[sortCol], y = q[sortCol];
      if (typeof x === "number" || typeof y === "number") return ((x ?? -Infinity) - (y ?? -Infinity)) * dir;
      return String(x).localeCompare(String(y), "fr", {numeric: true}) * dir;
    });
    if (!nd) rows = [];
    const total = line(A.total.slice(0, nd), A.total.slice(nd), B.total.slice(nd));
    return {header, rows, total, rowDims: nd, values: vals, rateCols, deltaCols, periods: per, compare: true,
            groups: map.size, truncatedCols: false, sourceRows: A.sourceRows + B.sourceRows};
  }

  // Préréglages selon les colonnes présentes
  function presets(table) {
    const cols = table.columns;
    const site = find(cols, /site|regie|publisher|media/, "dimension");
    const pl = find(cols, /placement|emplacement/, "dimension");
    const date = find(cols, /^date$|^jour$|^day$/, "dimension");
    const week = cols.findIndex((c) => c.label === "Semaine");
    const camp = find(cols, /^campaign$|^campagne$/, "dimension");
    const creative = find(cols, /creative|creatif|ad$/, "dimension");
    const device = find(cols, /platform type|device|appareil/, "dimension");
    const L = (i) => (i >= 0 ? cols[i].label : null);
    const metrics = cols.filter((c) => c.kind === "metric").map((c) => c.label);
    const out = [];
    const push = (name, rows, col) => { if (rows.every(Boolean) && (col === undefined || col)) out.push({name, spec: {rows, col: col || "", values: metrics}}); };
    if (camp >= 0 && new Set(table.rows.map((r) => r[camp])).size > 1) push("Par campagne", [L(camp)]);
    push("Par régie", [L(site)]);
    push("Par emplacement", [L(site), L(pl)]);
    push("Par jour", [L(date)]);
    if (week >= 0) push("Par semaine", [L(week)]);
    if (week >= 0) push("Régie × semaine", [L(site)], L(week));
    push("Emplacement × jour", [L(pl)], L(date));
    // Dimensions lues dans la nomenclature des emplacements
    const nom = (label) => cols.findIndex((c) => c.nomenclature && c.label === label);
    const ed = nom("Éditeur"), fmt = nom("Format"), obj = nom("Objectif"), tgt = nom("Ciblage");
    if (ed >= 0) push("Par éditeur", [L(ed)]);
    if (fmt >= 0) push("Par format", [L(fmt)]);
    if (obj >= 0 && fmt >= 0) push("Objectif × format", [L(obj), L(fmt)]);
    if (tgt >= 0) push("Par ciblage", [L(tgt)]);
    if (ed >= 0 && week >= 0) push("Éditeur × semaine", [L(ed)], L(week));
    if (creative >= 0) push("Par créative", [L(creative)]);
    if (device >= 0) push("Par device", [L(device)]);
    return out;
  }

  const api = {compute, presets, filterRows, dimValues, periods, compare};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Pivot = api;
})(typeof self !== "undefined" ? self : globalThis);

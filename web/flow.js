// Décor de l'accueil : des lignes descendent du haut et se divisent en branches de plus en plus fines,
// comme une ligne du plan média qui devient plusieurs emplacements (par format, puis par device,
// ciblage…). Des impulsions lumineuses parcourent les branches ; la souris éclaire la branche la plus
// proche et attire légèrement les nœuds. État du conteneur [data-state] : idle / file (calme, or),
// busy (beaucoup d'impulsions, bleu acier), ready (vert d'eau, feuilles allumées).
// Canvas 2D sans dépendance ; pause hors écran ; image fixe si mouvement réduit.
(function () {
  "use strict";
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isDark = () => document.documentElement.classList.contains("is-dark");
  const PAL = {
    light: {line: [176, 140, 86], node: [154, 116, 64], text: [98, 94, 87], pill: [255, 255, 255], busy: [64, 112, 168], ready: [36, 150, 120]},
    dark: {line: [214, 182, 124], node: [236, 204, 146], text: [200, 192, 176], pill: [28, 40, 62], busy: [130, 180, 235], ready: [111, 211, 181]},
  };
  const STATE = {
    idle: {pulses: 7, speed: 0.22, mix: 0, key: "busy", leaves: 0},
    file: {pulses: 10, speed: 0.3, mix: 0, key: "busy", leaves: 0},
    busy: {pulses: 34, speed: 0.75, mix: 0.85, key: "busy", leaves: 0.3},
    ready: {pulses: 12, speed: 0.3, mix: 0.9, key: "ready", leaves: 1},
  };
  // Arbre : 3 lignes du PM -> formats -> devices / ciblages (positions relatives 0..1)
  const PLAN = [
    {x: 0.17, formats: [{dx: -0.08, label: "Pavé", n: 3}, {dx: 0.08, label: "Bannière", n: 3}]},
    {x: 0.5, formats: [{dx: -0.14, label: "Vidéo", n: 3}, {dx: 0, label: "Native", n: 3}, {dx: 0.14, label: "Habillage", n: 3}]},
    {x: 0.83, formats: [{dx: -0.08, label: "Grand angle", n: 3}, {dx: 0.08, label: "Interstitiel", n: 3}]},
  ];
  const LEAF_TAGS = ["Mobile", "Desktop", "Tablette", "CTV", "18-34", "35-49", "Retarget.", "Contexte"];

  function build() {
    let seed = 11;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    const nodes = [], edges = [], paths = [];
    const node = (x, y, kind, label) => { const n = {x, y, kind, label, ph: rnd() * 6.28}; nodes.push(n); return n; };
    const edge = (a, b, dotted) => { const e = {a, b, dotted}; edges.push(e); return e; };
    for (const root of PLAN) {
      const top = node(root.x + (rnd() - 0.5) * 0.02, -0.04, "top");
      const split = node(root.x, 0.36 + rnd() * 0.04, "split");
      const e0 = edge(top, split, false);
      for (const f of root.formats) {
        const fx = root.x + f.dx, fy = 0.5 + rnd() * 0.05;
        const fmt = node(fx, fy, "format", f.label);
        const e1 = edge(split, fmt, rnd() < 0.3);
        for (let i = 0; i < f.n; i++) {
          const spread = 0.019 * (f.n - 1);
          const lx = fx - spread + (2 * spread * i) / Math.max(1, f.n - 1) + (rnd() - 0.5) * 0.01;
          const mid = node(lx, fy + 0.13 + rnd() * 0.04, "mid");
          const e2 = edge(fmt, mid, rnd() < 0.25);
          // dernier niveau : 2 ou 3 brindilles par branche
          const k = 2 + (rnd() < 0.5 ? 1 : 0);
          for (let j = 0; j < k; j++) {
            const leaf = node(Math.min(0.97, Math.max(0.03, lx + (j - (k - 1) / 2) * 0.014 + (rnd() - 0.5) * 0.006)), 0.8 + rnd() * 0.12, "leaf",
                              LEAF_TAGS[Math.floor(rnd() * LEAF_TAGS.length)]);
            const e3 = edge(mid, leaf, false);
            paths.push([e0, e1, e2, e3]);
          }
        }
      }
    }
    // lignes fines décoratives venant du haut (faisceau)
    const deco = Array.from({length: 9}, () => ({x: 0.1 + rnd() * 0.85, len: 0.12 + rnd() * 0.25, a: 0.25 + rnd() * 0.3}));
    return {nodes, edges, paths, deco};
  }

  function Flow(box) {
    const cv = document.createElement("canvas");
    cv.setAttribute("aria-hidden", "true");
    box.replaceChildren(cv);
    const ctx = cv.getContext("2d");
    const tree = build();
    const host = () => box.closest("[data-state]");
    let W = 0, H = 0, dpr = 1, t = 0, last = 0, raf = 0;
    const cur = {mix: 0, leaves: 0, speed: 0.2, accent: [64, 112, 168]};
    const mouse = {x: -1e4, y: -1e4, tx: -1e4, ty: -1e4, in: 0};
    let pulses = [], hot = null, hotLevel = 0;

    function size() {
      const r = box.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      cv.style.width = W + "px"; cv.style.height = H + "px";
    }
    window.addEventListener("pointermove", (e) => {
      const r = cv.getBoundingClientRect();
      mouse.tx = e.clientX - r.left; mouse.ty = e.clientY - r.top;
    }, {passive: true});
    window.addEventListener("pointerdown", () => {             // clic près d'une branche : une salve d'impulsions
      if (hot) for (let i = 0; i < 6; i++) pulses.push({path: hot, s: -i * 0.06, v: 1.4});
    }, {passive: true});

    // position animée d'un nœud (léger balancement, attiré par la souris)
    function pos(n) {
      if (n.kind === "top") return {x: n.x * W, y: n.y * H};
      let x = n.x * W + Math.sin(t * 0.8 + n.ph) * (n.kind === "leaf" ? 3 : 1.5), y = n.y * H;
      const dx = mouse.x - x, dy = mouse.y - y, d = Math.hypot(dx, dy), R = 140;
      if (d < R) { const f = (1 - d / R) ** 2 * (n.kind === "leaf" ? 14 : 8); x += dx / d * f; y += dy / d * f; }
      return {x, y};
    }
    function curve(e) {
      const a = pos(e.a), b = pos(e.b), dy = b.y - a.y;
      return [a, {x: a.x, y: a.y + dy * 0.55}, {x: b.x, y: b.y - dy * 0.45}, b];
    }
    const bez = (c, u) => {
      const v = 1 - u;
      return {x: v * v * v * c[0].x + 3 * v * v * u * c[1].x + 3 * v * u * u * c[2].x + u * u * u * c[3].x,
              y: v * v * v * c[0].y + 3 * v * v * u * c[1].y + 3 * v * u * u * c[2].y + u * u * u * c[3].y};
    };

    function frame(now) {
      raf = 0;
      if (!box.isConnected || box.offsetParent === null || document.hidden) return;
      const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
      last = now;
      step(dt);
      draw();
      if (!reduce) schedule();
    }
    function schedule() { if (!raf) raf = requestAnimationFrame(frame); }

    function step(dt) {
      const st = STATE[(host() && host().dataset.state) || "idle"] || STATE.idle;
      const pal = isDark() ? PAL.dark : PAL.light;
      const ease = 1 - Math.pow(0.05, dt);
      cur.mix += (st.mix - cur.mix) * ease;
      cur.leaves += (st.leaves - cur.leaves) * ease;
      cur.speed += (st.speed - cur.speed) * ease;
      cur.accent = cur.accent.map((v, i) => v + (pal[st.key][i] - v) * ease);
      mouse.x += (mouse.tx - mouse.x) * Math.min(1, dt * 12);
      mouse.y += (mouse.ty - mouse.y) * Math.min(1, dt * 12);
      t += dt;
      // branche survolée : la feuille la plus proche du curseur (dans un rayon raisonnable)
      let best = null, bd = 90;
      for (const p of tree.paths) {
        const l = pos(p[3].b), d = Math.hypot(l.x - mouse.x, l.y - mouse.y);
        const m = pos(p[2].b), d2 = Math.hypot(m.x - mouse.x, m.y - mouse.y);
        if (Math.min(d, d2) < bd) { bd = Math.min(d, d2); best = p; }
      }
      if (best !== hot && best) hotLevel = 0;
      hot = best || hot;
      hotLevel += ((best ? 1 : 0) - hotLevel) * Math.min(1, dt * 6);
      if (!best && hotLevel < 0.02) hot = null;
      // impulsions : chacune descend un chemin racine -> feuille
      while (pulses.length < st.pulses) pulses.push({path: tree.paths[Math.floor(Math.random() * tree.paths.length)], s: -Math.random() * 0.6, v: 0.7 + Math.random() * 0.6});
      for (const p of pulses) p.s += dt * cur.speed * p.v;
      pulses = pulses.filter((p) => p.s < 1).slice(0, 80);
      if (hot && hotLevel > 0.5 && Math.random() < dt * 3) pulses.push({path: hot, s: 0, v: 1.2});
    }

    function draw() {
      const pal = isDark() ? PAL.dark : PAL.light, dark = isDark();
      const col = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
      const blend = (a, b, m) => a.map((v, i) => v + (b[i] - v) * m);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      // faisceau de fines lignes venant du haut
      ctx.lineWidth = 1;
      for (const d of tree.deco) {
        const g = ctx.createLinearGradient(0, 0, 0, d.len * H);
        g.addColorStop(0, col(pal.line, d.a)); g.addColorStop(1, col(pal.line, 0));
        ctx.strokeStyle = g;
        ctx.beginPath(); ctx.moveTo(d.x * W, 0); ctx.lineTo(d.x * W, d.len * H); ctx.stroke();
      }
      // branches
      const hotSet = new Set(hot ? hot : []);
      for (const e of tree.edges) {
        const c = curve(e), depth = e.b.kind === "split" ? 0 : e.b.kind === "format" ? 1 : e.b.kind === "mid" ? 2 : 3;
        const lit = hotSet.has(e) ? hotLevel : 0;
        ctx.setLineDash(e.dotted ? [2, 5] : []);
        ctx.lineWidth = [1.6, 1.2, 1, 0.8][depth] + lit * 1.2;
        const hotCol = cur.mix > 0.3 ? cur.accent : pal.node;      // survol : or au repos, couleur d'état sinon
        ctx.strokeStyle = col(blend(blend(pal.line, cur.accent, cur.mix * 0.35), hotCol, lit * 0.8), (dark ? 0.55 : 0.6) - depth * 0.08 + lit * 0.4);
        ctx.beginPath(); ctx.moveTo(c[0].x, c[0].y); ctx.bezierCurveTo(c[1].x, c[1].y, c[2].x, c[2].y, c[3].x, c[3].y); ctx.stroke();
      }
      ctx.setLineDash([]);
      // nœuds, étiquettes des formats, feuilles
      ctx.font = "500 11px Inter, system-ui, sans-serif";
      ctx.textBaseline = "middle";
      let fi = 0;
      for (const n of tree.nodes) {
        if (n.kind === "top") continue;
        const p = pos(n);
        if (n.kind === "format" && W >= 480) {                // étiquettes seulement quand il y a la place
          const w = ctx.measureText(n.label).width + 30, x = p.x - w / 2, y = p.y + (fi++ % 2 ? 34 : 12);   // en quinconce
          ctx.fillStyle = col(pal.pill, dark ? 0.85 : 0.9);
          ctx.strokeStyle = col(pal.line, 0.35);
          ctx.beginPath(); ctx.roundRect(x, y, w, 22, 11); ctx.fill(); ctx.stroke();
          ctx.fillStyle = col(blend(pal.node, cur.accent, cur.mix * 0.6), 0.9);
          ctx.beginPath(); ctx.arc(x + 11, y + 11, 3, 0, 6.283); ctx.fill();
          ctx.fillStyle = col(pal.text, 0.95);
          ctx.fillText(n.label, x + 19, y + 11.5);
        }
        const r = n.kind === "split" ? 5 : n.kind === "format" ? 4 : n.kind === "mid" ? 2.4 : 3;
        const leafLit = n.kind === "leaf" ? cur.leaves * (0.5 + 0.5 * Math.sin(t * 2 + n.ph)) : 0;
        const c = blend(pal.node, cur.accent, Math.max(cur.mix * (n.kind === "leaf" ? 0.8 : 0.3), leafLit));
        if (n.kind === "split" || leafLit > 0.1) {
          ctx.fillStyle = col(c, 0.18 + leafLit * 0.25);
          ctx.beginPath(); ctx.arc(p.x, p.y, r * 2.6, 0, 6.283); ctx.fill();
        }
        ctx.fillStyle = col(c, n.kind === "leaf" ? 0.55 + leafLit * 0.45 : 0.9);
        ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.283); ctx.fill();
      }
      // étiquettes des feuilles de la branche survolée (device, ciblage…)
      if (hot && hotLevel > 0.3) {
        const leaf = hot[3].b, p = pos(leaf);
        ctx.fillStyle = col(pal.text, hotLevel);
        ctx.textAlign = "center";
        ctx.fillText(leaf.label, p.x, p.y + 16);
        ctx.textAlign = "start";
      }
      // impulsions lumineuses
      for (const pu of pulses) {
        if (pu.s <= 0) continue;
        const seg = Math.min(3, Math.floor(pu.s * 4)), u = pu.s * 4 - seg;
        const pt = bez(curve(pu.path[seg]), u);
        const c = blend(pal.node, cur.accent, Math.max(cur.mix, 0.15));
        const g = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, 7);
        g.addColorStop(0, col(c, 0.95)); g.addColorStop(0.35, col(c, 0.5)); g.addColorStop(1, col(c, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(pt.x, pt.y, 7, 0, 6.283); ctx.fill();
      }
    }

    size();
    new ResizeObserver(() => { size(); step(0.016); draw(); schedule(); }).observe(box);
    return {wake: () => { last = 0; schedule(); }, still: () => { step(0.016); draw(); }};
  }

  const flows = [...document.querySelectorAll("[data-flow]")].map(Flow);
  const wake = () => flows.forEach((f) => (reduce ? f.still() : f.wake()));
  document.addEventListener("visibilitychange", wake);
  new MutationObserver(wake).observe(document.body, {subtree: true, attributes: true, attributeFilter: ["hidden", "data-state"]});
  new MutationObserver(wake).observe(document.documentElement, {attributes: true, attributeFilter: ["class"]});
  wake();
})();

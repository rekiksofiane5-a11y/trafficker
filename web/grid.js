// Fond animé de l'accueil : trame de points or, traversée de vagues. Suit l'état du conteneur
// [data-state] : idle / file (la trame respire, vague discrète toutes les ~9 s), busy (vagues bleu
// acier continues pendant l'analyse), ready (points « en ligne » vert d'eau, frémissement lent).
// Halo doux sous la souris ; un clic sur le fond lance une vague depuis ce point (au repos, les
// points touchés restent allumés). Bords en fondu. Canvas 2D sans dépendance ; pause hors écran ;
// image fixe (état prêt) si l'utilisateur a demandé moins d'animations.
(function () {
  "use strict";
  const PAL = {
    dark: {line: [214, 182, 124], busy: [130, 180, 235], ready: [111, 211, 181]},
    light: {line: [176, 140, 86], busy: [64, 112, 168], ready: [36, 150, 120]},
  };
  const SPACING = 34, WAVE_SPEED = 250, HALO = 130;
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isDark = () => document.documentElement.classList.contains("is-dark");
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const INTERACTIVE = "button, a, input, select, textarea, label, summary, .up-card, .hero-drop, [role=button]";

  function Grid(box) {
    const cv = document.createElement("canvas");
    cv.setAttribute("aria-hidden", "true");
    box.replaceChildren(cv);
    const ctx = cv.getContext("2d");
    const host = box.parentElement;                      // conteneur qui porte data-state
    let W = 0, H = 0, dpr = 1, t = 0, last = 0, raf = 0, autoT = -10, prevState = "";
    let dots = [], waves = [];
    const mouse = {x: -1e4, y: -1e4};
    const state = () => {
      const s = host.dataset.state || "idle";
      return s === "file" ? "idle" : s;
    };

    function build() {
      dots = [];
      const cols = Math.max(14, Math.round(W / SPACING)), rows = Math.max(8, Math.round(H / SPACING));
      const mx = (W - (cols - 1) * SPACING) / 2, my = (H - (rows - 1) * SPACING) / 2;
      for (let r = 0; r < rows; r++) for (let q = 0; q < cols; q++) {
        const x = mx + q * SPACING, y = my + r * SPACING;
        const fx = Math.min(1, Math.min(x, W - x) / (W * 0.18)), fy = Math.min(1, Math.min(y, H - y) / (H * 0.22));
        dots.push({x, y, lit: 0, live: state() === "ready", ph: Math.random() * 7,
                   edge: Math.max(0, Math.min(1, fx)) * Math.max(0, Math.min(1, fy))});
      }
    }
    function size() {
      const r = box.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      cv.style.width = W + "px"; cv.style.height = H + "px";
      build();
    }
    window.addEventListener("pointermove", (e) => {
      const r = cv.getBoundingClientRect();
      mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
    }, {passive: true});
    // clic sur le fond (pas sur un bouton, un champ ou la carte) : vague depuis ce point
    host.addEventListener("pointerdown", (e) => {
      if (e.target.closest(INTERACTIVE)) return;
      const r = cv.getBoundingClientRect();
      waves.push({x: e.clientX - r.left, y: e.clientY - r.top, t0: t, mode: "launch"});
      wake();
    });

    function emit(mode) {
      if (!dots.length) return;
      const d = dots[Math.floor(Math.random() * dots.length)];
      waves.push({x: d.x, y: d.y, t0: t, mode});
    }
    function step(dt) {
      const s = state();
      if (s !== prevState) {                            // changement d'état : points « en ligne » ou non
        if (s === "ready") dots.forEach((d) => { d.live = true; });
        if (s === "idle" && prevState) dots.forEach((d) => { d.live = false; });
        prevState = s;
        autoT = -10;
      }
      if (s === "idle" && t - autoT > 9) { autoT = t; emit("idle"); }
      if (s === "busy" && t - autoT > 2) { autoT = t; emit("busy"); }
      if (s === "ready" && t - autoT > 7) { autoT = t; emit("shimmer"); }
      for (const w of waves) {
        const ring = (t - w.t0) * WAVE_SPEED;
        for (const d of dots) {
          const dd = Math.hypot(d.x - w.x, d.y - w.y);
          if (Math.abs(dd - ring) < 30) {
            d.lit = Math.max(d.lit, w.mode === "idle" ? 0.5 : 1);
            if (w.mode === "launch") d.live = true;
          }
        }
      }
      waves = waves.filter((w) => (t - w.t0) * WAVE_SPEED < Math.hypot(W, H) + 60);
      for (const d of dots) d.lit = Math.max(0, d.lit - dt * 0.5);
    }
    function draw() {
      const p = isDark() ? PAL.dark : PAL.light, s = state();
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      for (const d of dots) {
        const breathe = (0.13 + 0.05 * Math.sin(t * 0.6 + d.ph)) * (s === "ready" ? 0.6 : 1);
        const dm = Math.hypot(d.x - mouse.x, d.y - mouse.y);
        const glow = reduce ? 0 : Math.max(0, 1 - dm / HALO) * 0.32;
        const lit = d.lit;
        let col = p.line;
        if (s === "busy") col = lit > 0.05 ? p.busy : p.line;
        else if (s === "ready" || d.live || lit > 0.05) col = p.ready;
        let a = (lit > 0.05 ? 0.35 + lit * 0.6 : breathe) + glow;
        if (s === "ready" || d.live) a = Math.max(a, 0.2 + 0.08 * Math.sin(t * 0.4 + d.ph));
        a *= 0.35 + 0.65 * d.edge;
        const rad = 1.4 + lit * 2.4 + (d.live || s === "ready" ? 0.5 : 0) + glow * 1.2;
        ctx.fillStyle = rgba(col, Math.min(1, a).toFixed(3));
        ctx.beginPath(); ctx.arc(d.x, d.y, rad, 0, 6.283); ctx.fill();
      }
      if (!reduce && mouse.x > -1000) {                 // halo doux sous la souris
        const g = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, HALO);
        g.addColorStop(0, rgba(p.line, 0.05)); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }
    }
    function still() {                                  // moins d'animations : image fixe de l'état prêt
      const p = isDark() ? PAL.dark : PAL.light;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      for (const d of dots) {
        ctx.fillStyle = rgba(p.ready, ((0.24 + 0.06 * Math.sin(d.ph)) * (0.35 + 0.65 * d.edge)).toFixed(3));
        ctx.beginPath(); ctx.arc(d.x, d.y, 1.9, 0, 6.283); ctx.fill();
      }
    }
    function frame(now) {
      raf = 0;
      if (!box.isConnected || box.offsetParent === null || document.hidden) return;   // relancé par wake()
      t = now / 1000;
      const dt = Math.min(0.05, last ? t - last : 0.016);
      last = t;
      step(dt);
      draw();
      raf = requestAnimationFrame(frame);
    }
    function wake() {
      if (reduce) { still(); return; }
      if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
    }
    size();
    new ResizeObserver(() => { size(); wake(); }).observe(box);
    return {wake};
  }

  const grids = [...document.querySelectorAll("[data-grid]")].map(Grid);
  const wake = () => grids.forEach((g) => g.wake());
  document.addEventListener("visibilitychange", wake);
  new MutationObserver(wake).observe(document.body, {subtree: true, attributes: true, attributeFilter: ["hidden", "data-state"]});
  new MutationObserver(wake).observe(document.documentElement, {attributes: true, attributeFilter: ["class"]});
  wake();
})();

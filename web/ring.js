// Anneau de particules (décor de l'accueil) : rubans ondulants faits de milliers de points,
// réagit à la souris (les points s'écartent du curseur, l'anneau suit légèrement) et à l'état
// du conteneur [data-state] : idle / file (calme, doré), busy (plus vif, bleu), ready (vert d'eau).
// Canvas 2D sans dépendance ; pause quand l'anneau est caché ; image fixe si mouvement réduit.
(function () {
  "use strict";
  const TAU = Math.PI * 2;
  const reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const isDark = () => document.documentElement.classList.contains("is-dark");
  // Couleurs [r, g, b] par thème : or (rubans), accent d'état (analyse : bleu acier, prêt : vert d'eau)
  const PAL = {
    light: {gold: [168, 126, 64], hi: [120, 88, 40], busy: [64, 112, 168], ready: [36, 150, 120], core: [19, 32, 58]},
    dark: {gold: [222, 188, 128], hi: [255, 226, 170], busy: [130, 180, 235], ready: [111, 211, 181], core: [233, 241, 251]},
  };
  const STATE = {           // vitesse, ampleur des ondulations, part de couleur d'état
    idle: {speed: 1, amp: 1, mix: 0, key: "busy"},
    file: {speed: 1.25, amp: 1.1, mix: 0, key: "busy"},
    busy: {speed: 2.8, amp: 1.7, mix: 0.75, key: "busy"},
    ready: {speed: 0.8, amp: 0.85, mix: 0.85, key: "ready"},
  };
  const RIBBONS = 5, STRANDS = 14, SAMPLES = 260;

  function makeRibbons(seed) {
    let s = seed;
    const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
    return Array.from({length: RIBBONS}, (_, i) => ({
      r: 0.78 + i * 0.045 + rnd() * 0.02,                       // rayon relatif
      waves: [2, 3, 5].map((k) => ({k: k + Math.floor(rnd() * 2), a: 0.025 + rnd() * 0.03, ph: rnd() * TAU, w: (rnd() - 0.5) * 0.9})),
      width: 0.05 + rnd() * 0.05, twist: 1 + Math.floor(rnd() * 3), spin: (rnd() - 0.5) * 0.12, ph: rnd() * TAU,
    }));
  }

  function Ring(box) {
    const cv = document.createElement("canvas");
    cv.setAttribute("aria-hidden", "true");
    box.replaceChildren(cv);
    const ctx = cv.getContext("2d");
    const ribbons = makeRibbons(7 + box.getBoundingClientRect().width | 0);
    const host = () => box.closest("[data-state]");
    let W = 0, H = 0, dpr = 1, t = 0, last = 0, raf = 0;
    const cur = {speed: 1, amp: 1, mix: 0, accent: [64, 112, 168]};
    const mouse = {x: 0, y: 0, in: 0, tx: 0, ty: 0, tin: 0};
    let pulse = 0;

    function size() {
      const r = box.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      cv.style.width = W + "px"; cv.style.height = H + "px";
    }
    function onMove(e) {
      const r = cv.getBoundingClientRect();
      mouse.tx = e.clientX - r.left; mouse.ty = e.clientY - r.top;
      // influence : forte sur l'anneau, nulle au-delà d'une marge autour
      const dx = mouse.tx - W / 2, dy = mouse.ty - H / 2, d = Math.hypot(dx, dy);
      mouse.tin = Math.max(0, Math.min(1, 1.6 - d / (Math.min(W, H) * 0.55)));
    }
    window.addEventListener("pointermove", onMove, {passive: true});
    window.addEventListener("pointerdown", (e) => { onMove(e); if (mouse.tin > 0.2) pulse = 1; }, {passive: true});

    function frame(now) {
      raf = 0;
      if (!box.isConnected) return;
      const visible = box.offsetParent !== null && !document.hidden;
      if (!visible) return;                                   // relancé par le contrôleur
      const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
      last = now;
      const st = STATE[(host() && host().dataset.state) || "idle"] || STATE.idle;
      const pal = isDark() ? PAL.dark : PAL.light;
      const ease = 1 - Math.pow(0.04, dt);                    // transitions douces entre états
      cur.speed += (st.speed - cur.speed) * ease;
      cur.amp += (st.amp - cur.amp) * ease;
      cur.mix += (st.mix - cur.mix) * ease;
      cur.accent = cur.accent.map((v, i) => v + (pal[st.key][i] - v) * ease);
      mouse.x += (mouse.tx - mouse.x) * Math.min(1, dt * 10);
      mouse.y += (mouse.ty - mouse.y) * Math.min(1, dt * 10);
      mouse.in += (mouse.tin - mouse.in) * Math.min(1, dt * 6);
      pulse = Math.max(0, pulse - dt * 0.9);
      t += dt * cur.speed * (1 + mouse.in * 0.6);
      draw(pal);
      if (!reduce) schedule();
    }
    function schedule() { if (!raf) raf = requestAnimationFrame(frame); }

    function draw(pal) {
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      const dark = isDark();
      ctx.globalCompositeOperation = dark ? "lighter" : "source-over";
      const R = Math.min(W, H) * 0.42;
      // l'anneau suit un peu la souris (parallaxe)
      const cx = W / 2 + (mouse.x - W / 2) * 0.05 * mouse.in, cy = H / 2 + (mouse.y - H / 2) * 0.05 * mouse.in;
      const rad = Math.min(W, H) * 0.26, push = R * 0.24;   // zone et force d'écartement autour du curseur
      const col = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
      const blend = (a, b, m) => a.map((v, i) => v + (b[i] - v) * m);
      // cœur : petit disque et anneaux fins
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.26);
      const coreCol = blend(pal.core, cur.accent, cur.mix * 0.7);
      g.addColorStop(0, col(coreCol, dark ? 0.35 : 0.12));
      g.addColorStop(1, col(coreCol, 0));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(cx, cy, R * 0.26, 0, TAU); ctx.fill();
      ctx.strokeStyle = col(blend(pal.gold, cur.accent, cur.mix * 0.5), dark ? 0.35 : 0.3);
      ctx.lineWidth = 1;
      for (const k of [0.14, 0.2]) { ctx.beginPath(); ctx.arc(cx, cy, R * (k + 0.01 * Math.sin(t * 1.3 + k * 9)), 0, TAU); ctx.stroke(); }
      // rubans de points
      const amp = cur.amp * (1 + pulse * 0.8);
      for (let ri = 0; ri < RIBBONS; ri++) {
        const rb = ribbons[ri];
        const c = blend(ri % 2 ? pal.gold : pal.hi, cur.accent, cur.mix * (ri % 2 === 0 ? 1 : 0.15));
        const rot = t * rb.spin + rb.ph;
        for (let s = 0; s < STRANDS; s++) {
          const u = s / (STRANDS - 1) - 0.5;                 // position dans l'épaisseur du ruban
          const alpha = (dark ? 0.55 : 0.8) * (1 - Math.abs(u) * 1.2) + (dark ? 0.08 : 0.14);
          ctx.fillStyle = col(c, alpha.toFixed(3));
          const shift = (s * 0.618) % 1;                     // points décalés d'un brin à l'autre : pas d'alignement radial
          for (let i = 0; i < SAMPLES; i++) {
            const th = ((i + shift) / SAMPLES) * TAU + rot;
            let r = rb.r;
            // chaque brin a sa propre phase : les brins se croisent et forment un maillage
            for (const w of rb.waves) r += w.a * amp * Math.sin(w.k * th + w.ph + u * 1.6 + t * w.w);
            // épaisseur torsadée : le ruban s'élargit et se resserre le long du cercle
            r += u * rb.width * Math.sin(rb.twist * th + t * 0.7 + rb.ph + u * 2.2);
            let x = cx + Math.cos(th) * r * R, y = cy + Math.sin(th) * r * R;
            if (mouse.in > 0.01) {
              const dx = x - mouse.x, dy = y - mouse.y, d = Math.hypot(dx, dy);
              if (d < rad && d > 0.1) { const f = (1 - d / rad) ** 2 * push * mouse.in; x += dx / d * f; y += dy / d * f; }
            }
            ctx.fillRect(x, y, dark ? 1.05 : 1.25, dark ? 1.05 : 1.25);
          }
        }
      }
      ctx.globalCompositeOperation = "source-over";
    }

    size();
    new ResizeObserver(() => { size(); if (reduce) draw(isDark() ? PAL.dark : PAL.light); schedule(); }).observe(box);
    return {wake: () => { last = 0; schedule(); }, still: () => draw(isDark() ? PAL.dark : PAL.light)};
  }

  const rings = [...document.querySelectorAll("[data-ring]")].map(Ring);
  const wake = () => rings.forEach((r) => (reduce ? r.still() : r.wake()));
  // Réveil quand l'anneau redevient visible (changement d'écran, d'onglet, de thème ou d'état)
  document.addEventListener("visibilitychange", wake);
  new MutationObserver(wake).observe(document.body, {subtree: true, attributes: true, attributeFilter: ["hidden", "data-state", "class"]});
  new MutationObserver(wake).observe(document.documentElement, {attributes: true, attributeFilter: ["class"]});
  wake();
})();

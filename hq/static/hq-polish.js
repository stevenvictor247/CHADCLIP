// Finishing touches for the dashboard, built on libraries shipped in /vendor (nothing loads from the internet):
//   Motion: tabs and drop-down menus ease in, the money numbers count up to their new value.
//   PixiJS: drifting fireflies / pollen over the villages (WebGL, loaded after the page is ready).
// Everything here is optional: if a library didn't load or the browser asks for reduced motion, the dashboard works as before.
(function () {
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const M = window.Motion;

  // ---------- Motion ----------
  if (M && !calm) {
    // A tab's sections fade and slide in when you switch to it (the village stage only fades: it is a canvas).
    let first = true;
    document.addEventListener("hq-tab", () => {
      if (first) { first = false; return; }   // not on page load
      const tab = document.body.dataset.tab;
      const secs = [...document.querySelectorAll(`[data-tab~="${tab}"]`)].filter(e => e.style.display !== "none");
      const flat = secs.filter(e => e.id === "towns"), rest = secs.filter(e => e.id !== "towns");
      if (flat.length) M.animate(flat, {opacity: [0, 1]}, {duration: .35});
      if (rest.length) M.animate(rest, {opacity: [0, 1], y: [14, 0]}, {duration: .3, delay: M.stagger(.05)});
    });

    // Drop-down menus pop in when they open.
    document.querySelectorAll(".ddmenu").forEach(menu => {
      let was = menu.classList.contains("open");
      new MutationObserver(() => {
        const now = menu.classList.contains("open");
        if (now && !was) M.animate(menu, {opacity: [0, 1], y: [-6, 0]}, {duration: .18});
        was = now;
      }).observe(menu, {attributes: true, attributeFilter: ["class"]});
    });

    // The money numbers count up (or down) to their new value instead of jumping.
    const parse = t => Number(String(t).replace("−", "-").replace(/[$,]/g, ""));
    const fmt = n => (n < 0 ? "−$" : "$") + Math.abs(n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
    for (const id of ["m-spent", "m-made", "m-net"]) {
      const el = document.getElementById(id);
      if (!el) continue;
      let shown = parse(el.textContent), mine = "", anim = null;   // mine: the last text this tween wrote, which must not restart it
      new MutationObserver(() => {
        if (el.textContent === mine) return;
        const to = parse(el.textContent);
        if (!Number.isFinite(to) || to === shown) return;
        const from = shown, text = el.textContent;
        shown = to;
        anim?.stop();
        anim = M.animate(from, to, {duration: .6, ease: "easeOut", onUpdate: v => { mine = fmt(v); el.textContent = mine; }});
        anim.then(() => { mine = text; el.textContent = text; }, () => {});
      }).observe(el, {childList: true, characterData: true, subtree: true});
    }
  }

  // ---------- PixiJS ambient layer ----------
  const towns = document.getElementById("towns");
  if (!towns || calm) return;
  const load = src => new Promise((ok, no) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = no;
    document.head.appendChild(s);
  });

  async function startAmbient() {
    const host = document.createElement("div");
    host.id = "hq-fx";
    host.setAttribute("aria-hidden", "true");
    host.style.cssText = "position:absolute;inset:0;z-index:2;pointer-events:none;";
    towns.appendChild(host);
    try {
      await load("/vendor/pixi.min.js");
      const app = new PIXI.Application();
      await app.init({resizeTo: host, backgroundAlpha: 0, antialias: true, preference: "webgl", autoDensity: true,
                      resolution: Math.min(window.devicePixelRatio || 1, 2)});
      host.appendChild(app.canvas);
      app.canvas.style.cssText = "width:100%;height:100%;display:block;";
      app.ticker.maxFPS = 30;

      const night = () => !!(window.HQWorld?.sky && window.HQWorld.sky().night);
      const dots = [];
      const rnd = (a, b) => a + Math.random() * (b - a);
      for (let i = 0; i < 46; i++) {
        const g = new PIXI.Graphics().circle(0, 0, 1).fill(0xffffff);
        app.stage.addChild(g);
        dots.push({g, x: Math.random(), y: Math.random(), vx: rnd(-.004, .004), vy: rnd(-.006, .002), r: rnd(1.6, 3.4), ph: rnd(0, 6.28), sp: rnd(.6, 1.6)});
      }
      let t = 0;
      app.ticker.add(tk => {
        if (!host.offsetParent || document.hidden) return;   // villages not on screen: do nothing
        const w = app.screen.width, h = app.screen.height, dark = night();
        t += tk.deltaMS / 1000;
        for (const d of dots) {
          d.x += d.vx * tk.deltaTime * .06 + Math.sin(t * d.sp + d.ph) * .00025;
          d.y += d.vy * tk.deltaTime * .06 + Math.cos(t * d.sp * .7 + d.ph) * .0002;
          if (d.x < -.02) d.x = 1.02; else if (d.x > 1.02) d.x = -.02;
          if (d.y < -.02) d.y = 1.02; else if (d.y > 1.02) d.y = -.02;
          d.g.position.set(d.x * w, d.y * h);
          d.g.scale.set(dark ? d.r * 1.3 : d.r * .8);
          d.g.tint = dark ? 0xfff2a8 : 0xffffff;
          // Fireflies pulse at night; by day the pollen is faint.
          d.g.alpha = dark ? .25 + .75 * Math.max(0, Math.sin(t * d.sp * 2 + d.ph)) : .22;
        }
      });
    } catch (e) {
      console.debug("HQ ambient layer off:", e);
      host.remove();   // no WebGL or the library didn't load: the villages just look as they did
    }
  }
  const idle = window.requestIdleCallback || (f => setTimeout(f, 800));
  const go = () => idle(startAmbient, {timeout: 1500});
  document.readyState === "complete" ? go() : window.addEventListener("load", go, {once: true});
})();

// The stage that holds both villages (HQ Town and Warrior Village) and the parts they share: a camera that fits each
// village to its box and lets you zoom and drag around, the forest around the villages, and the cards that open when
// you click an agent or a building (status, recent work, approve or reject right there, talk to the Boss).
// world.js and football-town.js use it through window.HQTown. It loads before both of them.
(() => {
"use strict";
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fileName = p => String(p || "").split(/[\\/]/).pop();
const css = `
  #towns { position:relative; z-index:1; display:grid; grid-template-columns:1fr 1fr; grid-template-rows:100%; margin:10px 14px 0; height:70vh;
           border-radius:var(--radius); overflow:hidden; background:#4f9a48; box-shadow:0 18px 50px rgba(0,0,0,.45), 0 0 0 1px var(--line); }
  #towns .world { margin:0; border-radius:0; height:100%; min-height:0; min-width:0; box-shadow:none; }
  #towns .world canvas { width:100%; height:100%; aspect-ratio:auto; }
  #towns .world canvas.can-pan { cursor:grab; } #towns .world canvas.dragging { cursor:grabbing !important; }
  #towns[data-mode="hq"], #towns[data-mode="fb"] { grid-template-columns:1fr; }
  #towns[data-mode="hq"] #fbworld, #towns[data-mode="fb"] #world {
    position:absolute; right:14px; bottom:60px; width:min(24%, 320px); height:auto; aspect-ratio:960/416; z-index:3; border-radius:12px;
    cursor:pointer; box-shadow:0 10px 30px rgba(0,0,0,.5), 0 0 0 2px rgba(255,255,255,.75); transition:transform .2s var(--ease); }
  #towns[data-mode="hq"] #fbworld:hover, #towns[data-mode="fb"] #world:hover { transform:scale(1.04); }
  #towns[data-mode="hq"] #fbworld canvas, #towns[data-mode="fb"] #world canvas { pointer-events:none; }
  #towns[data-mode="hq"] #fbworld > :not(canvas), #towns[data-mode="fb"] #world > :not(canvas) { display:none !important; }
  #towns[data-mode="hq"] #fbworld::after, #towns[data-mode="fb"] #world::after { position:absolute; left:8px; bottom:6px; font-size:11px; font-weight:800;
    color:#fff; background:rgba(20,14,30,.75); padding:2px 8px; border-radius:999px; }
  #towns[data-mode="hq"] #fbworld::after { content:"🏈 Warrior Village ⇄"; } #towns[data-mode="fb"] #world::after { content:"🏘️ HQ Town ⇄"; }
  #towns.solo { grid-template-columns:1fr; } #towns.solo #world, #towns.solo .stage-modes { display:none !important; }
  #towns .stage-modes { position:absolute; left:50%; bottom:12px; transform:translateX(-50%); z-index:4; display:flex; gap:2px; padding:3px;
    border-radius:999px; background:rgba(20,14,30,.65); border:1px solid rgba(255,255,255,.15); backdrop-filter:blur(6px); }
  #towns .stage-modes .chip { border:0; background:transparent; padding:5px 12px; font-size:12px; white-space:nowrap; }
  #towns .stage-modes .short { display:none; }
  #towns .stage-modes .chip[aria-pressed="true"] { background:linear-gradient(135deg, var(--accent), #ff8a5c); color:#2a1405; }
  #towns .world-ticker { bottom:58px; }
  .world-zoom { position:absolute; left:10px; top:46px; display:flex; flex-direction:column; gap:4px; z-index:2; }
  .world-zoom .chip { width:30px; height:30px; padding:0; font-size:15px; display:grid; place-items:center; }
  .world-hint { position:absolute; left:50%; top:50%; transform:translate(-50%, -50%); background:rgba(20,14,30,.82); color:#fff; padding:8px 14px;
    border-radius:999px; font-size:13px; font-weight:800; opacity:0; transition:opacity .3s; pointer-events:none; z-index:3; white-space:nowrap; }
  .world-hint.show { opacity:1; }
  .world-hud .stat-chip { cursor:pointer; } .world-hud .stat-chip.hot { border-color:#ff4d6d; background:rgba(120,20,50,.75); }
  .world-hud .stat-chip:empty { display:none; }
  body[data-tab="home"] > header .stats, body[data-tab="home"] > #hq-update.ok { display:none; }
  body[data-tab="home"] > header { padding-top:8px; padding-bottom:8px; }

  #town-card { position:absolute; top:52px; right:14px; width:min(350px, calc(100% - 28px)); max-height:calc(100% - 120px); display:none;
    flex-direction:column; z-index:6; background:rgba(28,21,38,.95); border:1px solid var(--line); border-radius:16px; color:var(--text);
    box-shadow:0 20px 50px rgba(0,0,0,.55); backdrop-filter:blur(10px); overflow:hidden; }
  #town-card.show { display:flex; animation:cardIn .25s var(--ease) both; }
  #town-card[data-side="left"] { right:auto; left:52px; }
  @keyframes cardIn { from { opacity:0; transform:translateY(10px) scale(.97); } to { opacity:1; transform:none; } }
  #town-card header { display:flex; gap:10px; align-items:center; padding:12px 14px; border-bottom:1px solid var(--line); background:none;
    backdrop-filter:none; flex-wrap:nowrap; }
  #town-card header .ic { flex:none; width:40px; height:40px; border-radius:12px; display:grid; place-items:center; font-size:22px; background:var(--c);
    box-shadow:inset 0 -3px 0 rgba(0,0,0,.18); }
  #town-card header b { display:block; font-size:16px; } #town-card header small { color:var(--muted); font-size:12px; }
  #town-card .x { margin-left:auto; flex:none; background:transparent; color:var(--muted); border:1px solid var(--line); padding:4px 9px; border-radius:8px; box-shadow:none; }
  #town-card .x:hover { color:var(--text); transform:none; }
  #town-card .body { padding:12px 14px; overflow:auto; font-size:14px; }
  #town-card .body p { margin:0 0 8px; } #town-card .muted { color:var(--muted); }
  #town-card h4 { margin:12px 0 6px; font-size:11px; text-transform:uppercase; letter-spacing:.07em; color:var(--accent); }
  #town-card .feed { list-style:none; margin:0; padding:0; } #town-card .feed li { padding:5px 0; border-top:1px solid var(--line); font-size:13px; }
  #town-card .feed li span { color:var(--muted); font-size:11px; margin-right:6px; }
  #town-card .pill { display:inline-block; padding:1px 8px; border-radius:999px; background:#2c2338; color:var(--muted); font-size:12px; font-weight:800; margin-right:4px; }
  #town-card .pill.on { background:var(--good); color:#062b12; } #town-card .pill.bad { background:var(--bad); color:#2a0606; } #town-card .pill.warn { background:#fbbf24; color:#2a1a02; }
  #town-card .item { border:1px solid var(--line); border-radius:12px; padding:10px; margin-bottom:10px; display:flex; flex-direction:column; gap:4px; background:rgba(255,255,255,.03); }
  #town-card .item video { width:100%; max-height:240px; border-radius:8px; background:#000; }
  #town-card .item small { font-size:12px; } #town-card .item .note { color:#fde68a; }
  #town-card .item pre { white-space:pre-wrap; word-break:break-word; font:inherit; font-size:12.5px; max-height:170px; overflow:auto; margin:4px 0; }
  #town-card .row { display:flex; gap:6px; } #town-card .row button { flex:1; padding:7px 10px; }
  #town-card footer { display:flex; gap:6px; flex-wrap:wrap; padding:10px 14px; border-top:1px solid var(--line); }
  #town-card footer button { flex:1 1 auto; padding:8px 10px; font-size:13px; }
  #town-card .chat { max-height:260px; overflow:auto; display:flex; flex-direction:column; gap:6px; margin-bottom:8px; }
  #town-card .chat .msg { margin:0; padding:7px 10px; border-radius:12px; font-size:13px; white-space:pre-wrap; max-width:92%; animation:none; }
  #town-card .chat .msg.user { align-self:flex-end; }
  #town-card .say { display:flex; gap:6px; } #town-card .say input { flex:1; min-width:0; }
  #town-card .grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; margin:6px 0; }
  #town-card .grid div { background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:10px; padding:6px 9px; }
  #town-card .grid b { display:block; font-size:18px; } #town-card .grid b.neg { color:#fca5a5; } #town-card .grid span { color:var(--muted); font-size:11px; }
  #town-card .empty { text-align:center; padding:16px 8px; color:var(--muted); } #town-card .empty .big { font-size:30px; display:block; }
  @media (max-width:960px) { #towns { margin:8px 8px 0; } }
  @media (max-width:700px) {
    #towns[data-mode="both"] { grid-template-columns:1fr; grid-template-rows:1fr 1fr; }
    #towns[data-mode="hq"] #fbworld, #towns[data-mode="fb"] #world { display:none; }
    #towns .stage-modes .chip { padding:5px 10px; font-size:12px; }
    #towns .stage-modes .long { display:none; } #towns .stage-modes .short { display:inline; }
    #town-card, #town-card[data-side="left"] { left:8px; right:8px; width:auto; top:auto; bottom:8px; max-height:72%; }
    #towns .world-hud #worldclock, #towns .world-hud #worldmode, #towns .world-hud #worldposted { display:none; }
    body[data-tab="home"] #hq-money { gap:6px; padding:6px 8px; }
    body[data-tab="home"] #hq-money .mtile { min-width:0; flex:1 1 28%; padding:4px 8px; }
    body[data-tab="home"] #hq-money .mtile b { font-size:15px; } body[data-tab="home"] #hq-money .mtile span { font-size:10px; }
    body[data-tab="home"] #hq-money .mright, body[data-tab="home"] #hq-money .mperiod { flex:1 1 auto; }
    body[data-tab="home"] #hq-money .mbtn, body[data-tab="home"] #hq-money .mperiod button { padding:4px 8px; font-size:12px; }
  }`;
document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);
function seeded(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

// ---------- camera ----------
// Each village is drawn in its own units (960 wide). The camera picks how many screen pixels one unit gets so the whole
// village fits its box, then lets you zoom in (Ctrl + scroll, pinch, double-click or the + button) and drag around.
function camera(canvas, W, H, opts = {}) {
  const cam = {s: 1, ox: 0, oy: 0, zoom: 1, cx: W / 2, cy: H / 2, fit: 1, dpr: 1, cssW: W, cssH: H, version: 0, follow: null, dragged: false};
  const MAX = 4;
  const k = () => cam.fit * cam.zoom;   // CSS pixels per village unit
  function update() {
    const vw = cam.cssW / k(), vh = cam.cssH / k();
    cam.cx = vw >= W ? W / 2 : clamp(cam.cx, vw / 2, W - vw / 2);   // never drift off the village
    cam.cy = vh >= H ? H / 2 : clamp(cam.cy, vh / 2, H - vh / 2);
    cam.s = k() * cam.dpr;
    cam.ox = canvas.width / 2 - cam.cx * cam.s;
    cam.oy = canvas.height / 2 - cam.cy * cam.s;
    cam.version++;
    canvas.style.touchAction = cam.zoom > 1.01 ? "none" : "pan-y";   // zoomed in, a finger drags the village instead of the page
    canvas.classList.toggle("can-pan", cam.canPan());
    opts.onChange?.();
  }
  cam.resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = canvas.clientWidth || W, ch = canvas.clientHeight || H;
    if (!cw || !ch) return;
    cam.dpr = dpr; cam.cssW = cw; cam.cssH = ch;
    canvas.width = Math.round(cw * dpr); canvas.height = Math.round(ch * dpr);
    const contain = Math.min(cw / W, ch / H), cover = Math.max(cw / W, ch / H);
    // The whole village fits. In a box much narrower than the village (a phone) that would leave it small in a sea of
    // trees, so it starts closer and you drag sideways to see the rest.
    cam.fit = cw / ch < W / H / 1.3 ? Math.min(cover, contain * 1.6) : contain;
    update();
  };
  cam.canPan = () => cam.cssW / k() < W - 1 || cam.cssH / k() < H - 1;
  cam.apply = ctx => ctx.setTransform(cam.s, 0, 0, cam.s, cam.ox, cam.oy);
  cam.view = () => ({x0: -cam.ox / cam.s, y0: -cam.oy / cam.s, x1: (canvas.width - cam.ox) / cam.s, y1: (canvas.height - cam.oy) / cam.s});
  cam.toWorld = (clientX, clientY) => {
    const r = canvas.getBoundingClientRect();
    return {x: ((clientX - r.left) * cam.dpr - cam.ox) / cam.s, y: ((clientY - r.top) * cam.dpr - cam.oy) / cam.s};
  };
  cam.toScreen = (x, y) => ({x: (x * cam.s + cam.ox) / cam.dpr, y: (y * cam.s + cam.oy) / cam.dpr});   // CSS pixels inside the canvas
  cam.zoomAt = (factor, clientX, clientY) => {
    const r = canvas.getBoundingClientRect();
    if (clientX === undefined) { clientX = r.left + r.width / 2; clientY = r.top + r.height / 2; }
    const before = cam.toWorld(clientX, clientY);
    cam.zoom = clamp(cam.zoom * factor, 1, MAX);
    cam.cx = before.x - (clientX - r.left - cam.cssW / 2) / k();
    cam.cy = before.y - (clientY - r.top - cam.cssH / 2) / k();
    update();
  };
  cam.panBy = (dx, dy) => { cam.cx -= dx / k(); cam.cy -= dy / k(); cam.follow = null; update(); };
  cam.reset = () => { cam.zoom = 1; cam.cx = W / 2; cam.cy = H / 2; cam.follow = null; update(); };
  cam.lookAt = (x, y, zoom) => { if (zoom) cam.zoom = clamp(zoom, 1, MAX); cam.cx = x; cam.cy = y; update(); };
  cam.tick = dt => {   // glide after whoever you're following
    const t = cam.follow?.();
    if (cam.follow && !t) cam.follow = null;
    if (!t) return;
    const e = Math.min(1, dt * 3);
    cam.cx = lerp(cam.cx, t.x, e); cam.cy = lerp(cam.cy, t.y - 20, e);
    update();
  };

  // mouse, touch and pen
  const pts = new Map();
  let start = null, pinch = null;
  canvas.addEventListener("pointerdown", e => {
    if (e.button > 0) return;
    pts.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (pts.size === 1) { start = {x: e.clientX, y: e.clientY, moved: false}; cam.dragged = false; }
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), zoom: cam.zoom}; }
  });
  canvas.addEventListener("pointermove", e => {
    const p = pts.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y;
    p.x = e.clientX; p.y = e.clientY;
    if (pts.size === 2 && pinch) {
      const [a, b] = [...pts.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
      cam.zoomAt(pinch.zoom * d / pinch.d / cam.zoom, (a.x + b.x) / 2, (a.y + b.y) / 2);
      cam.dragged = true;
      return;
    }
    if (!start) return;
    if (!start.moved && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 6 && cam.canPan()) {
      start.moved = true; cam.dragged = true;
      try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
      canvas.classList.add("dragging");
    }
    if (start.moved) cam.panBy(dx, dy);
  });
  const up = e => {
    pts.delete(e.pointerId);
    if (pts.size < 2) pinch = null;
    if (!pts.size) { start = null; canvas.classList.remove("dragging"); setTimeout(() => { cam.dragged = false; }, 0); }
  };
  canvas.addEventListener("pointerup", up);
  canvas.addEventListener("pointercancel", up);
  canvas.addEventListener("wheel", e => {
    if (e.ctrlKey || e.metaKey) {   // Ctrl + scroll, or a trackpad pinch
      e.preventDefault();
      cam.zoomAt(Math.exp(-clamp(e.deltaY, -60, 60) * .01), e.clientX, e.clientY);
    } else if (cam.zoom > 1.01 && Math.abs(e.deltaX) > Math.abs(e.deltaY)) {   // sideways trackpad swipe pans when zoomed in
      e.preventDefault(); cam.panBy(-e.deltaX, 0);
    } else hint(canvas, "Hold Ctrl and scroll to zoom");
  }, {passive: false});
  canvas.addEventListener("dblclick", e => { e.preventDefault(); cam.zoom >= MAX - .01 ? cam.reset() : cam.zoomAt(2, e.clientX, e.clientY); });
  return cam;
}

let hintTimer = 0;
function hint(canvas, text) {
  const box = canvas.closest(".world");
  if (!box) return;
  let el = box.querySelector(".world-hint");
  if (!el) { el = document.createElement("div"); el.className = "world-hint"; box.appendChild(el); }
  el.textContent = text; el.classList.add("show");
  clearTimeout(hintTimer); hintTimer = setTimeout(() => el.classList.remove("show"), 1400);
}

// ---------- the forest around a village ----------
// Draws grass and trees outside the village (the part of the box the village doesn't cover) so it sits in a clearing
// instead of a black frame. The same seed always gives the same trees.
function outskirts(g, v, W, H, {grass = "#66b85a", seed = 5} = {}) {
  g.fillStyle = grass; g.fillRect(v.x0 - 2, v.y0 - 2, v.x1 - v.x0 + 4, v.y1 - v.y0 + 4);
  const C = 46, trees = [];
  for (let cy = Math.floor(v.y0 / C) - 1; cy * C < v.y1 + 60; cy++) for (let cx = Math.floor(v.x0 / C) - 1; cx * C < v.x1 + 40; cx++) {
    const r = seeded(cx * 7919 + cy * 104729 + seed);
    const x = cx * C + r() * C, y = cy * C + r() * C;
    const d = Math.max(-x, x - W, -y, y - H);   // how far outside the village
    if (d < 18 || r() > clamp(.3 + d / 160, 0, .9)) continue;
    trees.push({x, y, s: .8 + r() * .5, k: r()});
  }
  trees.sort((a, b) => a.y - b.y);
  g.fillStyle = "rgba(20,60,20,.18)";
  for (const t of trees) { g.beginPath(); g.ellipse(t.x + 5, t.y, 17 * t.s, 6 * t.s, 0, 0, 7); g.fill(); }
  for (const t of trees) {
    const c = t.k < .55 ? ["#2f7a3c", "#3f9248", "#5bae5c"] : t.k < .9 ? ["#3f9a45", "#56b55a", "#79cf6c"] : ["#2a6b45", "#357d52", "#4f9a66"];
    g.fillStyle = "#6b4426"; g.fillRect(t.x - 3 * t.s, t.y - 15 * t.s, 6 * t.s, 15 * t.s);
    const blob = (dx, dy, rad, col) => { g.fillStyle = col; g.beginPath(); g.arc(t.x + dx * t.s, t.y + dy * t.s, rad * t.s, 0, 7); g.fill(); };
    blob(0, -27, 17, c[0]); blob(-8, -31, 11, c[1]); blob(8, -32, 10, c[1]); blob(-3, -37, 8, c[2]);
  }
}

// ---------- the night overlay ----------
// Darkens everything in view (the forest too) and cuts soft holes where the lamps and windows are.
function night(ctx, cam, dark, sky, lights, t) {
  const v = cam.view(), vw = v.x1 - v.x0, vh = v.y1 - v.y0;
  if (sky.tint > 0) { ctx.fillStyle = `rgba(${sky.tc},${sky.tint})`; ctx.fillRect(v.x0, v.y0, vw, vh); }
  if (sky.dk <= 0) return false;
  const q = 2, dw = Math.ceil(vw / q), dh = Math.ceil(vh / q);
  if (dark.width !== dw || dark.height !== dh) { dark.width = dw; dark.height = dh; }
  const d = dark.getContext("2d");
  d.globalCompositeOperation = "source-over";
  d.clearRect(0, 0, dw, dh);
  d.fillStyle = `rgba(8,12,46,${sky.dk})`; d.fillRect(0, 0, dw, dh);
  d.globalCompositeOperation = "destination-out";
  for (const l of lights) {
    const x = (l.x - v.x0) / q, y = (l.y - v.y0) / q, r = l.r / q * (1 + Math.sin(t / 700 + l.x) * .03);
    if (x < -r || y < -r || x > dw + r || y > dh + r) continue;
    const gr = d.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, "rgba(0,0,0,.95)"); gr.addColorStop(1, "rgba(0,0,0,0)");
    d.fillStyle = gr; d.beginPath(); d.arc(x, y, r, 0, 7); d.fill();
  }
  ctx.drawImage(dark, v.x0, v.y0, dw * q, dh * q);
  return true;
}

// ---------- shared state and helpers ----------
let state = null;
const hq = {
  state: () => state,
  async post(url, body) {   // every change goes through a POST with HQ's own header, like the rest of the dashboard
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-HQ": "1"}, body: body ? JSON.stringify(body) : undefined});
    let data = {};
    try { data = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(data.detail || data.message || `HQ said ${r.status}`);
    return data;
  },
  goTab(id, elId) {
    window.hqTabs?.show(id);
    const el = elId && document.getElementById(elId);
    if (el) setTimeout(() => (el.closest("section") || el).scrollIntoView({behavior: calm ? "auto" : "smooth", block: "start"}), 60);
  },
};

// ---------- cards ----------
// One card at a time, inside the stage. A card is a function that returns its content, so it stays live: every refresh
// (about every 5 seconds) rebuilds it, unless you're typing in it or a video in it is playing.
let card = null, cardEl = null;
function cardBox() {
  if (cardEl) return cardEl;
  const stage = document.getElementById("towns") || document.body;
  cardEl = document.createElement("aside");
  cardEl.id = "town-card";
  cardEl.setAttribute("role", "dialog");
  cardEl.setAttribute("aria-live", "polite");
  stage.appendChild(cardEl);
  cardEl.addEventListener("click", e => {
    const b = e.target.closest("[data-act]");
    if (!b || b.disabled) return;
    const fn = card?.acts?.[b.dataset.act];
    if (fn) fn(b, e);
  });
  cardEl.addEventListener("submit", e => {
    e.preventDefault();
    const fn = card?.acts?.[e.target.dataset.act];
    if (fn) fn(e.target, e);
  });
  return cardEl;
}
function renderCard(force) {
  if (!card) return;
  const el = cardBox();
  if (!force && (el.contains(document.activeElement) && document.activeElement.matches("input, textarea")
      || [...el.querySelectorAll("video")].some(v => !v.paused))) return;
  const c = card.build();
  if (!c) { closeCard(); return; }
  card.acts = c.acts || {};
  const html = `<header style="--c:${esc(c.color || "#ffb347")}"><span class="ic">${esc(c.icon || "✨")}</span>
      <div><b>${esc(c.title)}</b>${c.sub ? `<small>${c.sub}</small>` : ""}</div>
      <button class="x" data-act="close" aria-label="Close">✕</button></header>
    <div class="body">${c.html || ""}</div>
    ${c.buttons?.length ? `<footer>${c.buttons.map(b => `<button data-act="${esc(b.act)}" class="${esc(b.kind || "")}">${b.label}</button>`).join("")}</footer>` : ""}`;
  card.acts.close = closeCard;
  if (html === card.shown) return;
  const keep = el.querySelector(".body")?.scrollTop || 0;
  card.shown = html;
  el.innerHTML = html;
  el.querySelector(".body").scrollTop = keep;
  c.after?.(el);
}
// The card opens on the far side of the stage from what you clicked, so it doesn't cover it.
let side = "right";
function at(e) {
  const r = (document.getElementById("towns") || document.body).getBoundingClientRect();
  side = e && e.clientX > r.left + r.width / 2 ? "left" : "right";
}
function openCard(key, build) {
  card = {key, build, shown: null};
  const el = cardBox();
  el.dataset.side = side;
  el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  renderCard(true);
}
function closeCard() { card = null; if (cardEl) { cardEl.classList.remove("show"); cardEl.innerHTML = ""; } }
document.addEventListener("keydown", e => { if (e.key === "Escape" && card) closeCard(); });

const when = iso => {
  const d = new Date(String(iso).replace(" ", "T") + (String(iso).includes("Z") || String(iso).includes("+") ? "" : "Z"));
  if (isNaN(d)) return "";
  const mins = Math.round((Date.now() - d) / 60000);
  return mins < 1 ? "just now" : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.round(mins / 60)}h ago` : `${Math.round(mins / 1440)}d ago`;
};
const usd = n => "$" + (+n || 0).toFixed(2);
const PANELS = {chad: ["clips", "library"], scout: ["campaigns", "campsection"], pitch: ["pitch", "leadsection"], sweep: ["sweep", "sweep"],
                boss: ["boss", "chatlog"], captain: ["football", "football"], clock: ["football", "fbweek"], ref: ["football", "fbfiles"],
                tells: ["football", "fbfiles"], scribe: ["football", "fbnotes"]};

// An agent's card: what they're doing, what they did lately, what they cost this month, and buttons to follow them,
// ask the Boss about them or open their part of the dashboard.
function agentCard(name, live) {
  openCard("agent:" + name, () => {
    const s = state || {}, key = name.toLowerCase();
    const info = (s.agents || []).find(a => a.name.toLowerCase() === key);
    if (!info) return null;
    const l = window.hqLook ? window.hqLook(name) : {color: "#7cc4ff", prop: "💡"};
    const a = live?.(name);
    const status = info.doing ? `<span class="pill on">Working</span> ${esc(info.doing)}`
      : a?.sleeping ? `<span class="pill">Asleep 💤</span> Back at work in the morning, or as soon as there's a job.`
      : `<span class="pill">Free</span> Waiting for a job.`;
    const recent = (s.activity || []).filter(r => String(r.agent).toLowerCase() === key).slice(0, 4);
    const cost = (s.spend?.month_by_agent || []).find(r => String(r.agent).toLowerCase() === key);
    const panel = PANELS[key];
    return {
      color: l.color, icon: l.prop, title: name, sub: esc(info.village === "football" ? "🏈 Warrior Village" : "🏘️ HQ Town"),
      html: `<p class="status">${status}</p><p class="muted">${esc(info.role)}</p>
        <h4>Lately</h4>${recent.length ? `<ul class="feed">${recent.map(r => `<li><span>${esc(when(r.created_at))}</span>${esc(r.message)}</li>`).join("")}</ul>`
          : `<p class="muted">Nothing yet.</p>`}
        ${key === "boss" ? "" : `<p class="muted cost">Claude cost this month: <b>${usd(cost?.usd)}</b></p>`}`,
      buttons: [
        key === "boss" ? {act: "chat", label: "💬 Talk to the Boss"} : {act: "ask", label: `💬 Ask the Boss about ${esc(name)}`},
        a ? {act: "follow", label: "📍 Follow", kind: "ghost"} : null,
        panel ? {act: "open", label: "Open ↗", kind: "ghost"} : null,
      ].filter(Boolean),
      acts: {
        ask: () => bossCard(`What is ${name} working on right now, and is anything stuck?`),
        chat: () => bossCard(),
        follow: () => { live?.(name, "follow"); closeCard(); },
        open: () => hq.goTab(panel[0], panel[1]),
      },
    };
  });
}

// Talk to the Boss without leaving the village. It sends through the Boss chat on the dashboard, so the reply shows up
// in both places and the Boss walks back to HQ to think, like before.
function bossCard(prefill = "") {
  openCard("boss", () => {
    const s = state || {};
    const msgs = (s.chat || []).map(m => ({role: m.role, text: (m.content || []).filter(b => b.type === "text").map(b => b.text)
      .filter(t => !t.startsWith("<vision")).join("\n")})).filter(m => m.text).slice(-4);
    const thinking = !!document.getElementById("thinking");
    return {
      color: "#ffb347", icon: "👑", title: "Boss", sub: "Directs the team and reports to you",
      html: `<div class="chat">${msgs.length ? msgs.map(m => `<div class="msg ${esc(m.role)}">${esc(m.text)}</div>`).join("")
          : `<p class="muted">Ask what the team is up to, or tell the Boss what you want done.</p>`}
        ${thinking ? `<div class="msg assistant muted">Boss is thinking…</div>` : ""}</div>
        <form data-act="send" class="say"><input name="q" placeholder="Tell the Boss what you want…" autocomplete="off" ${thinking ? "disabled" : ""}>
        <button ${thinking ? "disabled" : ""}>Send</button></form>`,
      buttons: [{act: "open", label: "Open the full chat ↗", kind: "ghost"}],
      acts: {
        send: form => {
          const q = form.q.value.trim(), input = document.getElementById("chatinput"), f = document.getElementById("chatform");
          if (!q || !input || !f) return;
          input.value = q;
          f.requestSubmit ? f.requestSubmit() : f.dispatchEvent(new Event("submit", {cancelable: true}));
          form.q.value = "";
          document.activeElement?.blur();
          setTimeout(() => renderCard(true), 50);
          const done = setInterval(() => { if (!document.getElementById("thinking")) { clearInterval(done); renderCard(true); } }, 500);
        },
        open: () => hq.goTab("boss", "chatlog"),
      },
      after: el => {
        const c = el.querySelector(".chat"); if (c) c.scrollTop = c.scrollHeight;
        const i = el.querySelector("input[name=q]");
        if (prefill && i && !i.value) { i.value = prefill; prefill = ""; }
        if (i && !i.disabled && matchMedia("(hover: hover)").matches) i.focus({preventScroll: true});
      },
    };
  });
}

// What's waiting for your OK in one village, with Approve and Reject right on the card. Clips play in the card so you
// see what you're approving. To change a clip's title or caption first, open it in the Approvals tab.
function approvalsCard(village) {
  const busy = new Set();
  const decide = async (b, url, msg) => {
    if (busy.has(url)) return;
    busy.add(url);
    b.closest(".item")?.querySelectorAll("button").forEach(x => { x.disabled = true; });
    try { const r = await hq.post(url); window.toast?.(esc((r.message || msg).split("\n")[0])); }
    catch (err) { window.toast?.("😬 " + esc(err.message)); }
    busy.delete(url);
    await window.hqRefresh?.();
    renderCard(true);
  };
  openCard("approvals:" + village, () => {
    const s = state || {};
    const clips = village === "business" ? s.pending || [] : [];
    const items = (s.approvals || []).filter(a => (a.village || "business") === village);
    const fb = village === "football";
    const n = clips.length + items.length;
    return {
      color: fb ? "#FFCC33" : "#3b82f6", icon: "📬", title: fb ? "Coaches' Mailroom" : "Approvals",
      sub: n ? `${n} waiting for your OK` : "Nothing waiting",
      html: (n ? "" : `<div class="empty"><span class="big">${fb ? "🏈" : "🌤️"}</span>All caught up.</div>`) +
        clips.map(c => `<div class="item"><video src="/clips/${esc(fileName(c.path))}" controls preload="metadata" playsinline></video>
          <b>${esc(c.title)}</b><small class="muted">#${c.id} · ${esc(c.creator)} · ★ ${esc(c.score ?? "?")}</small>
          ${c.boss_note ? `<small class="note">🧐 Boss: ${esc(c.boss_note)}</small>` : ""}
          <div class="row"><button data-act="clip-yes" data-id="${c.id}">👍 Approve</button><button class="bad" data-act="clip-no" data-id="${c.id}">Reject</button></div></div>`).join("") +
        items.map(a => `<div class="item"><b>${esc(a.title)}</b><small class="muted">from ${esc(a.agent)}</small>
          <pre>${esc(String(a.preview || "").slice(0, 900))}${String(a.preview || "").length > 900 ? "…" : ""}</pre>
          <div class="row"><button data-act="yes" data-id="${a.id}">${esc(a.yes_label || "Approve")}</button><button class="ghost" data-act="no" data-id="${a.id}">${esc(a.no_label || "No")}</button></div></div>`).join(""),
      buttons: [{act: "open", label: "Open Approvals ↗", kind: "ghost"}],
      acts: {
        "clip-yes": b => decide(b, `/api/clips/${b.dataset.id}/approve`, `👍 Clip #${b.dataset.id} approved`),
        "clip-no": b => decide(b, `/api/clips/${b.dataset.id}/reject`, `Clip #${b.dataset.id} rejected`),
        yes: b => decide(b, `/api/approvals/${b.dataset.id}/approve`, "Approved"),
        no: b => decide(b, `/api/approvals/${b.dataset.id}/reject`, "Done"),
        open: () => { const f = document.getElementById("apprfilter"); if (f && items.length) { f.value = village; f.onchange?.(); } hq.goTab("approvals", items.length ? "apprsection" : "pending"); },
      },
    };
  });
}

// A simple card for a building: a title, a few lines and a button that opens the matching part of the dashboard.
function infoCard(key, build) { openCard(key, build); }

// ---------- the stage ----------
// Both villages fill the screen under the money strip: side by side (they meet at the footbridge), or one big with the
// other as a small live window you can click to swap. Phones show one village at a time.
const stage = document.getElementById("towns");
const MODES = {both: ["◫", "Both", "Both"], hq: ["🏘️", "HQ Town", "HQ"], fb: ["🏈", "Warrior Village", "Warriors"]};
let mode = "both";
try { mode = localStorage.getItem("hq-stage") || (innerWidth < 700 ? "hq" : "both"); } catch (e) {}
if (!MODES[mode]) mode = "both";
function setMode(m, remember = true) {
  if (!stage || !MODES[m]) return;
  mode = m;
  if (stage.classList.contains("solo")) return;
  stage.dataset.mode = m;
  stage.querySelectorAll(".stage-modes button").forEach(b => b.setAttribute("aria-pressed", b.dataset.mode === m));
  if (remember) { try { localStorage.setItem("hq-stage", m); } catch (e) {} }
}
function fitStage() {
  if (!stage || stage.offsetParent === null) return;
  const top = stage.getBoundingClientRect().top + window.scrollY;
  const football = document.body.dataset.tab === "football";
  let h = innerHeight - top - 12;
  if (football) h = Math.min(h, innerHeight * .55);   // leave room for the football panel under it
  h = Math.max(innerWidth < 700 ? innerHeight * .62 : 360, h);
  stage.style.height = Math.round(h) + "px";
}
if (stage) {
  const bar = document.createElement("div");
  bar.className = "stage-modes";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "Which village to show");
  bar.innerHTML = Object.entries(MODES).map(([k, [icon, label, short]]) => `<button class="chip" data-mode="${k}" aria-pressed="false" aria-label="${label}">` +
    `${icon} <span class="long">${label}</span><span class="short">${short}</span></button>`).join("");
  stage.appendChild(bar);
  bar.addEventListener("click", e => { const b = e.target.closest("button[data-mode]"); if (b) setMode(b.dataset.mode); });
  // In one-village mode the other village is a small window: clicking it swaps them.
  stage.addEventListener("click", e => {
    const w = e.target.closest(".world");
    if (!w || e.target.closest(".world-zoom, .world-hud")) return;
    const small = (mode === "hq" && w.id === "fbworld") || (mode === "fb" && w.id === "world");
    if (small) { e.stopPropagation(); e.preventDefault(); setMode(mode === "hq" ? "fb" : "hq"); }
  }, true);
  // + / − / reset buttons on each village
  for (const w of stage.querySelectorAll(".world")) {
    w.insertAdjacentHTML("beforeend", `<div class="world-zoom"><button class="chip" data-z="in" title="Zoom in" aria-label="Zoom in">＋</button>` +
      `<button class="chip" data-z="out" title="Zoom out" aria-label="Zoom out">－</button><button class="chip" data-z="fit" title="Show the whole village" aria-label="Show the whole village">⤢</button></div>`);
  }
  setMode(mode, false);
  // The Warrior Village tab shows just that village, above the football panel.
  const solo = () => {
    const on = document.body.dataset.tab === "football";
    stage.classList.toggle("solo", on);
    if (on) { stage.dataset.mode = "fb"; } else setMode(mode, false);
    fitStage();
  };
  new MutationObserver(solo).observe(document.body, {attributes: true, attributeFilter: ["data-tab"]});
  addEventListener("resize", fitStage);
  new ResizeObserver(fitStage).observe(document.body);
  setInterval(fitStage, 2000);   // the bars above can grow (a banner, the money panel) without a resize
  requestAnimationFrame(fitStage);
}
const cams = {};
function register(id, cam) {
  cams[id] = cam;
  const w = document.getElementById(id)?.closest(".world");
  w?.querySelector(".world-zoom")?.addEventListener("click", e => {
    const b = e.target.closest("button[data-z]");
    if (!b) return;
    e.stopPropagation();
    if (b.dataset.z === "in") cam.zoomAt(1.5); else if (b.dataset.z === "out") cam.zoomAt(1 / 1.5); else cam.reset();
  });
}

window.HQTown = {
  camera, outskirts, night, seeded, register, hint, cams,
  setState(s) { state = s; renderCard(); },
  ...hq,
  agentCard, bossCard, approvalsCard, infoCard, closeCard, renderCard, at,
  cardOpen: key => card?.key === key,
  setMode, mode: () => mode, fitStage,
  esc, when, usd,
};
})();

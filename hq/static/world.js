// HQ Town: a little top-down world where the agents live, walk between their buildings and react to
// what's really happening in HQ. index.html feeds it with HQWorld.update(state) on every refresh.
(() => {
"use strict";
const canvas = document.getElementById("worldcanvas");
if (!canvas) return;
const ctx = canvas.getContext("2d");
const W = 960, H = 416, ROAD_Y = 240;
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMOJI = '"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
const FONT = '"Nunito",system-ui,sans-serif';

const rnd = (a, b) => a + Math.random() * (b - a);
const pick = a => a[Math.floor(Math.random() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
function seeded(seed) {   // repeatable randomness so the town looks the same every time
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
const look = name => window.hqLook ? window.hqLook(name) : {color: "#7cc4ff", prop: "💡", hat: null};

// ---------- the map ----------
const B = {
  studio: {x: 70, y: 52, w: 170, h: 118, wall: "#f9dbe6", roof: "#e0457b", door: 155, label: "Clip Studio", icon: "🎬"},
  hq:     {x: 395, y: 30, w: 190, h: 140, wall: "#fdeccd", roof: "#cf8a1e", door: 490, label: "Boss HQ", icon: "👑"},
  post:   {x: 640, y: 66, w: 124, h: 104, wall: "#dbeafe", roof: "#3b82f6", door: 702, label: "Approvals", icon: "📬"},
  tower:  {x: 842, y: 14, w: 72, h: 156, door: 878, label: "Broadcast Tower", icon: "📡"},
};
for (const b of Object.values(B)) b.front = {x: b.door, y: b.y + b.h + 20};
const PLOTS = [0, 1, 2, 3].map(i => ({x: 566 + i * 96, y: 300, w: 84, h: 72, agent: null}));   // four cottages since Sweep moved in
for (const p of PLOTS) p.front = {x: p.x + p.w / 2, y: p.y - 8};
const LITTER = [];   // bits of mess for Sweep to clean up: one per open problem Sweep has found
let messShown = null;
const POND = {x: 150, y: 342, rx: 95, ry: 44};
const PLAZA = {x: 480, y: 348, r: 68};
const MAILBOX = {x: 784, y: 178};
const TRASH = {x: 620, y: 178};
const BEACON = {x: 878, y: 12};
const TREES = [[30, 128], [292, 74], [345, 160], [612, 44], [806, 104], [298, 318], [338, 400], [612, 404], [952, 404],
               [28, 402], [262, 404], [946, 120], [372, 300]].map(([x, y], i) => ({x, y, i, kind: i % 4 === 2 ? "blossom" : i % 3 === 1 ? "dark" : "green"}));
const LAMPS = [[40, 214], [330, 214], [598, 214], [930, 214], [394, 306], [566, 306]].map(([x, y]) => ({x, y}));
const BENCHES = [{x: 430, y: 292}, {x: 530, y: 292}];
const SPOTS = [{x: 150, y: 288}, {x: 274, y: 352}, {x: 60, y: 300}, {x: 430, y: 296, bench: true}, {x: 530, y: 296, bench: true},
               {x: 480, y: 404}, {x: 418, y: 372}, {x: 542, y: 372}, {x: 330, y: 250}, {x: 600, y: 252}, {x: 100, y: 252},
               {x: 860, y: 252}, {x: 900, y: 392}, {x: 760, y: 252}];

function setMess(n) {   // called by the Sweep card; pieces only change when the number of open problems changes
  n = Math.min(8, Math.max(0, n | 0));
  if (n === messShown) return;
  messShown = n;
  const rr = seeded(99);
  LITTER.length = 0;
  for (let tries = 0; LITTER.length < n && tries < 400; tries++) {
    const x = 30 + rr() * (W - 60), y = 270 + rr() * (H - 290);
    if (!blocked(x, y, 8) && !LITTER.some(l => Math.hypot(l.x - x, l.y - y) < 40)) LITTER.push({x, y, kind: LITTER.length % 3});
  }
}
function drawLitter(l) {
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(l.x + 1, l.y + 2, 6, 2, 0, 0, 7); ctx.fill();
  if (l.kind === 0) { ctx.fillStyle = "#f4f0e6"; ctx.beginPath(); ctx.ellipse(l.x, l.y, 5, 4, .4, 0, 7); ctx.fill(); ctx.strokeStyle = "#b9b2a0"; ctx.lineWidth = 1; ctx.stroke(); }
  else if (l.kind === 1) { ctx.fillStyle = "#d8453b"; roundRect(ctx, l.x - 3, l.y - 6, 6, 8, 2); ctx.fill(); ctx.fillStyle = "#e8e8e8"; ctx.fillRect(l.x - 3, l.y - 6, 6, 2); }
  else { ctx.fillStyle = "#f2d04a"; ctx.beginPath(); ctx.ellipse(l.x, l.y, 6, 3, -.3, 0, 7); ctx.fill(); ctx.fillStyle = "#8a5a22"; ctx.fillRect(l.x + 2, l.y - 1, 2, 2); }
}

// ---------- canvas sizing ----------
let scale = 1, terrain = null;
const dark = document.createElement("canvas");
dark.width = W / 2; dark.height = H / 2;
const dctx = dark.getContext("2d");
function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const cssW = canvas.clientWidth || W;
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssW * H / W * dpr);
  scale = canvas.width / W;
  terrain = drawTerrain();
  if (calm) draw(performance.now());
}

// ---------- the ground, drawn once ----------
function blocked(x, y, m = 0) {
  if (y > 212 - m && y < 268 + m) return true;
  for (const b of Object.values(B)) if (x > b.x - 12 - m && x < b.x + b.w + 12 + m && y < b.y + b.h + 14 + m) return true;
  if (((x - POND.x) / (POND.rx + 14 + m)) ** 2 + ((y - POND.y) / (POND.ry + 14 + m)) ** 2 < 1) return true;
  if (Math.hypot(x - PLAZA.x, y - PLAZA.y) < PLAZA.r + 14 + m) return true;
  for (const p of PLOTS) if (x > p.x - 10 && x < p.x + p.w + 10 && y > p.y - 14 && y < p.y + p.h + 10) return true;
  for (const t of TREES) if (Math.hypot(x - t.x, y - t.y + 10) < 24) return true;
  return false;
}
const r = seeded(7);
const FLOWERS = [];
for (let tries = 0; FLOWERS.length < 22 && tries < 600; tries++) {
  const x = 20 + r() * (W - 40), y = 20 + r() * (H - 30);
  if (!blocked(x, y, 4)) FLOWERS.push({x, y, n: 4 + Math.floor(r() * 5), c: ["#ff7eb6", "#ffd34d", "#ffffff", "#c084fc", "#7cc4ff"][Math.floor(r() * 5)], s: Math.floor(r() * 1e6)});
}

function drawTerrain() {
  const c = document.createElement("canvas");
  c.width = canvas.width; c.height = canvas.height;
  const g = c.getContext("2d");
  g.setTransform(scale, 0, 0, scale, 0, 0);
  const rr = seeded(42);
  // grass, with a soft checker of tiles and tufts
  g.fillStyle = "#6cbf5c"; g.fillRect(0, 0, W, H);
  for (let ty = 0; ty < H; ty += 32) for (let tx = 0; tx < W; tx += 32) {
    g.fillStyle = ((tx + ty) / 32) % 2 ? "rgba(255,255,255,.035)" : "rgba(0,60,0,.035)";
    g.fillRect(tx, ty, 32, 32);
  }
  g.strokeStyle = "rgba(30,90,30,.35)"; g.lineWidth = 1.2;
  for (let i = 0; i < 320; i++) {
    const x = rr() * W, y = rr() * H;
    g.beginPath(); g.moveTo(x - 2, y); g.lineTo(x, y - 4); g.lineTo(x + 2, y); g.stroke();
  }
  // roads: the main street, little paths to each door, the plaza and the plots
  const path = (x, y, w, h) => {
    g.fillStyle = "#e4c792"; g.fillRect(x, y, w, h);
    g.fillStyle = "rgba(160,120,60,.25)"; g.fillRect(x, y, w, 2); g.fillRect(x, y + h - 2, w, 2);
  };
  path(0, ROAD_Y - 16, W, 32);
  for (const b of Object.values(B)) path(b.door - 12, b.y + b.h - 2, 24, ROAD_Y - 16 - (b.y + b.h - 2));
  path(PLAZA.x - 12, ROAD_Y + 16, 24, 40);
  for (const p of PLOTS) path(p.front.x - 10, ROAD_Y + 16, 20, p.y - ROAD_Y - 16);
  g.fillStyle = "rgba(120,90,50,.35)";
  for (let i = 0; i < 140; i++) { g.beginPath(); g.arc(rr() * W, ROAD_Y - 13 + rr() * 26, rr() * 1.4 + .4, 0, 7); g.fill(); }
  // pond
  g.fillStyle = "#d9c58f"; g.beginPath(); g.ellipse(POND.x, POND.y, POND.rx + 7, POND.ry + 6, 0, 0, 7); g.fill();
  g.fillStyle = "#3d8fd1"; g.beginPath(); g.ellipse(POND.x, POND.y, POND.rx, POND.ry, 0, 0, 7); g.fill();
  g.fillStyle = "#5aaee6"; g.beginPath(); g.ellipse(POND.x - 8, POND.y - 6, POND.rx - 22, POND.ry - 14, 0, 0, 7); g.fill();
  for (const [x, y] of [[100, 326], [196, 360], [120, 372], [214, 318]]) {
    g.fillStyle = "#3f9e4a"; g.beginPath(); g.arc(x, y, 7, .5, 6.1); g.lineTo(x, y); g.fill();
  }
  g.fillStyle = "#ff9ecb"; g.beginPath(); g.arc(196, 359, 2.5, 0, 7); g.fill();
  for (let i = 0; i < 14; i++) {   // reeds
    const a = rr() * Math.PI * 2, x = POND.x + Math.cos(a) * (POND.rx + 4), y = POND.y + Math.sin(a) * (POND.ry + 4);
    g.strokeStyle = "#2f7d3a"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, y); g.lineTo(x + rr() * 3 - 1.5, y - 9); g.stroke();
  }
  // plaza and fountain basin
  g.fillStyle = "#d8cfc0"; g.beginPath(); g.arc(PLAZA.x, PLAZA.y, PLAZA.r, 0, 7); g.fill();
  g.strokeStyle = "rgba(120,105,90,.35)"; g.lineWidth = 1;
  for (let rad = 20; rad < PLAZA.r; rad += 16) { g.beginPath(); g.arc(PLAZA.x, PLAZA.y, rad, 0, 7); g.stroke(); }
  for (let a = 0; a < 16; a++) {
    const k = a / 16 * Math.PI * 2; g.beginPath();
    g.moveTo(PLAZA.x + Math.cos(k) * 36, PLAZA.y + Math.sin(k) * 36); g.lineTo(PLAZA.x + Math.cos(k) * PLAZA.r, PLAZA.y + Math.sin(k) * PLAZA.r); g.stroke();
  }
  g.fillStyle = "#9aaab9"; g.beginPath(); g.arc(PLAZA.x, PLAZA.y, 28, 0, 7); g.fill();
  g.fillStyle = "#4fa6e3"; g.beginPath(); g.arc(PLAZA.x, PLAZA.y, 23, 0, 7); g.fill();
  g.fillStyle = "#8b9bab"; g.beginPath(); g.arc(PLAZA.x, PLAZA.y, 6, 0, 7); g.fill();
  // plots: tilled soil
  for (const p of PLOTS) {
    g.fillStyle = "#a8794b"; g.fillRect(p.x, p.y, p.w, p.h);
    g.strokeStyle = "rgba(70,40,20,.35)"; g.lineWidth = 2;
    for (let y = p.y + 10; y < p.y + p.h; y += 12) { g.beginPath(); g.moveTo(p.x + 6, y); g.lineTo(p.x + p.w - 6, y); g.stroke(); }
  }
  // flowers
  for (const f of FLOWERS) {
    const fr = seeded(f.s);
    for (let i = 0; i < f.n; i++) {
      const x = f.x + fr() * 22 - 11, y = f.y + fr() * 12 - 6;
      g.fillStyle = "#3f8f3a"; g.fillRect(x - .5, y, 1, 4);
      g.fillStyle = f.c; for (let k = 0; k < 4; k++) { g.beginPath(); g.arc(x + Math.cos(k * 1.57) * 1.8, y + Math.sin(k * 1.57) * 1.8, 1.6, 0, 7); g.fill(); }
      g.fillStyle = "#ffcf3f"; g.beginPath(); g.arc(x, y, 1, 0, 7); g.fill();
    }
  }
  return c;
}

// ---------- world state ----------
const agents = new Map();   // lower-case name -> agent
const particles = [], flyers = [], clouds = [], birds = [];
const ducks = [{a: 0, sp: .16, k: .62}, {a: 2.6, sp: .12, k: .45}];
const butterflies = FLOWERS.slice(0, 6).map((f, i) => ({cx: f.x, cy: f.y - 10, ph: i * 1.7, c: ["#ffb347", "#ff6fa8", "#7cc4ff", "#fff59e"][i % 4]}));
const fireflies = Array.from({length: 16}, (_, i) => ({x: rnd(0, W), y: rnd(270, H), vx: rnd(-8, 8), vy: rnd(-6, 6), ph: i}));
for (let i = 0; i < 3; i++) clouds.push({x: rnd(0, W), y: rnd(40, H - 40), s: rnd(.8, 1.4)});
let mode = "auto", prev = null, deliveriesOnTheWay = 0, mailboxBump = 0, towerGlow = 0, thinking = false;
let shown = {pending: 0, approved: 0};
let nextBirds = performance.now() + rnd(4000, 12000);

function addParticle(p) { if (!calm && particles.length < 500) particles.push({vx: 0, vy: 0, g: 0, life: 1, ...p, max: p.life ?? 1}); }
function burst(x, y, n, kind, colors, opts = {}) {
  for (let i = 0; i < n; i++) {
    const a = rnd(0, Math.PI * 2), sp = rnd(opts.min ?? 30, opts.max ?? 110);
    addParticle({x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - (opts.up ?? 30), g: opts.g ?? 120, life: rnd(.6, 1.2) * (opts.life ?? 1),
                 kind, color: pick(colors), size: rnd(2, 4), rot: rnd(0, 6), vr: rnd(-8, 8)});
  }
}
function floatText(x, y, text, color = "#fff", size = 13) { addParticle({x, y, vy: -22, life: 2, kind: "text", text, color, size}); }
function fly(from, to, emoji, dur = 1.1, arc = 60, done) { if (calm) { done?.(); return; } flyers.push({from, to, emoji, dur, arc, t: 0, done}); }

let tickerTimer = 0;
function ticker(text) {
  const el = document.getElementById("worldticker");
  if (!el) return;
  el.textContent = text; el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  clearTimeout(tickerTimer); tickerTimer = setTimeout(() => el.classList.remove("show"), 6000);
}

// ---------- time of day ----------
function sky() {
  const d = new Date();
  const h = mode === "day" ? 13 : mode === "night" ? 23.5 : d.getHours() + d.getMinutes() / 60;
  let dk = 0, tint = 0, tc = "255,160,80", label = "Day", icon = "☀️";
  if (h < 5 || h >= 21.5) { dk = .7; label = "Night"; icon = "🌙"; }
  else if (h < 7) { const k = (h - 5) / 2; dk = lerp(.7, 0, k); tint = .16 * Math.sin(k * Math.PI); label = "Dawn"; icon = "🌅"; }
  else if (h < 17.5) { dk = 0; }
  else if (h < 19.5) { const k = (h - 17.5) / 2; dk = lerp(0, .25, k); tint = .16 * k; tc = "255,110,90"; label = "Dusk"; icon = "🌇"; }
  else { const k = (h - 19.5) / 2; dk = lerp(.25, .7, k); tint = .16 * (1 - k); tc = "255,110,90"; label = "Evening"; icon = "🌆"; }
  return {dk, tint, tc, label, icon, night: dk > .45};
}
let SKY = sky();

// ---------- agents ----------
function makeAgent(info) {
  const key = info.name.toLowerCase();
  const l = look(info.name);
  let home = key === "boss" ? B.hq : key === "chad" ? B.studio : null;
  if (!home) {
    const plot = PLOTS.find(p => !p.agent) || PLOTS[PLOTS.length - 1];
    plot.agent = plot.agent || info.name;
    home = plot;
  }
  const a = {name: info.name, key, role: info.role, color: l.color, hat: l.hat, prop: l.prop, home,
             x: home.front.x + rnd(-10, 10), y: home.front.y + rnd(0, 6), path: [], actions: [], current: null, waitUntil: 0,
             busy: null, sleeping: false, facing: 1, phase: 0, seed: Math.random() * 1000, jumpT: 0, face: "happy", faceUntil: 0,
             carry: null, say: null, sayUntil: 0, nextSpark: 0, speed: key === "boss" ? 46 : 54};
  agents.set(key, a);
  return a;
}

function route(a, to) {
  if (calm) { a.x = to.x; a.y = to.y; a.path = []; return; }
  const p = [];
  const onRoad = y => Math.abs(y - ROAD_Y) < 6;
  if (Math.abs(a.x - to.x) < 4) p.push({x: to.x, y: to.y});
  else {
    if (!onRoad(a.y)) p.push({x: a.x, y: ROAD_Y + rnd(-5, 5)});
    p.push({x: to.x, y: p.length ? p[0].y : a.y});
    p.push({x: to.x, y: to.y});
  }
  a.path = p;
}
function hurry(a) {   // drop whatever idle thing they were doing so a real job starts right away
  if (a.current && !a.current.urgent) { a.current = null; a.path = []; }
  if (!a.current) a.waitUntil = 0;
  a.actions = a.actions.filter(x => x.urgent);
  wake(a);
}
function say(a, text, secs = 4) { a.say = text; a.sayUntil = performance.now() + secs * 1000; }
function feel(a, face, secs = 3) { a.face = face; a.faceUntil = performance.now() + secs * 1000; }
function wake(a) { if (a.sleeping) { a.sleeping = false; a.x = a.home.front.x; a.y = a.home.front.y - 6; } }
const workSpot = a => ({x: a.home.front.x + (a.key === "boss" ? -26 : 0), y: a.home.front.y});

const CHATTER = ["Nice day for clips ☀️", "☕ coffee break", "Anything trending?", "🎵 la la la", "Stretching 🙆", "Vibes are good ✨", "Who moved my chair?"];
const NIGHT_CHATTER = ["Night shift 🌙", "Still grinding 💪", "The stars are out ✨"];
const SWEEP_SAY = ["Squeaky clean ✨", "Who dropped this? 🧹", "Spotless!", "Mopping up 🪣", "Every cent counts 💰"];
const BOSS_PRAISE = ["Looking good, {n}! 👏", "Keep it up, {n}! 🔥", "How's it going, {n}?", "Proud of you, {n} 👑"];

function think(a, now) {
  if (a.path.length || now < a.waitUntil) return;
  if (a.current) {   // just arrived somewhere with a job to do
    const c = a.current; a.current = null;
    c.do?.(); a.waitUntil = now + (c.wait || 0) * 1000;
    return;
  }
  if (a.actions.length) { wake(a); a.working = false; a.current = a.actions.shift(); a.rush = !!a.current.urgent; route(a, a.current.at); return; }
  a.rush = false;
  if (a.key === "boss" && thinking) {
    wake(a);
    if (Math.hypot(a.x - B.hq.front.x, a.y - B.hq.front.y) > 4) route(a, B.hq.front);
    return;
  }
  if (a.busy) {
    wake(a);
    const s = workSpot(a);
    if (Math.hypot(a.x - s.x, a.y - s.y) > 4) { route(a, s); return; }
    a.working = true;
    return;
  }
  a.working = false;
  if (SKY.night) {
    if (a.sleeping) return;
    const f = a.home.front;
    if (Math.hypot(a.x - f.x, a.y - f.y) > 4) { route(a, f); return; }
    a.sleeping = true;
    return;
  }
  wake(a);
  // Idle: wander, sit by the pond, chat, or (for the Boss) check on whoever is working.
  const busy = [...agents.values()].filter(o => o !== a && o.busy && !o.sleeping);
  if (a.key === "boss" && busy.length && Math.random() < .45) {
    const o = pick(busy), s = workSpot(o);
    a.actions.push({at: {x: s.x + 26, y: s.y + 4}, do: () => { a.facing = -1; say(a, pick(BOSS_PRAISE).replace("{n}", o.name), 3.5); }, wait: 4});
    return;
  }
  if (a.key === "sweep" && LITTER.length) {   // the janitor goes to the nearest bit of mess and sweeps it up
    const l = LITTER.reduce((best, o) => Math.hypot(o.x - a.x, o.y - a.y) < Math.hypot(best.x - a.x, best.y - a.y) ? o : best);
    a.actions.push({at: {x: l.x - 12, y: l.y + 4}, wait: 2.2, do: () => {
      a.facing = 1; a.jumpT = .3;
      burst(l.x, l.y - 4, 12, "smoke", ["#d8cdb4", "#e9e1cc"], {min: 8, max: 30, g: -10, up: 6});
      burst(l.x, l.y - 6, 5, "spark", ["#fff8c4", "#9bd1ff"], {min: 15, max: 40, g: 20, life: .8});
      const i = LITTER.indexOf(l); if (i >= 0) LITTER.splice(i, 1);
      say(a, pick(SWEEP_SAY), 3);
    }});
    return;
  }
  const spot = pick(SPOTS);
  a.actions.push({at: {x: spot.x + rnd(-8, 8), y: spot.y + (spot.bench ? 0 : rnd(-6, 6))},
                  do: () => { if (Math.random() < .3) say(a, pick(SKY.label === "Night" ? NIGHT_CHATTER : CHATTER), 3); }, wait: rnd(3, 9)});
}

function step(a, dt, now) {
  if (now > a.faceUntil) a.face = "happy";
  if (a.jumpT > 0) a.jumpT = Math.max(0, a.jumpT - dt);
  if (a.path.length) {
    const t = a.path[0], dx = t.x - a.x, dy = t.y - a.y, d = Math.hypot(dx, dy), s = a.speed * (a.rush ? 2.2 : 1) * dt;
    if (Math.abs(dx) > .5) a.facing = Math.sign(dx);
    if (d <= s) { a.x = t.x; a.y = t.y; a.path.shift(); }
    else { a.x += dx / d * s; a.y += dy / d * s; }
    a.phase += dt * 11;
  }
  if (!a.path.length && !a.sleeping) for (const o of agents.values()) {
    if (o === a || o.sleeping || o.path.length) continue;
    const dx = a.x - o.x, dy = a.y - o.y, d = Math.hypot(dx, dy);
    if (d < 20) { const k = (20 - d) * dt * 2; a.x += (dx || 1) / (d || 1) * k; a.y += dy / (d || 1) * k * .4; }
  }
  if (a.working && !a.path.length && now > a.nextSpark) {
    a.nextSpark = now + 900;
    burst(a.x, a.y - 16, 3, "spark", [a.color, "#fff8c4"], {min: 20, max: 50, g: 40, life: .8});
    if (Math.random() < .35) addParticle({x: a.x + rnd(-8, 8), y: a.y - 30, vy: -18, life: 1.4, kind: "emoji", text: a.prop, size: 11});
  }
  if (a.sleeping && now > a.nextSpark) {
    a.nextSpark = now + 1600;
    const b = a.home;
    addParticle({x: b.x + b.w * .7, y: b.y + 6, vx: 6, vy: -10, life: 2.6, kind: "text", text: "z", color: "#e8e4ff", size: 11});
  }
}

// ---------- reacting to HQ ----------
function deliverer() { return agents.get("chad") || [...agents.values()].find(a => a.key !== "boss") || agents.get("boss"); }

function syncAgents(list) {
  for (const info of list) {
    const a = agents.get(info.name.toLowerCase()) || makeAgent(info);
    a.role = info.role;
    const was = a.busy;
    a.busy = info.doing || null;
    if (!prev) { if (a.busy) { const s = workSpot(a); a.x = s.x; a.y = s.y; } continue; }
    if (a.busy && !was) { hurry(a); say(a, "On it! 💪", 2.5); a.jumpT = .5; ticker(`${a.name} started: ${a.busy}`); }
    if (!a.busy && was) {
      say(a, "Done! ✅", 3); a.jumpT = .5;
      burst(a.x, a.y - 18, 14, "spark", [a.color, "#fff", "#ffd34d"], {g: 60});
      ticker(`${a.name} finished a job`);
    }
  }
}

function react(c) {
  const p = prev;
  const d = k => (c[k] || 0) - (p[k] || 0);
  const chad = deliverer();
  if (d("pending_approval") > 0 && chad) {
    const n = d("pending_approval");
    deliveriesOnTheWay += n;
    let delivered = false;
    const arrive = () => { if (!delivered) { delivered = true; deliveriesOnTheWay = Math.max(0, deliveriesOnTheWay - n); } };
    ticker(`${chad.name} is bringing ${n} new clip${n > 1 ? "s" : ""} to Approvals`);
    hurry(chad);
    chad.actions.push(
      {urgent: true, at: chad.home.front, do: () => { chad.carry = "🎞️"; say(chad, n > 1 ? `${n} fresh clips!` : "Fresh clip!", 2); }, wait: .6},
      {urgent: true, at: {x: B.post.door - 20, y: B.post.front.y}, wait: 1.5, do: () => {
        chad.carry = null; chad.facing = 1;
        arrive();
        mailboxBump = 1;
        fly({x: chad.x, y: chad.y - 30}, {x: MAILBOX.x, y: MAILBOX.y - 28}, "🎞️", .6, 20);
        burst(MAILBOX.x, MAILBOX.y - 30, 10, "emoji", ["💖"], {min: 20, max: 60, g: -10, life: 1.2});
        say(chad, "Waiting for your OK 👀", 3.5);
      }});
    setTimeout(arrive, 30000);   // never leave the mailbox wrong for long
  }
  if (d("approved") > 0) {
    const n = d("approved");
    for (let i = 0; i < Math.min(n, 5); i++) setTimeout(() => {
      addParticle({x: MAILBOX.x, y: MAILBOX.y - 40, vy: -16, life: 1.5, kind: "emoji", text: "👍", size: 16});
      fly({x: MAILBOX.x, y: MAILBOX.y - 26}, {x: BEACON.x, y: BEACON.y + 50}, "✉️", 1.2, 70, () => { towerGlow = 1; floatText(BEACON.x, BEACON.y + 40, "queued ⏳", "#ffe9b0", 11); });
    }, i * 300);
    ticker(`You approved ${n} clip${n > 1 ? "s" : ""}. Off to the Broadcast Tower!`);
  }
  if (d("rejected") > 0) {
    fly({x: MAILBOX.x, y: MAILBOX.y - 26}, {x: TRASH.x, y: TRASH.y - 14}, "🗞️", .9, 50, () => burst(TRASH.x, TRASH.y - 16, 8, "smoke", ["#cfcfcf"], {min: 5, max: 25, g: -20, up: 10}));
    ticker("Clip tossed in the bin 🗑️");
  }
  if (d("posted") > 0) {
    const n = d("posted");
    towerGlow = 1;
    for (let i = 0; i < 3; i++) setTimeout(() => addParticle({x: BEACON.x, y: BEACON.y + 6, life: 1.4, kind: "ring", color: "#7cc4ff"}), i * 280);
    for (let i = 0; i < 3; i++) setTimeout(() => burst(BEACON.x + rnd(-60, 60), rnd(20, 70), 26, "spark", ["#ffb347", "#ff6fa8", "#7cc4ff", "#4ade80", "#fff59e"], {min: 40, max: 120, g: 60, up: 0}), 300 + i * 400);
    burst(BEACON.x, BEACON.y + 20, 30, "confetti", ["#ffb347", "#ff6fa8", "#7cc4ff", "#4ade80"], {up: 80});
    floatText(BEACON.x - 10, BEACON.y + 70, `+${n} posted 🚀`, "#bff7cf", 14);
    if (chad) { chad.jumpT = .7; say(chad, "We're live! 🎉", 3.5); }
    ticker(`${n} clip${n > 1 ? "s" : ""} went live 🚀`);
  }
  if (d("failed") > 0) {
    burst(BEACON.x, BEACON.y + 30, 14, "smoke", ["#8a8a8a", "#b0b0b0"], {min: 10, max: 40, g: -30, up: 10});
    if (chad) { feel(chad, "sad", 5); say(chad, "Posting failed 😬 check Clips", 5); }
    ticker("A post failed. Check the Clips list for why.");
  }
}

let lastActivity = null;
function chatter(activity) {
  const newest = activity[0]?.id ?? 0;
  if (lastActivity === null) { lastActivity = newest; return; }
  const fresh = activity.filter(r => r.id > lastActivity).slice(0, 3).reverse();
  lastActivity = Math.max(lastActivity, newest);
  fresh.forEach((row, i) => setTimeout(() => {
    const a = agents.get(String(row.agent).toLowerCase());
    if (a && !a.sleeping) say(a, row.message, 5);
  }, i * 1800));
}

// ---------- drawing ----------
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }
function outlinedText(text, x, y, size, color, weight = 800) {
  ctx.font = `${weight} ${size}px ${FONT}`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.lineWidth = 3; ctx.strokeStyle = "rgba(20,14,30,.85)"; ctx.strokeText(text, x, y);
  ctx.fillStyle = color; ctx.fillText(text, x, y);
}
function emoji(text, x, y, size, rot = 0) {
  ctx.save(); ctx.translate(x, y); if (rot) ctx.rotate(rot);
  ctx.font = `${size}px ${EMOJI}`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, 0, 0); ctx.restore();
}

let lights = [];
function house(b, t) {
  const wallY = b.y + b.h * .52, bottom = b.y + b.h;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(b.x + b.w / 2 + 6, bottom + 2, b.w / 2 + 8, 8, 0, 0, 7); ctx.fill();
  ctx.fillStyle = b.wall; ctx.fillRect(b.x, wallY, b.w, bottom - wallY);
  ctx.fillStyle = "rgba(0,0,0,.08)"; ctx.fillRect(b.x, bottom - 6, b.w, 6);
  // roof
  ctx.fillStyle = b.roof; ctx.beginPath();
  ctx.moveTo(b.x - 8, wallY + 2); ctx.lineTo(b.x + b.w + 8, wallY + 2); ctx.lineTo(b.x + b.w - 8, b.y); ctx.lineTo(b.x + 8, b.y); ctx.closePath(); ctx.fill();
  ctx.save(); ctx.clip();
  ctx.strokeStyle = "rgba(0,0,0,.14)"; ctx.lineWidth = 2;
  for (let y = b.y + 9; y < wallY; y += 9) { ctx.beginPath(); ctx.moveTo(b.x - 10, y); ctx.lineTo(b.x + b.w + 10, y); ctx.stroke(); }
  ctx.fillStyle = "rgba(255,255,255,.18)"; ctx.fillRect(b.x, b.y, b.w, 4);
  ctx.restore();
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.fillRect(b.x - 8, wallY, b.w + 16, 3);
  // windows
  const lit = SKY.dk > .15;
  for (const wx of b.small ? [] : [b.x + 16, b.x + b.w - 40]) {
    const wy = bottom - 34;
    ctx.fillStyle = "#6b4b2e"; ctx.fillRect(wx - 2, wy - 2, 28, 20);
    ctx.fillStyle = lit ? "#ffd56b" : "#a9dcff"; ctx.fillRect(wx, wy, 24, 16);
    ctx.fillStyle = lit ? "rgba(255,160,40,.35)" : "rgba(255,255,255,.6)"; ctx.fillRect(wx + 2, wy + 2, 6, 5);
    ctx.fillStyle = "#6b4b2e"; ctx.fillRect(wx + 11, wy, 2, 16); ctx.fillRect(wx, wy + 7, 24, 2);
    if (lit) lights.push({x: wx + 12, y: wy + 10, r: 46, warm: .9});
  }
  // door and sign
  ctx.fillStyle = "#7a4a2a"; roundRect(ctx, b.door - 11, bottom - 30, 22, 30, 4); ctx.fill();
  ctx.fillStyle = "#5a361e"; ctx.fillRect(b.door - 1, bottom - 28, 2, 28);
  ctx.fillStyle = "#ffd34d"; ctx.beginPath(); ctx.arc(b.door + 6, bottom - 14, 1.6, 0, 7); ctx.fill();
  ctx.font = `800 9px ${FONT}`;
  const label = `${b.icon} ${b.label}`, lw = ctx.measureText(label).width + 12;
  ctx.fillStyle = "#3a2a1c"; roundRect(ctx, b.door - lw / 2, wallY + 5, lw, 14, 4); ctx.fill();
  ctx.fillStyle = "#fff2d6"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, b.door, wallY + 12.5);
}

function drawBuildings(t, pending) {
  house(B.studio, t);
  emoji("🎥", B.studio.x + 130, B.studio.y + 22, 20, Math.sin(t / 900) * .12);
  // Boss HQ: chimney and a crown flag
  const hq = B.hq;
  ctx.fillStyle = "#a0522d"; ctx.fillRect(hq.x + 146, hq.y - 6, 14, 30);
  ctx.fillStyle = "#7d3f22"; ctx.fillRect(hq.x + 144, hq.y - 8, 18, 5);
  house(hq, t);
  ctx.fillStyle = "#5a4636"; ctx.fillRect(hq.x + 24, hq.y - 26, 3, 40);
  ctx.fillStyle = "#ffb347"; ctx.beginPath(); ctx.moveTo(hq.x + 27, hq.y - 26);
  for (let i = 0; i <= 8; i++) ctx.lineTo(hq.x + 27 + i * 4, hq.y - 26 + Math.sin(t / 220 + i * .8) * 2);
  for (let i = 8; i >= 0; i--) ctx.lineTo(hq.x + 27 + i * 4, hq.y - 10 + Math.sin(t / 220 + i * .8) * 2);
  ctx.fill();
  emoji("👑", hq.x + 43, hq.y - 18 + Math.sin(t / 220 + 3) * 2, 10);
  house(B.post, t);
  // bin and mailbox
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(TRASH.x, TRASH.y, 9, 3, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#7d8a96"; roundRect(ctx, TRASH.x - 8, TRASH.y - 20, 16, 20, 3); ctx.fill();
  ctx.fillStyle = "#5f6b76"; ctx.fillRect(TRASH.x - 9, TRASH.y - 22, 18, 4);
  const mb = MAILBOX, bump = 1 + Math.sin(mailboxBump * Math.PI) * .25;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(mb.x, mb.y, 9, 3, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#6b4b2e"; ctx.fillRect(mb.x - 2, mb.y - 16, 4, 16);
  ctx.save(); ctx.translate(mb.x, mb.y - 22); ctx.scale(bump, bump);
  ctx.fillStyle = "#2f6fd6"; roundRect(ctx, -12, -8, 24, 15, 6); ctx.fill();
  ctx.fillStyle = "#1f4f9e"; ctx.fillRect(-10, -1, 20, 2);
  ctx.fillStyle = "#e53e3e";
  if (pending > 0) { ctx.fillRect(10, -18, 3, 12); ctx.fillRect(10, -18, 8, 5); } else ctx.fillRect(10, -4, 10, 3);
  ctx.restore();
  if (pending > 0) {
    const s = 1 + Math.sin(t / 250) * .08;
    ctx.save(); ctx.translate(mb.x - 12, mb.y - 34); ctx.scale(s, s);
    ctx.fillStyle = "#ff4d6d"; ctx.beginPath(); ctx.arc(0, 0, 8, 0, 7); ctx.fill();
    ctx.font = `900 10px ${FONT}`; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(pending > 99 ? "99+" : pending, 0, .5);
    ctx.restore();
  }
  drawTower(t);
}

function drawTower(t) {
  const b = B.tower, cx = b.x + b.w / 2, base = b.y + b.h;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(cx + 6, base + 2, 44, 8, 0, 0, 7); ctx.fill();
  // lattice
  ctx.strokeStyle = "#c6d3e0"; ctx.lineWidth = 3;
  ctx.beginPath(); ctx.moveTo(b.x + 8, base - 30); ctx.lineTo(cx - 3, b.y + 16); ctx.moveTo(b.x + b.w - 8, base - 30); ctx.lineTo(cx + 3, b.y + 16); ctx.stroke();
  ctx.lineWidth = 1.5; ctx.strokeStyle = "#9fb0c2";
  for (let i = 0; i < 6; i++) {
    const y1 = base - 30 - i * 18, y2 = y1 - 18, k1 = i / 6.5, k2 = (i + 1) / 6.5;
    const l1 = lerp(b.x + 8, cx - 3, k1), r1 = lerp(b.x + b.w - 8, cx + 3, k1), l2 = lerp(b.x + 8, cx - 3, k2), r2 = lerp(b.x + b.w - 8, cx + 3, k2);
    ctx.beginPath(); ctx.moveTo(l1, y1); ctx.lineTo(r2, y2); ctx.moveTo(r1, y1); ctx.lineTo(l2, y2); ctx.moveTo(l2, y2); ctx.lineTo(r2, y2); ctx.stroke();
  }
  // dish and mast
  ctx.fillStyle = "#e9eef5"; ctx.beginPath(); ctx.ellipse(cx + 12, b.y + 52, 9, 6, -.5, 0, 7); ctx.fill();
  ctx.strokeStyle = "#c6d3e0"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(cx, b.y + 16); ctx.lineTo(cx, BEACON.y); ctx.stroke();
  const on = Math.sin(t / 300) > 0 || towerGlow > 0;
  ctx.fillStyle = on ? "#ff3b3b" : "#7a2020"; ctx.beginPath(); ctx.arc(BEACON.x, BEACON.y, 3.5, 0, 7); ctx.fill();
  if (on) lights.push({x: BEACON.x, y: BEACON.y, r: 26, red: true});
  if (towerGlow > 0) {
    ctx.fillStyle = `rgba(124,196,255,${towerGlow * .5})`; ctx.beginPath(); ctx.arc(BEACON.x, BEACON.y, 10 + (1 - towerGlow) * 16, 0, 7); ctx.fill();
  }
  // control shed
  const shed = {x: b.x + 4, y: base - 44, w: b.w - 8, h: 44, wall: "#e2e8f0", roof: "#64748b", door: b.door, label: "Live", icon: "📡", small: true};
  house(shed, t);
  if (shown.approved > 0) {
    ctx.font = `800 10px ${FONT}`;
    const txt = `⏳ ${shown.approved} queued`, w = ctx.measureText(txt).width + 10;
    ctx.fillStyle = "rgba(42,26,8,.85)"; roundRect(ctx, cx - w / 2, base - 62, w, 14, 7); ctx.fill();
    ctx.fillStyle = "#ffd59a"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(txt, cx, base - 55);
  }
}

function drawTree(tr, t) {
  const sway = Math.sin(t / 1100 + tr.i) * 1.4;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(tr.x + 5, tr.y, 18, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#7a4f2c"; ctx.fillRect(tr.x - 3, tr.y - 16, 6, 16);
  const c = {green: ["#3f9a45", "#56b55a", "#79cf6c"], dark: ["#2f7a3c", "#3f9248", "#5bae5c"], blossom: ["#d9709c", "#ef8db5", "#ffc2d9"]}[tr.kind];
  const blob = (dx, dy, r, col) => { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(tr.x + dx + sway, tr.y + dy, r, 0, 7); ctx.fill(); };
  blob(0, -28, 17, c[0]); blob(-8, -32, 11, c[1]); blob(8, -33, 10, c[1]); blob(-3, -38, 8, c[2]);
}
function drawLamp(l) {
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(l.x + 2, l.y, 5, 2, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#3b3346"; ctx.fillRect(l.x - 1.5, l.y - 26, 3, 26);
  const on = SKY.dk > .15;
  ctx.fillStyle = on ? "#fff1b0" : "#cfd6dd"; roundRect(ctx, l.x - 4.5, l.y - 33, 9, 8, 2); ctx.fill();
  ctx.fillStyle = "#3b3346"; ctx.fillRect(l.x - 5.5, l.y - 35, 11, 2.5);
  if (on) lights.push({x: l.x, y: l.y - 28, r: 70, warm: 1});
}
function drawBench(b) {
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.fillRect(b.x - 18, b.y + 1, 38, 3);
  ctx.fillStyle = "#6b4b2e"; ctx.fillRect(b.x - 16, b.y - 4, 3, 6); ctx.fillRect(b.x + 13, b.y - 4, 3, 6);
  ctx.fillStyle = "#a8713f"; ctx.fillRect(b.x - 18, b.y - 8, 36, 5); ctx.fillRect(b.x - 18, b.y - 15, 36, 4);
}
function drawPlot(p) {
  ctx.strokeStyle = "#8a5a32"; ctx.lineWidth = 2;
  const posts = [];
  for (let x = p.x - 4; x <= p.x + p.w + 4; x += 15) posts.push([x, p.y + p.h + 4]);
  for (let y = p.y; y <= p.y + p.h; y += 15) posts.push([p.x - 4, y], [p.x + p.w + 4, y]);
  ctx.beginPath(); ctx.moveTo(p.x - 4, p.y); ctx.lineTo(p.x - 4, p.y + p.h + 4); ctx.lineTo(p.x + p.w + 4, p.y + p.h + 4); ctx.lineTo(p.x + p.w + 4, p.y); ctx.stroke();
  ctx.fillStyle = "#6b4226"; for (const [x, y] of posts) ctx.fillRect(x - 1.5, y - 7, 3, 8);
  if (!p.agent) {
    ctx.fillStyle = "#6b4226"; ctx.fillRect(p.x + p.w / 2 - 1.5, p.y + 20, 3, 20);
    ctx.fillStyle = "#fff6e0"; roundRect(ctx, p.x + p.w / 2 - 32, p.y + 10, 64, 16, 3); ctx.fill();
    ctx.font = `800 8px ${FONT}`; ctx.fillStyle = "#6b4226"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("+ HIRING SOON", p.x + p.w / 2, p.y + 18.5);
    return;
  }
  const a = agents.get(p.agent.toLowerCase());
  const col = a?.color || "#7cc4ff";
  const hx = p.x + 14, hy = p.y + 14, hw = p.w - 28, hh = 46;
  ctx.fillStyle = "#fff6e0"; ctx.fillRect(hx, hy + hh * .45, hw, hh * .55);
  ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(hx - 5, hy + hh * .47); ctx.lineTo(hx + hw + 5, hy + hh * .47); ctx.lineTo(hx + hw - 5, hy); ctx.lineTo(hx + 5, hy); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#7a4a2a"; ctx.fillRect(p.x + p.w / 2 - 6, hy + hh - 16, 12, 16);
  const lit = SKY.dk > .15;
  ctx.fillStyle = lit ? "#ffd56b" : "#a9dcff"; ctx.fillRect(hx + 4, hy + hh - 16, 10, 8); ctx.fillRect(hx + hw - 14, hy + hh - 16, 10, 8);
  if (lit) lights.push({x: p.x + p.w / 2, y: hy + hh - 12, r: 40, warm: .8});
  if (a?.key === "sweep") { emoji("🪣", p.x + 10, p.y + p.h - 6, 15); emoji("🧹", p.x + p.w - 8, p.y + p.h - 16, 17, .35); }   // the janitor's shed
}

function drawAgent(a, t) {
  if (a.sleeping) return;
  if (a.key === "boss") return drawBoss(a, t);
  const walking = a.path.length > 0;
  let bob = walking ? -Math.abs(Math.sin(a.phase)) * 3 : Math.sin(t / 500 + a.seed) * 1.2;
  if (a.working && !walking) bob = -Math.abs(Math.sin(t / 140)) * 4;
  if (a.jumpT > 0) bob -= Math.sin((1 - a.jumpT / .7) * Math.PI) * 12;
  const x = a.x, y = a.y, f = a.facing;
  ctx.fillStyle = "rgba(0,0,0,.28)"; ctx.beginPath(); ctx.ellipse(x, y, 11, 3.5, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#2a2233";
  const step = walking ? Math.sin(a.phase) * 3 : 0;
  ctx.beginPath(); ctx.ellipse(x - 5 + step, y - 1, 3.5, 2.2, 0, 0, 7); ctx.ellipse(x + 5 - step, y - 1, 3.5, 2.2, 0, 0, 7); ctx.fill();
  const by = y - 14 + bob;
  ctx.fillStyle = a.color; ctx.beginPath(); ctx.ellipse(x, by, 13, 12.5, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,.5)"; ctx.lineWidth = 2; ctx.lineCap = "round";
  ctx.beginPath(); ctx.arc(x, by, 9, Math.PI * 1.1, Math.PI * 1.45); ctx.stroke();
  // face
  const ex = f * 2, blink = (t + a.seed * 7) % 4200 < 130;
  ctx.fillStyle = "#1d1426";
  for (const dx of [-5, 5]) {
    if (blink) ctx.fillRect(x + dx + ex - 2, by - 2, 4, 1.4);
    else { ctx.beginPath(); ctx.ellipse(x + dx + ex, by - 2, 2, 2.7, 0, 0, 7); ctx.fill(); }
  }
  if (!blink) { ctx.fillStyle = "#fff"; for (const dx of [-5, 5]) { ctx.beginPath(); ctx.arc(x + dx + ex + .7, by - 3, .8, 0, 7); ctx.fill(); } }
  ctx.fillStyle = "rgba(255,255,255,.3)"; ctx.beginPath(); ctx.arc(x - 8 + ex, by + 3, 2.4, 0, 7); ctx.arc(x + 8 + ex, by + 3, 2.4, 0, 7); ctx.fill();
  ctx.strokeStyle = "#1d1426"; ctx.lineWidth = 1.6;
  ctx.beginPath();
  if (a.face === "sad") ctx.arc(x + ex, by + 6.5, 3, Math.PI * 1.15, Math.PI * 1.85);
  else if ((a.key === "boss" && thinking) || a.face === "o") { ctx.ellipse(x + ex, by + 4, 1.6, 2, 0, 0, 7); }
  else ctx.arc(x + ex, by + 2, 3.2, Math.PI * .15, Math.PI * .85);
  ctx.stroke();
  if (a.hat === "janitor") { ctx.fillStyle = "#ff9f1c"; ctx.fillRect(x - 11, by + 6, 22, 3); ctx.fillStyle = "rgba(255,255,255,.55)"; ctx.fillRect(x - 11, by + 7, 22, 1); }   // hi-vis stripe
  // hat
  if (a.hat === "crown") {
    ctx.fillStyle = "#ffd34d"; ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 1;
    ctx.beginPath(); const hy = by - 11;
    ctx.moveTo(x - 8, hy); ctx.lineTo(x - 7, hy - 8); ctx.lineTo(x - 3, hy - 4); ctx.lineTo(x, hy - 10); ctx.lineTo(x + 3, hy - 4); ctx.lineTo(x + 7, hy - 8); ctx.lineTo(x + 8, hy); ctx.closePath(); ctx.fill(); ctx.stroke();
  } else if (a.hat === "janitor") {
    ctx.fillStyle = "#2b5fb8"; ctx.beginPath(); ctx.ellipse(x, by - 9, 11, 6, 0, Math.PI, 0); ctx.fill();
    ctx.fillRect(f > 0 ? x + 4 : x - 14, by - 10, 10, 2.6);
    ctx.fillStyle = "#ffd34d"; ctx.fillRect(x - 3, by - 14, 6, 2.2);
  } else if (a.hat === "cap") {
    ctx.fillStyle = "#2a2233"; ctx.beginPath(); ctx.ellipse(x, by - 9, 11, 6, 0, Math.PI, 0); ctx.fill();
    ctx.fillRect(f > 0 ? x + 4 : x - 14, by - 10, 10, 2.6);
  }
  // what they're holding, or carrying overhead
  const swing = a.working && !walking ? Math.sin(t / 90) * .6 : Math.sin(t / 600 + a.seed) * .15;
  emoji(a.prop, x + f * 14, by + 5, 11, swing);
  if (a.carry) emoji(a.carry, x, by - 26 + Math.sin(t / 150) * 1.5, 15);
}
// The Boss is a full person (taller than the round agents) so he stands out: suit, tie, cape, crown.
const BOSS_SCALE = 1.4;
function drawBoss(a, t) {
  const walking = a.path.length > 0;
  let bob = walking ? -Math.abs(Math.sin(a.phase)) * 3 : Math.sin(t / 500 + a.seed) * 1.2;
  if (a.working && !walking) bob = -Math.abs(Math.sin(t / 140)) * 3;
  if (a.jumpT > 0) bob -= Math.sin((1 - a.jumpT / .7) * Math.PI) * 12;
  const x = 0, y = 0, f = a.facing, step = walking ? Math.sin(a.phase) * 4 : 0;
  ctx.save(); ctx.translate(a.x, a.y); ctx.scale(BOSS_SCALE, BOSS_SCALE);
  const SKIN = "#e9b48a", SUIT = "#2b2f6b", SUIT_HI = "#3d438f";
  ctx.fillStyle = "rgba(0,0,0,.3)"; ctx.beginPath(); ctx.ellipse(x, y, 15, 4.5, 0, 0, 7); ctx.fill();
  // gold glow so he pops off the grass
  const g = ctx.createRadialGradient(x, y - 26 + bob, 4, x, y - 26 + bob, 40);
  g.addColorStop(0, "rgba(255,215,90,.28)"); g.addColorStop(1, "rgba(255,215,90,0)");
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y - 26 + bob, 40, 0, 7); ctx.fill();
  // cape (behind the body)
  const sway = Math.sin(t / 350 + a.seed) * 2 - f * (walking ? 3 : 1);
  ctx.fillStyle = "#b3202a";
  ctx.beginPath(); ctx.moveTo(x - 10, y - 37 + bob); ctx.lineTo(x + 10, y - 37 + bob);
  ctx.quadraticCurveTo(x + 15 + sway, y - 18 + bob, x + 13 + sway, y - 6); ctx.lineTo(x - 13 + sway, y - 6);
  ctx.quadraticCurveTo(x - 15 + sway, y - 18 + bob, x - 10, y - 37 + bob); ctx.fill();
  // legs + shoes
  ctx.strokeStyle = "#1c1f45"; ctx.lineWidth = 5.5; ctx.lineCap = "round";
  ctx.beginPath(); ctx.moveTo(x - 4, y - 18 + bob); ctx.lineTo(x - 4 + step, y - 4);
  ctx.moveTo(x + 4, y - 18 + bob); ctx.lineTo(x + 4 - step, y - 4); ctx.stroke();
  ctx.fillStyle = "#15121c";
  ctx.beginPath(); ctx.ellipse(x - 4 + step + f * 1.5, y - 2, 4.2, 2.4, 0, 0, 7); ctx.ellipse(x + 4 - step + f * 1.5, y - 2, 4.2, 2.4, 0, 0, 7); ctx.fill();
  // suit jacket
  const ty = y - 38 + bob;
  ctx.fillStyle = SUIT; roundRect(ctx, x - 11, ty, 22, 23, 6); ctx.fill();
  ctx.fillStyle = SUIT_HI; ctx.fillRect(x - 9, ty + 2, 3, 18);
  // shirt V, tie, buttons
  ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.moveTo(x - 5, ty); ctx.lineTo(x + 5, ty); ctx.lineTo(x, ty + 10); ctx.fill();
  ctx.fillStyle = "#d4282f"; ctx.beginPath(); ctx.moveTo(x - 1.6, ty + 1); ctx.lineTo(x + 1.6, ty + 1); ctx.lineTo(x + 2.4, ty + 9); ctx.lineTo(x, ty + 12); ctx.lineTo(x - 2.4, ty + 9); ctx.fill();
  ctx.fillStyle = "#ffd34d"; for (const by of [ty + 14, ty + 18]) { ctx.beginPath(); ctx.arc(x, by, 1.1, 0, 7); ctx.fill(); }
  // arms (wave when he's praising someone, pump when working)
  const swing = walking ? Math.sin(a.phase) * 5 : a.working ? Math.sin(t / 120) * 4 : Math.sin(t / 700 + a.seed) * 1.5;
  const waving = a.say && performance.now() < a.sayUntil;
  ctx.strokeStyle = SUIT; ctx.lineWidth = 5;
  ctx.beginPath(); ctx.moveTo(x - 10, ty + 4); ctx.lineTo(x - 13 - swing * .3, ty + 18 + swing * .2);
  if (waving) { ctx.moveTo(x + 10 * f, ty + 4); ctx.lineTo(x + 18 * f, ty - 6 + Math.sin(t / 110) * 2); }
  else { ctx.moveTo(x + 10, ty + 4); ctx.lineTo(x + 13 + swing * .3, ty + 18 - swing * .2); }
  ctx.stroke();
  ctx.fillStyle = SKIN; ctx.beginPath();
  ctx.arc(x - 13 - swing * .3, ty + 19 + swing * .2, 2.8, 0, 7);
  if (waving) ctx.arc(x + 18 * f, ty - 8 + Math.sin(t / 110) * 2, 3, 0, 7); else ctx.arc(x + 13 + swing * .3, ty + 19 - swing * .2, 2.8, 0, 7);
  ctx.fill();
  // neck + head
  const hy = ty - 10;
  ctx.fillStyle = SKIN; ctx.fillRect(x - 3, ty - 4, 6, 5);
  ctx.beginPath(); ctx.ellipse(x, hy, 10, 11, 0, 0, 7); ctx.fill();
  ctx.beginPath(); ctx.ellipse(x - 10 * f, hy + 1, 2, 3, 0, 0, 7); ctx.fill();   // ear
  // hair
  ctx.fillStyle = "#3b2a20";
  ctx.beginPath(); ctx.ellipse(x - f * 1, hy - 6, 10.5, 6, 0, Math.PI, 0); ctx.fill();
  ctx.fillRect(x - 10.5, hy - 7, 3, 7); ctx.fillRect(x + 7.5, hy - 7, 3, 7);
  // face
  const ex = f * 2.5, blink = (t + a.seed * 7) % 4200 < 130;
  ctx.fillStyle = "#1d1426";
  for (const dx of [-3.8, 3.8]) {
    if (blink) ctx.fillRect(x + dx + ex - 1.6, hy, 3.2, 1.2);
    else { ctx.beginPath(); ctx.ellipse(x + dx + ex, hy + .5, 1.5, 2, 0, 0, 7); ctx.fill(); }
  }
  ctx.strokeStyle = "#3b2a20"; ctx.lineWidth = 1.4;
  ctx.beginPath(); ctx.moveTo(x - 6 + ex, hy - 3.5); ctx.lineTo(x - 2 + ex, hy - 3); ctx.moveTo(x + 2 + ex, hy - 3); ctx.lineTo(x + 6 + ex, hy - 3.5); ctx.stroke();
  ctx.fillStyle = "rgba(230,110,110,.35)"; ctx.beginPath(); ctx.arc(x - 6 + ex, hy + 4.5, 2, 0, 7); ctx.arc(x + 6 + ex, hy + 4.5, 2, 0, 7); ctx.fill();
  ctx.fillStyle = "#3b2a20"; ctx.beginPath(); ctx.ellipse(x + ex, hy + 5.6, 4.5, 1.5, 0, Math.PI, 0); ctx.fill();   // moustache
  ctx.strokeStyle = "#7a3a2a"; ctx.lineWidth = 1.3; ctx.beginPath();
  if (a.face === "sad") ctx.arc(x + ex, hy + 10, 2.4, Math.PI * 1.15, Math.PI * 1.85);
  else if (thinking || a.face === "o") ctx.ellipse(x + ex, hy + 8, 1.3, 1.6, 0, 0, 7);
  else ctx.arc(x + ex, hy + 6.5, 2.6, Math.PI * .15, Math.PI * .85);
  ctx.stroke();
  // crown
  ctx.fillStyle = "#ffd34d"; ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 1;
  const cy = hy - 10;
  ctx.beginPath(); ctx.moveTo(x - 8, cy); ctx.lineTo(x - 8, cy - 8); ctx.lineTo(x - 4, cy - 4); ctx.lineTo(x, cy - 10); ctx.lineTo(x + 4, cy - 4); ctx.lineTo(x + 8, cy - 8); ctx.lineTo(x + 8, cy); ctx.closePath(); ctx.fill(); ctx.stroke();
  ctx.fillStyle = "#d4282f"; ctx.beginPath(); ctx.arc(x, cy - 3, 1.5, 0, 7); ctx.fill();
  if (a.carry) emoji(a.carry, x, cy - 20 + Math.sin(t / 150) * 1.5, 15);
  ctx.restore();
}
function drawNames() {
  for (const a of agents.values()) if (!a.sleeping) {
    if (a.key === "boss") outlinedText("👑 " + a.name, a.x, a.y + 14, 12, "#ffd34d");
    else outlinedText(a.name, a.x, a.y + 10, 9, "#fff");
  }
}
function drawBubble(a, t) {
  if (a.sleeping) return;
  const now = performance.now();
  let text = null, dots = false;
  if (a.say && now < a.sayUntil) text = a.say;
  else if (a.key === "boss" && thinking) { text = "Thinking"; dots = true; }
  else if (a.busy && a.working) text = a.busy;
  if (!text) return;
  ctx.font = `700 10px ${FONT}`;
  let s = text;
  if (ctx.measureText(s).width > 170) { while (s.length > 1 && ctx.measureText(s + "…").width > 170) s = s.slice(0, -1); s += "…"; }
  const w = ctx.measureText(s).width + (dots ? 22 : 0) + 14, h = 18;
  const bx = clamp(a.x - w / 2, 4, W - w - 4), by = a.y - (a.carry ? 70 : 52) - (a.key === "boss" ? 46 : 0) + Math.sin(t / 400 + a.seed) * 1;
  ctx.fillStyle = "rgba(0,0,0,.18)"; roundRect(ctx, bx + 1, by + 2, w, h, 8); ctx.fill();
  ctx.fillStyle = "#fff"; roundRect(ctx, bx, by, w, h, 8); ctx.fill();
  ctx.beginPath(); ctx.moveTo(a.x - 4, by + h - 1); ctx.lineTo(a.x + 4, by + h - 1); ctx.lineTo(a.x, by + h + 5); ctx.fill();
  ctx.fillStyle = "#2a2233"; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(s, bx + 7, by + h / 2 + .5);
  if (dots) for (let i = 0; i < 3; i++) {
    ctx.globalAlpha = .3 + .7 * Math.max(0, Math.sin(t / 160 - i * .8));
    ctx.beginPath(); ctx.arc(bx + w - 18 + i * 5, by + h / 2, 1.8, 0, 7); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawWater(t) {
  ctx.save(); ctx.beginPath(); ctx.ellipse(POND.x, POND.y, POND.rx, POND.ry, 0, 0, 7); ctx.clip();
  ctx.strokeStyle = "rgba(255,255,255,.45)"; ctx.lineWidth = 1.5;
  for (let i = 0; i < 6; i++) {
    const x = POND.x - 70 + ((i * 37 + t / 60) % 140), y = POND.y - 26 + i * 10;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 10 + Math.sin(t / 500 + i) * 3, y); ctx.stroke();
  }
  if (SKY.dk > .3) { ctx.fillStyle = "rgba(255,250,220,.5)"; ctx.beginPath(); ctx.arc(POND.x + 40, POND.y - 12, 6, 0, 7); ctx.fill(); }
  ctx.restore();
  for (const d of ducks) {
    const x = POND.x + Math.cos(d.a) * POND.rx * d.k, y = POND.y + Math.sin(d.a) * POND.ry * d.k;
    const dir = -Math.sin(d.a) >= 0 ? 1 : -1;
    ctx.strokeStyle = "rgba(255,255,255,.4)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(x - dir * 4, y + 2, 6 + (t / 200 % 4), Math.PI * .2, Math.PI * .8); ctx.stroke();
    ctx.fillStyle = "#fff"; ctx.beginPath(); ctx.ellipse(x, y, 6, 4, 0, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(x + dir * 5, y - 4, 3, 0, 7); ctx.fill();
    ctx.fillStyle = "#ffa62b"; ctx.fillRect(x + dir * 7.5 - (dir < 0 ? 3 : 0), y - 4.5, 3, 1.6);
    ctx.fillStyle = "#1d1426"; ctx.fillRect(x + dir * 5.5, y - 5, 1, 1);
  }
}

function drawParticles() {
  for (const p of particles) {
    const k = clamp(p.life / p.max, 0, 1);
    ctx.globalAlpha = p.kind === "smoke" ? k * .45 : Math.min(1, k * 1.6);
    if (p.kind === "spark") {
      ctx.fillStyle = p.color; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      const s = p.size; ctx.beginPath(); ctx.moveTo(0, -s); ctx.lineTo(s * .3, 0); ctx.lineTo(0, s); ctx.lineTo(-s * .3, 0); ctx.closePath(); ctx.fill();
      ctx.rotate(Math.PI / 2); ctx.fill(); ctx.restore();
    } else if (p.kind === "confetti") {
      ctx.fillStyle = p.color; ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot); ctx.fillRect(-2.5, -1.5, 5, 3); ctx.restore();
    } else if (p.kind === "smoke") {
      ctx.fillStyle = p.color; ctx.beginPath(); ctx.arc(p.x, p.y, 3 + (1 - k) * 9, 0, 7); ctx.fill();
    } else if (p.kind === "ring") {
      ctx.strokeStyle = p.color; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(p.x, p.y, 6 + (1 - k) * 70, 0, 7); ctx.stroke();
    } else if (p.kind === "drop") {
      ctx.fillStyle = "#cdeeff"; ctx.beginPath(); ctx.arc(p.x, p.y, 1.4, 0, 7); ctx.fill();
    } else if (p.kind === "text") {
      outlinedText(p.text, p.x, p.y, p.size, p.color);
    } else if (p.kind === "emoji") {
      emoji(p.text || p.color, p.x, p.y, p.size || 12);
    }
  }
  ctx.globalAlpha = 1;
  for (const f of flyers) {
    const k = Math.min(1, f.t / f.dur), e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    const x = lerp(f.from.x, f.to.x, e), y = lerp(f.from.y, f.to.y, e) - Math.sin(k * Math.PI) * f.arc;
    emoji(f.emoji, x, y, 14, Math.sin(k * Math.PI * 2) * .3);
  }
}

function drawLightsAndDark(t) {
  if (SKY.tint > 0) { ctx.fillStyle = `rgba(${SKY.tc},${SKY.tint})`; ctx.fillRect(0, 0, W, H); }
  if (SKY.dk <= 0) return;
  dctx.globalCompositeOperation = "source-over";
  dctx.clearRect(0, 0, dark.width, dark.height);
  dctx.fillStyle = `rgba(8,12,46,${SKY.dk})`; dctx.fillRect(0, 0, dark.width, dark.height);
  dctx.globalCompositeOperation = "destination-out";
  for (const l of lights) {
    const x = l.x / 2, y = l.y / 2, r = l.r / 2 * (1 + Math.sin(t / 700 + l.x) * .03);
    const g = dctx.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, "rgba(0,0,0,.95)"); g.addColorStop(1, "rgba(0,0,0,0)");
    dctx.fillStyle = g; dctx.beginPath(); dctx.arc(x, y, r, 0, 7); dctx.fill();
  }
  ctx.drawImage(dark, 0, 0, W, H);
  ctx.globalCompositeOperation = "lighter";
  for (const l of lights) {
    const g = ctx.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.r * .6);
    g.addColorStop(0, l.red ? `rgba(255,60,60,${.35 * SKY.dk})` : `rgba(255,190,90,${.28 * SKY.dk * (l.warm || 1)})`); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(l.x, l.y, l.r * .6, 0, 7); ctx.fill();
  }
  if (SKY.dk > .3) for (const f of fireflies) {
    const a = (.5 + .5 * Math.sin(t / 300 + f.ph * 2)) * (SKY.dk - .3) * 2.5;
    const g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, 7);
    g.addColorStop(0, `rgba(220,255,120,${a})`); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(f.x, f.y, 7, 0, 7); ctx.fill();
  }
  ctx.globalCompositeOperation = "source-over";
}

function drawSkyLife(t) {
  const day = 1 - clamp(SKY.dk * 2, 0, 1);
  if (day <= 0) return;
  for (const c of clouds) {
    ctx.fillStyle = `rgba(20,50,20,${.07 * day})`;
    for (const [dx, dy, rx] of [[0, 0, 44], [34, 6, 30], [-30, 8, 28]]) { ctx.beginPath(); ctx.ellipse(c.x + dx * c.s, c.y + dy * c.s, rx * c.s, rx * .45 * c.s, 0, 0, 7); ctx.fill(); }
  }
  ctx.globalAlpha = day;
  for (const b of butterflies) {
    const x = b.cx + Math.sin(t / 1400 + b.ph) * 30, y = b.cy + Math.sin(t / 770 + b.ph) * 14, w = Math.abs(Math.sin(t / 55 + b.ph)) * 4 + 1;
    ctx.fillStyle = b.c; ctx.beginPath(); ctx.ellipse(x - w / 2 - .5, y, w / 2 + .5, 3, 0, 0, 7); ctx.ellipse(x + w / 2 + .5, y, w / 2 + .5, 3, 0, 0, 7); ctx.fill();
  }
  ctx.strokeStyle = "#2a2233"; ctx.lineWidth = 1.5;
  for (const fl of birds) for (const b of fl.birds) {
    const x = fl.x + b.dx, y = fl.y + b.dy, wing = Math.sin(t / 90 + b.dx) * 4;
    ctx.fillStyle = "rgba(0,0,0,.12)"; ctx.beginPath(); ctx.ellipse(x + 10, y + 46, 4, 1.5, 0, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.moveTo(x - 6, y - wing); ctx.lineTo(x, y); ctx.lineTo(x + 6, y - wing); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function draw(t) {
  if (!terrain) return;
  SKY = sky();
  lights = [];
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(terrain, 0, 0);
  ctx.setTransform(scale, 0, 0, scale, 0, 0);
  drawWater(t);
  const pending = Math.max(0, shown.pending - deliveriesOnTheWay);
  drawBuildings(t, pending);
  const things = [
    ...TREES.map(o => ({y: o.y, d: () => drawTree(o, t)})),
    ...LAMPS.map(o => ({y: o.y, d: () => drawLamp(o)})),
    ...BENCHES.map(o => ({y: o.y - 2, d: () => drawBench(o)})),
    ...PLOTS.map(o => ({y: o.y + 40, d: () => drawPlot(o)})),
    ...LITTER.map(o => ({y: o.y, d: () => drawLitter(o)})),
    ...[...agents.values()].map(a => ({y: a.y, d: () => drawAgent(a, t)})),
  ].sort((p, q) => p.y - q.y);
  for (const th of things) th.d();
  drawParticles();
  drawSkyLife(t);
  drawLightsAndDark(t);
  drawNames();
  if (pending > 0) {   // a bouncing "!" over Approvals while clips wait for you
    const y = B.post.y - 14 + Math.sin(t / 220) * 4;
    ctx.fillStyle = "#ffd34d"; ctx.beginPath(); ctx.arc(B.post.door, y, 10, 0, 7); ctx.fill();
    ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.font = `900 14px ${FONT}`; ctx.fillStyle = "#4a2a00"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("!", B.post.door, y + 1);
  }
  for (const a of agents.values()) drawBubble(a, t);
}

// ---------- simulation ----------
let fountainAcc = 0, smokeAcc = 0;
function tick(dt, now) {
  for (const a of agents.values()) { think(a, now); step(a, dt, now); }
  mailboxBump = Math.max(0, mailboxBump - dt * 2);
  towerGlow = Math.max(0, towerGlow - dt * .7);
  for (const d of ducks) d.a += d.sp * dt;
  for (const c of clouds) { c.x += 9 * dt; if (c.x > W + 160) { c.x = -160; c.y = rnd(40, H - 40); } }
  for (const f of fireflies) {
    f.vx = clamp(f.vx + rnd(-20, 20) * dt, -12, 12); f.vy = clamp(f.vy + rnd(-20, 20) * dt, -10, 10);
    f.x = (f.x + f.vx * dt + W) % W; f.y = clamp(f.y + f.vy * dt, 40, H - 4);
  }
  if (!SKY.night && now > nextBirds) {
    nextBirds = now + rnd(18000, 40000);
    const n = 3 + Math.floor(Math.random() * 3), dir = Math.random() < .5 ? 1 : -1;
    birds.push({x: dir > 0 ? -60 : W + 60, y: rnd(30, H - 120), vx: dir * rnd(55, 80), vy: rnd(-6, 6), birds: Array.from({length: n}, (_, i) => ({dx: -dir * i * 12, dy: (i % 2 ? 1 : -1) * Math.ceil(i / 2) * 9}))});
  }
  for (let i = birds.length - 1; i >= 0; i--) { const b = birds[i]; b.x += b.vx * dt; b.y += b.vy * dt; if (b.x < -120 || b.x > W + 120) birds.splice(i, 1); }
  fountainAcc += dt * 26;
  while (fountainAcc > 1) { fountainAcc--; addParticle({x: PLAZA.x + rnd(-1, 1), y: PLAZA.y - 6, vx: rnd(-22, 22), vy: rnd(-62, -48), g: 170, life: .62, kind: "drop"}); }
  smokeAcc += dt;
  if (smokeAcc > .55) { smokeAcc = 0; addParticle({x: B.hq.x + 153 + rnd(-2, 2), y: B.hq.y - 10, vx: rnd(4, 10), vy: rnd(-16, -10), g: -2, life: 3, kind: "smoke", color: "#ece8f0"}); }
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.life -= dt; if (p.life <= 0) { particles.splice(i, 1); continue; }
    p.vy += p.g * dt; p.x += p.vx * dt; p.y += p.vy * dt; if (p.vr) p.rot += p.vr * dt;
    if (p.kind === "confetti") { p.vx *= .98; p.vy = Math.min(p.vy, 60); }
  }
  for (let i = flyers.length - 1; i >= 0; i--) { const f = flyers[i]; f.t += dt; if (f.t >= f.dur) { flyers.splice(i, 1); f.done?.(); } }
}

let last = performance.now(), visible = true;
function frame(t) {
  if (t - last < 30) { requestAnimationFrame(frame); return; }
  const dt = Math.min(.05, (t - last) / 1000); last = t;
  tick(dt, t);
  if (visible) draw(t);
  requestAnimationFrame(frame);
}

// ---------- HUD, hover and clicks ----------
function hud() {
  const el = document.getElementById("worldclock");
  if (!el) return;
  const s = sky(), time = new Date().toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  el.textContent = mode === "auto" ? `${s.icon} ${s.label} · ${time}` : `${s.icon} ${s.label}`;
  const btn = document.getElementById("worldmode");
  if (btn) btn.textContent = {auto: "🕒 Real time", day: "☀️ Always day", night: "🌙 Always night"}[mode];
}
const modeBtn = document.getElementById("worldmode");
if (modeBtn) modeBtn.onclick = () => { mode = {auto: "day", day: "night", night: "auto"}[mode]; hud(); if (calm) draw(performance.now()); };

function toWorld(e) {
  const r = canvas.getBoundingClientRect();
  return {x: (e.clientX - r.left) / r.width * W, y: (e.clientY - r.top) / r.height * H};
}
function hit(p) {
  for (const a of agents.values()) if (!a.sleeping && (a.key === "boss" ? Math.abs(p.x - a.x) < 22 && p.y > a.y - 86 && p.y < a.y + 4 : Math.hypot(p.x - a.x, p.y - (a.y - 14)) < 18)) return {agent: a};
  for (const [k, b] of Object.entries(B)) if (p.x > b.x - 8 && p.x < b.x + b.w + 8 && p.y > b.y - 10 && p.y < b.y + b.h + 4) return {building: k};
  if (Math.hypot(p.x - MAILBOX.x, p.y - (MAILBOX.y - 18)) < 18) return {building: "post"};
  for (const pl of PLOTS) if (p.x > pl.x && p.x < pl.x + pl.w && p.y > pl.y && p.y < pl.y + pl.h) return {plot: pl};
  return null;
}
const TIPS = {
  studio: "Clip Studio: where Chad cuts clips. Click to see your clips.",
  hq: "Boss HQ: click to talk to the Boss.",
  post: () => `Approvals: ${shown.pending} clip${shown.pending === 1 ? "" : "s"} waiting for you. Click to review.`,
  tower: () => `Broadcast Tower: approved clips get posted from here.${shown.approved ? ` ${shown.approved} queued.` : ""} Click to see posted clips.`,
};
const tip = document.getElementById("worldtip");
canvas.addEventListener("mousemove", e => {
  const p = toWorld(e), h = hit(p);
  canvas.style.cursor = h ? "pointer" : "default";
  if (!tip) return;
  let text = "";
  if (h?.agent) {
    const a = h.agent;
    text = `${a.name}: ${a.busy ? "working on " + a.busy : a.role || ""}`;
  } else if (h?.building) { const v = TIPS[h.building]; text = typeof v === "function" ? v() : v; }
  else if (h?.plot) text = h.plot.agent ? (h.plot.agent === "Sweep" ? "Sweep's shed: the janitor lives here. Click for today's cost report." : `${h.plot.agent}'s cottage`) : "An empty plot for your next agent.";
  tip.textContent = text;
  tip.style.display = text ? "block" : "none";
  if (text) {
    const r = canvas.getBoundingClientRect();
    tip.style.left = clamp(e.clientX - r.left + 14, 4, r.width - 230) + "px";
    tip.style.top = (e.clientY - r.top + 14) + "px";
  }
});
canvas.addEventListener("mouseleave", () => { if (tip) tip.style.display = "none"; });
canvas.addEventListener("click", e => {
  const h = hit(toWorld(e));
  if (!h) return;
  const goTo = id => (window.hqTabs?.showFor(id), (document.getElementById(id)?.closest("section") || document.getElementById(id))?.scrollIntoView({behavior: calm ? "auto" : "smooth", block: "start"}));
  if (h.agent) {
    const a = h.agent;
    a.jumpT = .5;
    say(a, a.busy ? `Working on: ${a.busy}` : (a.key === "boss" ? "Need something? Click HQ or the Boss tab to chat 👑" : `Hi! I'm ${a.name} 👋`), 3.5);
    burst(a.x, a.y - 30, 6, "emoji", ["💖"], {min: 10, max: 40, g: -10});
    if (a.key === "sweep") goTo("sweep");
  } else if (h.building === "post") goTo("pending");
  else if (h.building === "tower" || h.building === "studio") goTo("library");
  else if (h.building === "hq") { goTo("chatlog"); setTimeout(() => document.getElementById("chatinput")?.focus({preventScroll: true}), 400); }
  else if (h.plot?.agent === "Sweep") goTo("sweep");
  else if (h.plot && !h.plot.agent) floatText(h.plot.x + h.plot.w / 2, h.plot.y, "Coming soon 🌱", "#e8ffd8", 12);
});

// ---------- public API ----------
window.HQWorld = {
  update(s) {
    syncAgents((s.agents || []).filter(a => (a.village || "business") === "business"));   // Warrior Village draws the football agents
    const c = s.counts || {};
    if (prev) react(c);
    chatter(s.activity || []);
    shown = {pending: c.pending_approval || 0, approved: c.approved || 0};
    prev = {...c};
    if (calm) draw(performance.now());
  },
  setMess,
  sky: () => sky(),   // Warrior Village follows the same time of day (and the same day/night button)
  bossThinking(on) {
    thinking = on;
    const boss = agents.get("boss");
    if (!boss) return;
    if (on) { wake(boss); boss.actions = []; boss.path = []; boss.current = null; boss.waitUntil = 0; }
    else { say(boss, "Answered you in chat 💬", 4); boss.jumpT = .5; addParticle({x: boss.x + 10, y: boss.y - 40, vy: -20, life: 1.6, kind: "emoji", text: "💡", size: 16}); }
  },
};

new ResizeObserver(resize).observe(canvas);
new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(canvas);
resize();
hud(); setInterval(hud, 15000);
if (calm) setInterval(() => { tick(1, performance.now()); draw(performance.now()); }, 2000);
else requestAnimationFrame(frame);
})();

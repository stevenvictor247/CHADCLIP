// Print Street: the Etsy village, where shirts are thought up, drawn, checked and sent to Printify. Drawn next to HQ Town
// and Warrior Village on the same stage. The shirt line runs along Second Street from left to right: Quill's Copy Desk,
// Loom's Design Studio, Warden's Rule Gate and the Loading Dock where Dock's truck takes shirts to Printify. Up on Main
// Street: Etta's Shop Front, Radar's Research Lab, the Publish Window (what waits for you) and the Sample Closet. Live
// shirts hang on the clothesline in the plaza. index.html feeds it with EtsyTown.update(state) on every refresh.
(() => {
"use strict";
const canvas = document.getElementById("etsycanvas");
const kit = window.HQTown;
if (!canvas || !kit) return;
const ctx = canvas.getContext("2d");
const W = 960, H = 720, ROAD_Y = 240, ROAD2_Y = 650, SOUTH = 430;
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMOJI = '"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
const FONT = '"Nunito",system-ui,sans-serif';
const PINK = "#f472b6", PLUM = "#7c2d5b", CREAM = "#fff6e8", INK = "#2a2233";

const rnd = (a, b) => a + Math.random() * (b - a);
const pick = a => a[Math.floor(Math.random() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
const seeded = kit.seeded;
const look = name => window.hqLook ? window.hqLook(name) : {color: "#f472b6", prop: "👕", hat: null};
const esc = kit.esc;

// ---------- the map ----------
const B = {   // Main Street, north side
  shop:   {x: 50, y: 30, w: 210, h: 150, wall: "#fff1f5", roof: PINK, door: 155, label: "Shop Front", icon: "🛍️"},
  lab:    {x: 300, y: 50, w: 150, h: 130, wall: "#eef6ff", roof: "#2563eb", door: 375, label: "Research Lab", icon: "📡"},
  window: {x: 490, y: 66, w: 130, h: 114, wall: "#fffbea", roof: "#f59e0b", door: 555, label: "Publish Window", icon: "🪟"},
  closet: {x: 660, y: 62, w: 124, h: 118, wall: "#f5f3ff", roof: "#7c3aed", door: 722, label: "Sample Closet", icon: "👕"},
};
const S = {   // Second Street, the shirt line
  desk:   {x: 50, y: 492, w: 142, h: 128, wall: "#fff8e1", roof: "#d97706", door: 121, label: "Copy Desk", icon: "✒️"},
  studio: {x: 226, y: 472, w: 176, h: 148, wall: "#f5f3ff", roof: "#8b5cf6", door: 314, label: "Design Studio", icon: "🎨"},
  dock:   {x: 600, y: 476, w: 190, h: 144, wall: "#ecfdf5", roof: "#16a34a", door: 668, label: "Loading Dock", icon: "📦"},
};
for (const b of [...Object.values(B), ...Object.values(S)]) b.front = {x: b.door, y: b.y + b.h + (b.y < SOUTH ? 20 : 18)};
const GATE = {x: 444, y: 498, w: 118, h: 122, door: 503, label: "Rule Gate", icon: "🛡️"};
GATE.front = {x: GATE.door, y: GATE.y + GATE.h + 18};
const TRUCK = {x: 808, y: 556, w: 120, h: 62};
const BOARD = {x: 56, y: 288, w: 196, h: 112};
const LINE = {x0: 320, x1: 680, y: 300};   // the clothesline
const LOT = {x: 732, y: 296, w: 196, h: 104};
const MAILBOX = {x: 640, y: 178};
const LINKS = [282, 712];
const TREES = [[838, 96], [900, 150], [940, 60], [470, 160], [276, 196], [300, 420], [700, 420], [30, 420], [940, 430],
               [210, 712], [420, 712], [600, 712], [820, 712], [60, 712], [950, 700]]
  .map(([x, y], i) => ({x, y, i, kind: i % 3 === 1 ? "dark" : "green"}));
const LAMPS = [[30, 214], [290, 214], [480, 214], [650, 214], [860, 214], [200, 634], [420, 634], [580, 634], [800, 634]].map(([x, y]) => ({x, y}));
const BENCHES = [{x: 380, y: 404}, {x: 560, y: 404}];
const SPOTS = [{x: 400, y: 360, line: true}, {x: 500, y: 370, line: true}, {x: 600, y: 360, line: true}, {x: 380, y: 418, bench: true},
               {x: 560, y: 418, bench: true}, {x: 150, y: 420}, {x: 820, y: 420}, {x: 900, y: 256}, {x: 40, y: 256}, {x: 540, y: 256},
               {x: 300, y: 664}, {x: 520, y: 664}, {x: 900, y: 664}, {x: 250, y: 256}];

const terrain = document.createElement("canvas"), dark = document.createElement("canvas");
let terrainAt = -1;
const cam = kit.camera(canvas, W, H, {onChange: () => { if (calm) draw(performance.now()); }});
kit.register("etsyworld", cam);

function blocked(x, y) {
  if (y > 210 && y < 270 || y > ROAD2_Y - 30 && y < ROAD2_Y + 30) return true;
  for (const b of [...Object.values(B)]) if (x > b.x - 12 && x < b.x + b.w + 12 && y < b.y + b.h + 30) return true;
  for (const b of [...Object.values(S), GATE, TRUCK]) if (x > b.x - 12 && x < b.x + b.w + 12 && y > b.y - 40 && y < b.y + b.h + 14) return true;
  for (const b of [BOARD, LOT]) if (x > b.x - 10 && x < b.x + b.w + 10 && y > b.y - 20 && y < b.y + b.h + 14) return true;
  if (x > LINE.x0 - 10 && x < LINE.x1 + 10 && y > LINE.y - 30 && y < LINE.y + 50) return true;
  if (LINKS.some(l => Math.abs(x - l) < 22) && y > ROAD_Y && y < ROAD2_Y) return true;
  for (const t of TREES) if (Math.hypot(x - t.x, y - t.y + 10) < 24) return true;
  return false;
}
const r0 = seeded(31);
const FLOWERS = [];
for (let tries = 0; FLOWERS.length < 28 && tries < 900; tries++) {
  const x = 20 + r0() * (W - 40), y = 20 + r0() * (H - 30);
  if (!blocked(x, y)) FLOWERS.push({x, y, n: 3 + Math.floor(r0() * 4), c: ["#f9a8d4", "#ffffff", "#fde68a", "#c4b5fd"][Math.floor(r0() * 4)], s: Math.floor(r0() * 1e6)});
}

function drawTerrain() {
  const c = terrain;
  if (c.width !== canvas.width || c.height !== canvas.height) { c.width = canvas.width; c.height = canvas.height; }
  const g = c.getContext("2d");
  g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, c.width, c.height);
  g.setTransform(cam.s, 0, 0, cam.s, cam.ox, cam.oy);
  kit.outskirts(g, cam.view(), W, H, {grass: "#5cb054", seed: 41});
  const rr = seeded(41);
  g.fillStyle = "#66ba5c"; g.fillRect(0, 0, W, H);
  for (let ty = 0; ty < H; ty += 32) for (let tx = 0; tx < W; tx += 32) {
    g.fillStyle = ((tx + ty) / 32) % 2 ? "rgba(255,255,255,.035)" : "rgba(0,60,0,.035)";
    g.fillRect(tx, ty, 32, 32);
  }
  g.strokeStyle = "rgba(30,90,30,.35)"; g.lineWidth = 1.2;
  for (let i = 0; i < 420; i++) { const x = rr() * W, y = rr() * H; g.beginPath(); g.moveTo(x - 2, y); g.lineTo(x, y - 4); g.lineTo(x + 2, y); g.stroke(); }
  // brick-paved streets: Main Street, Second Street and the two lanes between them
  const street = (x, y, w, h) => {
    g.fillStyle = "#d9b99b"; g.fillRect(x, y, w, h);
    g.fillStyle = "rgba(140,90,60,.18)";
    for (let by = y + 2; by < y + h; by += 8) for (let bx = x + ((by - y) / 8 % 2) * 6; bx < x + w; bx += 12) g.fillRect(bx, by, 11, 1.2);
    g.fillStyle = "rgba(120,80,50,.3)"; g.fillRect(x, y, w, 2); g.fillRect(x, y + h - 2, w, 2);
  };
  street(0, ROAD_Y - 16, W, 32);
  street(0, ROAD2_Y - 16, W, 32);
  for (const l of LINKS) street(l - 12, ROAD_Y + 16, 24, ROAD2_Y - ROAD_Y - 32);
  const path = (x, y, w, h) => { g.fillStyle = "#e9d3b4"; g.fillRect(x, y, w, h); g.fillStyle = "rgba(160,120,60,.25)"; g.fillRect(x, y, 2, h); g.fillRect(x + w - 2, y, 2, h); };
  for (const b of Object.values(B)) path(b.door - 12, b.y + b.h - 2, 24, ROAD_Y - 16 - (b.y + b.h - 2));
  for (const b of [...Object.values(S), GATE]) path(b.door - 12, b.y + b.h - 2, 24, ROAD2_Y - 16 - (b.y + b.h - 2));
  // the plaza: a round of pale stone under the clothesline
  g.fillStyle = "#efe3cf"; g.beginPath(); g.ellipse((LINE.x0 + LINE.x1) / 2, 360, 210, 64, 0, 0, 7); g.fill();
  g.strokeStyle = "rgba(160,120,80,.35)"; g.lineWidth = 2; g.stroke();
  g.strokeStyle = "rgba(160,120,80,.18)"; g.lineWidth = 1;
  for (let k = 1; k < 4; k++) { g.beginPath(); g.ellipse((LINE.x0 + LINE.x1) / 2, 360, 210 - k * 46, 64 - k * 14, 0, 0, 7); g.stroke(); }
  // crosswalk stripes where the lanes meet the streets
  g.fillStyle = "rgba(255,255,255,.8)";
  for (const l of LINKS) for (const y of [ROAD_Y, ROAD2_Y]) for (let k = -2; k <= 2; k++) g.fillRect(l - 14 + (k + 2) * 6, y - 12, 3, 24);
  for (const fl of FLOWERS) {
    const fr = seeded(fl.s);
    for (let i = 0; i < fl.n; i++) {
      const x = fl.x + fr() * 22 - 11, y = fl.y + fr() * 12 - 6;
      g.fillStyle = "#3f8f3a"; g.fillRect(x - .5, y, 1, 4);
      g.fillStyle = fl.c; for (let k = 0; k < 4; k++) { g.beginPath(); g.arc(x + Math.cos(k * 1.57) * 1.8, y + Math.sin(k * 1.57) * 1.8, 1.6, 0, 7); g.fill(); }
      g.fillStyle = "#ffcf3f"; g.beginPath(); g.arc(x, y, 1, 0, 7); g.fill();
    }
  }
  terrainAt = cam.version;
}

// ---------- village state ----------
const agents = new Map();
const particles = [], flyers = [], clouds = [], birds = [];
for (let i = 0; i < 3; i++) clouds.push({x: rnd(0, W), y: rnd(40, H - 40), s: rnd(.8, 1.4)});
const fireflies = Array.from({length: 12}, (_, i) => ({x: rnd(40, W), y: rnd(270, H), vx: rnd(-8, 8), vy: rnd(-6, 6), ph: i}));
let prev = null, mailBump = 0, boardGlow = 0, deliveriesOnTheWay = 0, nextBirds = performance.now() + rnd(6000, 15000);
let gate = {color: "idle", until: 0}, truck = {t: 0, away: false}, dish = 0;
let shown = {pending: 0, ready: 0, live: [], sales: 0, counts: {}, held: 0, orders: 0, latest: null, printify: false, brief: 0};

function addParticle(p) { if (!calm && particles.length < 400) particles.push({vx: 0, vy: 0, g: 0, life: 1, ...p, max: p.life ?? 1}); }
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
  const el = document.getElementById("etsyticker");
  if (!el) return;
  el.textContent = text; el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  clearTimeout(tickerTimer); tickerTimer = setTimeout(() => el.classList.remove("show"), 6000);
}

function ownSky() {
  const d = new Date(), h = d.getHours() + d.getMinutes() / 60;
  const dk = h < 5 || h >= 21.5 ? .7 : h < 7 ? lerp(.7, 0, (h - 5) / 2) : h < 17.5 ? 0 : h < 19.5 ? lerp(0, .25, (h - 17.5) / 2) : lerp(.25, .7, (h - 19.5) / 2);
  return {dk, tint: 0, tc: "255,160,80", night: dk > .45};
}
const sky = () => window.HQWorld?.sky?.() || ownSky();
let SKY = sky();

// ---------- agents ----------
const HOMES = {etta: B.shop, radar: B.lab, quill: S.desk, loom: S.studio, warden: GATE, dock: S.dock};
function makeAgent(info) {
  const key = info.name.toLowerCase(), l = look(info.name);
  const home = HOMES[key] || B.shop;
  const a = {name: info.name, key, role: info.role, color: l.color, hat: l.hat, prop: l.prop, home,
             x: home.front.x + rnd(-10, 10), y: home.front.y + rnd(0, 6), path: [], actions: [], current: null, waitUntil: 0,
             busy: null, sleeping: false, facing: 1, phase: 0, seed: Math.random() * 1000, jumpT: 0, face: "happy", faceUntil: 0,
             carry: null, say: null, sayUntil: 0, nextSpark: 0, speed: key === "etta" ? 50 : 56};
  agents.set(key, a);
  return a;
}
function route(a, to) {   // along the nearest street, down a lane if the trip crosses between Main Street and Second Street
  if (calm) { a.x = to.x; a.y = to.y; a.path = []; return; }
  const road = y => y > SOUTH ? ROAD2_Y : ROAD_Y, from = road(a.y), dest = road(to.y), p = [];
  if (Math.abs(a.x - to.x) < 4 && from === dest) { a.path = [{x: to.x, y: to.y}]; return; }
  let y = a.y;
  if (Math.abs(a.y - from) >= 6) { y = from + rnd(-5, 5); p.push({x: a.x, y}); }
  if (from !== dest) {
    const cost = l => Math.abs(a.x - l) + Math.abs(l - to.x);
    const link = LINKS.reduce((best, l) => cost(l) < cost(best) ? l : best);
    p.push({x: link, y}); y = dest + rnd(-5, 5); p.push({x: link, y});
  }
  p.push({x: to.x, y}, {x: to.x, y: to.y});
  a.path = p;
}
function hurry(a) {
  if (a.current && !a.current.urgent) { a.current = null; a.path = []; }
  if (!a.current) a.waitUntil = 0;
  a.actions = a.actions.filter(x => x.urgent);
  wake(a);
}
function say(a, text, secs = 4) { a.say = text; a.sayUntil = performance.now() + secs * 1000; }
function wake(a) { if (a.sleeping) { a.sleeping = false; a.x = a.home.front.x; a.y = a.home.front.y - 6; } }
const workSpot = a => ({x: a.home.front.x + (a.key === "etta" ? -34 : 0), y: a.home.front.y});
const CHATTER = ["Cute shirt alert 👕", "Coffee break ☕", "Is that font kerned? 🤔", "Love this color 💖", "Ship it! 📦", "Trend spotted 📈",
                 "Cozy season vibes 🍂", "Gift idea! 🎁", "Matching set? 👨‍👩‍👧"];
const NIGHT_CHATTER = ["Late night designs 🌙", "One more mockup ✨", "Lights out soon 💤"];
const ETTA_TALK = ["Looking good, {n}! 💖", "Nice one, {n} 👏", "How's it going, {n}?", "That'll sell, {n} 🛍️"];

function think(a, now) {
  if (a.path.length || now < a.waitUntil) return;
  if (a.current) { const c = a.current; a.current = null; c.do?.(); a.waitUntil = now + (c.wait || 0) * 1000; return; }
  if (a.actions.length) { wake(a); a.working = false; a.current = a.actions.shift(); a.rush = !!a.current.urgent; route(a, a.current.at); return; }
  a.rush = false;
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
  const busy = [...agents.values()].filter(o => o !== a && o.busy && !o.sleeping);
  if (a.key === "etta" && busy.length && Math.random() < .45) {
    const o = pick(busy), s = workSpot(o);
    a.actions.push({at: {x: s.x + 26, y: s.y + 4}, do: () => { a.facing = -1; say(a, pick(ETTA_TALK).replace("{n}", o.name), 3.5); }, wait: 4});
    return;
  }
  const spot = pick(SPOTS);
  a.actions.push({at: {x: spot.x + rnd(-8, 8), y: spot.y + rnd(-6, 6)}, wait: rnd(3, 9), do: () => {
    if (spot.line && shown.live.length && Math.random() < .5) { a.facing = 1; say(a, pick(["Our best seller? 😍", "So proud of these 👕", "Fresh off the line ✨"]), 3); }
    else if (spot.bench && Math.random() < .5) say(a, pick(["Coffee break ☕", "Sketching ideas ✏️"]), 3);
    else if (Math.random() < .3) say(a, pick(SKY.night ? NIGHT_CHATTER : CHATTER), 3);
  }});
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
      burst(a.x, a.y - 18, 14, "spark", [a.color, "#fff", PINK], {g: 60});
      ticker(`${a.name} finished a job`);
    }
  }
}
function deliver(a, emoji, n) {   // walks something to the Publish Window's mailbox
  deliveriesOnTheWay += n;
  let delivered = false;
  const arrive = () => { if (!delivered) { delivered = true; deliveriesOnTheWay = Math.max(0, deliveriesOnTheWay - n); } };
  hurry(a);
  a.actions.push(
    {urgent: true, at: a.home.front, do: () => { a.carry = emoji; }, wait: .5},
    {urgent: true, at: {x: MAILBOX.x - 24, y: B.window.front.y}, wait: 1.5, do: () => {
      a.carry = null; a.facing = 1; arrive(); mailBump = 1;
      fly({x: a.x, y: a.y - 30}, {x: MAILBOX.x, y: MAILBOX.y - 28}, emoji, .6, 20);
      say(a, "Waiting for your OK 👀", 3.5);
    }});
  setTimeout(arrive, 30000);
}
const centre = b => ({x: b.x + b.w / 2, y: b.y + b.h * .4});
function react(st) {
  const c = st.counts, p = prev, was = p.counts || {};
  const fresh = st.approvals.filter(x => !p.approvals.includes(x.id));
  for (const x of fresh) { const a = agents.get(String(x.agent).toLowerCase()) || agents.get("etta"); if (a) deliver(a, "👕", 1); }
  if (fresh.length) ticker(`${fresh[0].title}: it's at the Publish Window for your OK.`);
  if (p.approvals.some(id => !st.approvals.some(x => x.id === id))) addParticle({x: MAILBOX.x, y: MAILBOX.y - 40, vy: -16, life: 1.5, kind: "emoji", text: "👍", size: 16});
  // the shirt line: each step sends a shirt along Second Street
  const more = k => (c[k] || 0) > (was[k] || 0);
  if (more("written")) { const q = agents.get("quill"); if (q) { say(q, "New slogans ✍️", 3); q.jumpT = .5; } fly(centre(S.desk), centre(S.studio), "📝", 1.1, 50); }
  if (more("drawn")) { fly(centre(S.studio), centre(GATE), "👕", 1.1, 50); const l = agents.get("loom"); if (l) say(l, "Fresh design 🎨", 3); }
  if ((c.held || 0) > (was.held || 0)) { gate = {color: "red", until: performance.now() + 8000}; const w = agents.get("warden"); if (w) { say(w, "Held! That name's taken 🛑", 4); w.face = "sad"; w.faceUntil = performance.now() + 3000; } ticker("Warden held a design: a brand or name it can't use."); }
  if (more("approved")) { gate = {color: "green", until: performance.now() + 6000}; fly(centre(GATE), centre(S.dock), "👕", 1.1, 50); const w = agents.get("warden"); if (w) say(w, "Passed ✅", 3); }
  if (more("ready")) {
    truck = {t: 0, away: true};
    ticker("Dock built a shirt in Printify. Add a real photo, then press Publish there.");
    const d = agents.get("dock"); if (d) { say(d, "In Printify! 🚚", 4); d.jumpT = .6; }
  }
  if (more("live")) {
    boardGlow = 1;
    burst((LINE.x0 + LINE.x1) / 2, LINE.y + 10, 30, "confetti", [PINK, "#ffffff", "#fde68a", "#a78bfa"], {up: 70});
    ticker("A shirt went live on Etsy 🎉");
    const e = agents.get("etta"); if (e) { say(e, "We're live! 🎉", 4); e.jumpT = .7; }
  }
  if (st.sales > (p.sales || 0)) {
    burst(B.shop.door, B.shop.y + 40, 34, "confetti", [PINK, "#4ade80", "#fde68a", "#fff"], {up: 80});
    floatText(B.shop.door, B.shop.y - 6, "Sold! 💸", "#bbf7d0", 15);
    ticker(`A shirt sold! Check Printify > Orders and press Send to production.`);
  }
  if (st.orders > (p.orders || 0)) { const d = agents.get("dock"); if (d) say(d, "Order waiting for you 📦", 5); }
  if (st.brief > (p.brief || 0)) { const r = agents.get("radar"); if (r) { say(r, "New trend brief 📈", 4); r.jumpT = .5; } }
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
let lights = [];
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
function fit(text, max) {
  let s = String(text);
  if (ctx.measureText(s).width <= max) return s;
  while (s.length > 1 && ctx.measureText(s + "…").width > max) s = s.slice(0, -1);
  return s + "…";
}
function plaque(text, x, y, bg = "rgba(124,45,91,.92)", fg = "#fff1f5") {
  ctx.font = `800 9px ${FONT}`;
  const w = ctx.measureText(text).width + 12;
  ctx.fillStyle = bg; roundRect(ctx, x - w / 2, y - 7, w, 14, 7); ctx.fill();
  ctx.fillStyle = fg; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, x, y + .5);
}
function badge(x, y, n, t, color = "#ff4d6d") {
  const k = 1 + Math.sin(t / 250) * .08;
  ctx.save(); ctx.translate(x, y); ctx.scale(k, k);
  ctx.fillStyle = color; ctx.beginPath(); ctx.arc(0, 0, 8, 0, 7); ctx.fill();
  ctx.font = `900 10px ${FONT}`; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(n > 99 ? "99+" : n, 0, .5);
  ctx.restore();
}
// a little T-shirt shape, centred on x, y
function tee(x, y, s, color, ink, rot = 0) {
  ctx.save(); ctx.translate(x, y); if (rot) ctx.rotate(rot); ctx.scale(s, s);
  ctx.fillStyle = color; ctx.beginPath();
  ctx.moveTo(-5, -10); ctx.lineTo(-2, -11); ctx.quadraticCurveTo(0, -8, 2, -11); ctx.lineTo(5, -10); ctx.lineTo(11, -5); ctx.lineTo(8, -1);
  ctx.lineTo(6, -3); ctx.lineTo(6, 10); ctx.lineTo(-6, 10); ctx.lineTo(-6, -3); ctx.lineTo(-8, -1); ctx.lineTo(-11, -5); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.lineWidth = 1 / s; ctx.stroke();
  if (ink) { ctx.fillStyle = ink; ctx.fillRect(-3.5, -4, 7, 1.6); ctx.fillRect(-3, -1, 6, 1.6); ctx.fillRect(-2.5, 2, 5, 1.2); }
  ctx.restore();
}
function house(b) {
  const wallY = b.y + b.h * .52, bottom = b.y + b.h;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(b.x + b.w / 2 + 6, bottom + 2, b.w / 2 + 8, 8, 0, 0, 7); ctx.fill();
  ctx.fillStyle = b.wall; ctx.fillRect(b.x, wallY, b.w, bottom - wallY);
  ctx.fillStyle = "rgba(0,0,0,.08)"; ctx.fillRect(b.x, bottom - 6, b.w, 6);
  ctx.fillStyle = b.roof; ctx.beginPath();
  ctx.moveTo(b.x - 8, wallY + 2); ctx.lineTo(b.x + b.w + 8, wallY + 2); ctx.lineTo(b.x + b.w - 8, b.y); ctx.lineTo(b.x + 8, b.y); ctx.closePath(); ctx.fill();
  ctx.save(); ctx.clip();
  ctx.strokeStyle = "rgba(0,0,0,.14)"; ctx.lineWidth = 2;
  for (let y = b.y + 9; y < wallY; y += 9) { ctx.beginPath(); ctx.moveTo(b.x - 10, y); ctx.lineTo(b.x + b.w + 10, y); ctx.stroke(); }
  ctx.fillStyle = "rgba(255,255,255,.18)"; ctx.fillRect(b.x, b.y, b.w, 4);
  ctx.restore();
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.fillRect(b.x - 8, wallY, b.w + 16, 3);
  const lit = SKY.dk > .15;
  for (const wx of [b.x + 16, b.x + b.w - 40]) {
    const wy = bottom - 34;
    ctx.fillStyle = "#6b4b2e"; ctx.fillRect(wx - 2, wy - 2, 28, 20);
    ctx.fillStyle = lit ? "#ffd56b" : "#a9dcff"; ctx.fillRect(wx, wy, 24, 16);
    ctx.fillStyle = lit ? "rgba(255,160,40,.35)" : "rgba(255,255,255,.6)"; ctx.fillRect(wx + 2, wy + 2, 6, 5);
    ctx.fillStyle = "#6b4b2e"; ctx.fillRect(wx + 11, wy, 2, 16); ctx.fillRect(wx, wy + 7, 24, 2);
    if (lit) lights.push({x: wx + 12, y: wy + 10, r: 46, warm: .9});
  }
  ctx.fillStyle = "#7a4a2a"; roundRect(ctx, b.door - 11, bottom - 30, 22, 30, 4); ctx.fill();
  ctx.fillStyle = "#5a361e"; ctx.fillRect(b.door - 1, bottom - 28, 2, 28);
  ctx.fillStyle = "#ffd34d"; ctx.beginPath(); ctx.arc(b.door + 6, bottom - 14, 1.6, 0, 7); ctx.fill();
  ctx.font = `800 9px ${FONT}`;
  const label = `${b.icon} ${b.label}`, lw = ctx.measureText(label).width + 12;
  ctx.fillStyle = "#3b1d2e"; roundRect(ctx, b.door - lw / 2, wallY + 5, lw, 14, 4); ctx.fill();
  ctx.fillStyle = "#fff2d6"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, b.door, wallY + 12.5);
}

function drawShop(t) {   // Etta's Shop Front: a striped awning and a window full of shirts
  const b = B.shop;
  house(b);
  const wallY = b.y + b.h * .52, aw = b.y + b.h * .52 + 22;
  for (let i = 0; i < 12; i++) {   // the awning, scalloped
    const x = b.x - 4 + i * (b.w + 8) / 12;
    ctx.fillStyle = i % 2 ? "#fff" : PINK; ctx.fillRect(x, wallY + 20, (b.w + 8) / 12 + .5, 12);
    ctx.beginPath(); ctx.arc(x + (b.w + 8) / 24, wallY + 32, (b.w + 8) / 24, 0, Math.PI); ctx.fill();
  }
  // the shop window shows the newest live shirts (or a sample rack while nothing is live)
  const wx = b.x + 70, wy = aw + 16;
  ctx.fillStyle = "#6b4b2e"; ctx.fillRect(wx - 3, wy - 3, 66, 30);
  ctx.fillStyle = SKY.dk > .15 ? "#ffe9a8" : "#dff2ff"; ctx.fillRect(wx, wy, 60, 24);
  const live = shown.live.slice(-3);
  (live.length ? live : [{style: "bold"}, {style: "retro"}, {style: "script"}]).forEach((d, i) =>
    tee(wx + 12 + i * 18, wy + 12, .85, i % 2 ? "#1f1f24" : "#f8f5ee", i % 2 ? PINK : PLUM));
  ctx.font = `900 10px ${FONT}`; ctx.fillStyle = PLUM; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("PRINT STREET SHOP", b.x + b.w / 2, b.y + 18);
  const open = SKY.dk < .45;   // the OPEN sign, lit at night when the shop is still selling
  ctx.fillStyle = open ? "#16a34a" : "#7f1d1d"; roundRect(ctx, b.x + b.w - 46, b.y + 30, 38, 13, 3); ctx.fill();
  ctx.font = `900 8px ${FONT}`; ctx.fillStyle = "#fff"; ctx.fillText(open ? "OPEN" : "24/7", b.x + b.w - 27, b.y + 37);
  if (shown.ready) badge(b.x + b.w - 8, wallY + 8, shown.ready, t, "#f59e0b");
  plaque(`👕 ${shown.live.length} live · 💸 ${shown.sales} sold`, b.door, b.y - 8);
}
function drawLab(t) {   // Radar's lab: a dish on the roof that turns, faster while Radar is searching
  const b = B.lab;
  house(b);
  const cx = b.x + b.w - 34, cy = b.y + 10;
  ctx.fillStyle = "#64748b"; ctx.fillRect(cx - 2, cy, 4, 18);
  ctx.save(); ctx.translate(cx, cy); ctx.scale(Math.cos(dish), 1);
  ctx.fillStyle = "#e2e8f0"; ctx.beginPath(); ctx.ellipse(0, -4, 16, 9, 0, 0, Math.PI); ctx.fill();
  ctx.strokeStyle = "#94a3b8"; ctx.lineWidth = 1.5; ctx.stroke();
  ctx.strokeStyle = "#475569"; ctx.beginPath(); ctx.moveTo(0, -4); ctx.lineTo(0, -16); ctx.stroke();
  ctx.fillStyle = "#ef4444"; ctx.beginPath(); ctx.arc(0, -17, 2.2, 0, 7); ctx.fill();
  ctx.restore();
  if (agents.get("radar")?.busy && !calm) for (let k = 0; k < 3; k++) {   // radio waves
    const r = ((t / 30 + k * 12) % 36) + 6;
    ctx.strokeStyle = `rgba(56,189,248,${1 - r / 42})`; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.arc(cx, cy - 18, r, Math.PI * 1.15, Math.PI * 1.85); ctx.stroke();
  }
  emoji("📈", b.x + 30, b.y + 22, 16);
  plaque(shown.brief ? `📈 ${shown.brief} themes in the brief` : "No trend brief yet", b.door, b.y - 8, "rgba(37,99,235,.92)");
}
function drawWindow(t, pending) {   // the Publish Window: what waits for you, with a mailbox out front
  const b = B.window;
  house(b);
  ctx.fillStyle = "#334155"; ctx.fillRect(b.x + 14, b.y + 18, b.w - 28, 26);
  ctx.fillStyle = SKY.dk > .15 ? "#ffd56b" : "#e0f2fe"; ctx.fillRect(b.x + 18, b.y + 21, b.w - 36, 20);
  ctx.font = `900 9px ${FONT}`; ctx.fillStyle = "#7c2d12"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(pending + shown.ready ? "YOUR TURN" : "ALL CLEAR", b.x + b.w / 2, b.y + 31);
  if (SKY.dk > .15) lights.push({x: b.x + b.w / 2, y: b.y + 31, r: 60, warm: 1});
  const mb = MAILBOX, bump = 1 + Math.sin(mailBump * Math.PI) * .25;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(mb.x, mb.y, 9, 3, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#6b4b2e"; ctx.fillRect(mb.x - 2, mb.y - 16, 4, 16);
  ctx.save(); ctx.translate(mb.x, mb.y - 22); ctx.scale(bump, bump);
  ctx.fillStyle = PINK; roundRect(ctx, -12, -8, 24, 15, 6); ctx.fill();
  ctx.fillStyle = PLUM; ctx.fillRect(-10, -1, 20, 2);
  ctx.fillStyle = "#ef4444";
  if (pending > 0) { ctx.fillRect(10, -18, 3, 12); ctx.fillRect(10, -18, 8, 5); } else ctx.fillRect(10, -4, 10, 3);
  ctx.restore();
  if (pending > 0) badge(mb.x - 12, mb.y - 34, pending, t);
}
function drawCloset(t) {   // the Sample Closet: a rail of sample shirts for the real photo Etsy wants on every listing
  const b = B.closet;
  house(b);
  ctx.strokeStyle = "#78716c"; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(b.x + 18, b.y + 22); ctx.lineTo(b.x + b.w - 18, b.y + 22); ctx.stroke();
  ["#f8f5ee", "#1f1f24", "#f9a8d4", "#1e3a8a", "#f8f5ee"].forEach((c, i) => tee(b.x + 28 + i * 17, b.y + 34, .8, c, c === "#f8f5ee" || c === "#f9a8d4" ? PLUM : "#fde68a", Math.sin(t / 900 + i) * .05));
  const need = shown.needPhoto || 0;
  plaque(need ? `📸 ${need} need a real photo` : "📸 Sample photos", b.door, b.y - 8, need ? "rgba(185,28,28,.92)" : "rgba(124,58,237,.92)");
}
function drawDesk(t) {
  const b = S.desk;
  house(b);
  emoji("📝", b.x + 30, b.y + 22, 16); emoji("✒️", b.x + b.w - 30, b.y + 22, 15, Math.sin(t / 500) * .2);
  plaque(`✍️ ${shown.counts.written || 0} written`, b.door, b.y - 8, "rgba(217,119,6,.92)");
}
function drawStudio(t) {   // Loom's studio: an easel with the newest design on it
  const b = S.studio;
  house(b);
  const ex = b.x + b.w - 40, ey = b.y + 8;
  ctx.strokeStyle = "#8a5a32"; ctx.lineWidth = 2.5;
  ctx.beginPath(); ctx.moveTo(ex - 14, ey + 44); ctx.lineTo(ex, ey); ctx.lineTo(ex + 14, ey + 44); ctx.moveTo(ex, ey); ctx.lineTo(ex, ey + 44); ctx.stroke();
  ctx.fillStyle = "#fff"; ctx.fillRect(ex - 16, ey + 6, 32, 26);
  tee(ex, ey + 19, .95, shown.latest?.dark ? "#1f1f24" : "#f8f5ee", PINK);
  emoji("🎨", b.x + 30, b.y + 24, 16, Math.sin(t / 700) * .1);
  plaque(`🎨 ${shown.counts.drawn || 0} drawn`, b.door, b.y - 8, "rgba(139,92,246,.92)");
}
function drawGate(t) {   // Warden's Rule Gate: an arch over the line with a lantern, red when it holds a design
  const g = GATE, cx = g.x + g.w / 2, bottom = g.y + g.h;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(cx + 6, bottom + 2, g.w / 2 + 8, 7, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#9ca3af"; ctx.fillRect(g.x + 6, g.y + 30, 22, g.h - 30); ctx.fillRect(g.x + g.w - 28, g.y + 30, 22, g.h - 30);
  ctx.fillStyle = "rgba(0,0,0,.1)"; for (let y = g.y + 38; y < bottom; y += 10) { ctx.fillRect(g.x + 6, y, 22, 1.5); ctx.fillRect(g.x + g.w - 28, y, 22, 1.5); }
  ctx.fillStyle = "#6b7280"; ctx.beginPath(); ctx.moveTo(g.x, g.y + 34); ctx.quadraticCurveTo(cx, g.y - 18, g.x + g.w, g.y + 34); ctx.lineTo(g.x + g.w, g.y + 48);
  ctx.quadraticCurveTo(cx, g.y + 2, g.x, g.y + 48); ctx.closePath(); ctx.fill();
  emoji("🛡️", cx, g.y + 22, 16);
  const now = performance.now(), col = now < gate.until ? gate.color : "idle";
  const lamp = col === "red" ? "#ef4444" : col === "green" ? "#22c55e" : "#fbbf24";
  ctx.strokeStyle = "#374151"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.moveTo(cx, g.y + 32); ctx.lineTo(cx, g.y + 44); ctx.stroke();
  ctx.fillStyle = "#374151"; roundRect(ctx, cx - 6, g.y + 44, 12, 14, 3); ctx.fill();
  ctx.fillStyle = lamp; ctx.beginPath(); ctx.arc(cx, g.y + 51, 4.5 + (col !== "idle" && !calm ? Math.sin(t / 120) * .8 : 0), 0, 7); ctx.fill();
  lights.push({x: cx, y: g.y + 51, r: 40, warm: 1});
  if (col !== "idle") { ctx.globalAlpha = .25; ctx.fillStyle = lamp; ctx.beginPath(); ctx.arc(cx, g.y + 51, 14, 0, 7); ctx.fill(); ctx.globalAlpha = 1; }
  plaque(`${g.icon} ${g.label}`, cx, bottom - 10, "#3b1d2e", "#fff2d6");
  if (shown.held) badge(g.x + g.w - 6, g.y + 30, shown.held, t, "#ef4444");
}
function drawDock(t) {
  const b = S.dock;
  house(b);
  // a roll-up door and stacked boxes
  ctx.fillStyle = "#cbd5e1"; ctx.fillRect(b.x + b.w - 66, b.y + b.h - 54, 50, 54);
  ctx.strokeStyle = "rgba(0,0,0,.18)"; ctx.lineWidth = 1; for (let y = b.y + b.h - 50; y < b.y + b.h; y += 6) { ctx.beginPath(); ctx.moveTo(b.x + b.w - 66, y); ctx.lineTo(b.x + b.w - 16, y); ctx.stroke(); }
  for (const [dx, dy] of [[0, 0], [16, 0], [8, -12]]) { ctx.fillStyle = "#c08a4f"; ctx.fillRect(b.x + 18 + dx, b.y + 24 + dy, 14, 11); ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.fillRect(b.x + 24 + dx, b.y + 24 + dy, 2, 11); }
  if (shown.orders) badge(b.x + 52, b.y + 18, shown.orders, t, "#16a34a");
  plaque(shown.printify ? `🚚 ${shown.counts.ready || 0} in Printify` : "🔌 Connect Printify", b.door, b.y - 8, shown.printify ? "rgba(22,163,74,.92)" : "rgba(107,114,128,.92)");
}
function drawTruck(t) {   // drives off to Printify when Dock builds a shirt, then comes back
  let off = 0;
  if (truck.away) {
    const k = truck.t / 6;   // 6 seconds there and back
    off = k < .5 ? (k * 2) ** 2 * 260 : (1 - (k - .5) * 2) ** 2 * 260;
  }
  const x = TRUCK.x + off, y = TRUCK.y;
  if (x > W + 20) return;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(x + 60, y + TRUCK.h + 2, 62, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#f8fafc"; roundRect(ctx, x, y, 84, 48, 5); ctx.fill();
  ctx.fillStyle = PINK; ctx.fillRect(x, y + 34, 84, 6);
  ctx.font = `900 9px ${FONT}`; ctx.fillStyle = PLUM; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("PRINT & SHIP", x + 42, y + 14); tee(x + 42, y + 26, .6, "#1f1f24", PINK);
  ctx.fillStyle = "#16a34a"; roundRect(ctx, x + 84, y + 14, 34, 34, 5); ctx.fill();
  ctx.fillStyle = "#bfe3ff"; ctx.fillRect(x + 98, y + 18, 16, 12);
  for (const wx of [x + 18, x + 66, x + 102]) {
    ctx.fillStyle = "#1f2937"; ctx.beginPath(); ctx.arc(wx, y + 50, 7, 0, 7); ctx.fill();
    ctx.fillStyle = "#9ca3af"; ctx.beginPath(); ctx.arc(wx, y + 50, 3, 0, 7); ctx.fill();
  }
  if (SKY.dk > .15) lights.push({x: x + 118, y: y + 40, r: 50, warm: 1});
  if (truck.away && off > 4 && !calm && Math.random() < .3) addParticle({x: x - 4, y: y + 44, vx: -20, vy: -8, life: 1, kind: "smoke", text: "💨", size: 10});
}
function drawBoard(t) {   // the product board: how many shirts are at each step
  const b = BOARD, c = shown.counts, glow = boardGlow > 0;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(b.x + b.w / 2 + 6, b.y + b.h + 14, b.w / 2, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#6b4226"; ctx.fillRect(b.x + 24, b.y + b.h, 6, 14); ctx.fillRect(b.x + b.w - 30, b.y + b.h, 6, 14);
  ctx.fillStyle = PLUM; roundRect(ctx, b.x - 4, b.y - 4, b.w + 8, b.h + 8, 8); ctx.fill();
  ctx.fillStyle = glow ? "#fff7fb" : "#fdf2f8"; roundRect(ctx, b.x, b.y + 16, b.w, b.h - 16, 5); ctx.fill();
  ctx.font = `900 10px ${FONT}`; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("PRODUCT BOARD", b.x + b.w / 2, b.y + 6);
  const rows = [["✍️ Written", c.written], ["🎨 Drawn", c.drawn], ["👀 Your OK", c.review], ["✅ Approved", (c.approved || 0) + (c.building || 0)],
                ["🚚 In Printify", c.ready], ["🛍️ Live", c.live]];
  rows.forEach(([label, n], i) => {
    const x = b.x + 10 + (i % 2) * (b.w / 2), y = b.y + 32 + Math.floor(i / 2) * 26;
    ctx.font = `800 9px ${FONT}`; ctx.textAlign = "left"; ctx.fillStyle = INK; ctx.fillText(label, x, y);
    ctx.font = `900 13px ${FONT}`; ctx.textAlign = "right"; ctx.fillStyle = n ? (i === 2 ? "#d97706" : PLUM) : "#9ca3af"; ctx.fillText(String(n || 0), x + b.w / 2 - 18, y);
  });
}
function drawLine(t) {   // the clothesline: one shirt for each live design
  const {x0, x1, y} = LINE;
  for (const x of [x0, x1]) {
    ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(x + 3, y + 46, 6, 2, 0, 0, 7); ctx.fill();
    ctx.fillStyle = "#8a5a32"; ctx.fillRect(x - 2.5, y - 10, 5, 56);
  }
  const live = shown.live.slice(-12), n = Math.max(live.length, 1);
  ctx.strokeStyle = "#57534e"; ctx.lineWidth = 1.3; ctx.beginPath(); ctx.moveTo(x0, y - 6);
  ctx.quadraticCurveTo((x0 + x1) / 2, y + 12, x1, y - 6); ctx.stroke();
  const sag = k => y - 6 + 18 * k * (1 - k) * 2 * .5 * 2;
  if (!live.length) {
    ctx.font = `800 9px ${FONT}`; ctx.fillStyle = "rgba(42,34,51,.65)"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillText("Live shirts hang here", (x0 + x1) / 2, y + 30);
    for (let i = 0; i < 5; i++) { const k = (i + 1) / 6; ctx.fillStyle = "#d6d3d1"; ctx.fillRect(x0 + (x1 - x0) * k - 1.5, sag(k) - 3, 3, 6); }
    return;
  }
  live.forEach((d, i) => {
    const k = (i + 1) / (n + 1), x = x0 + (x1 - x0) * k, yy = sag(k);
    const sway = calm ? 0 : Math.sin(t / 700 + i) * .08, darkTee = i % 2 === 1;
    tee(x, yy + 12, 1.4, darkTee ? "#1f1f24" : "#f8f5ee", darkTee ? "#f9a8d4" : PLUM, sway);
    ctx.fillStyle = "#d97706"; ctx.fillRect(x - 1.5, yy - 3, 3, 6);
    if (d.sales) { ctx.font = `900 8px ${FONT}`; ctx.fillStyle = "#16a34a"; ctx.textAlign = "center"; ctx.fillText(`${d.sales} sold`, x, yy + 34); }
  });
}
function drawLot(t) {
  const l = LOT;
  ctx.strokeStyle = "#8a5a32"; ctx.lineWidth = 2; ctx.strokeRect(l.x, l.y, l.w, l.h);
  ctx.fillStyle = "#a8794b"; ctx.fillRect(l.x + 2, l.y + 2, l.w - 4, l.h - 4);
  ctx.strokeStyle = "rgba(70,40,20,.35)"; for (let y = l.y + 10; y < l.y + l.h; y += 12) { ctx.beginPath(); ctx.moveTo(l.x + 6, y); ctx.lineTo(l.x + l.w - 6, y); ctx.stroke(); }
  ctx.fillStyle = "#6b4226"; ctx.fillRect(l.x + l.w / 2 - 1.5, l.y + 18, 3, 26);
  ctx.fillStyle = PLUM; roundRect(ctx, l.x + l.w / 2 - 56, l.y + 6, 112, 24, 4); ctx.fill();
  ctx.font = `900 9px ${FONT}`; ctx.fillStyle = "#fde68a"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("COMING NEXT", l.x + l.w / 2, l.y + 13);
  ctx.font = `800 8px ${FONT}`; ctx.fillStyle = "#fff"; ctx.fillText("Hoodies · Mugs · Stickers", l.x + l.w / 2, l.y + 23);
  emoji("🧥", l.x + 40, l.y + l.h - 24, 16); emoji("☕", l.x + l.w / 2 + 40, l.y + l.h - 24, 16); emoji("🏷️", l.x + l.w - 30, l.y + l.h - 26, 14);
}
function drawBench(b) {
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.fillRect(b.x - 18, b.y + 2, 40, 4);
  ctx.fillStyle = "#8a5a32"; ctx.fillRect(b.x - 20, b.y - 10, 40, 4); ctx.fillRect(b.x - 20, b.y - 4, 40, 4);
  ctx.fillStyle = "#3b3346"; ctx.fillRect(b.x - 18, b.y - 2, 3, 6); ctx.fillRect(b.x + 15, b.y - 2, 3, 6);
}
function drawTree(tr, t) {
  const sway = Math.sin(t / 1100 + tr.i) * 1.4;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(tr.x + 5, tr.y, 18, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#7a4f2c"; ctx.fillRect(tr.x - 3, tr.y - 16, 6, 16);
  const c = {green: ["#3f9a45", "#56b55a", "#79cf6c"], dark: ["#2f7a3c", "#3f9248", "#5bae5c"]}[tr.kind];
  const blob = (dx, dy, r, col) => { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(tr.x + dx + sway, tr.y + dy, r, 0, 7); ctx.fill(); };
  blob(0, -28, 17, c[0]); blob(-8, -32, 11, c[1]); blob(8, -33, 10, c[1]); blob(-3, -38, 8, c[2]);
  if (tr.i % 4 === 0) { ctx.fillStyle = "#f9a8d4"; for (const [dx, dy] of [[-6, -30], [7, -36], [0, -24]]) { ctx.beginPath(); ctx.arc(tr.x + dx + sway, tr.y + dy, 2, 0, 7); ctx.fill(); } }
}
function drawLamp(l) {
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(l.x + 2, l.y, 5, 2, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#3b3346"; ctx.fillRect(l.x - 1.5, l.y - 26, 3, 26);
  const on = SKY.dk > .15;
  ctx.fillStyle = on ? "#fff1b0" : "#cfd6dd"; roundRect(ctx, l.x - 4.5, l.y - 33, 9, 8, 2); ctx.fill();
  ctx.fillStyle = "#3b3346"; ctx.fillRect(l.x - 5.5, l.y - 35, 11, 2.5);
  ctx.fillStyle = PINK; ctx.fillRect(l.x + 1.5, l.y - 24, 7, 10);   // a little shop banner on each lamp post
  if (on) lights.push({x: l.x, y: l.y - 28, r: 70, warm: 1});
}
function drawAgent(a, t) {
  if (a.sleeping) return;
  const walking = a.path.length > 0;
  let bob = walking ? -Math.abs(Math.sin(a.phase)) * 3 : Math.sin(t / 500 + a.seed) * 1.2;
  if (a.working && !walking) bob = -Math.abs(Math.sin(t / 140)) * 4;
  if (a.jumpT > 0) bob -= Math.sin((1 - a.jumpT / .7) * Math.PI) * 12;
  const x = a.x, y = a.y, f = a.facing;
  ctx.fillStyle = "rgba(0,0,0,.28)"; ctx.beginPath(); ctx.ellipse(x, y, 11, 3.5, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#2a2233";
  const st = walking ? Math.sin(a.phase) * 3 : 0;
  ctx.beginPath(); ctx.ellipse(x - 5 + st, y - 1, 3.5, 2.2, 0, 0, 7); ctx.ellipse(x + 5 - st, y - 1, 3.5, 2.2, 0, 0, 7); ctx.fill();
  const by = y - 14 + bob;
  ctx.fillStyle = a.color; ctx.beginPath(); ctx.ellipse(x, by, 13, 12.5, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = "rgba(255,255,255,.5)"; ctx.lineWidth = 2; ctx.lineCap = "round";
  ctx.beginPath(); ctx.arc(x, by, 9, Math.PI * 1.1, Math.PI * 1.45); ctx.stroke();
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
  else ctx.arc(x + ex, by + 2, 3.2, Math.PI * .15, Math.PI * .85);
  ctx.stroke();
  if (a.hat === "bow") {   // Etta's bow
    ctx.fillStyle = "#be185d"; ctx.beginPath(); ctx.moveTo(x + 2, by - 11); ctx.lineTo(x - 7, by - 17); ctx.lineTo(x - 7, by - 7); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.moveTo(x + 2, by - 11); ctx.lineTo(x + 11, by - 17); ctx.lineTo(x + 11, by - 7); ctx.closePath(); ctx.fill();
    ctx.fillStyle = "#9d174d"; ctx.beginPath(); ctx.arc(x + 2, by - 12, 2.6, 0, 7); ctx.fill();
  } else if (a.hat === "beret") {
    ctx.fillStyle = "#3b1f5c"; ctx.beginPath(); ctx.ellipse(x - 1, by - 10, 11, 4.5, -.15, 0, 7); ctx.fill();
    ctx.beginPath(); ctx.arc(x, by - 15, 1.8, 0, 7); ctx.fill();
  } else if (a.hat === "cap") {
    ctx.fillStyle = a.key === "warden" ? "#1f2937" : "#14532d"; ctx.beginPath(); ctx.ellipse(x, by - 9, 11, 6, 0, Math.PI, 0); ctx.fill();
    ctx.fillRect(f > 0 ? x + 4 : x - 14, by - 10, 10, 2.6);
  }
  const swing = a.working && !walking ? Math.sin(t / 90) * .6 : Math.sin(t / 600 + a.seed) * .15;
  emoji(a.prop, x + f * 14, by + 5, 11, swing);
  if (a.carry) emoji(a.carry, x, by - 26 + Math.sin(t / 150) * 1.5, 15);
}
function drawNames() { for (const a of agents.values()) if (!a.sleeping) outlinedText(a.name, a.x, a.y + 10, 9, "#fff"); }
function drawBubble(a, t) {
  if (a.sleeping) return;
  const now = performance.now();
  let text = null;
  if (a.say && now < a.sayUntil) text = a.say;
  else if (a.busy && a.working) text = a.busy;
  if (!text) return;
  ctx.font = `700 10px ${FONT}`;
  const s = fit(text, 170), w = ctx.measureText(s).width + 14, h = 18;
  const bx = clamp(a.x - w / 2, 4, W - w - 4), by = a.y - (a.carry ? 70 : 52) + Math.sin(t / 400 + a.seed);
  ctx.fillStyle = "rgba(0,0,0,.18)"; roundRect(ctx, bx + 1, by + 2, w, h, 8); ctx.fill();
  ctx.fillStyle = "#fff"; roundRect(ctx, bx, by, w, h, 8); ctx.fill();
  ctx.beginPath(); ctx.moveTo(a.x - 4, by + h - 1); ctx.lineTo(a.x + 4, by + h - 1); ctx.lineTo(a.x, by + h + 5); ctx.fill();
  ctx.fillStyle = "#2a2233"; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(s, bx + 7, by + h / 2 + .5);
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
    } else if (p.kind === "text") outlinedText(p.text, p.x, p.y, p.size, p.color);
    else if (p.kind === "emoji" || p.kind === "smoke") emoji(p.text || p.color, p.x, p.y, p.size || 12);
  }
  ctx.globalAlpha = 1;
  for (const f of flyers) {
    const k = Math.min(1, f.t / f.dur), e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    const x = lerp(f.from.x, f.to.x, e), y = lerp(f.from.y, f.to.y, e) - Math.sin(k * Math.PI) * f.arc;
    emoji(f.emoji, x, y, 14, Math.sin(k * Math.PI * 2) * .3);
  }
}
function drawLightsAndDark(t) {
  if (!kit.night(ctx, cam, dark, SKY, lights, t)) return;
  ctx.globalCompositeOperation = "lighter";
  for (const l of lights) {
    const g = ctx.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.r * .6);
    g.addColorStop(0, `rgba(255,190,140,${.28 * SKY.dk * (l.warm || 1)})`); g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(l.x, l.y, l.r * .6, 0, 7); ctx.fill();
  }
  if (SKY.dk > .3) for (const f of fireflies) {
    const a = (.5 + .5 * Math.sin(t / 300 + f.ph * 2)) * (SKY.dk - .3) * 2.5;
    const g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, 7);
    g.addColorStop(0, `rgba(255,200,240,${a})`); g.addColorStop(1, "rgba(0,0,0,0)");
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
  ctx.globalAlpha = day; ctx.strokeStyle = "#2a2233"; ctx.lineWidth = 1.5;
  for (const fl of birds) for (const b of fl.birds) {
    const x = fl.x + b.dx, y = fl.y + b.dy, wing = Math.sin(t / 90 + b.dx) * 4;
    ctx.beginPath(); ctx.moveTo(x - 6, y - wing); ctx.lineTo(x, y); ctx.lineTo(x + 6, y - wing); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function draw(t) {
  if (!canvas.width) return;
  if (terrainAt !== cam.version) drawTerrain();
  SKY = sky();
  lights = [];
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.drawImage(terrain, 0, 0);
  cam.apply(ctx);
  const pending = Math.max(0, shown.pending - deliveriesOnTheWay);
  const things = [
    {y: B.shop.y + B.shop.h, d: () => drawShop(t)}, {y: B.lab.y + B.lab.h, d: () => drawLab(t)},
    {y: B.window.y + B.window.h, d: () => drawWindow(t, pending)}, {y: B.closet.y + B.closet.h, d: () => drawCloset(t)},
    {y: S.desk.y + S.desk.h, d: () => drawDesk(t)}, {y: S.studio.y + S.studio.h, d: () => drawStudio(t)},
    {y: GATE.y + GATE.h, d: () => drawGate(t)}, {y: S.dock.y + S.dock.h, d: () => drawDock(t)},
    {y: TRUCK.y + TRUCK.h, d: () => drawTruck(t)}, {y: BOARD.y + BOARD.h, d: () => drawBoard(t)},
    {y: LINE.y + 40, d: () => drawLine(t)}, {y: LOT.y + LOT.h, d: () => drawLot(t)},
    ...BENCHES.map(b => ({y: b.y, d: () => drawBench(b)})),
    ...TREES.map(o => ({y: o.y, d: () => drawTree(o, t)})),
    ...LAMPS.map(o => ({y: o.y, d: () => drawLamp(o)})),
    ...[...agents.values()].map(a => ({y: a.y, d: () => drawAgent(a, t)})),
  ].sort((p, q) => p.y - q.y);
  for (const th of things) th.d();
  drawParticles();
  drawSkyLife(t);
  drawLightsAndDark(t);
  drawNames();
  if (pending > 0) {
    const y = B.window.y - 14 + Math.sin(t / 220) * 4;
    ctx.fillStyle = "#ffd34d"; ctx.beginPath(); ctx.arc(B.window.door, y, 10, 0, 7); ctx.fill();
    ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.font = `900 14px ${FONT}`; ctx.fillStyle = "#4a2a00"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("!", B.window.door, y + 1);
  }
  kit.glow(ctx, hoverShape(), t);
  for (const a of agents.values()) drawBubble(a, t);
}
let hover = null;
function hoverShape() {
  const h = hover;
  if (!h) return null;
  const box = b => ({x: b.x - 8, y: b.y - 12, w: b.w + 16, h: b.h + 18});
  if (h.agent) return h.agent.sleeping ? null : {x: h.agent.x, y: h.agent.y, r: 18};
  const named = {board: BOARD, line: {x: LINE.x0, y: LINE.y - 14, w: LINE.x1 - LINE.x0, h: 64}, lot: LOT, gate: GATE, truck: TRUCK,
                 mail: {x: MAILBOX.x - 16, y: MAILBOX.y - 40, w: 32, h: 44}};
  const b = named[h.building] || B[h.building] || S[h.building];
  return b ? box(b) : null;
}

function tick(dt, now) {
  for (const a of agents.values()) { think(a, now); step(a, dt, now); }
  cam.tick(dt);
  mailBump = Math.max(0, mailBump - dt * 2);
  boardGlow = Math.max(0, boardGlow - dt * .7);
  dish += dt * (agents.get("radar")?.busy ? 3 : .6);
  if (truck.away) { truck.t += dt; if (truck.t >= 6) truck = {t: 0, away: false}; }
  for (const c of clouds) { c.x += 9 * dt; if (c.x > W + 160) { c.x = -160; c.y = rnd(40, H - 40); } }
  for (const f of fireflies) {
    f.vx = clamp(f.vx + rnd(-20, 20) * dt, -12, 12); f.vy = clamp(f.vy + rnd(-20, 20) * dt, -10, 10);
    f.x = 20 + ((f.x - 20 + f.vx * dt + (W - 20)) % (W - 20)); f.y = clamp(f.y + f.vy * dt, 40, H - 4);
  }
  if (!SKY.night && now > nextBirds) {
    nextBirds = now + rnd(20000, 45000);
    const n = 3 + Math.floor(Math.random() * 3), dir = Math.random() < .5 ? 1 : -1;
    birds.push({x: dir > 0 ? -60 : W + 60, y: rnd(30, H - 120), vx: dir * rnd(55, 80), vy: rnd(-6, 6), birds: Array.from({length: n}, (_, i) => ({dx: -dir * i * 12, dy: (i % 2 ? 1 : -1) * Math.ceil(i / 2) * 9}))});
  }
  for (let i = birds.length - 1; i >= 0; i--) { const b = birds[i]; b.x += b.vx * dt; b.y += b.vy * dt; if (b.x < -120 || b.x > W + 120) birds.splice(i, 1); }
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
  const w = document.getElementById("etsywaiting"), l = document.getElementById("etsylive");
  const n = shown.pending + shown.ready;
  if (w) { w.textContent = n ? `👀 ${n} for you` : ""; w.classList.toggle("hot", shown.pending > 0); w.onclick = () => kit.approvalsCard("etsy"); }
  if (l) l.textContent = `👕 ${shown.live.length} live · ${shown.sales} sold`;
}
const toWorld = e => cam.toWorld(e.clientX, e.clientY);
function hit(p) {
  for (const a of agents.values()) if (!a.sleeping && Math.hypot(p.x - a.x, p.y - (a.y - 14)) < 18) return {agent: a};
  if (Math.hypot(p.x - MAILBOX.x, p.y - (MAILBOX.y - 18)) < 18) return {building: "mail"};
  for (const [k, b] of Object.entries(B)) if (p.x > b.x - 8 && p.x < b.x + b.w + 8 && p.y > b.y - 10 && p.y < b.y + b.h + 4) return {building: k};
  for (const [k, b] of Object.entries(S)) if (p.x > b.x - 6 && p.x < b.x + b.w + 6 && p.y > b.y - 16 && p.y < b.y + b.h + 4) return {building: k};
  if (p.x > GATE.x && p.x < GATE.x + GATE.w && p.y > GATE.y - 10 && p.y < GATE.y + GATE.h) return {building: "gate"};
  if (p.x > TRUCK.x && p.x < TRUCK.x + TRUCK.w && p.y > TRUCK.y && p.y < TRUCK.y + TRUCK.h) return {building: "truck"};
  if (p.x > BOARD.x - 4 && p.x < BOARD.x + BOARD.w + 4 && p.y > BOARD.y - 4 && p.y < BOARD.y + BOARD.h + 14) return {building: "board"};
  if (p.x > LINE.x0 && p.x < LINE.x1 && p.y > LINE.y - 14 && p.y < LINE.y + 50) return {building: "line"};
  if (p.x > LOT.x && p.x < LOT.x + LOT.w && p.y > LOT.y && p.y < LOT.y + LOT.h) return {building: "lot"};
  return null;
}
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const TIPS = {
  shop: () => `Shop Front: Etta runs the shop from here. ${shown.live.length} live, ${shown.sales} sold${shown.ready ? `, ${shown.ready} ready for you to publish` : ""}. Click for the shop.`,
  lab: "Research Lab: Radar finds which shirt themes sell and when holidays start. Click for this week's brief.",
  window: () => `Publish Window: ${plural(shown.pending, "shirt")} waiting for your OK. Click to approve right here.`,
  mail: () => `Publish Window mailbox: ${plural(shown.pending, "shirt")} waiting for your OK.`,
  closet: "Sample Closet: order a sample of your best shirts. Etsy wants one real, unedited photo on every listing.",
  desk: "Copy Desk: Quill writes the slogans, titles and tags. Click for Quill.",
  studio: "Design Studio: Loom draws each shirt in two inks. Click to see the newest designs.",
  gate: () => `Rule Gate: Warden checks every shirt for brands, teams and Etsy's rules.${shown.held ? ` ${shown.held} held.` : ""} Click for the rules.`,
  dock: () => shown.printify ? `Loading Dock: Dock builds approved shirts in Printify and watches orders.${shown.orders ? ` ${plural(shown.orders, "order")} waiting for you.` : ""}` : "Loading Dock: connect Printify in Settings and Dock starts building shirts.",
  truck: "The Print & Ship truck takes each approved shirt to Printify. It never publishes or orders.",
  board: "Product Board: every shirt and where it is. Click for the board.",
  line: () => shown.live.length ? `Clothesline: your ${plural(shown.live.length, "live shirt")}. Click to see them.` : "Clothesline: shirts hang here once they're live on Etsy.",
  lot: "Coming next: hoodies, mugs and stickers from the same designs. Click to plan.",
};
const tip = document.getElementById("etsytip");
canvas.addEventListener("mousemove", e => {
  if (canvas.classList.contains("dragging")) { if (tip) tip.style.display = "none"; return; }
  const h = hit(toWorld(e));
  hover = h;
  canvas.style.cursor = h ? "pointer" : "";
  if (!tip) return;
  let text = "";
  if (h?.agent) text = `${h.agent.name}: ${h.agent.busy ? "working on " + h.agent.busy : h.agent.role || ""}`;
  else if (h?.building) { const v = TIPS[h.building]; text = typeof v === "function" ? v() : v; }
  tip.textContent = text;
  tip.style.display = text ? "block" : "none";
  if (text) {
    const rc = canvas.getBoundingClientRect();
    tip.style.left = clamp(e.clientX - rc.left + 14, 4, rc.width - 230) + "px";
    tip.style.top = clamp(e.clientY - rc.top + 14, 4, rc.height - 60) + "px";
  }
});
canvas.addEventListener("mouseleave", () => { hover = null; if (tip) tip.style.display = "none"; });

function live(name, act) {
  const a = agents.get(String(name).toLowerCase());
  if (a && act === "follow") {
    wake(a);
    cam.lookAt(a.x, a.y - 20, Math.max(cam.zoom, 2.2));
    cam.startFollow(() => agents.get(a.key) === a ? a : null, a.name);
  }
  return a;
}
const etsy = () => (kit.state() || {}).etsy || {};
const STAGE_NAME = {written: "written", drawn: "drawn", review: "your OK", approved: "approved", building: "building", ready: "in Printify",
                    live: "live", retired: "retired", held: "held", rejected: "skipped"};
const STAGE_PILL = {review: "warn", ready: "warn", live: "on", held: "bad"};
const designLine = d => `<li><span class="pill ${STAGE_PILL[d.stage] || ""}">${esc(STAGE_NAME[d.stage] || d.stage)}</span>${esc(d.slogan.replace(/\s*\/\s*/g, " "))} <span>${esc(d.theme)}</span></li>`;
function shopCard() {
  kit.infoCard("etsy-shop", () => {
    const e = etsy(), ready = (e.designs || []).filter(d => d.stage === "ready"), m = e.money || {};
    return {color: PINK, icon: "🛍️", title: "Shop Front", sub: `Etta's shop · ${shown.live.length} live · ${shown.sales} sold`,
      html: (ready.length ? `<h4>Ready for you to publish in Printify</h4><ul class="feed">${ready.slice(0, 6).map(d => `<li>${d.photo_added ? "📸" : "<span class='pill warn'>photo?</span>"} ${esc(d.title.slice(0, 70))}</li>`).join("")}</ul>
          <p class="muted">For each: add one real photo of your sample shirt, then press Publish in Printify. HQ never publishes for you.</p>`
          : `<p class="muted">Nothing waiting to publish. New shirts come down the line on their own.</p>`) +
        `<div class="grid"><div><b>${kit.usd(m.month_usd)}</b><span>Etsy agents this month</span></div><div><b>${kit.usd(m.today_usd)}</b><span>today (cap ${kit.usd(m.budget_usd)})</span></div></div>`,
      buttons: [{act: "etta", label: "🛍️ Etta's card"}, {act: "open", label: "Open the shop ↗", kind: "ghost"}],
      acts: {etta: () => kit.agentCard("Etta", live), open: () => kit.goTab("etsy", "etsy")}};
  });
}
function labCard() {
  kit.infoCard("etsy-lab", () => {
    const e = etsy(), b = e.brief, hol = (e.holidays || []).slice(0, 3);
    return {color: "#38bdf8", icon: "📡", title: "Research Lab", sub: b ? `Radar's brief from ${kit.when(b.created_at)}` : "No brief yet",
      html: (b ? `<h4>Themes to design for</h4><ul class="feed">${b.themes.slice(0, 8).map(t => `<li>${esc(t.theme)} <span>${esc(t.why || "")}</span></li>`).join("")}</ul>` : `<p class="muted">Radar makes the first brief within a few minutes.</p>`) +
        (hol.length ? `<h4>Holidays coming</h4><ul class="feed">${hol.map(h => `<li><span class="pill ${h.late ? "warn" : ""}">${h.late ? "late" : "start by " + esc(h.start_by.slice(5))}</span>${esc(h.name)} ${esc(h.date.slice(5))}</li>`).join("")}</ul>` : ""),
      buttons: [{act: "radar", label: "📡 Radar's card"}, {act: "open", label: "Add research ↗", kind: "ghost"}],
      acts: {radar: () => kit.agentCard("Radar", live), open: () => kit.goTab("etsy", "etsyresearch")}};
  });
}
function studioCard() {
  kit.infoCard("etsy-studio", () => {
    const list = (etsy().designs || []).filter(d => d.has_preview && !["rejected", "retired"].includes(d.stage)).slice(0, 3);
    return {color: "#a78bfa", icon: "🎨", title: "Design Studio", sub: "Loom's newest shirts",
      html: list.length ? list.map(d => `<div class="item"><img src="/api/etsy/designs/${d.id}/file/preview" alt="" style="width:100%;border-radius:8px" loading="lazy">
          <b>${esc(d.slogan.replace(/\s*\/\s*/g, " "))}</b><small class="muted">${esc(d.theme)} · ${esc(STAGE_NAME[d.stage] || d.stage)}</small></div>`).join("")
        : `<p class="muted">No designs yet. Quill writes them first, then Loom draws them here.</p>`,
      buttons: [{act: "loom", label: "🎨 Loom's card"}, {act: "open", label: "Open the board ↗", kind: "ghost"}],
      acts: {loom: () => kit.agentCard("Loom", live), open: () => kit.goTab("etsy", "etsyboard")}};
  });
}
function gateCard() {
  kit.infoCard("etsy-gate", () => {
    const e = etsy(), held = (e.designs || []).filter(d => d.stage === "held").slice(0, 4);
    return {color: "#ef4444", icon: "🛡️", title: "Rule Gate", sub: "Warden checks every shirt before it goes anywhere",
      html: (held.length ? `<h4>Held</h4><ul class="feed">${held.map(d => `<li>${esc(d.slogan.replace(/\s*\/\s*/g, " "))} <span>${esc((d.warden.problems || []).join("; "))}</span></li>`).join("")}</ul>` : "") +
        `<h4>The rules</h4><ul class="feed">${(e.rules || []).slice(0, 6).map(r => `<li>${esc(r.rule)} <span>checked ${esc(r.checked)}</span></li>`).join("")}</ul>`,
      buttons: [{act: "warden", label: "🛡️ Warden's card"}, {act: "open", label: "All rules ↗", kind: "ghost"}],
      acts: {warden: () => kit.agentCard("Warden", live), open: () => kit.goTab("etsy", "etsyrules")}};
  });
}
function dockCard() {
  kit.infoCard("etsy-dock", () => {
    const e = etsy(), orders = (e.orders || []).slice(0, 5), on = e.connections?.printify;
    return {color: "#22c55e", icon: "📦", title: "Loading Dock", sub: on ? "Connected to Printify" : "Printify isn't connected yet",
      html: (on ? "" : `<p>Paste your Printify API token in Settings and Dock starts building approved shirts there (never published).</p>`) +
        (orders.length ? `<h4>Orders</h4><ul class="feed">${orders.map(o => `<li><span class="pill ${o.status === "on-hold" ? "warn" : "on"}">${esc(o.status)}</span>${esc((o.items || []).map(i => `${i.quantity}× ${i.title}`).join(", "))}</li>`).join("")}</ul>
            <p class="muted">An order "on-hold" waits for you to press Send to production in Printify. HQ never does that.</p>` : `<p class="muted">No orders yet.</p>`),
      buttons: [{act: "dock", label: "📦 Dock's card"}, on ? {act: "orders", label: "Printify orders ↗", kind: "ghost"} : {act: "settings", label: "Open Settings ↗", kind: "ghost"}],
      acts: {dock: () => kit.agentCard("Dock", live), orders: () => window.open("https://printify.com/app/orders", "_blank", "noopener"),
             settings: () => { location.href = "/settings#g-etsy"; }}};
  });
}
function boardCard() {
  kit.infoCard("etsy-board", () => {
    const list = (etsy().designs || []).slice(0, 8);
    return {color: PLUM, icon: "📋", title: "Product Board", sub: "Every shirt and where it is",
      html: list.length ? `<ul class="feed">${list.map(designLine).join("")}</ul>` : `<p class="muted">Nothing on the board yet.</p>`,
      buttons: [{act: "open", label: "Open the board ↗", kind: "ghost"}], acts: {open: () => kit.goTab("etsy", "etsyboard")}};
  });
}
function lineCard() {
  kit.infoCard("etsy-line", () => {
    const list = (etsy().designs || []).filter(d => d.stage === "live");
    return {color: "#f59e0b", icon: "👕", title: "The clothesline", sub: `${plural(list.length, "shirt")} live on Etsy`,
      html: list.length ? `<ul class="feed">${list.slice(0, 10).map(d => `<li>${esc(d.slogan.replace(/\s*\/\s*/g, " "))} <span>${d.sales ? d.sales + " sold" : "no sales yet"}</span></li>`).join("")}</ul>`
        : `<p class="muted">Shirts hang here once you've published them in Printify and they're live on Etsy.</p>`,
      buttons: [{act: "open", label: "Open the shop ↗", kind: "ghost"}], acts: {open: () => kit.goTab("etsy", "etsy")}};
  });
}
function closetCard() {
  kit.infoCard("etsy-closet", () => {
    const ready = (etsy().designs || []).filter(d => ["ready", "live"].includes(d.stage) && !d.photo_added);
    return {color: "#7c3aed", icon: "📸", title: "Sample Closet", sub: "One real photo per listing",
      html: `<p>Etsy now wants at least one real, unedited photo on every listing. Order one sample of a shirt in Printify (Orders, then Create order),
        wear it or lay it flat, and add that photo when you publish.</p>` +
        (ready.length ? `<h4>Still need a real photo</h4><ul class="feed">${ready.slice(0, 6).map(d => `<li>${esc(d.slogan.replace(/\s*\/\s*/g, " "))}</li>`).join("")}</ul>` : ""),
      buttons: [{act: "open", label: "Tick photos off ↗", kind: "ghost"}], acts: {open: () => kit.goTab("etsy", "etsyboard")}};
  });
}
function lotCard() {
  kit.infoCard("etsy-lot", () => ({color: PLUM, icon: "🏗️", title: "Coming next", sub: "More products from the same designs",
    html: `<ul class="feed"><li><b>Hoodies</b>: the same art on a hoodie, for fall and winter</li><li><b>Mugs</b>: the slogan on a mug, a big gift seller</li>
      <li><b>Stickers</b>: cheap add-ons that lift each order</li></ul><p class="muted">Tell the Boss which one you want first and it becomes the next wave.</p>`,
    buttons: [{act: "plan", label: "💬 Plan it with the Boss"}], acts: {plan: () => kit.bossCard("For the Etsy village's next wave, I want to add ")}}));
}
canvas.addEventListener("click", e => {
  if (cam.dragged) return;
  const h = hit(toWorld(e));
  kit.at(e);
  if (!h) { kit.closeCard(); return; }
  if (h.agent) {
    const a = h.agent;
    a.jumpT = .5;
    burst(a.x, a.y - 30, 6, "emoji", ["💖", "👕"], {min: 10, max: 40, g: -10});
    kit.agentCard(a.name, live);
    return;
  }
  ({shop: shopCard, lab: labCard, window: () => kit.approvalsCard("etsy"), mail: () => kit.approvalsCard("etsy"), closet: closetCard,
    desk: () => kit.agentCard("Quill", live), studio: studioCard, gate: gateCard, dock: dockCard, truck: dockCard, board: boardCard,
    line: lineCard, lot: lotCard})[h.building]?.();
});

// ---------- public API ----------
window.EtsyTown = {
  update(s) {
    const e = s.etsy;
    if (!e) return;
    const list = (s.agents || []).filter(a => a.village === "etsy");
    const appr = (s.approvals || []).filter(a => a.village === "etsy");
    syncAgents(list);
    const designs = e.designs || [];
    const liveList = designs.filter(d => d.stage === "live").reverse();
    const orders = (e.orders || []).filter(o => ["on-hold", "pending"].includes(o.status)).length;
    const st = {approvals: appr, counts: e.counts || {}, sales: e.money?.sales || 0, orders, brief: e.brief?.id || 0};
    if (prev) react(st);
    chatter((s.activity || []).filter(r => agents.has(String(r.agent).toLowerCase())));
    shown = {pending: appr.length, ready: (e.counts || {}).ready || 0, live: liveList, sales: e.money?.sales || 0, counts: e.counts || {},
             held: (e.counts || {}).held || 0, orders, latest: designs.find(d => d.has_preview), printify: !!e.connections?.printify,
             brief: (e.brief?.themes || []).length, needPhoto: designs.filter(d => ["ready", "live"].includes(d.stage) && !d.photo_added).length};
    prev = {approvals: appr.map(a => a.id), counts: {...(e.counts || {})}, sales: st.sales, orders, brief: st.brief};
    hud();
    if (calm) draw(performance.now());
  },
};

new ResizeObserver(() => cam.resize()).observe(canvas);
new IntersectionObserver(es => { visible = es[0].isIntersecting; }).observe(canvas);
cam.resize();
if (calm) setInterval(() => { tick(1, performance.now()); draw(performance.now()); }, 2000);
else requestAnimationFrame(frame);
})();

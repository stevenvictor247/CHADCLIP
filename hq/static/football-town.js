// Warrior Village: the football side of HQ Town, drawn next to it in Wayne State green and gold. Captain works in the
// Film Room, Clock, Ref, Tells and Scribe have cottages around a little Tom Adams Field, and the scoreboard counts down
// to the next game. index.html feeds it with FootballTown.update(state) on every refresh, the same state HQ Town gets.
// Colors are Wayne State's official green (PMS 561, #0C5449) and gold (PMS 1225, #FFCC33). The Warrior W and the
// shield are the university's artwork and must not be redrawn, so the village only uses the words, never the marks.
(() => {
"use strict";
const canvas = document.getElementById("fbcanvas");
const kit = window.HQTown;
if (!canvas || !kit) return;
const ctx = canvas.getContext("2d");
const W = 960, H = 416, ROAD_Y = 240;
const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
const EMOJI = '"Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif';
const FONT = '"Nunito",system-ui,sans-serif';
const GREEN = "#0C5449", GOLD = "#FFCC33", TURF = ["#3f9a4a", "#479f50"], BRICK = "#9a4a32";

const rnd = (a, b) => a + Math.random() * (b - a);
const pick = a => a[Math.floor(Math.random() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, k) => a + (b - a) * k;
function seeded(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
const look = name => window.hqLook ? window.hqLook(name) : {color: "#7cc4ff", prop: "🏈", hat: null};

// ---------- the map ----------
const B = {
  film:  {x: 96, y: 40, w: 180, h: 130, wall: "#e6f0ec", roof: GREEN, door: 186, label: "Film Room", icon: "🎞️"},
  mail:  {x: 330, y: 66, w: 136, h: 104, wall: "#fff6dc", roof: "#e0ad1f", door: 398, label: "Coaches' Mailroom", icon: "📬"},
  press: {x: 806, y: 34, w: 124, h: 136, wall: "#f1ece4", roof: GREEN, door: 868, label: "Press Box", icon: "🎧"},
};
for (const b of Object.values(B)) b.front = {x: b.door, y: b.y + b.h + 20};
const BOARD = {x: 532, y: 20, w: 230, h: 124, front: {x: 647, y: 196}};
const FIELD = {x: 286, y: 290, w: 372, h: 106};
const TENT = {x: 898, y: 300, w: 56, h: 44};   // the Warrior Village tailgate, like the real one in the south end zone
const CORNHOLE = {x: 926, y: 384};
const TOWERS = [{x: 274, y: 300}, {x: 672, y: 300}];   // stadium lights at the field corners
const COTTAGES = [["Clock", "⏰", 66], ["Ref", "🚩", 168], ["Tells", "📊", 696], ["Scribe", "📓", 806]]
  .map(([agent, icon, x]) => ({agent, icon, x, y: 300, w: 86, h: 72}));
for (const p of COTTAGES) p.front = {x: p.x + p.w / 2, y: p.y - 8};
const CREEK = 34;   // the creek on the left edge: HQ Town is across the footbridge
const MAILBOX = {x: 488, y: 178};
const TREES = [[296, 92], [300, 168], [500, 40], [784, 168], [948, 214], [262, 410], [676, 410], [60, 404], [512, 160]]
  .map(([x, y], i) => ({x, y, i, kind: i % 3 === 1 ? "dark" : "green"}));
const LAMPS = [[70, 214], [310, 214], [520, 214], [790, 214]].map(([x, y]) => ({x, y}));
const SPOTS = [{x: 360, y: 330, field: true}, {x: 470, y: 352, field: true}, {x: 584, y: 330, field: true}, {x: 410, y: 384, field: true},
               {x: 540, y: 386, field: true}, {x: 472, y: 276}, {x: 647, y: 196}, {x: 22, y: 244}, {x: 300, y: 250}, {x: 760, y: 252},
               {x: 904, y: 370, tailgate: true}, {x: 946, y: 370, tailgate: true}, {x: 120, y: 254}];

// ---------- canvas sizing ----------
// The camera (town-kit.js) fits the village to its box and handles zooming and dragging, like in HQ Town.
const terrain = document.createElement("canvas"), dark = document.createElement("canvas");
let terrainAt = -1;
const cam = kit.camera(canvas, W, H, {onChange: () => { if (calm) draw(performance.now()); }});
kit.register("fbworld", cam);

function creekEdge(y) { return CREEK + Math.sin(y / 38) * 6 + Math.sin(y / 13) * 2; }
function blocked(x, y) {
  if (x < creekEdge(y) + 14) return true;
  if (y > 210 && y < 270) return true;
  for (const b of [...Object.values(B), BOARD]) if (x > b.x - 12 && x < b.x + b.w + 12 && y < b.y + b.h + 30) return true;
  if (x > FIELD.x - 14 && x < FIELD.x + FIELD.w + 14 && y > FIELD.y - 20) return true;
  if (x > TENT.x - 10 && y > TENT.y - 14 && y < CORNHOLE.y + 10) return true;
  for (const p of COTTAGES) if (x > p.x - 12 && x < p.x + p.w + 12 && y > p.y - 16 && y < p.y + p.h + 10) return true;
  for (const t of TREES) if (Math.hypot(x - t.x, y - t.y + 10) < 24) return true;
  return false;
}
const r = seeded(11);
const FLOWERS = [];
for (let tries = 0; FLOWERS.length < 16 && tries < 600; tries++) {
  const x = 40 + r() * (W - 60), y = 20 + r() * (H - 30);
  if (!blocked(x, y)) FLOWERS.push({x, y, n: 3 + Math.floor(r() * 4), c: ["#ffd34d", "#ffffff", "#7cc4ff", "#4ade80"][Math.floor(r() * 4)], s: Math.floor(r() * 1e6)});
}

function drawTerrain() {
  const c = terrain;
  if (c.width !== canvas.width || c.height !== canvas.height) { c.width = canvas.width; c.height = canvas.height; }
  const g = c.getContext("2d");
  g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, c.width, c.height);
  g.setTransform(cam.s, 0, 0, cam.s, cam.ox, cam.oy);
  kit.outskirts(g, cam.view(), W, H, {grass: "#5cb054", seed: 24});
  const rr = seeded(24);
  g.fillStyle = "#62b85a"; g.fillRect(0, 0, W, H);
  for (let ty = 0; ty < H; ty += 32) for (let tx = 0; tx < W; tx += 32) {
    g.fillStyle = ((tx + ty) / 32) % 2 ? "rgba(255,255,255,.035)" : "rgba(0,60,0,.035)";
    g.fillRect(tx, ty, 32, 32);
  }
  g.strokeStyle = "rgba(30,90,30,.35)"; g.lineWidth = 1.2;
  for (let i = 0; i < 260; i++) {
    const x = rr() * W, y = rr() * H;
    g.beginPath(); g.moveTo(x - 2, y); g.lineTo(x, y - 4); g.lineTo(x + 2, y); g.stroke();
  }
  // roads and paths
  const path = (x, y, w, h) => {
    g.fillStyle = "#e4c792"; g.fillRect(x, y, w, h);
    g.fillStyle = "rgba(160,120,60,.25)"; g.fillRect(x, y, w, 2); g.fillRect(x, y + h - 2, w, 2);
  };
  path(0, ROAD_Y - 16, W, 32);
  for (const b of Object.values(B)) path(b.door - 12, b.y + b.h - 2, 24, ROAD_Y - 16 - (b.y + b.h - 2));
  path(BOARD.front.x - 10, BOARD.y + BOARD.h + 26, 20, ROAD_Y - 16 - (BOARD.y + BOARD.h + 26));
  path(FIELD.x + FIELD.w / 2 - 12, ROAD_Y + 16, 24, FIELD.y - ROAD_Y - 16);
  for (const p of COTTAGES) path(p.front.x - 10, ROAD_Y + 16, 20, p.y - ROAD_Y - 16);
  g.fillStyle = "rgba(120,90,50,.35)";
  for (let i = 0; i < 120; i++) { g.beginPath(); g.arc(rr() * W, ROAD_Y - 13 + rr() * 26, rr() * 1.4 + .4, 0, 7); g.fill(); }
  // the creek, with sandy banks
  const creek = (pad, color) => {
    g.fillStyle = color; g.beginPath(); g.moveTo(0, 0);
    for (let y = 0; y <= H; y += 4) g.lineTo(creekEdge(y) + pad, y);
    g.lineTo(0, H); g.closePath(); g.fill();
  };
  creek(7, "#d9c58f"); creek(0, "#3d8fd1"); creek(-10, "#5aaee6");
  for (let i = 0; i < 10; i++) {
    const y = rr() * H; if (Math.abs(y - ROAD_Y) < 30) continue;
    const x = creekEdge(y) + 6;
    g.strokeStyle = "#2f7d3a"; g.lineWidth = 1.5; g.beginPath(); g.moveTo(x, y); g.lineTo(x + rr() * 3 - 1.5, y - 9); g.stroke();
  }
  // the footbridge over the creek
  g.fillStyle = "rgba(0,0,0,.2)"; g.fillRect(0, ROAD_Y + 16, CREEK + 22, 5);
  g.fillStyle = "#a8713f"; g.fillRect(0, ROAD_Y - 18, CREEK + 22, 36);
  g.strokeStyle = "rgba(70,40,20,.45)"; g.lineWidth = 1.2;
  for (let x = 4; x < CREEK + 22; x += 7) { g.beginPath(); g.moveTo(x, ROAD_Y - 18); g.lineTo(x, ROAD_Y + 18); g.stroke(); }
  g.fillStyle = "#6b4226"; g.fillRect(0, ROAD_Y - 22, CREEK + 22, 4); g.fillRect(0, ROAD_Y + 18, CREEK + 22, 4);
  for (const x of [2, 20, CREEK + 18]) { g.fillRect(x, ROAD_Y - 27, 4, 9); g.fillRect(x, ROAD_Y + 18, 4, 9); }
  // the field: striped turf, green end zones with the words in gold, and the brick "sitting wall" of the home stands
  const f = FIELD, ez = 34, yard = (f.w - 2 * ez) / 10;
  g.fillStyle = "#f4f4f4"; g.fillRect(f.x - 4, f.y - 4, f.w + 8, f.h + 8);
  for (let i = 0; i < 10; i++) { g.fillStyle = TURF[i % 2]; g.fillRect(f.x + ez + i * yard, f.y, yard, f.h); }
  g.fillStyle = GREEN; g.fillRect(f.x, f.y, ez, f.h); g.fillRect(f.x + f.w - ez, f.y, ez, f.h);
  g.strokeStyle = "rgba(255,255,255,.9)"; g.lineWidth = 1.5;
  for (let i = 0; i <= 10; i++) { const x = f.x + ez + i * yard; g.beginPath(); g.moveTo(x, f.y); g.lineTo(x, f.y + f.h); g.stroke(); }
  g.lineWidth = 1;
  for (let i = 0; i < 50; i++) {
    const x = f.x + ez + i * yard / 5;
    for (const y of [f.y + 3, f.y + f.h * .38, f.y + f.h * .62, f.y + f.h - 6]) { g.beginPath(); g.moveTo(x, y); g.lineTo(x, y + 3); g.stroke(); }
  }
  g.textAlign = "center"; g.textBaseline = "middle";
  for (const [x, rot, word] of [[f.x + ez / 2, -Math.PI / 2, "WAYNE STATE"], [f.x + f.w - ez / 2, Math.PI / 2, "WARRIORS"]]) {
    g.save(); g.translate(x, f.y + f.h / 2); g.rotate(rot);
    g.font = `900 13px ${FONT}`; g.lineWidth = 3; g.strokeStyle = "#ffffff"; g.strokeText(word, 0, 0); g.fillStyle = GOLD; g.fillText(word, 0, 0);
    g.restore();
  }
  g.fillStyle = "rgba(255,255,255,.9)"; g.font = `800 9px ${FONT}`;
  for (const [i, n] of [[1, "10"], [2, "20"], [3, "30"], [4, "40"], [5, "50"], [6, "40"], [7, "30"], [8, "20"], [9, "10"]]) g.fillText(n, f.x + ez + i * yard, f.y + f.h - 14);
  g.fillStyle = GREEN; g.beginPath(); g.ellipse(f.x + f.w / 2, f.y + f.h / 2, 24, 15, 0, 0, 7); g.fill();
  g.strokeStyle = GOLD; g.lineWidth = 2; g.stroke();
  g.fillStyle = GOLD; g.font = `900 12px ${FONT}`; g.fillText("WSU", f.x + f.w / 2, f.y + f.h / 2 + 1);
  for (let x = f.x - 4, row = 0; x < f.x + f.w + 4; x += 12, row++) {
    g.fillStyle = BRICK; g.fillRect(x, f.y + f.h + 6, 11, 5);
    g.fillStyle = "#7d3a26"; g.fillRect(x + 6, f.y + f.h + 12, 11, 5);
  }
  g.fillStyle = "#cfc6b8"; g.fillRect(f.x - 4, f.y + f.h + 4, f.w + 8, 2);
  // flowers
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
let shown = {pending: 0, week: null, flagged: 0};

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
  const el = document.getElementById("fbticker");
  if (!el) return;
  el.textContent = text; el.classList.remove("show"); void el.offsetWidth; el.classList.add("show");
  clearTimeout(tickerTimer); tickerTimer = setTimeout(() => el.classList.remove("show"), 6000);
}

// Same sky as HQ Town (and the same Real time / Always day / Always night button).
function ownSky() {
  const d = new Date(), h = d.getHours() + d.getMinutes() / 60;
  const dk = h < 5 || h >= 21.5 ? .7 : h < 7 ? lerp(.7, 0, (h - 5) / 2) : h < 17.5 ? 0 : h < 19.5 ? lerp(0, .25, (h - 17.5) / 2) : lerp(.25, .7, (h - 19.5) / 2);
  return {dk, tint: 0, tc: "255,160,80", night: dk > .45};
}
const sky = () => window.HQWorld?.sky?.() || ownSky();
let SKY = sky();

// ---------- agents ----------
const cottageOf = name => COTTAGES.find(p => p.agent.toLowerCase() === name.toLowerCase());
function makeAgent(info) {
  const key = info.name.toLowerCase(), l = look(info.name);
  const home = cottageOf(info.name) || B.film;
  const a = {name: info.name, key, role: info.role, color: l.color, hat: l.hat, prop: l.prop, home,
             x: home.front.x + rnd(-10, 10), y: home.front.y + rnd(0, 6), path: [], actions: [], current: null, waitUntil: 0,
             busy: null, sleeping: false, facing: 1, phase: 0, seed: Math.random() * 1000, jumpT: 0, face: "happy", faceUntil: 0,
             carry: null, say: null, sayUntil: 0, nextSpark: 0, speed: key === "captain" ? 48 : 54};
  agents.set(key, a);
  return a;
}
function route(a, to) {
  if (calm) { a.x = to.x; a.y = to.y; a.path = []; return; }
  const p = [], onRoad = y => Math.abs(y - ROAD_Y) < 6;
  if (Math.abs(a.x - to.x) < 4) p.push({x: to.x, y: to.y});
  else {
    if (!onRoad(a.y)) p.push({x: a.x, y: ROAD_Y + rnd(-5, 5)});
    p.push({x: to.x, y: p.length ? p[0].y : a.y});
    p.push({x: to.x, y: to.y});
  }
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
const workSpot = a => ({x: a.home.front.x + (a.key === "captain" ? -30 : 0), y: a.home.front.y});
const onField = a => a.x > FIELD.x && a.x < FIELD.x + FIELD.w && a.y > FIELD.y && a.y < FIELD.y + FIELD.h;

const CHATTER = ["Watching film 🎞️", "Run it back ⏪", "Go Warriors! 💚💛", "Hydrate 💧", "What's the down and distance?", "Stretching 🙆", "Next play ▶️",
                 "Win the week 💪", "GLIAC grind 🏈", "Tailgate snacks? 🌭"];
const NIGHT_CHATTER = ["Late film session 🌙", "One more cut-up 💪", "Lights out soon ✨"];
const CAPTAIN_TALK = ["How's it going, {n}?", "Nice work, {n} 👏", "Keep grinding, {n} 🏈", "Need anything, {n}?"];

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
  if (a.key === "captain" && busy.length && Math.random() < .45) {
    const o = pick(busy), s = workSpot(o);
    a.actions.push({at: {x: s.x + 26, y: s.y + 4}, do: () => { a.facing = -1; say(a, pick(CAPTAIN_TALK).replace("{n}", o.name), 3.5); }, wait: 4});
    return;
  }
  const spot = pick(SPOTS);
  a.actions.push({at: {x: spot.x + rnd(-8, 8), y: spot.y + rnd(-6, 6)}, wait: rnd(3, 9), do: () => {
    const mate = spot.field && [...agents.values()].find(o => o !== a && !o.sleeping && !o.path.length && onField(o));
    if (mate && Math.random() < .7) {   // play catch with whoever else is on the field
      a.facing = Math.sign(mate.x - a.x) || 1;
      fly({x: a.x, y: a.y - 22}, {x: mate.x, y: mate.y - 22}, "🏈", .9, 40, () => { mate.jumpT = .5; if (Math.random() < .4) say(mate, "Got it! 🙌", 2); });
    } else if (spot.tailgate && Math.random() < .6) {
      a.facing = Math.sign(CORNHOLE.x - a.x) || 1;
      fly({x: a.x, y: a.y - 20}, {x: CORNHOLE.x + 14 * a.facing, y: CORNHOLE.y - 8}, "🟨", .8, 30, () => { if (Math.random() < .3) floatText(CORNHOLE.x, CORNHOLE.y - 20, "Cornhole! 🎯", "#fde68a", 11); });
    } else if (Math.random() < .3) say(a, pick(SKY.night ? NIGHT_CHATTER : CHATTER), 3);
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
      burst(a.x, a.y - 18, 14, "spark", [a.color, "#fff", GOLD], {g: 60});
      ticker(`${a.name} finished a job`);
    }
  }
}

function deliver(a, emoji, n) {
  deliveriesOnTheWay += n;
  let delivered = false;
  const arrive = () => { if (!delivered) { delivered = true; deliveriesOnTheWay = Math.max(0, deliveriesOnTheWay - n); } };
  hurry(a);
  a.actions.push(
    {urgent: true, at: a.home.front, do: () => { a.carry = emoji; }, wait: .5},
    {urgent: true, at: {x: B.mail.door + 24, y: B.mail.front.y}, wait: 1.5, do: () => {
      a.carry = null; a.facing = 1; arrive(); mailBump = 1;
      fly({x: a.x, y: a.y - 30}, {x: MAILBOX.x, y: MAILBOX.y - 28}, emoji, .6, 20);
      say(a, "Waiting for your OK 👀", 3.5);
    }});
  setTimeout(arrive, 30000);
}

function react(s) {
  const fb = s.football, p = prev;
  // new football approvals: whoever asked walks it to the Mailroom
  const known = new Set(p.approvals);
  const fresh = s.approvals.filter(x => !known.has(x.id));
  for (const x of fresh) {
    const a = agents.get(String(x.agent).toLowerCase()) || agents.get("captain");
    if (a) deliver(a, x.agent === "Tells" ? "📄" : "📓", 1);
  }
  if (fresh.length) ticker(`${fresh[0].agent}: ${fresh[0].title}. It's in the Coaches' Mailroom for your OK.`);
  const gone = p.approvals.filter(id => !s.approvals.some(x => x.id === id)).length;
  if (gone) { addParticle({x: MAILBOX.x, y: MAILBOX.y - 40, vy: -16, life: 1.5, kind: "emoji", text: "👍", size: 16}); }
  // Ref finished checking a sheet
  const ref = agents.get("ref");
  for (const f of fb.files) {
    const was = p.files[f.id];
    if (was === undefined && p.loaded) ticker(`New sheet in the Inbox: ${f.name}`);
    if (f.status === "checked" && was && was !== "checked" && ref) {
      if (f.fix) {
        say(ref, `🚩 Flag! ${f.fix} to fix`, 5);
        fly({x: ref.x, y: ref.y - 24}, {x: FIELD.x + 70, y: FIELD.y + 40}, "🚩", 1, 60);
      } else say(ref, f.check_count ? `${f.check_count} to look at 👀` : "Clean sheet ✅", 4);
      ref.jumpT = .5;
    }
  }
  // the checklist
  const done = n => (n?.checklist || []).filter(x => x.state === "done").length;
  if (fb.week && p.week && fb.week.game?.opponent === p.week.game?.opponent && done(fb.week) > done(p.week)) {
    const clock = agents.get("clock");
    boardGlow = 1;
    burst(BOARD.x + BOARD.w / 2, BOARD.y + 40, 26, "confetti", [GOLD, "#ffffff", "#4ade80", "#0f9d7a"], {up: 70});
    if (clock) { clock.jumpT = .7; say(clock, "Ticked off ✅", 3); }
    const item = fb.week.checklist.find(x => x.state === "done" && !p.week.checklist.some(y => y.item === x.item && y.state === "done"));
    ticker(item ? `${item.item}: done for ${fb.week.game.opponent}` : "Checklist updated");
  }
  // the notebook and the Outbox
  if (fb.notes_total > p.notes && agents.get("scribe")) { const sc = agents.get("scribe"); say(sc, "Noted ✍️", 3); sc.jumpT = .5; }
  if (fb.outbox.length > p.outbox) {
    const a = agents.get("tells") || agents.get("captain");
    if (a) { say(a, "Saved to your Outbox 📤", 4); burst(a.x, a.y - 20, 14, "spark", [GOLD, "#fff"], {g: 60}); }
    ticker(`In your football Outbox: ${fb.outbox[0].name}`);
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
  ctx.fillStyle = "#1f2a24"; roundRect(ctx, b.door - lw / 2, wallY + 5, lw, 14, 4); ctx.fill();
  ctx.fillStyle = "#fff2d6"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, b.door, wallY + 12.5);
}

function drawBuildings(t, pending) {
  // Film Room: a projector beam on the roof and a green and gold pennant
  const fr = B.film;
  house(fr);
  emoji("📽️", fr.x + 140, fr.y + 22, 20, Math.sin(t / 900) * .1);
  ctx.fillStyle = "#5a4636"; ctx.fillRect(fr.x + 24, fr.y - 26, 3, 40);
  ctx.fillStyle = GOLD; ctx.beginPath(); ctx.moveTo(fr.x + 27, fr.y - 26);
  for (let i = 0; i <= 8; i++) ctx.lineTo(fr.x + 27 + i * 4, fr.y - 26 + Math.sin(t / 220 + i * .8) * 2);
  for (let i = 8; i >= 0; i--) ctx.lineTo(fr.x + 27 + i * 4, fr.y - 10 + Math.sin(t / 220 + i * .8) * 2);
  ctx.fill();
  ctx.fillStyle = GREEN; ctx.beginPath();
  for (let i = 0; i <= 8; i++) ctx.lineTo(fr.x + 27 + i * 4, fr.y - 20 + Math.sin(t / 220 + i * .8) * 2);
  for (let i = 8; i >= 0; i--) ctx.lineTo(fr.x + 27 + i * 4, fr.y - 16 + Math.sin(t / 220 + i * .8) * 2);
  ctx.fill();
  house(B.mail);
  // the Mailroom's mailbox, flag up while something waits for you
  const mb = MAILBOX, bump = 1 + Math.sin(mailBump * Math.PI) * .25;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(mb.x, mb.y, 9, 3, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#6b4b2e"; ctx.fillRect(mb.x - 2, mb.y - 16, 4, 16);
  ctx.save(); ctx.translate(mb.x, mb.y - 22); ctx.scale(bump, bump);
  ctx.fillStyle = GREEN; roundRect(ctx, -12, -8, 24, 15, 6); ctx.fill();
  ctx.fillStyle = "#08483a"; ctx.fillRect(-10, -1, 20, 2);
  ctx.fillStyle = GOLD;
  if (pending > 0) { ctx.fillRect(10, -18, 3, 12); ctx.fillRect(10, -18, 8, 5); } else ctx.fillRect(10, -4, 10, 3);
  ctx.restore();
  if (pending > 0) {
    const s = 1 + Math.sin(t / 250) * .08;
    ctx.save(); ctx.translate(mb.x - 12, mb.y - 34); ctx.scale(s, s);
    ctx.fillStyle = "#ff4d6d"; ctx.beginPath(); ctx.arc(0, 0, 8, 0, 7); ctx.fill();
    ctx.font = `900 10px ${FONT}`; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(pending > 99 ? "99+" : pending, 0, .5);
    ctx.restore();
  }
  // Press Box: a tall booth with a long window, where you chart on game day
  const pb = B.press;
  house(pb);
  ctx.fillStyle = "#334155"; ctx.fillRect(pb.x + 10, pb.y + 26, pb.w - 20, 22);
  ctx.fillStyle = SKY.dk > .15 ? "#ffd56b" : "#bfe3ff"; ctx.fillRect(pb.x + 14, pb.y + 29, pb.w - 28, 16);
  ctx.fillStyle = "#334155"; for (let x = pb.x + 40; x < pb.x + pb.w - 20; x += 26) ctx.fillRect(x, pb.y + 29, 2, 16);
  if (SKY.dk > .15) lights.push({x: pb.x + pb.w / 2, y: pb.y + 37, r: 60, warm: 1});
  ctx.fillStyle = GREEN; ctx.fillRect(pb.x + 6, pb.y + 10, pb.w - 12, 13);
  ctx.font = `900 8px ${FONT}`; ctx.fillStyle = GOLD; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("WAYNE STATE UNIVERSITY", pb.x + pb.w / 2, pb.y + 17);
  drawBoard(t);
}

function drawBoard(t) {
  const b = BOARD, w = shown.week, cx = b.x + b.w / 2, led = boardGlow > 0 ? "#fff6c8" : GOLD;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(cx + 6, b.y + b.h + 30, b.w / 2, 7, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#4b5563"; ctx.fillRect(b.x + 40, b.y + b.h, 8, 30); ctx.fillRect(b.x + b.w - 48, b.y + b.h, 8, 30);
  ctx.fillStyle = GREEN; roundRect(ctx, b.x - 5, b.y - 5, b.w + 10, b.h + 10, 8); ctx.fill();
  ctx.fillStyle = "#101413"; roundRect(ctx, b.x, b.y + 18, b.w, b.h - 18, 4); ctx.fill();
  ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.font = `900 11px ${FONT}`; ctx.fillStyle = GOLD; ctx.fillText("WAYNE STATE WARRIORS", cx, b.y + 7);
  lights.push({x: cx, y: b.y + 60, r: 100, warm: .7});
  if (!w) { ctx.font = `800 12px ${FONT}`; ctx.fillStyle = "#94a3b8"; ctx.fillText("Loading…", cx, b.y + 70); return; }
  if (w.season_over) {
    ctx.font = `900 18px ${FONT}`; ctx.fillStyle = led; ctx.fillText("SEASON OVER", cx, b.y + 62);
    ctx.font = `800 10px ${FONT}`; ctx.fillStyle = "#cbd5e1"; ctx.fillText("Great work this year 🏈", cx, b.y + 90);
    return;
  }
  const g = w.game, days = w.days_to_game;
  // HOME and GUEST boxes either side of the countdown, like the real board
  const box = (x, label, name) => {
    ctx.font = `800 7px ${FONT}`; ctx.fillStyle = "#cbd5e1"; ctx.fillText(label, x, b.y + 28);
    ctx.fillStyle = "#1c2422"; roundRect(ctx, x - 37, b.y + 34, 74, 18, 3); ctx.fill();
    ctx.font = `900 ${name.length > 9 ? 8 : 10}px ${FONT}`; ctx.fillStyle = "#ffffff"; ctx.fillText(fit(name, 70), x, b.y + 43.5);
  };
  const away = g.site === "away";
  box(b.x + 42, away ? "GUEST" : "HOME", "WSU");
  box(b.x + b.w - 42, away ? "HOME" : "GUEST", g.opponent.toUpperCase());
  const pulse = days === 0 && !calm ? 1 + Math.sin(t / 200) * .05 : 1;
  ctx.save(); ctx.translate(cx, b.y + 46); ctx.scale(pulse, pulse);
  ctx.fillStyle = "#1c2422"; roundRect(ctx, -26, -16, 52, 32, 4); ctx.fill();
  ctx.font = `900 ${days === 0 ? 11 : days > 99 ? 16 : 24}px ${FONT}`; ctx.fillStyle = led;
  ctx.fillText(days === 0 ? "GAME" : String(days), 0, days === 0 ? -5 : 1);
  if (days === 0) ctx.fillText("DAY", 0, 7);
  ctx.restore();
  ctx.font = `800 7px ${FONT}`; ctx.fillStyle = "#cbd5e1";
  ctx.fillText(days === 0 ? "KICKOFF TODAY" : days === 1 ? "DAY TO GO" : "DAYS TO GO", cx, b.y + 69);
  ctx.font = `800 9px ${FONT}`; ctx.fillStyle = "#e2e8f0";
  ctx.fillText(`${g.day.toUpperCase()} ${g.date.slice(5).replace("-", "/")}${g.kickoff ? " · " + g.kickoff : ""}${g.confirmed ? "" : " (DATE?)"}`, cx, b.y + 82);
  // the bottom row reads like DOWN and TO GO: what's done and what's late
  const total = w.checklist.length, done = w.checklist.filter(x => x.state === "done").length, late = w.late.length;
  const cell = (x, label, value, color) => {
    ctx.font = `800 7px ${FONT}`; ctx.fillStyle = "#cbd5e1"; ctx.fillText(label, x, b.y + 96);
    ctx.font = `900 12px ${FONT}`; ctx.fillStyle = color; ctx.fillText(value, x, b.y + 110);
  };
  cell(b.x + 40, "DONE", `${done}/${total}`, "#4ade80");
  cell(cx, "DUE TODAY", String(w.due_today.length), w.due_today.length ? GOLD : "#e2e8f0");
  cell(b.x + b.w - 40, "LATE", String(late), late ? (Math.sin(t / 300) > 0 || calm ? "#f87171" : "#b91c1c") : "#e2e8f0");
}

function drawGoalpost(x, t) {   // seen from the side: a gold post, the crossbar running along the end line, two uprights
  const base = FIELD.y + FIELD.h / 2, top = base - 26;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(x + 4, base + 2, 6, 2, 0, 0, 7); ctx.fill();
  ctx.strokeStyle = GOLD; ctx.lineCap = "round";
  ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(x, base); ctx.lineTo(x, top); ctx.stroke();
  ctx.lineWidth = 2.5; ctx.beginPath(); ctx.moveTo(x, top - 12); ctx.lineTo(x, top + 12); ctx.stroke();
  ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x, top - 12); ctx.lineTo(x + 3, top - 44); ctx.moveTo(x, top + 12); ctx.lineTo(x - 3, top - 20); ctx.stroke();
  ctx.fillStyle = "#e11d48"; ctx.fillRect(x + 2, top - 46 + Math.sin(t / 300) * .5, 4, 2);
}
function drawTower(o) {   // stadium lights; at night they light up the whole field
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(o.x + 3, o.y, 6, 2, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#6b7280"; ctx.fillRect(o.x - 2, o.y - 66, 4, 66);
  ctx.fillStyle = "#374151"; roundRect(ctx, o.x - 11, o.y - 78, 22, 13, 2); ctx.fill();
  const on = SKY.dk > .15;
  ctx.fillStyle = on ? "#fffbe0" : "#cbd5e1";
  for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) ctx.fillRect(o.x - 9 + i * 7, o.y - 76 + j * 6, 5, 4);
  if (on) lights.push({x: o.x, y: o.y - 72, r: 40, warm: 1});
}
function drawTent(t) {   // the Warrior Village tailgate: a green and gold canopy, a table and the cornhole boards
  const c = TENT, tx = c.x, ty = c.y;
  ctx.fillStyle = "rgba(0,0,0,.18)"; ctx.beginPath(); ctx.ellipse(tx + c.w / 2 + 4, ty + c.h + 2, c.w / 2 + 6, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#9ca3af"; ctx.fillRect(tx + 2, ty + 14, 2, c.h - 14); ctx.fillRect(tx + c.w - 4, ty + 14, 2, c.h - 14);
  ctx.fillStyle = "#8a5a32"; ctx.fillRect(tx + 8, ty + c.h - 14, c.w - 16, 6);
  emoji("🌭", tx + 18, ty + c.h - 18, 9); emoji("🥤", tx + 36, ty + c.h - 18, 9);
  for (let i = 0; i < 4; i++) {
    ctx.fillStyle = i % 2 ? GOLD : GREEN; ctx.beginPath();
    ctx.moveTo(tx + i * c.w / 4, ty + 16); ctx.lineTo(tx + (i + 1) * c.w / 4, ty + 16); ctx.lineTo(tx + c.w / 2, ty); ctx.closePath(); ctx.fill();
  }
  for (let i = 0; i < 8; i++) {   // the scalloped valance
    ctx.fillStyle = i % 2 ? GOLD : GREEN; ctx.beginPath(); ctx.arc(tx + 3.5 + i * 7, ty + 16, 3.5, 0, Math.PI); ctx.fill();
  }
  ctx.font = `900 6px ${FONT}`; ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText("WARRIOR VILLAGE", tx + c.w / 2, ty + c.h + 8);
  const cb = CORNHOLE;
  for (const dx of [-14, 14]) {
    ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.fillRect(cb.x + dx - 6, cb.y + 1, 13, 3);
    ctx.fillStyle = dx < 0 ? GREEN : "#e0ad1f"; ctx.fillRect(cb.x + dx - 6, cb.y - 12, 12, 13);
    ctx.fillStyle = "#1d1426"; ctx.beginPath(); ctx.arc(cb.x + dx, cb.y - 8, 2, 0, 7); ctx.fill();
  }
  if (SKY.dk > .15) lights.push({x: tx + c.w / 2, y: ty + 20, r: 50, warm: 1});
}

function drawCottage(p) {
  ctx.strokeStyle = "#8a5a32"; ctx.lineWidth = 2;
  ctx.beginPath(); ctx.moveTo(p.x - 4, p.y); ctx.lineTo(p.x - 4, p.y + p.h + 4); ctx.lineTo(p.x + p.w + 4, p.y + p.h + 4); ctx.lineTo(p.x + p.w + 4, p.y); ctx.stroke();
  ctx.fillStyle = "#6b4226";
  for (let x = p.x - 4; x <= p.x + p.w + 4; x += 15) ctx.fillRect(x - 1.5, p.y + p.h - 3, 3, 8);
  for (let y = p.y; y <= p.y + p.h; y += 15) { ctx.fillRect(p.x - 5.5, y - 7, 3, 8); ctx.fillRect(p.x + p.w + 2.5, y - 7, 3, 8); }
  const a = agents.get(p.agent.toLowerCase()), col = a?.color || look(p.agent).color;
  const hx = p.x + 14, hy = p.y + 14, hw = p.w - 28, hh = 46;
  ctx.fillStyle = "#fff6e0"; ctx.fillRect(hx, hy + hh * .45, hw, hh * .55);
  ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(hx - 5, hy + hh * .47); ctx.lineTo(hx + hw + 5, hy + hh * .47); ctx.lineTo(hx + hw - 5, hy); ctx.lineTo(hx + 5, hy); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#7a4a2a"; ctx.fillRect(p.x + p.w / 2 - 6, hy + hh - 16, 12, 16);
  const lit = SKY.dk > .15;
  ctx.fillStyle = lit ? "#ffd56b" : "#a9dcff"; ctx.fillRect(hx + 4, hy + hh - 16, 10, 8); ctx.fillRect(hx + hw - 14, hy + hh - 16, 10, 8);
  if (lit) lights.push({x: p.x + p.w / 2, y: hy + hh - 12, r: 40, warm: .8});
  emoji(p.icon, p.x + p.w / 2, hy + 8, 11);
  ctx.font = `800 8px ${FONT}`; ctx.fillStyle = "#3a2a1c"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
  ctx.fillText(p.agent.toUpperCase(), p.x + p.w / 2, p.y + p.h - 3);
}
function drawTree(tr, t) {
  const sway = Math.sin(t / 1100 + tr.i) * 1.4;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(tr.x + 5, tr.y, 18, 6, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#7a4f2c"; ctx.fillRect(tr.x - 3, tr.y - 16, 6, 16);
  const c = {green: ["#3f9a45", "#56b55a", "#79cf6c"], dark: ["#2f7a3c", "#3f9248", "#5bae5c"]}[tr.kind];
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
function drawFlag(t) {   // a penalty flag on the field while a sheet still has tags to fix
  if (!shown.flagged) return;
  const x = FIELD.x + 70, y = FIELD.y + 44;
  ctx.fillStyle = "rgba(0,0,0,.2)"; ctx.beginPath(); ctx.ellipse(x + 2, y + 6, 9, 3, 0, 0, 7); ctx.fill();
  ctx.fillStyle = "#facc15"; ctx.save(); ctx.translate(x, y); ctx.rotate(Math.sin(t / 700) * .08);
  ctx.beginPath(); ctx.moveTo(-8, -2); ctx.lineTo(8, -4); ctx.lineTo(6, 6); ctx.lineTo(-7, 5); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(0, 1, 2.5, 0, 7); ctx.fill(); ctx.restore();
  outlinedText(`${shown.flagged} to fix`, x, y - 12, 9, "#fde68a");
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
  if (a.hat === "stripes") {   // the Ref's striped shirt
    ctx.save(); ctx.beginPath(); ctx.ellipse(x, by, 13, 12.5, 0, 0, 7); ctx.clip();
    ctx.fillStyle = "#1d1426"; for (let sx = -12; sx <= 12; sx += 6) ctx.fillRect(x + sx - 1.2, by + 4, 2.4, 10);
    ctx.restore();
  }
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
  if (a.hat === "cap" || a.hat === "headset") {   // Captain's green ball cap, with a headset like on the sideline
    ctx.fillStyle = GREEN; ctx.beginPath(); ctx.ellipse(x, by - 9, 11, 6, 0, Math.PI, 0); ctx.fill();
    ctx.fillRect(f > 0 ? x + 4 : x - 14, by - 10, 10, 2.6);
    ctx.fillStyle = GOLD; ctx.beginPath(); ctx.arc(x, by - 12, 1.8, 0, 7); ctx.fill();
    if (a.hat === "headset") {
      ctx.strokeStyle = "#1d1426"; ctx.lineWidth = 1.5; ctx.beginPath(); ctx.arc(x, by - 4, 13, Math.PI * 1.1, Math.PI * 1.9); ctx.stroke();
      ctx.fillStyle = "#1d1426"; ctx.fillRect(x - 14, by - 6, 3, 6); ctx.fillRect(x + 11, by - 6, 3, 6);
    }
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
function drawWater(t) {
  ctx.strokeStyle = "rgba(255,255,255,.45)"; ctx.lineWidth = 1.5;
  for (let i = 0; i < 9; i++) {
    const y = (i * 47 + t / 40) % H;
    if (Math.abs(y - ROAD_Y) < 26) continue;
    const x = creekEdge(y) / 2 - 4;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 2 + Math.sin(t / 500 + i) * 2, y + 9); ctx.stroke();
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
    } else if (p.kind === "text") outlinedText(p.text, p.x, p.y, p.size, p.color);
    else if (p.kind === "emoji") emoji(p.text || p.color, p.x, p.y, p.size || 12);
  }
  ctx.globalAlpha = 1;
  for (const f of flyers) {
    const k = Math.min(1, f.t / f.dur), e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    const x = lerp(f.from.x, f.to.x, e), y = lerp(f.from.y, f.to.y, e) - Math.sin(k * Math.PI) * f.arc;
    emoji(f.emoji, x, y, 14, f.emoji === "🏈" ? k * Math.PI * 4 : Math.sin(k * Math.PI * 2) * .3);
  }
}
function drawLightsAndDark(t) {
  if (!kit.night(ctx, cam, dark, SKY, lights, t)) return;
  ctx.globalCompositeOperation = "lighter";
  for (const l of lights) {
    const g = ctx.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.r * .6);
    g.addColorStop(0, `rgba(255,190,90,${.28 * SKY.dk * (l.warm || 1)})`); g.addColorStop(1, "rgba(0,0,0,0)");
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
  drawWater(t);
  const pending = Math.max(0, shown.pending - deliveriesOnTheWay);
  drawBuildings(t, pending);
  drawFlag(t);
  const things = [
    ...TREES.map(o => ({y: o.y, d: () => drawTree(o, t)})),
    ...LAMPS.map(o => ({y: o.y, d: () => drawLamp(o)})),
    ...COTTAGES.map(o => ({y: o.y + 40, d: () => drawCottage(o)})),
    ...TOWERS.map(o => ({y: o.y, d: () => drawTower(o)})),
    {y: FIELD.y + FIELD.h / 2, d: () => { drawGoalpost(FIELD.x + 2, t); drawGoalpost(FIELD.x + FIELD.w - 2, t); }},
    {y: TENT.y + TENT.h, d: () => drawTent(t)},
    ...[...agents.values()].map(a => ({y: a.y, d: () => drawAgent(a, t)})),
  ].sort((p, q) => p.y - q.y);
  for (const th of things) th.d();
  drawParticles();
  drawSkyLife(t);
  if (SKY.dk > .15) lights.push({x: FIELD.x + FIELD.w * .3, y: FIELD.y + FIELD.h / 2, r: 190, warm: .5},
                                {x: FIELD.x + FIELD.w * .7, y: FIELD.y + FIELD.h / 2, r: 190, warm: .5});
  drawLightsAndDark(t);
  drawNames();
  if (pending > 0) {
    const y = B.mail.y - 14 + Math.sin(t / 220) * 4;
    ctx.fillStyle = "#ffd34d"; ctx.beginPath(); ctx.arc(B.mail.door, y, 10, 0, 7); ctx.fill();
    ctx.strokeStyle = "#b8860b"; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.font = `900 14px ${FONT}`; ctx.fillStyle = "#4a2a00"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText("!", B.mail.door, y + 1);
  }
  for (const a of agents.values()) drawBubble(a, t);
}

// ---------- simulation ----------
function tick(dt, now) {
  for (const a of agents.values()) { think(a, now); step(a, dt, now); }
  cam.tick(dt);
  mailBump = Math.max(0, mailBump - dt * 2);
  boardGlow = Math.max(0, boardGlow - dt * .7);
  for (const c of clouds) { c.x += 9 * dt; if (c.x > W + 160) { c.x = -160; c.y = rnd(40, H - 40); } }
  for (const f of fireflies) {
    f.vx = clamp(f.vx + rnd(-20, 20) * dt, -12, 12); f.vy = clamp(f.vy + rnd(-20, 20) * dt, -10, 10);
    f.x = 40 + ((f.x - 40 + f.vx * dt + (W - 40)) % (W - 40)); f.y = clamp(f.y + f.vy * dt, 40, H - 4);
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
  const el = document.getElementById("fbcountdown"), w = shown.week;
  if (!el || !w) return;
  el.textContent = w.season_over ? "🏁 Season over" : w.days_to_game === 0 ? `🏟️ Game day vs ${w.game.opponent}`
    : `🏈 ${w.game.opponent} in ${w.days_to_game} day${w.days_to_game === 1 ? "" : "s"}`;
}
const toWorld = e => cam.toWorld(e.clientX, e.clientY);
function hit(p) {
  for (const a of agents.values()) if (!a.sleeping && Math.hypot(p.x - a.x, p.y - (a.y - 14)) < 18) return {agent: a};
  for (const [k, b] of Object.entries(B)) if (p.x > b.x - 8 && p.x < b.x + b.w + 8 && p.y > b.y - 10 && p.y < b.y + b.h + 4) return {building: k};
  if (Math.hypot(p.x - MAILBOX.x, p.y - (MAILBOX.y - 18)) < 18) return {building: "mail"};
  if (p.x > BOARD.x - 4 && p.x < BOARD.x + BOARD.w + 4 && p.y > BOARD.y - 4 && p.y < BOARD.y + BOARD.h + 30) return {building: "board"};
  if (p.x > FIELD.x && p.x < FIELD.x + FIELD.w && p.y > FIELD.y && p.y < FIELD.y + FIELD.h) return {building: "field"};
  for (const c of COTTAGES) if (p.x > c.x && p.x < c.x + c.w && p.y > c.y && p.y < c.y + c.h) return {cottage: c};
  if (p.x < CREEK + 22 && Math.abs(p.y - ROAD_Y) < 22) return {building: "bridge"};
  if (p.x > TENT.x - 4 && p.y > TENT.y - 4 && p.y < CORNHOLE.y + 6) return {building: "tent"};
  return null;
}
function boardTip() {
  const w = shown.week;
  if (!w) return "Scoreboard";
  if (w.season_over) return "Scoreboard: the season is over.";
  const done = w.checklist.filter(x => x.state === "done").length;
  return `Scoreboard: ${w.game.opponent}, ${w.game.day} ${w.game.date.slice(5).replace("-", "/")}${w.game.confirmed ? "" : " (date not confirmed)"}. ` +
         `${done} of ${w.checklist.length} done${w.late.length ? `, ${w.late.length} late` : ""}. Click for the checklist.`;
}
const TIPS = {
  film: "Film Room: Captain runs Warrior Village from here. Click to talk to the Boss, who hands football work to Captain.",
  mail: () => `Coaches' Mailroom: ${shown.pending} football item${shown.pending === 1 ? "" : "s"} waiting for your OK. Click to approve or reject right here.`,
  press: "Press Box: where you chart on game day.",
  tent: "Warrior Village tailgate: where the agents take a cornhole break.",
  board: boardTip,
  field: "Tom Adams Field: drop tagging sheets in the football Inbox and Ref checks them. Click to see your sheets.",
  bridge: "The footbridge to HQ Town. Both villages share the Boss.",
};
const tip = document.getElementById("fbtip");
canvas.addEventListener("mousemove", e => {
  if (canvas.classList.contains("dragging")) { if (tip) tip.style.display = "none"; return; }
  const h = hit(toWorld(e));
  canvas.style.cursor = h ? "pointer" : "";
  if (!tip) return;
  let text = "";
  if (h?.agent) text = `${h.agent.name}: ${h.agent.busy ? "working on " + h.agent.busy : h.agent.role || ""}`;
  else if (h?.building) { const v = TIPS[h.building]; text = typeof v === "function" ? v() : v; }
  else if (h?.cottage) text = `${h.cottage.agent}'s cottage. Click for ${h.cottage.agent}'s card.`;
  tip.textContent = text;
  tip.style.display = text ? "block" : "none";
  if (text) {
    const rc = canvas.getBoundingClientRect();
    tip.style.left = clamp(e.clientX - rc.left + 14, 4, rc.width - 230) + "px";
    tip.style.top = clamp(e.clientY - rc.top + 14, 4, rc.height - 60) + "px";
  }
});
canvas.addEventListener("mouseleave", () => { if (tip) tip.style.display = "none"; });

// Clicks open a card on the stage, like in HQ Town: agents, the Mailroom (approve right there), the scoreboard's
// checklist and the sheets on the field.
function live(name, act) {
  const a = agents.get(String(name).toLowerCase());
  if (a && act === "follow") {
    wake(a);
    cam.lookAt(a.x, a.y - 20, Math.max(cam.zoom, 2.2));
    cam.follow = () => agents.get(a.key) === a ? a : null;
  }
  return a;
}
const STATE_PILL = {done: "on", late: "bad", due: "warn"};
function boardCard() {
  kit.infoCard("board", () => {
    const w = (kit.state() || {}).football?.week;
    if (!w) return null;
    if (w.season_over) return {color: "#0C5449", icon: "🏁", title: "Season over", html: `<p>Great work this year 🏈</p>`, buttons: []};
    const g = w.game, list = w.checklist || [];
    return {color: "#0C5449", icon: "🏈", title: `${g.opponent}, ${g.day} ${g.date.slice(5).replace("-", "/")}`,
      sub: `${w.days_to_game === 0 ? "Game day" : `${w.days_to_game} day${w.days_to_game === 1 ? "" : "s"} to go`}${g.confirmed ? "" : " · date not confirmed"}`,
      html: `<h4>This week's checklist</h4><ul class="feed">${list.map(x => `<li><span class="pill ${STATE_PILL[x.state] || ""}">${kit.esc(x.state)}</span>
        ${kit.esc(x.item)} <span>${kit.esc(x.due_day || "")}</span></li>`).join("")}</ul>`,
      buttons: [{act: "clock", label: "⏰ Clock's card"}, {act: "open", label: "Open the checklist ↗", kind: "ghost"}],
      acts: {clock: () => kit.agentCard("Clock", live), open: () => kit.goTab("football", "fbweek")}};
  });
}
function fieldCard() {
  kit.infoCard("field", () => {
    const fb = (kit.state() || {}).football || {}, files = (fb.files || []).slice(0, 6);
    return {color: "#3f9a4a", icon: "🏟️", title: "Tom Adams Field", sub: "Your tagged sheets",
      html: files.length ? `<ul class="feed">${files.map(f => `<li><span class="pill ${f.status === "checked" ? (f.fix ? "bad" : "on") : ""}">${f.status === "checked" ? (f.fix ? `${f.fix} to fix` : "clean") : kit.esc(f.status)}</span>
          ${kit.esc(f.name)}</li>`).join("")}</ul>`
        : `<p class="muted">No sheets yet. Drop a Hudl export or practice sheet in the football Inbox and Ref checks the tags.</p>`,
      buttons: [{act: "ref", label: "🚩 Ref's card"}, {act: "open", label: "Open sheets ↗", kind: "ghost"}],
      acts: {ref: () => kit.agentCard("Ref", live), open: () => kit.goTab("football", "fbfiles")}};
  });
}
canvas.addEventListener("click", e => {
  if (cam.dragged) return;
  const h = hit(toWorld(e));
  kit.at(e);
  if (!h) { kit.closeCard(); return; }
  if (h.agent) {
    const a = h.agent;
    a.jumpT = .5;
    burst(a.x, a.y - 30, 6, "emoji", ["💚", "💛"], {min: 10, max: 40, g: -10});
    kit.agentCard(a.name, live);
  } else if (h.building === "mail") kit.approvalsCard("football");
  else if (h.building === "board") boardCard();
  else if (h.building === "field") fieldCard();
  else if (h.building === "film") kit.agentCard("Captain", live);
  else if (h.building === "tent") floatText(TENT.x + TENT.w / 2, TENT.y - 6, "Go Warriors! 🌭", "#fde68a", 12);
  else if (h.building === "press") floatText(B.press.door, B.press.y - 6, "Go Warriors! 💚💛", "#fde68a", 12);
  else if (h.building === "bridge") { if (kit.mode() === "fb") kit.setMode("hq"); else floatText(CREEK + 30, ROAD_Y - 30, "HQ Town is across the bridge ⬅️", "#e8ffd8", 11); }
  else if (h.cottage) kit.agentCard(h.cottage.agent, live);
});

// ---------- public API ----------
window.FootballTown = {
  update(s) {
    const fb = s.football;
    if (!fb) return;
    const list = (s.agents || []).filter(a => a.village === "football");
    const appr = (s.approvals || []).filter(a => a.village === "football");
    syncAgents(list);
    const state = {football: fb, approvals: appr};
    if (prev) react(state);
    chatter((s.activity || []).filter(r => agents.has(String(r.agent).toLowerCase())));
    const latest = fb.files.find(f => f.status === "checked");
    shown = {pending: appr.length, week: fb.week, flagged: latest?.fix || 0};
    prev = {approvals: appr.map(a => a.id), files: Object.fromEntries(fb.files.map(f => [f.id, f.status])), loaded: true,
            week: fb.week, notes: fb.notes_total, outbox: fb.outbox.length};
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

// The Etsy Village panel under Print Street: what needs you, the team, the product board (every shirt, with its
// preview, price and Warden's notes), research and the trend brief, orders and your Etsy sales file, and the rules.
// The dashboard calls HQEtsy.update(state) on each refresh.
(function () {
  const root = document.getElementById("etsy");
  if (!root) return;
  const css = `
    #etsy { display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:0 22px 4px; position:relative; z-index:1; --pink:#f472b6; --plum:#7c2d5b; }
    #etsy .ehead { grid-column:1 / -1; display:flex; align-items:center; gap:10px; flex-wrap:wrap; padding:10px 16px; border-radius:var(--radius);
                   background:linear-gradient(90deg, #7c2d5b, #4c1d3a); border:1px solid rgba(244,114,182,.45); box-shadow:inset 0 -3px 0 var(--pink); }
    #etsy .ehead h2 { margin:0; color:#fbcfe8; font-size:16px; } #etsy .ehead .sub { color:#fce7f3; font-size:13px; font-weight:700; }
    #etsy .ehead .muted { margin-left:auto; color:#f9d5e8; }
    #etsy section { background:linear-gradient(180deg, rgba(124,45,91,.32), var(--panel) 140px); border-color:rgba(244,114,182,.22); }
    #etsy h2 { color:#f9a8d4; }
    #etsy button:not(.ghost) { background:linear-gradient(135deg, #f472b6, #db2777); color:#fff; }
    #etsy button.ghost:hover, #etsy input:focus, #etsy textarea:focus, #etsy select:focus { border-color:var(--pink); }
    #etsy a { color:#f9a8d4; }
    #etsy .wide { grid-column:1 / -1; }
    #etsy .eagents { display:grid; grid-template-columns:repeat(6, 1fr); gap:12px; }
    #etsy .eagents .room { min-height:0; padding-bottom:40px; } #etsy .eagents .room .role { display:none; }
    @media (max-width:900px) { #etsy .eagents { grid-template-columns:repeat(3, 1fr); gap:8px; } }
    #etsy .todo { display:flex; gap:10px; align-items:center; padding:8px 2px; border-top:1px solid var(--line); font-size:14px; flex-wrap:wrap; }
    #etsy .todo:first-child { border-top:0; } #etsy .todo .grow { flex:1 1 220px; } #etsy .todo b { color:#fbcfe8; }
    #etsy .chips { display:flex; gap:6px; flex-wrap:wrap; margin:0 0 10px; }
    #etsy .chips button { padding:4px 10px; font-size:12px; border-radius:999px; }
    #etsy .chips button[aria-pressed="true"] { background:linear-gradient(135deg, #f472b6, #db2777); color:#fff; border-color:transparent; }
    #etsy .board { display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:12px; }
    #etsy .shirt { border:1px solid var(--line); border-radius:14px; padding:10px; background:rgba(255,255,255,.03); display:flex; flex-direction:column; gap:5px; }
    #etsy .shirt img { width:100%; border-radius:10px; background:#eee9e0; aspect-ratio:1200/720; object-fit:cover; }
    #etsy .shirt .blank { aspect-ratio:1200/720; border-radius:10px; display:grid; place-items:center; background:#2c2338; color:var(--muted); font-size:13px; }
    #etsy .shirt b { font-size:15px; } #etsy .shirt small { color:var(--muted); font-size:12px; }
    #etsy .shirt .row { display:flex; gap:6px; flex-wrap:wrap; } #etsy .shirt .row button, #etsy .shirt .row a { flex:1 1 auto; padding:6px 8px; font-size:12px; }
    #etsy .shirt .row a { text-align:center; text-decoration:none; border:1px solid var(--line); border-radius:10px; font-weight:800; color:var(--text); }
    #etsy .shirt .row a:hover { border-color:var(--pink); }
    #etsy .st { display:inline-block; border-radius:999px; padding:0 8px; font-size:11px; font-weight:800; margin-right:6px; background:#3a3046; color:var(--text); }
    #etsy .st.review, #etsy .st.ready { background:#fbbf24; color:#2a1a02; } #etsy .st.live { background:var(--good); color:#062b12; }
    #etsy .st.held { background:var(--bad); color:#fff; } #etsy .st.rejected, #etsy .st.retired { background:#1f1a28; color:var(--muted); }
    #etsy .warn { color:#fde68a; font-size:12px; } #etsy .bad { color:#fca5a5; font-size:12px; }
    #etsy .line { font-size:13px; padding:5px 0; border-top:1px solid var(--line); } #etsy .line:first-child { border-top:0; }
    #etsy .line .r { float:right; color:var(--muted); font-size:12px; }
    #etsy textarea { width:100%; min-height:80px; font-size:13px; margin:6px 0; }
    #etsy .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:6px 0; }
    #etsy .grid2 div { background:rgba(255,255,255,.04); border:1px solid var(--line); border-radius:10px; padding:6px 9px; }
    #etsy .grid2 b { display:block; font-size:18px; } #etsy .grid2 span { color:var(--muted); font-size:11px; }
    #etsy .drop { border:2px dashed var(--line); border-radius:12px; padding:12px; text-align:center; color:var(--muted); font-size:13px; margin:8px 0; }
    #etsy .drop label { color:#f9a8d4; cursor:pointer; text-decoration:underline; } #etsy .drop input { display:none; }
    #etsy .msg { font-size:13px; margin-top:6px; white-space:pre-wrap; }
    #etsy .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    @media (max-width:960px) { #etsy { grid-template-columns:1fr; padding:0 14px 4px; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const toast = html => window.toast ? window.toast(html) : null;
  const refresh = () => window.hqRefresh?.();
  const usd = n => "$" + (+n || 0).toFixed(2);
  const words = s => String(s || "").replace(/\s*\/\s*/g, " ");
  const STAGE = {written: "written", drawn: "drawn", review: "needs your OK", approved: "approved", building: "building", ready: "ready to publish",
                 live: "live", retired: "retired", held: "held by Warden", rejected: "skipped"};
  const FILTERS = [["active", "Working on"], ["review", "Your OK"], ["ready", "Ready to publish"], ["live", "Live"], ["held", "Held"], ["all", "All"]];

  root.innerHTML = `
    <div class="ehead"><h2>🛍️ Etsy Village</h2><span class="sub">Print Street · shirt designs on Etsy, printed and shipped by Printify</span><span class="muted" id="espend"></span></div>
    <section id="etsyyou" class="wide"><h2>What needs you <span class="count" id="eyoucount"></span></h2><div id="eyou"></div></section>
    <section id="etsyteam" class="wide"><h2>The shop team</h2><div class="eagents" id="eagents"></div></section>
    <section id="etsyboard" class="wide"><h2>Product board <span class="count" id="eboardcount"></span></h2>
      <div class="chips" id="efilter">${FILTERS.map(([k, l]) => `<button class="ghost" data-f="${k}" aria-pressed="false">${l}</button>`).join("")}</div>
      <div class="board" id="eboard"></div></section>
    <section id="etsyresearch"><h2>Research and the trend brief</h2><div id="ebrief"></div>
      <h3 style="margin:12px 0 4px;font-size:14px">Add what you saw</h3>
      <textarea id="enote" placeholder="Paste anything useful: Etsy search bar suggestions you saw, a trend, a shirt idea in your own words. Radar reads it in the next brief."></textarea>
      <div class="row"><button id="enotesave">Save for Radar</button><button class="ghost" id="eradar">📡 New brief now</button></div>
      <h3 style="margin:14px 0 4px;font-size:14px">Ask for shirts on a theme</h3>
      <form class="row" id="equillform"><input id="etheme" placeholder="e.g. nurses, fishing dads, fall teachers" autocomplete="off" style="flex:1 1 200px"><button>✒️ Write 3</button></form>
      <div class="msg muted" id="eresmsg"></div></section>
    <section id="etsyorders"><h2>Orders and sales</h2><div id="eorders"></div>
      <div class="drop">Load your Etsy sales file: Shop Manager › Settings › Options › Download Data › Orders (Order Items CSV).<br>
        <label>Choose the CSV<input type="file" id="estats" accept=".csv,text/csv"></label></div>
      <div class="msg muted" id="estatsmsg"></div></section>
    <section id="etsyrules" class="wide"><h2>Rules, pace and money</h2><div id="erules"></div></section>`;
  const $ = id => document.getElementById(id);
  let data = null, filter = "active";
  try { filter = localStorage.getItem("hq-etsy-filter") || "active"; } catch (e) {}
  const shown = {};
  const changed = (key, value) => { const s = JSON.stringify(value); if (shown[key] === s) return false; shown[key] = s; return true; };

  async function post(url, body, isForm) {
    const opts = {method: "POST", headers: {"X-HQ": "1"}};
    if (isForm) opts.body = body;
    else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body ?? {}); }
    let r;
    try { r = await fetch(url, opts); } catch (e) { return {ok: false, message: "Couldn't reach HQ. Is it running?"}; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return {ok: false, message: typeof j.detail === "string" ? j.detail : "That didn't work."};
    return {ok: true, ...j};
  }
  async function act(url, body) {
    const r = await post(url, body);
    toast(esc(r.ok ? r.message : "😬 " + r.message));
    for (const k in shown) shown[k] = null;
    refresh();
    return r;
  }

  // ---- what needs you ----
  function drawYou(e, approvals) {
    const ready = e.designs.filter(d => d.stage === "ready"), orders = (e.orders || []).filter(o => ["on-hold", "pending"].includes(o.status));
    const c = e.connections || {}, items = [];
    if (!c.claude) items.push(`<div class="todo"><span class="grow">🔑 <b>Add your Claude key</b> so Radar and Quill can research and write shirts. Without it you get the free holiday brief only.</span><a href="/settings">Settings ›</a></div>`);
    if (!c.printify) items.push(`<div class="todo"><span class="grow">🔌 <b>Connect Printify</b>: Printify › My account › Connections › API tokens, then paste it in Settings (Etsy Village). Also turn on manual order approval in Printify.</span><a href="/settings#g-etsy">Settings ›</a></div>`);
    if (approvals.length) items.push(`<div class="todo"><span class="grow">👀 <b>${approvals.length} new shirt${approvals.length === 1 ? "" : "s"}</b> waiting for your OK (the first few always are).</span><button data-approvals>Look now</button></div>`);
    for (const d of ready.slice(0, 5)) items.push(`<div class="todo"><span class="grow">🚚 <b>${esc(words(d.slogan))}</b> is in Printify. ${d.photo_added ? "Photo added ✓." : "Add a real photo of your sample,"} then press Publish there.</span>
      <button class="ghost" data-photo="${d.id}">${d.photo_added ? "📸 Photo ✓" : "📸 Photo added"}</button><a href="https://printify.com/app/products" target="_blank" rel="noopener">Printify ›</a></div>`);
    if (ready.length > 5) items.push(`<div class="todo"><span class="grow">…and ${ready.length - 5} more ready to publish on the board.</span></div>`);
    if (orders.length) items.push(`<div class="todo"><span class="grow">📦 <b>${orders.length} order${orders.length === 1 ? "" : "s"}</b> waiting: check each in Printify and press Send to production. HQ never does that step.</span><a href="https://printify.com/app/orders" target="_blank" rel="noopener">Orders ›</a></div>`);
    if (!changed("you", items)) return;
    $("eyoucount").textContent = items.length || "";
    $("eyou").innerHTML = items.join("") || `<div class="muted">Nothing needs you right now. The team keeps making shirts on its own.</div>`;
    $("eyou").querySelector("[data-approvals]")?.addEventListener("click", () => { window.hqTabs?.show("approvals"); window.hqShowApprovals?.("etsy"); });
    $("eyou").querySelectorAll("[data-photo]").forEach(b => b.onclick = () => act(`/api/etsy/designs/${b.dataset.photo}/photo`));
  }

  // ---- the board ----
  const inFilter = d => filter === "all" ? true : filter === "active" ? ["written", "drawn", "review", "approved", "building"].includes(d.stage) : d.stage === filter;
  function shirtCard(d) {
    const w = d.warden || {}, problems = w.problems || [], warnings = w.warnings || [];
    const btn = (a, label, ghost = true) => `<button class="${ghost ? "ghost" : ""}" data-a="${a}" data-id="${d.id}">${label}</button>`;
    const buttons = [];
    if (d.stage === "review") buttons.push(btn("approve", "✅ Build it", false), btn("reject", "Skip"));
    if (["written", "drawn", "review", "held", "approved"].includes(d.stage)) buttons.push(btn("edit", "✏️ Edit"));
    if (["drawn", "review", "held"].includes(d.stage)) buttons.push(btn("redraw", "🎨 Redraw"));
    if (d.stage === "held") buttons.push(btn("reject", "Skip"));
    if (["ready", "live"].includes(d.stage)) buttons.push(btn("photo", d.photo_added ? "📸 Photo ✓" : "📸 Photo added"), btn("retire", "Retire"));
    if (d.has_preview) buttons.push(`<a class="ghost" href="/api/etsy/designs/${d.id}/file/dark" title="Print file for light shirts">⬇ Dark ink</a>`,
                                    `<a class="ghost" href="/api/etsy/designs/${d.id}/file/light" title="Print file for dark shirts">⬇ Light ink</a>`);
    buttons.push(btn("listing", "📋 Listing"));
    return `<div class="shirt">${d.has_preview ? `<img src="/api/etsy/designs/${d.id}/file/preview?v=${encodeURIComponent(d.updated_at)}" alt="" loading="lazy">` : `<div class="blank">Loom draws it next</div>`}
      <div><span class="st ${esc(d.stage)}">${esc(STAGE[d.stage] || d.stage)}</span>${d.ai_art ? `<span class="st">AI art</span>` : ""}</div>
      <b>${esc(words(d.slogan))}</b>${d.subline ? `<small>${esc(d.subline)}</small>` : ""}
      <small>${esc(d.theme)} · ${usd(d.price)} · about ${usd(d.profit_each)} profit each${d.sales ? ` · <b style="color:#86efac">${d.sales} sold</b>` : ""}</small>
      ${problems.map(p => `<div class="bad">🛑 ${esc(p)}</div>`).join("")}${warnings.map(p => `<div class="warn">⚠️ ${esc(p)}</div>`).join("")}
      ${d.note ? `<small>${esc(d.note)}</small>` : ""}
      <div class="row">${buttons.join("")}</div></div>`;
  }
  function drawBoard(e) {
    const list = e.designs.filter(inFilter);
    if (!changed("board", [filter, list.map(d => [d.id, d.stage, d.updated_at, d.photo_added, d.sales])])) return;
    $("efilter").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", b.dataset.f === filter));
    $("eboardcount").textContent = e.designs.length || "";
    $("eboard").innerHTML = list.slice(0, 60).map(shirtCard).join("") ||
      `<div class="muted">${e.designs.length ? "No shirts in this view." : "No shirts yet. Radar makes a brief, Quill writes shirts for it, and Loom draws them here, all on their own."}</div>`;
  }
  $("efilter").addEventListener("click", ev => {
    const b = ev.target.closest("button[data-f]");
    if (!b) return;
    filter = b.dataset.f;
    try { localStorage.setItem("hq-etsy-filter", filter); } catch (e) {}
    shown.board = null;
    if (data) drawBoard(data);
  });
  $("eboard").addEventListener("click", async ev => {
    const b = ev.target.closest("button[data-a]");
    if (!b || !data) return;
    const id = +b.dataset.id, d = data.designs.find(x => x.id === id), a = b.dataset.a;
    if (!d) return;
    if (a === "listing") {
      const r = await fetch(`/api/etsy/designs/${id}/listing`).then(x => x.json()).catch(() => null);
      if (!r) return;
      const text = `${r.title}\n\nTags: ${r.tags.join(", ")}\n\n${r.description}\n\nPrice: ${usd(r.price)}`;
      try { await navigator.clipboard.writeText(text); toast("📋 Listing text copied"); } catch (e) { prompt("Copy the listing text:", text); }
      return;
    }
    if (a === "edit") {
      const slogan = prompt("Words on the shirt (use / for a new line):", d.slogan);
      if (slogan === null) return;
      const title = prompt("Etsy title (up to 140 characters):", d.title);
      if (title === null) return;
      const price = prompt("Price in dollars:", d.price.toFixed(2));
      if (price === null) return;
      const style = prompt("Look: bold, retro, script, marker or badge", d.style);
      if (style === null) return;
      await act(`/api/etsy/designs/${id}/edit`, {slogan, title, price: parseFloat(price) || d.price, style: style.trim().toLowerCase()});
      return;
    }
    if (a === "retire" && !confirm(`Retire "${words(d.slogan)}"? If it's live, also deactivate it on Etsy yourself.`)) return;
    b.disabled = true;
    await act(`/api/etsy/designs/${id}/${a}`);
  });

  // ---- research ----
  function drawBrief(e) {
    if (!changed("brief", [e.brief?.id, e.holidays, e.notes?.length])) return;
    const b = e.brief, hol = (e.holidays || []).slice(0, 4);
    $("ebrief").innerHTML = (b ? `<div class="muted" style="margin-bottom:6px">${b.source === "radar" ? "Radar's web research" : "The free holiday-and-evergreen brief"}${b.note ? `: ${esc(b.note)}` : ""}</div>
        ${b.themes.slice(0, 10).map(t => `<div class="line"><b>${esc(t.theme)}</b> <span class="r">${t.until ? "until " + esc(String(t.until).slice(5)) : "all year"}</span><br><span class="muted">${esc(t.why || t.audience || "")}</span></div>`).join("")}`
      : `<div class="muted">No brief yet. Radar makes one within a few minutes of HQ starting.</div>`) +
      (hol.length ? `<h3 style="margin:12px 0 4px;font-size:14px">Holidays coming</h3>${hol.map(h => `<div class="line">${esc(h.name)} <span class="r">${esc(h.date)} · ${h.late ? "late, still worth it" : "start by " + esc(h.start_by)}</span></div>`).join("")}` : "");
  }
  $("enotesave").onclick = async () => {
    const text = $("enote").value.trim();
    if (!text) return;
    const r = await post("/api/etsy/notes", {text});
    $("eresmsg").textContent = r.message;
    if (r.ok) $("enote").value = "";
  };
  $("eradar").onclick = async () => { const r = await post("/api/etsy/run/radar"); $("eresmsg").textContent = r.message; refresh(); };
  $("equillform").onsubmit = async ev => {
    ev.preventDefault();
    const theme = $("etheme").value.trim();
    if (!theme) return;
    const r = await post("/api/etsy/run/quill", {theme, count: 3});
    $("eresmsg").textContent = r.message;
    if (r.ok) $("etheme").value = "";
    refresh();
  };

  // ---- orders and sales ----
  function drawOrders(e) {
    const orders = e.orders || [];
    if (!changed("orders", [orders, e.money?.sales])) return;
    $("eorders").innerHTML = `<div class="grid2"><div><b>${e.money?.sales || 0}</b><span>shirts sold so far</span></div><div><b>${e.counts.live || 0}</b><span>live on Etsy</span></div></div>` +
      (orders.length ? orders.map(o => `<div class="line"><span class="st ${o.status === "on-hold" ? "review" : "live"}">${esc(o.status)}</span>${esc((o.items || []).map(i => `${i.quantity}× ${i.title}`).join(", "))}
          <span class="r">${usd((o.total_cents || 0) / 100)}${o.cost_cents ? ` · cost ${usd(o.cost_cents / 100)}` : ""}</span></div>`).join("")
        : `<div class="muted">No orders yet. Dock checks Printify every 30 minutes once it's connected.</div>`);
  }
  $("estats").onchange = async () => {
    const f = $("estats").files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await post("/api/etsy/stats", fd, true);
    $("estatsmsg").textContent = r.message;
    $("estats").value = "";
    if (r.ok) { shown.orders = null; refresh(); }
  };

  // ---- rules, pace and money ----
  function drawRules(e) {
    if (!changed("rules", [e.rules, e.pace, e.money, e.connections])) return;
    const p = e.pace || {}, m = e.money || {}, c = e.connections || {};
    const review = {auto: `the first 5, then only ones with warnings (you've approved ${p.you_approved})`, always: "every one", never: "only ones with warnings"}[p.review_mode] || p.review_mode;
    $("erules").innerHTML = `<div class="grid2">
        <div><b>${usd(m.today_usd)}</b><span>Claude and pictures today (cap ${m.budget_usd ? usd(m.budget_usd) : "none"})</span></div>
        <div><b>${usd(m.month_usd)}</b><span>this month (cap ${m.month_budget_usd ? usd(m.month_budget_usd) : "none"})</span></div>
        <div><b>${p.made_today || 0} / ${p.per_day}</b><span>new shirts today</span></div>
        <div><b>${p.waiting || 0} / ${p.max_waiting}</b><span>waiting before Quill pauses</span></div></div>
      <div class="line">You see ${esc(review)}. Change it in <a href="/settings#g-etsy">Settings</a>.</div>
      <div class="line">Pictures: ${c.images ? `on, ${usd(m.images_month_usd)} of ${usd(m.images_cap_usd)} this month` : "off (words-only designs are free). Add an OpenAI key in Settings to turn them on."}</div>
      <div class="line">Shirt cost for profit math: ${usd(m.shirt_cost)} (Etsy takes $0.20 a listing, 6.5% and about 3% + $0.25 a sale).</div>
      <h3 style="margin:12px 0 4px;font-size:14px">Warden's rules</h3>
      ${(e.rules || []).map(r => `<div class="line">${esc(r.rule)} <span class="r">${esc(r.source)} · checked ${esc(r.checked)}</span></div>`).join("")}`;
    $("espend").textContent = `${usd(m.today_usd)} today${m.over_budget ? " · budget used up, the team rests" : ""}`;
  }

  window.HQEtsy = {
    update(s) {
      const e = s.etsy;
      if (!e) return;
      data = e;
      const team = (s.agents || []).filter(a => a.village === "etsy");
      if (changed("team", team.map(a => [a.name, a.doing]))) $("eagents").innerHTML = window.hqRooms ? window.hqRooms(team) : team.map(a => `<div>${esc(a.name)}</div>`).join("");
      drawYou(e, (s.approvals || []).filter(a => a.village === "etsy"));
      drawBoard(e);
      drawBrief(e);
      drawOrders(e);
      drawRules(e);
    },
  };
})();

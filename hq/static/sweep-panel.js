// Sweep's tab: the janitor and quality control. On top, "How to improve HQ": a health score, the top three things to do,
// every other idea grouped by area, each with the one step to take, a link to where to take it, a one-tap fix where one
// is safe, and "Hide for a week". Below, what Claude costs, what Sweep tidied up by itself and the trash (every file
// Sweep moved can be put back for a week). Fetches /api/sweep by itself, so the dashboard needs no other wiring. It also
// tells HQ Town how much mess is open, so the village gets litter for Sweep to sweep up.
(function () {
  const root = document.getElementById("sweep");
  if (!root) return;
  const css = `
    #sweep { padding:0 22px 4px; position:relative; z-index:1; }
    #sweep section { margin-bottom:18px; background:linear-gradient(180deg, rgba(56,130,200,.16), var(--panel) 120px); }
    #sweep h2 { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    #sweep h2 .muted { margin-left:auto; font-weight:400; }
    #sweep .swgrid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
    #sweep .swline { font-size:14px; padding:6px 2px; border-top:1px solid var(--line); }
    #sweep .swline:first-child { border-top:0; }
    #sweep .swline.high b { color:#fca5a5; } #sweep .swline.medium b { color:#fde68a; }
    #sweep .swline .muted { display:block; margin-top:2px; }
    #sweep .swcost { font-size:15px; margin:0 0 10px; line-height:1.5; }
    #sweep .swcost b { font-variant-numeric:tabular-nums; }
    #sweep h3 { margin:14px 0 6px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
    #sweep .swtrash { display:flex; gap:8px; align-items:center; font-size:13px; padding:5px 2px; border-top:1px solid var(--line); }
    #sweep .swtrash span:first-child { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
    #sweep .swerr { color:var(--bad); font-size:13px; }
    #sweep .swhead { display:flex; gap:18px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }
    #sweep .swscore { --c:var(--good); width:92px; height:92px; flex:none; border-radius:50%; display:grid; place-items:center;
                      background:conic-gradient(var(--c) calc(var(--v) * 1%), rgba(255,255,255,.08) 0); }
    #sweep .swscore div { width:74px; height:74px; border-radius:50%; background:var(--panel2); display:grid; place-items:center;
                          text-align:center; line-height:1.05; }
    #sweep .swscore b { font-size:26px; font-variant-numeric:tabular-nums; } #sweep .swscore small { font-size:11px; color:var(--muted); }
    #sweep .swscore.mid { --c:var(--accent); } #sweep .swscore.low { --c:var(--bad); }
    #sweep .swsum { flex:1; min-width:220px; font-size:15px; line-height:1.5; }
    #sweep .swup { color:var(--good); font-weight:800; } #sweep .swdown { color:var(--bad); font-weight:800; }
    #sweep .swcoach { margin:10px 0 4px; padding:10px 14px; border-radius:12px; border:1px solid rgba(124,196,255,.35);
                      background:rgba(124,196,255,.08); font-size:14px; line-height:1.5; }
    #sweep .swcoach b { color:var(--sky); }
    #sweep .swtip { display:flex; gap:12px; padding:12px 2px; border-top:1px solid var(--line); }
    #sweep .swtip:first-child { border-top:0; }
    #sweep .swtip .dot { flex:none; width:10px; height:10px; margin-top:6px; border-radius:50%; background:var(--muted); }
    #sweep .swtip.high .dot { background:var(--bad); } #sweep .swtip.medium .dot { background:var(--accent); }
    #sweep .swtip .body { flex:1; min-width:0; }
    #sweep .swtip .t { font-weight:800; font-size:15px; }
    #sweep .swtip .why { color:var(--muted); font-size:13px; margin-top:3px; overflow-wrap:anywhere; }
    #sweep .swtip .do { font-size:14px; margin-top:6px; }
    #sweep .swtip .do::before { content:"Do this: "; font-weight:800; color:var(--accent); }
    #sweep .swtip .acts { display:flex; flex-wrap:wrap; gap:8px; margin-top:8px; align-items:center; }
    #sweep .swtip .acts a { font-size:13px; font-weight:800; color:var(--sky); text-decoration:none; }
    #sweep .swtip .acts .hide { margin-left:auto; font-size:12px; padding:4px 10px; }
    #sweep .swtip .age { font-size:12px; color:var(--muted); }
    #sweep .swtop { border:1px solid var(--line); border-radius:14px; padding:2px 14px; background:rgba(255,179,71,.05); }
    #sweep details { margin-top:6px; } #sweep summary { cursor:pointer; font-weight:800; padding:6px 0; color:var(--muted); }
    #sweep .swfixn { color:var(--accent); font-weight:700; }
    #sweep .swfixed { font-size:13px; color:var(--good); margin-top:8px; }
    #sweep .swunits { font-size:13px; color:var(--muted); margin-top:4px; }
    #sweep .swhist { font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; }
    @media (max-width:900px) { #sweep { padding:0 14px 4px; } #sweep .swgrid { grid-template-columns:1fr; }
                               #sweep .swtip .acts .hide { margin-left:0; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const AREAS = {organization: "🗂️ Organization", efficiency: "⚙️ Efficiency", quality: "🎯 Quality", money: "💸 Money"};
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const usd = n => "$" + Number(n || 0).toFixed(n >= 0.01 || !n ? 2 : 3);
  const size = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  let busy = "", err = "", shown = "", openAreas = new Set();

  async function call(url, method) {
    const r = await fetch(url, {method, headers: {"X-HQ": "1"}});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || "Something went wrong");
    return body;
  }

  function tipHtml(t) {
    const age = t.open_days >= 2 ? `<span class="age">open ${t.open_days} days</span>` : "";
    return `<div class="swtip ${esc(t.severity)}"><span class="dot" title="${esc(t.severity)}"></span><div class="body">
      <div class="t">${esc(t.title)}</div><div class="why">${esc(t.why)}</div><div class="do">${esc(t.do)}</div>
      <div class="acts">
        ${t.fix ? `<button data-fix="${esc(t.fix.id)}" ${busy ? "disabled" : ""}>${busy === t.fix.id ? "Working…" : "🧹 " + esc(t.fix.label)}</button>` : ""}
        ${t.link ? `<a href="${esc(t.link.href)}">${esc(t.link.label)} →</a>` : ""}
        ${age}
        <button class="ghost hide" data-hide="${esc(t.id)}" title="It comes back after a week if it's still true">Hide for a week</button>
      </div></div></div>`;
  }

  const fixes = list => { const n = list.filter(t => t.fix).length; return n ? ` <span class="swfixn">· 🧹 ${n} one-tap fix${n === 1 ? "" : "es"}</span>` : ""; };

  function improveHtml(d, imp) {
    const tips = imp.tips || [];
    const v = imp.score ?? 100;
    const band = v >= 80 ? "" : v >= 55 ? "mid" : "low";
    const ch = imp.change;
    const trend = ch ? (ch > 0 ? `<span class="swup">▲ ${ch}</span> since yesterday` : `<span class="swdown">▼ ${-ch}</span> since yesterday`) : "";
    const hist = (d.history || []).slice(-7).map(h => h.score);
    const highs = tips.filter(t => t.severity === "high").length;
    const top = tips.slice(0, 3), rest = tips.slice(3);
    const groups = {};
    rest.forEach(t => (groups[t.area] = groups[t.area] || []).push(t));
    const units = (imp.units || []).filter(u => u.each !== null);
    return `
      <div class="swhead">
        <div class="swscore ${band}" style="--v:${v}" role="img" aria-label="HQ health ${v} out of 100"><div><span><b>${v}</b><br><small>of 100</small></span></div></div>
        <div class="swsum">
          <b>HQ health</b> ${trend}<br>
          ${tips.length ? `${tips.length} idea${tips.length === 1 ? "" : "s"} to make HQ run better${highs ? `, <b>${highs} important</b>` : ""}.`
            : "Every agent's work looks clean today. ✨"}
          ${hist.length > 1 ? `<div class="swhist">Last ${hist.length} daily reports: ${hist.join(" → ")}</div>` : ""}
          ${imp.hidden ? `<div class="swhist">${imp.hidden} hidden for now. <button class="ghost" id="swunhide" style="font-size:12px;padding:2px 10px">Show them again</button></div>` : ""}
        </div>
      </div>
      ${imp.coach ? `<div class="swcoach"><b>Coach's note:</b> ${esc(imp.coach)}</div>` : ""}
      ${top.length ? `<h3>Top ${top.length} for today</h3><div class="swtop">${top.map(tipHtml).join("")}</div>` : ""}
      ${Object.keys(AREAS).filter(a => groups[a]).map(a => `<details data-area="${a}" ${openAreas.has(a) ? "open" : ""}>
          <summary>${AREAS[a]} · ${groups[a].length}${fixes(groups[a])}</summary>${groups[a].map(tipHtml).join("")}</details>`).join("")}
      ${(imp.fixed || []).length ? `<div class="swfixed">✓ Fixed since the last report: ${imp.fixed.map(esc).join("; ")}</div>` : ""}
      ${units.length ? `<div class="swunits">Claude cost per result this week: ${units.map(u => `${esc(u.agent)} ${usd(u.each)} per ${esc(u.unit)}`).join(" · ")}</div>` : ""}
      ${(imp.broken_checks || []).length ? `<div class="swerr">Some checks couldn't run: ${imp.broken_checks.map(esc).join("; ")}</div>` : ""}`;
  }

  function budgetsHtml(d) {
    const b = d.budgets || {};
    const rows = (b.agents || []).map(a => `<div class="swline ${a.state === "paused" ? "high" : a.state === "alert" ? "med" : ""}"><b>${esc(a.agent)}</b>
      <span class="muted">${usd(a.spent)} of ${usd(a.cap)} today (${a.pct}%)${a.state === "paused" ? " · paused until tomorrow" : a.state === "alert" ? " · over 80%" : ""}</span></div>`).join("");
    const rec = (b.receipts || []).slice(0, 8).map(r => `<div class="swline"><span title="${esc(r.summary || "")}">${r.status === "done" ? "✓" : "✗"} #${r.task_id} ${esc(r.agent)}
      · ${usd(r.cost_usd)} · ${esc(r.stop_reason)}</span></div>`).join("");
    return `<section><h2>💸 Agent budgets and run receipts <span class="muted">set in Settings under General</span></h2>
      <div class="swgrid"><div><h3>Daily limits</h3>${rows || `<div class="swline muted">No per-agent limits set. Add some like Chad=2, Scout=0.5 in Settings.</div>`}</div>
      <div><h3>Latest runs</h3>${rec || `<div class="swline muted">No finished runs yet.</div>`}</div></div></section>`;
  }

  function render(d) {
    const key = JSON.stringify(d) + busy + err;
    if (key === shown) return;
    shown = key;
    const rep = d.report;
    if (!rep) {
      root.innerHTML = `<section><h2>🧹 Sweep <span class="muted">janitor and quality control</span></h2>
        <p class="muted">Sweep has not made its first round yet. It tidies up and checks Claude's costs every few hours,
        and each day around ${d.hour}:00 it sends a "How to improve HQ" report here and to your phone.</p>
        <button id="swrun">Run a round now</button> <span class="swerr">${esc(err)}</span></section>`;
    } else {
      const s = rep.spend || {};
      const cap = s.budget ? ` of ${usd(s.budget)} budget` : "";
      root.innerHTML = `<section>
        <h2>🧹 How to improve HQ <span class="muted">Sweep's report · ${esc(rep.day)}</span></h2>
        ${improveHtml(d, rep.improve || {})}
        <p style="margin:14px 0 0"><button id="swrun" ${busy ? "disabled" : ""}>${busy === "run" ? "Checking…" : "Check again and send the report"}</button>
          <span class="swerr">${esc(err)}</span>
          <span class="muted"> One-tap fixes are small and safe. Sweep never posts, emails, spends or changes settings without asking you first.</span></p>
      </section>
      <section>
        <h2>💵 Costs and tidying <span class="muted">every 6 hours</span></h2>
        <p class="swcost">Claude cost: <b>${usd(s.yesterday)}</b> yesterday, <b>${usd(s.today)}</b> so far today${cap}.
          7-day average <b>${usd(s.week_avg)}</b>/day · this month <b>${usd(s.month)}</b> (on pace for ${usd(s.month_projected)}).
          ${(rep.by_agent || []).length ? `<br><span class="muted">Last 24 hours: ${rep.by_agent.slice(0, 5).map(a => esc(a.agent) + " " + usd(a.usd)).join(" · ")}</span>` : ""}</p>
        <div class="swgrid">
          <div>
            <h3>Costs to look at</h3>
            ${(rep.problems || []).length ? rep.problems.map(p => `<div class="swline ${esc(p.severity)}"><b>${esc(p.title)}</b><span class="muted">${esc(p.detail)}</span></div>`).join("")
              : `<div class="swline muted">Nothing is wasting money right now. ✨</div>`}
          </div>
          <div>
            <h3>Tidied up on its own</h3>
            ${(rep.actions || []).length ? rep.actions.slice().reverse().map(a => `<div class="swline">${esc(a)}</div>`).join("")
              : `<div class="swline muted">Nothing to tidy up yet.</div>`}
            ${(d.trash || []).length ? `<h3>In the trash (kept 7 days)</h3>` + d.trash.slice(-6).reverse().map(t =>
              `<div class="swtrash"><span title="${esc(t.why)}">${esc(t.name)} · ${size(t.bytes)}</span><button class="ghost" data-restore="${t.id}">Put back</button></div>`).join("") : ""}
          </div>
        </div>
      </section>` + budgetsHtml(d);
    }
    root.querySelectorAll("details[data-area]").forEach(el => el.addEventListener("toggle", () => {
      el.open ? openAreas.add(el.dataset.area) : openAreas.delete(el.dataset.area);
    }));
    root.querySelector("#swrun")?.addEventListener("click", async () => {
      busy = "run"; err = ""; render(d);
      try { await call("/api/sweep/run", "POST"); setTimeout(() => { busy = ""; load(); }, 6000); }
      catch (e) { busy = ""; err = e.message; render(d); }
    });
    const act = (sel, attr, url, mark) => root.querySelectorAll(sel).forEach(b => b.addEventListener("click", async () => {
      if (mark) { busy = b.dataset[attr]; render(d); }
      try { const r = await call(url + encodeURIComponent(b.dataset[attr]), "POST"); err = ""; window.toast?.("🧹 " + esc(r.message || "Done")); }
      catch (e) { err = e.message; }
      busy = ""; load();
    }));
    root.querySelector("#swunhide")?.addEventListener("click", async () => {
      try { for (const id of Object.keys(d.snoozed || {})) await call("/api/sweep/unhide/" + encodeURIComponent(id), "POST"); err = ""; }
      catch (e) { err = e.message; }
      load();
    });
    act("[data-fix]", "fix", "/api/sweep/fix/", true);
    act("[data-hide]", "hide", "/api/sweep/hide/", false);
    act("[data-restore]", "restore", "/api/sweep/restore/", false);
  }

  async function load() {
    try {
      const d = await (await fetch("/api/sweep")).json();
      render(d);
      window.HQWorld?.setMess?.(d.mess || 0);
    } catch (e) { /* the dashboard shows its own offline state */ }
  }
  load();
  setInterval(load, 60000);
})();

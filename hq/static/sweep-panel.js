// Sweep's card under the towns: today's Claude cost, what the janitor tidied up by itself, what needs a look, and the
// trash (every file Sweep moved can be put back for a week). Fetches /api/sweep by itself, so the dashboard needs no
// other wiring. It also tells HQ Town how much mess is open, so the village gets litter for Sweep to sweep up.
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
    #sweep h3 { margin:12px 0 4px; font-size:13px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }
    #sweep .swtrash { display:flex; gap:8px; align-items:center; font-size:13px; padding:5px 2px; border-top:1px solid var(--line); }
    #sweep .swtrash span:first-child { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
    #sweep .swerr { color:var(--bad); font-size:13px; }
    @media (max-width:900px) { #sweep { padding:0 14px 4px; } #sweep .swgrid { grid-template-columns:1fr; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const usd = n => "$" + Number(n || 0).toFixed(n >= 0.01 || !n ? 2 : 3);
  const size = n => n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";
  let busy = false, err = "", shown = "";

  async function call(url, method) {
    const r = await fetch(url, {method, headers: {"X-HQ": "1"}});
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || "Something went wrong");
    return body;
  }

  function render(d) {
    const key = JSON.stringify(d) + busy + err;
    if (key === shown) return;
    shown = key;
    const rep = d.report;
    if (!rep) {
      root.innerHTML = `<section><h2>🧹 Sweep <span class="muted">the janitor</span></h2>
        <p class="muted">Sweep has not made its first round yet. It tidies up and checks Claude's costs every few hours,
        and sends one report a day around ${d.hour}:00.</p>
        <button id="swrun">Run a round now</button> <span class="swerr">${esc(err)}</span></section>`;
    } else {
      const s = rep.spend || {};
      const cap = s.budget ? ` of ${usd(s.budget)} budget` : "";
      root.innerHTML = `<section>
        <h2>🧹 Sweep <span class="muted">the janitor · ${esc(rep.day)}</span></h2>
        <p class="swcost">Claude cost: <b>${usd(s.yesterday)}</b> yesterday, <b>${usd(s.today)}</b> so far today${cap}.
          7-day average <b>${usd(s.week_avg)}</b>/day · this month <b>${usd(s.month)}</b> (on pace for ${usd(s.month_projected)}).
          ${(rep.by_agent || []).length ? `<br><span class="muted">Last 24 hours: ${rep.by_agent.slice(0, 5).map(a => esc(a.agent) + " " + usd(a.usd)).join(" · ")}</span>` : ""}</p>
        <div class="swgrid">
          <div>
            <h3>Needs a look</h3>
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
        <p style="margin:12px 0 0"><button id="swrun" ${busy ? "disabled" : ""}>${busy ? "Sweeping…" : "Run a round and send the report"}</button>
          <span class="swerr">${esc(err)}</span>
          <span class="muted"> Sweep never posts, emails, spends or changes settings without asking you first.</span></p>
      </section>`;
    }
    root.querySelector("#swrun")?.addEventListener("click", async () => {
      busy = true; err = ""; render(d);
      try { await call("/api/sweep/run", "POST"); setTimeout(() => { busy = false; load(); }, 6000); }
      catch (e) { busy = false; err = e.message; render(d); }
    });
    root.querySelectorAll("[data-restore]").forEach(b => b.addEventListener("click", async () => {
      try { await call("/api/sweep/restore/" + b.dataset.restore, "POST"); err = ""; } catch (e) { err = e.message; }
      load();
    }));
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

// Pitch tab: "Today's 10", the daily send list. Queue counts today's drafted, approved and sent pitches against the goal,
// shows the best-fit drafts first, and each has Copy and Mark sent. Nothing is sent from here; you send it yourself.
(function () {
  const root = document.getElementById("queue");
  if (!root) return;
  const css = `
    #queue { padding:0 22px 4px; position:relative; z-index:1; }
    #queue section { margin-bottom:18px; }
    #queue h2 { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    #queue h2 .muted { margin-left:auto; font-weight:400; }
    #queue .qbar { height:10px; border-radius:999px; background:rgba(255,255,255,.08); overflow:hidden; margin:6px 0 10px; }
    #queue .qbar div { height:100%; background:linear-gradient(90deg, var(--accent), #ff8a5c); }
    #queue .qstats { display:flex; gap:18px; flex-wrap:wrap; font-size:14px; margin-bottom:10px; }
    #queue .qstats b { font-variant-numeric:tabular-nums; font-size:18px; }
    #queue .qlead { border-top:1px solid var(--line); padding:12px 2px; }
    #queue .qlead .t { font-weight:800; } #queue .qlead pre { white-space:pre-wrap; font:inherit; font-size:14px; margin:6px 0; color:var(--muted); }
    #queue .qlead .acts { display:flex; gap:8px; flex-wrap:wrap; }
    #queue .qpaused { padding:10px 14px; border-radius:12px; border:1px solid var(--line); background:rgba(255,179,71,.08); }
    @media (max-width:900px) { #queue { padding:0 14px 4px; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  let data = null, msg = "";

  function render() {
    const d = data, n = d.show.length;
    const leads = d.show.map(l => `<div class="qlead"><div class="t">${esc(l.name)} <span class="muted">${esc(l.platform)} · fit ${l.score ?? "?"}/10${l.score_why ? " · " + esc(l.score_why) : ""}</span></div>
      <div class="muted">${esc(l.contact || "")}</div><pre>${esc(l.pitch)}</pre>
      <div class="acts"><button class="ghost" data-copy="${l.id}">Copy</button><button data-sent="${l.id}">Mark sent</button></div></div>`).join("");
    root.innerHTML = `<section><h2>📋 Today's ${d.goal} <span class="muted">Queue · best fit first</span></h2>
      ${d.paused ? `<div class="qpaused"><b>Pitch paused.</b> No new drafts and no texts until you turn off Pause Pitch emails in Settings. Drafts already waiting are below.</div>` : ""}
      <div class="qbar"><div style="width:${Math.min(100, 100 * d.sent / d.goal)}%"></div></div>
      <div class="qstats"><span><b>${d.sent}</b> of ${d.goal} sent</span><span><b>${d.drafted}</b> drafted today</span><span><b>${d.approved}</b> approved today</span>
        <span><b>${d.ready_count}</b> ready</span>
        ${d.reply_rate ? `<span><b>${d.reply_rate.percent}%</b> replied (${d.reply_rate.replied} of ${d.reply_rate.sent} sent)</span>` : `<span class="muted">Reply rate shows after a week of sending</span>`}</div>
      ${d.short_by && !d.paused ? `<div class="muted">${d.short_by} short of today's goal. Weak leads are never added to fill it.</div>` : ""}
      ${msg ? `<div class="muted">${esc(msg)}</div>` : ""}
      ${leads || `<div class="muted">${d.left ? "No drafts ready." : "Goal reached. Nice."}</div>`}
      ${d.more ? `<div class="muted" style="padding-top:8px">${d.more} more waiting for tomorrow.</div>` : ""}</section>`;
    root.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
      const l = d.show.find(x => x.id == b.dataset.copy);
      try { await navigator.clipboard.writeText(l.pitch); b.textContent = "Copied"; } catch { b.textContent = "Copy failed"; }
    });
    root.querySelectorAll("[data-sent]").forEach(b => b.onclick = async () => {
      b.disabled = true;
      const r = await fetch("/api/queue/sent/" + b.dataset.sent, {method: "POST", headers: {"X-HQ": "1"}});
      msg = (await r.json().catch(() => ({}))).message || "Something went wrong";
      load();
    });
  }
  async function load() {
    try { data = await (await fetch("/api/queue")).json(); render(); } catch { /* try again next minute */ }
  }
  load();
  setInterval(load, 60000);
})();

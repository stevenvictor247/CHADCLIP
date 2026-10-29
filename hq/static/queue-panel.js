// Queue's "Today's 10" screen on the Pitch tab: the day's count against the goal, the best unsent drafts first, a Copy and a
// Mark sent button on each. Nothing is sent from here: Steven sends each pitch himself, then taps Mark sent.
(function () {
  const root = document.getElementById("queue");
  if (!root) return;
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const css = `#queue { padding:0 22px 4px; position:relative; z-index:1; } #queue section { margin-bottom:18px; }
    #queue .qrow { padding:10px 2px; border-top:1px solid var(--line); } #queue .qrow:first-of-type { border-top:0; }
    #queue pre { white-space:pre-wrap; font:inherit; font-size:13px; margin:6px 0; max-height:7.5em; overflow:auto; }
    #queue .qbtns { display:flex; gap:8px; }`;
  root.innerHTML = `<style>${css}</style><section><h2>Today's 10</h2><div id="queue-body" class="muted">Loading…</div></section>`;
  const body = document.getElementById("queue-body");
  let drafts = [];
  async function load() {
    try {
      const q = await (await fetch("/api/queue")).json();
      drafts = q.drafts;
      const rate = q.reply_rate ? ` · ${q.reply_rate.replied} of ${q.reply_rate.sent} replied (${q.reply_rate.rate}%)` : "";
      let h = `<p><b>${q.sent}/${q.goal} sent</b> · ${q.approved} approved · ${q.drafted} drafted today${rate}</p>`;
      if (q.short_by) h += `<p class="swerr">${q.short_by} short of ${q.goal}: Pitch needs more leads.</p>`;
      h += drafts.length ? drafts.map((d, i) => `<div class="qrow"><b>${esc(d.name)}</b> (${esc(d.platform)}) · score ${d.score == null ? "?" : d.score}/10
        <span class="muted">${esc(d.score_why || "")}</span><pre>${esc(d.pitch)}</pre>
        <div class="qbtns"><button data-copy="${i}">Copy</button><button data-sent="${d.id}">Mark sent</button></div></div>`).join("")
        : `<p class="muted">${q.sent >= q.goal ? "Goal reached. Nice." : "No drafts waiting."}</p>`;
      body.innerHTML = h;
    } catch (e) { body.textContent = "Couldn't load Queue."; }
  }
  body.addEventListener("click", async e => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.copy) {
      try { await navigator.clipboard.writeText(drafts[b.dataset.copy].pitch); b.textContent = "Copied"; } catch (_) { b.textContent = "Copy failed"; }
    } else if (b.dataset.sent) {
      await fetch(`/api/queue/${b.dataset.sent}/sent`, {method: "POST", headers: {"x-hq": "1"}});
      load();
    }
  });
  load();
  setInterval(load, 60000);
})();

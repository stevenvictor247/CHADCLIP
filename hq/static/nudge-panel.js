// Pitch tab: Nudge's reply rate. Nudge reads Gmail (read-only) for answers to Pitch emails; this just shows the counts.
(function () {
  const root = document.getElementById("nudge");
  if (!root) return;
  root.style.cssText = "padding:0 22px 4px;position:relative;z-index:1";
  async function load() {
    try {
      const d = await (await fetch("/api/nudge")).json();
      root.innerHTML = `<section><h2>📬 Replies <span class="muted">Nudge · reads Gmail, never sends</span></h2>
        ${d.configured ? "" : `<div class="muted">Add your Gmail address and app password in Settings (and turn on IMAP in Gmail) so Nudge can see replies.</div>`}
        <div style="display:flex;gap:18px;flex-wrap:wrap;font-size:14px">
          <span><b style="font-size:18px">${d.percent ?? "–"}${d.percent == null ? "" : "%"}</b> reply rate (${d.replied} of ${d.pitched} pitched)</span>
          <span><b style="font-size:18px">${d.bounced}</b> bounced</span>
          <span><b style="font-size:18px">${d.quiet}</b> quiet after ${d.quiet_days} days</span></div></section>`;
    } catch { /* try again next minute */ }
  }
  load();
  setInterval(load, 60000);
})();

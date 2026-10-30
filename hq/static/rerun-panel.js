// Approvals and Pitch tabs: "Second try". Rerun drafts a short new angle for quiet leads; you copy it, send it yourself and tap Mark sent.
(function () {
  const root = document.getElementById("rerun");
  if (!root) return;
  root.style.cssText = "padding:0 22px 4px;position:relative;z-index:1";
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  let data = null, msg = "";
  function render() {
    const d = data;
    const items = d.waiting.map(t => `<div class="qlead" style="border-top:1px solid var(--line);padding:12px 2px">
      <div style="font-weight:800">${esc(t.name)} <span class="muted">${esc(t.platform)} · try ${t.n} of ${d.max_tries}</span></div>
      <div class="muted">${esc(t.contact || "")} · ${esc(t.subject)}</div>
      <pre style="white-space:pre-wrap;font:inherit;font-size:14px;margin:6px 0;color:var(--muted)">${esc(t.message)}</pre>
      <div style="display:flex;gap:8px;flex-wrap:wrap"><button class="ghost" data-copy="${t.id}">Copy</button>
        <button data-act="sent" data-id="${t.id}">Mark sent</button><button class="ghost" data-act="skipped" data-id="${t.id}">Skip</button></div></div>`).join("");
    root.innerHTML = `<section><h2>🔁 Second try <span class="muted">Rerun · you send each one yourself</span></h2>
      <div class="muted">${d.waiting.length} to review (up to ${d.daily} a day) · ${d.queued_up} more quiet leads in line · ${d.sent} sent so far. Two tries per lead, then they are closed.</div>
      ${d.paused ? `<div class="muted">Pitch is paused, so no new drafts.</div>` : ""}
      ${msg ? `<div class="muted">${esc(msg)}</div>` : ""}
      ${items || `<div class="muted">No second tries waiting.</div>`}</section>`;
    root.querySelectorAll("[data-copy]").forEach(b => b.onclick = async () => {
      const t = d.waiting.find(x => x.id == b.dataset.copy);
      try { await navigator.clipboard.writeText(t.message); b.textContent = "Copied"; } catch { b.textContent = "Copy failed"; }
    });
    root.querySelectorAll("[data-act]").forEach(b => b.onclick = async () => {
      b.disabled = true;
      const r = await fetch(`/api/rerun/${b.dataset.id}/${b.dataset.act}`, {method: "POST", headers: {"X-HQ": "1"}});
      msg = (await r.json().catch(() => ({}))).message || "Something went wrong";
      load();
    });
  }
  async function load() {
    try { data = await (await fetch("/api/rerun")).json(); render(); } catch { /* try again next minute */ }
  }
  load();
  setInterval(load, 60000);
})();

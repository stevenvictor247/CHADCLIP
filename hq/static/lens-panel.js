// Clips tab: Lens's weekly fix list. Lens only suggests; Done and Ignore just hide a fix, nothing is changed on any account.
(function () {
  const root = document.getElementById("lens");
  if (!root) return;
  root.style.cssText = "padding:0 22px 4px;position:relative;z-index:1";
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  async function decide(key, state) {
    await fetch(`/api/lens/fix?key=${encodeURIComponent(key)}&state=${state}`, {method: "POST"});
    load();
  }
  async function load() {
    try {
      const d = await (await fetch("/api/lens")).json();
      const fixes = d.fixes.map((f, i) => `<li style="margin:6px 0">${esc(f.text)}
        <button data-i="${i}" data-s="done">Done</button> <button data-i="${i}" data-s="ignored">Ignore</button></li>`).join("");
      root.innerHTML = `<section><h2>🔎 Fix list <span class="muted">Lens · last ${d.days} days, rules only</span></h2>
        <div style="font-size:14px;margin-bottom:6px"><b>${d.posts}</b> posts, <b>${d.views}</b> views</div>
        ${fixes ? `<ul style="padding-left:18px">${fixes}</ul>` : `<div class="muted">No fixes right now.</div>`}</section>`;
      root.querySelectorAll("button[data-i]").forEach(b => b.onclick = () => decide(d.fixes[b.dataset.i].key, b.dataset.s));
    } catch { /* try again next minute */ }
  }
  load();
  setInterval(load, 60000);
})();

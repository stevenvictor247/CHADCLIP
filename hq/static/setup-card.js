// The getting-started checklist at the top of the dashboard: what HQ still needs, in order, with a Fix link for each.
// Once everything required is done it folds down to one line.
(function () {
  const css = `
    #setup { border-color:rgba(124,196,255,.45); }
    #setup h2 { justify-content:space-between; flex-wrap:wrap; }
    #setup .bar { height:8px; border-radius:999px; background:rgba(255,255,255,.08); overflow:hidden; margin:0 0 12px; }
    #setup .bar i { display:block; height:100%; background:linear-gradient(90deg, var(--good), var(--sky)); transition:width .6s var(--ease); }
    #setup .items { display:grid; gap:8px; }
    #setup .it { display:grid; grid-template-columns:26px 1fr auto; gap:4px 10px; align-items:start; padding:9px 10px; border-radius:12px;
                 background:rgba(255,255,255,.03); border:1px solid transparent; }
    #setup .it.next { border-color:var(--accent); background:rgba(255,179,71,.08); }
    #setup .it .ic { font-size:18px; line-height:1.2; }
    #setup .it b { font-size:14px; }
    #setup .it .opt { font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:999px; padding:1px 7px; margin-left:6px; font-weight:600; }
    #setup .it p { margin:2px 0 0; color:var(--muted); font-size:13px; }
    #setup .it .fix { font-size:12px; color:var(--text); margin-top:3px; }
    #setup .it a { align-self:center; white-space:nowrap; color:#1a1209; background:linear-gradient(135deg, var(--accent), var(--accent2));
                   text-decoration:none; font-weight:800; font-size:12px; border-radius:9px; padding:6px 10px; }
    #setup .it.done { opacity:.7; } #setup .it.done p { display:none; }
    #setup .tools { display:flex; gap:8px; align-items:center; }
    #setup .tools button { background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:9px; padding:4px 10px;
                           font:inherit; font-size:12px; font-weight:700; cursor:pointer; text-transform:none; letter-spacing:0; }
    #setup .tools button:disabled { opacity:.6; cursor:wait; }
    #setup .try { margin-top:12px; padding:10px; border-radius:12px; border:1px dashed var(--line); display:flex; gap:10px;
                  align-items:center; flex-wrap:wrap; font-size:13px; color:var(--muted); }
    #setup .try b { color:var(--text); }
    #setup .try label { cursor:pointer; color:#1a1209; background:linear-gradient(135deg, var(--good), var(--sky)); font-weight:800;
                        border-radius:9px; padding:6px 10px; font-size:12px; }
    #setup .try input { display:none; }
    #setup.folded .items, #setup.folded .bar, #setup.folded .try { display:none; }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);
  const column = document.querySelector("main > div:nth-child(2)");
  if (!column) return;
  column.insertAdjacentHTML("afterbegin", `<section id="setup" style="display:none"></section>`);
  const box = document.getElementById("setup");
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const ICON = {done: "✅", todo: "⬜", problem: "⚠️"};
  let folded = null, last = null, tryMsg = "";

  function draw(s) {
    last = s;
    if (folded === null) folded = s.ready;  // start folded once everything required is done
    const pct = Math.round(100 * s.done / s.total);
    const title = s.ready ? `✅ HQ is set up · ${s.done} of ${s.total}` : `🧭 Getting started · ${s.done} of ${s.total} done`;
    box.className = folded ? "folded" : "";
    box.style.display = "";
    box.innerHTML = `<h2><span>${title}</span><span class="tools">
        <button type="button" id="setup-check" title="Test every key and account again">Check again</button>
        <button type="button" id="setup-fold">${folded ? "Show" : "Hide"}</button></span></h2>
      <div class="bar"><i style="width:${pct}%"></i></div>
      <div class="items">${s.items.map(i => `
        <div class="it ${i.status}${s.next && s.next.id === i.id ? " next" : ""}">
          <span class="ic">${ICON[i.status] || "⬜"}</span>
          <div><b>${esc(i.title)}</b>${i.required ? "" : `<span class="opt">Optional</span>`}
            <p>${esc(i.detail)}</p>${i.status !== "done" && i.fix ? `<p class="fix">👉 ${esc(i.fix)}</p>` : ""}</div>
          ${i.status !== "done" && i.link ? `<a href="${esc(i.link)}">Fix</a>` : "<span></span>"}
        </div>`).join("")}</div>
      <div class="try"><span>🎬 <b>Try it end to end:</b> give Chad a video you made yourself. Approved clips go to the practice
        account (a folder) until a real account is on.</span>
        <label>Pick a video<input type="file" id="setup-video" accept="video/*"></label><span id="setup-try-msg">${esc(tryMsg)}</span></div>`;
    document.getElementById("setup-fold").onclick = () => { folded = !folded; draw(last); };
    document.getElementById("setup-check").onclick = async e => {
      e.target.disabled = true; e.target.textContent = "Checking…";
      try { draw(await (await fetch("/api/setup/check", {method: "POST", headers: {"X-HQ": "1"}})).json()); }
      catch (err) { e.target.disabled = false; e.target.textContent = "Check again"; }
    };
    document.getElementById("setup-video").onchange = async e => {
      const file = e.target.files[0], msg = document.getElementById("setup-try-msg");
      if (!file) return;
      const say = t => { tryMsg = t; msg.textContent = t; };
      say(`Uploading ${file.name}…`);
      const form = new FormData();
      form.append("video", file);
      try {
        const r = await fetch("/api/try-chad", {method: "POST", headers: {"X-HQ": "1"}, body: form});
        const d = await r.json();
        say(r.ok ? `Chad is on it (task #${d.task_id}). Clips show up under "waiting for approval" in a few minutes.`
                 : (d.detail || "Upload failed."));
      } catch (err) { say("Upload failed. Is HQ running?"); }
    };
    box.querySelectorAll('a[href="/#boss"]').forEach(a => a.onclick = ev => {
      ev.preventDefault(); window.hqTabs?.show("boss"); document.getElementById("chatinput")?.focus();
    });
  }

  async function load() {
    try { draw(await (await fetch("/api/setup")).json()); } catch (e) {}
  }
  load();
  setInterval(load, 60 * 1000);
})();

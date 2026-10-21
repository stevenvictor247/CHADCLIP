// Adds the Settings button and the "update available" banner to the dashboard header.
(function () {
  const css = `
    .hqbar-btn { background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:12px; padding:8px 12px;
                 font:inherit; font-weight:700; cursor:pointer; text-decoration:none; display:inline-flex; gap:6px; align-items:center; }
    .hqbar-btn:hover { border-color:var(--accent); }
    #hq-update { position:relative; z-index:2; display:none; gap:12px; align-items:center; flex-wrap:wrap; padding:10px 22px;
                 background:linear-gradient(90deg, rgba(74,222,128,.18), rgba(124,196,255,.14)); border-bottom:1px solid var(--line); }
    #hq-update.zip { background:rgba(248,113,113,.14); }
    #hq-update.ok { background:transparent; padding:6px 22px; }
    #hq-update.ok button { background:var(--panel); color:var(--text); border:1px solid var(--line); padding:5px 10px; }
    #hq-update.testing { background:rgba(124,196,255,.10); }
    #hq-update b { margin-right:4px; }
    #hq-update .what { color:var(--muted); font-size:13px; flex:1; min-width:200px; }
    #hq-update button { background:linear-gradient(135deg, var(--good), var(--sky)); color:#0d1a12; border:0; border-radius:10px;
                        padding:8px 14px; font:inherit; font-weight:800; cursor:pointer; }
    #hq-update button:disabled { opacity:.6; cursor:wait; }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const header = document.querySelector("header");
  if (!header) return;
  header.insertAdjacentHTML("beforeend", `<a class="hqbar-btn" href="/settings" title="API keys, accounts and options">⚙️ Settings</a>`);
  header.insertAdjacentHTML("afterend", `<div id="hq-update"></div>`);
  const bar = document.getElementById("hq-update");
  const esc = s => String(s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  async function waitForRestart() {
    bar.innerHTML = `<b>🔄 Restarting HQ…</b><span class="what">This page reloads by itself in a few seconds.</span>`;
    await new Promise(r => setTimeout(r, 4000));
    for (let i = 0; i < 60; i++) {
      try { if ((await fetch("/api/update")).ok) return location.reload(); } catch (e) {}
      await new Promise(r => setTimeout(r, 1500));
    }
    bar.innerHTML = `<b>HQ hasn't come back yet.</b><span class="what">Close the window and open the Agent HQ icon again.</span>`;
  }
  window.hqWaitForRestart = waitForRestart;

  async function check() {
    let s;
    try { s = await (await fetch("/api/update")).json(); } catch (e) { return; }
    if (!s.git) {
      bar.className = "zip"; bar.style.display = "flex";
      bar.innerHTML = `<b>This copy of HQ can't update itself.</b><span class="what">It came from a ZIP download. Run Install-Agent-HQ.bat once and HQ keeps itself up to date from then on.</span>`;
    } else if (s.available) {
      bar.className = ""; bar.style.display = "flex";
      const list = s.changes.length ? "New: " + s.changes.map(esc).join(" · ") : "";
      const passed = s.tested ? `<span class="what">✅ Passed all tests on GitHub</span>` : "";
      bar.innerHTML = `<b>✨ Update ready (${s.count} change${s.count === 1 ? "" : "s"})</b><span class="what">${list}</span>${passed}<button id="hq-do-update">Update and restart</button>`;
      document.getElementById("hq-do-update").onclick = async e => {
        e.target.disabled = true; e.target.textContent = "Updating…";
        try {
          const r = await (await fetch("/api/update", {method: "POST", headers: {"X-HQ": "1"}})).json();
          if (r.updated) return waitForRestart();
          bar.innerHTML = `<b>Couldn't update.</b><span class="what">${esc(r.message)}</span>`;
        } catch (err) { waitForRestart(); }
      };
    } else if (s.testing) {
      bar.className = "testing"; bar.style.display = "flex";
      bar.innerHTML = `<b>🧪 ${s.testing} new change${s.testing === 1 ? " is" : "s are"} being tested</b><span class="what">It shows up here as an update once every test passes on GitHub.</span>`;
    } else {
      // Nothing to install: say so, so a missing bar never looks like a broken updater.
      bar.className = "ok"; bar.style.display = "flex";
      const ago = s.checked ? Math.max(0, Math.round((Date.now() / 1000 - s.checked) / 60)) : 0;
      bar.innerHTML = s.error
        ? `<b>Couldn't check for updates.</b><span class="what">${esc(s.error)}</span><button id="hq-recheck">Try again</button>`
        : `<b>✅ HQ is up to date</b><span class="what">Version ${esc(s.version || "unknown")} · checked ${ago < 1 ? "just now" : ago + " min ago"}</span><button id="hq-recheck">Check for updates</button>`;
      document.getElementById("hq-recheck").onclick = async e => {
        e.target.disabled = true; e.target.textContent = "Checking…";
        try { await fetch("/api/update?refresh=true"); } catch (err) {}
        check();
      };
    }
  }
  check();
  setInterval(check, 10 * 60 * 1000);
})();

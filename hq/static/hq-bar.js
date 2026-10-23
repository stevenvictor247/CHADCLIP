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
    #hq-update button:disabled { opacity:.6; cursor:wait; }
    #hq-paused { display:none; position:relative; z-index:2; gap:12px; align-items:center; flex-wrap:wrap; padding:10px 22px;
                 background:rgba(251,191,36,.18); border-bottom:1px solid var(--line); }
    #hq-paused .what { color:var(--muted); font-size:13px; flex:1; min-width:200px; }
    #hq-stopped { display:none; position:relative; z-index:2; gap:12px; align-items:center; flex-wrap:wrap; padding:10px 22px;
                  background:rgba(248,113,113,.18); border-bottom:1px solid var(--line); }
    #hq-stopped .what { color:var(--muted); font-size:13px; flex:1; min-width:200px; }
    #hq-stopped button { background:var(--panel); color:var(--text); border:1px solid var(--line); border-radius:10px;
                         padding:8px 14px; font:inherit; font-weight:800; cursor:pointer; }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const header = document.querySelector("header");
  if (!header) return;
  header.insertAdjacentHTML("beforeend", `<button class="hqbar-btn" id="hq-pause" title="Stop every agent and all posting until you press Resume">⏸ Pause all</button>`);
  header.insertAdjacentHTML("beforeend", `<a class="hqbar-btn" href="/settings" title="API keys, accounts and options">⚙️ Settings</a>`);
  header.insertAdjacentHTML("afterend", `<div id="hq-stopped"><b>⚠️ The agents haven't checked in for <span id="hq-stopped-min"></span> minutes.</b><span class="what">They may be stuck on a job. Restarting HQ puts any cut-off job back in the queue.</span><button id="hq-restart">Restart HQ</button></div>`);
  header.insertAdjacentHTML("afterend", `<div id="hq-update"></div><div id="hq-paused"><b>⏸ HQ is paused.</b><span class="what">No agent works and nothing posts until you press Resume. The Boss still chats.</span></div>`);
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

  // Pause All: one button that stops every agent and all posting (texting "pause" to the Relay bot does the same)
  const pauseBtn = document.getElementById("hq-pause");
  const pausedBar = document.getElementById("hq-paused");
  function showPaused(p) {
    pauseBtn.dataset.paused = p ? "1" : "";
    pauseBtn.textContent = p ? "▶️ Resume" : "⏸ Pause all";
    pausedBar.style.display = p ? "flex" : "none";
  }
  pauseBtn.onclick = async () => {
    const want = !pauseBtn.dataset.paused;
    if (want && !confirm("Pause HQ? Every agent stops and nothing posts until you press Resume.")) return;
    pauseBtn.disabled = true;
    try {
      const r = await (await fetch("/api/pause", {method: "POST", headers: {"Content-Type": "application/json", "X-HQ": "1"},
                                                  body: JSON.stringify({paused: want})})).json();
      showPaused(r.paused);
    } catch (e) {}
    pauseBtn.disabled = false;
  };
  // "Agents stopped" warning: the background loop goes round every few seconds; 20 quiet minutes means it's stuck
  const stoppedBar = document.getElementById("hq-stopped");
  document.getElementById("hq-restart").onclick = async e => {
    e.target.disabled = true;
    try { await fetch("/api/restart", {method: "POST", headers: {"X-HQ": "1"}}); } catch (err) {}
    if (window.hqWaitForRestart) window.hqWaitForRestart();
  };
  async function checkPause() {
    try {
      const s = await (await fetch("/api/pause")).json();
      showPaused(s.paused);
      const quiet = s.worker_seconds_ago;
      stoppedBar.style.display = quiet !== null && quiet !== undefined && quiet > 20 * 60 ? "flex" : "none";
      if (quiet) document.getElementById("hq-stopped-min").textContent = Math.round(quiet / 60);
    } catch (e) {}
  }
  checkPause();
  setInterval(checkPause, 30 * 1000);
})();

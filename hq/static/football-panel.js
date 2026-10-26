// The Warrior Village panel under the towns: the football team, this game week's checklist, the sheets in the
// football Inbox (with Ref's flags), the Outbox, the Coaching Notebook and the rulebook.
// The dashboard calls HQFootball.update(state) on each refresh.
(function () {
  const root = document.getElementById("football");
  if (!root) return;
  const css = `
    #football { display:grid; grid-template-columns:400px 1fr; gap:18px; padding:0 22px 4px; position:relative; z-index:1; }
    /* Wayne State's official green (PMS 561) and gold (PMS 1225) */
    #football { --wsu-green:#0C5449; --wsu-gold:#FFCC33; }
    #football .fbhead { grid-column:1 / -1; display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin:0 0 -2px; padding:10px 16px;
                        border-radius:var(--radius); background:linear-gradient(90deg, var(--wsu-green), #08403a); border:1px solid rgba(255,204,51,.45);
                        box-shadow:inset 0 -3px 0 var(--wsu-gold); }
    #football .fbhead h2 { margin:0; color:var(--wsu-gold); font-size:16px; }
    #football .fbhead .sub { color:#e6f0ec; font-size:13px; font-weight:700; }
    #football .fbhead .muted { margin-left:auto; color:#cfe3dc; }
    #football section { background:linear-gradient(180deg, rgba(12,84,73,.38), var(--panel) 140px); border-color:rgba(255,204,51,.22); }
    #football h2 { color:var(--wsu-gold); }
    #football button:not(.ghost) { background:linear-gradient(135deg, var(--wsu-gold), #e0ad1f); color:#06302a; }
    #football button:not(.ghost):hover { box-shadow:0 6px 16px rgba(255,204,51,.3); }
    #football button.ghost:hover, #football input:focus, #football textarea:focus { border-color:var(--wsu-gold); }
    #football input:focus, #football textarea:focus { box-shadow:0 0 0 3px rgba(255,204,51,.2); }
    #football a { color:var(--wsu-gold); }
    #football #fbteam { grid-column:1 / -1; margin-bottom:0; }
    #football .fbagents { display:grid; grid-template-columns:repeat(5, 1fr); gap:12px; }
    #football .fbagents .room { min-height:0; padding-bottom:40px; }
    #football .fbagents .room .role { display:none; }   /* hover a room for its job */
    @media (max-width:700px) { #football .fbagents { grid-template-columns:repeat(3, 1fr); gap:8px; } }
    #football .fbline { display:flex; gap:10px; align-items:center; padding:7px 2px; border-top:1px solid var(--line); font-size:14px; }
    #football .fbline:first-child { border-top:0; }
    #football .fbline input[type=checkbox] { flex:0 0 auto; width:18px; height:18px; accent-color:var(--wsu-green); cursor:pointer; }
    #football .fbline .when { margin-left:auto; color:var(--muted); font-size:12px; white-space:nowrap; }
    #football .fbline.done .what { text-decoration:line-through; color:var(--muted); }
    #football .st { display:inline-block; border-radius:999px; padding:0 8px; font-size:11px; font-weight:800; margin-left:6px; }
    #football .st.late, #football .st.failed { background:var(--bad); color:#fff; }
    #football .st.today { background:var(--accent); color:#2a1405; }
    #football .st.done, #football .st.checked { background:var(--good); color:#062b12; }
    #football .st.new, #football .st.checking { background:#3a3046; color:var(--text); }
    #football .fbgame { font-size:15px; margin-bottom:8px; }
    #football .fbgame b { color:var(--wsu-gold); }
    #football .warn { color:#fbbf24; font-size:13px; margin:2px 0 8px; }
    #football details { margin-top:8px; font-size:13px; }
    #football summary { cursor:pointer; color:var(--muted); }
    #football .sched { width:100%; border-collapse:collapse; margin-top:6px; }
    #football .sched td { padding:3px 4px; border-top:1px solid var(--line); }
    #football .sched tr.next td { color:var(--wsu-gold); font-weight:800; }
    #football .drop { border:2px dashed var(--line); border-radius:12px; padding:12px; text-align:center; color:var(--muted); font-size:13px;
                      transition:border-color .2s, background .2s; margin-bottom:10px; }
    #football .drop.over { border-color:var(--wsu-gold); background:rgba(12,84,73,.3); }
    #football .drop label { color:var(--wsu-gold); cursor:pointer; text-decoration:underline; }
    #football .drop input { display:none; }
    #football .flag { font-size:13px; padding:4px 0; border-top:1px solid var(--line); }
    #football .flag b.fix { color:#fca5a5; } #football .flag b.check { color:#fde68a; }
    #football .flag code { background:#150f1d; border-radius:5px; padding:0 4px; }
    #football .row { flex-wrap:wrap; margin-top:8px; }
    #football .row select { margin-left:0; flex:1 1 140px; }
    #football .note { font-size:13px; padding:5px 0; border-top:1px solid var(--line); }
    #football .note .tab { color:var(--wsu-gold); font-weight:800; margin-right:6px; }
    #football .msg { font-size:13px; margin-top:6px; white-space:pre-wrap; }
    #football textarea.rules { width:100%; min-height:220px; font-size:13px; margin-top:8px; }
    #football .path { font-family:ui-monospace, Consolas, monospace; font-size:12px; word-break:break-all; }
    @media (max-width:960px) { #football { grid-template-columns:1fr; padding:0 14px 4px; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const md = iso => { const [, m, d] = String(iso).split("-"); return `${+m}/${+d}`; };
  const STATE = {late: "late", today: "due today", done: "done", coming: ""};
  const FILE_STATE = {new: "waiting for Ref", checking: "Ref is checking", checked: "checked", failed: "couldn't read"};
  const toast = html => window.toast ? window.toast(html) : null;
  const refresh = () => window.hqRefresh?.();

  root.innerHTML = `
    <div class="fbhead"><h2>🏈 Warrior Village</h2><span class="sub">Wayne State Warriors football · GLIAC</span><span class="muted" id="fbspend"></span></div>
    <section id="fbteam"><h2>The football team</h2><div class="fbagents" id="fbagents"></div></section>
    <div>
      <section id="fbweek"><h2>Game week <span class="count" id="fbweekcount" style="display:none"></span></h2><div id="fbweekbody"></div></section>
      <section id="fbnotes">
        <h2>Coaching Notebook <span class="count" id="fbnotecount"></span></h2>
        <form id="fbnoteform"><input id="fbnote" placeholder="NB: Davenport runs Trey Off on 3rd and short" autocomplete="off"><button>Save</button></form>
        <div class="muted" style="margin-top:6px">Scribe files it under the right section with today's date. You can also start a Boss chat message with NB:</div>
        <div class="msg" id="fbnotemsg"></div>
        <div id="fbnotelist"></div>
        <div class="muted" style="margin-top:8px"><a href="/api/football/notebook.md">⬇️ Download the whole notebook</a></div>
      </section>
    </div>
    <div>
      <section id="fbfiles">
        <h2>Sheets in the football Inbox <span class="count" id="fbfilecount" style="display:none"></span></h2>
        <div class="drop" id="fbdrop">Drop a Hudl export or practice sheet here (.xlsx or .csv), or <label>pick files<input type="file" id="fbpick" multiple
          accept=".xlsx,.xlsm,.csv,.pdf,.md,.txt"></label>. Ref checks every sheet against your tagging rules. It never changes your file.</div>
        <div class="msg" id="fbupmsg"></div>
        <div id="fbfilelist"></div>
      </section>
      <section id="fboutbox"><h2>Outbox</h2><div id="fboutlist"></div></section>
      <section id="fbprint"><h2>🖨️ Thursday print <span class="count" id="fbprintcount" style="display:none"></span></h2>
        <div id="fbprintbody"></div>
        <div class="row"><button id="fbprintnow">Print now</button><button class="ghost" id="fbprintpause">Pause</button><button class="ghost" id="fbprintfolders">Make opponent folders</button></div>
        <div class="msg" id="fbprintmsg"></div>
      </section>
      <section id="fbdepth"><h2>📋 Monday personnel sheet</h2><div id="fbdepthbody"></div>
        <div class="row"><select id="fbdepthopp"></select><label class="ghost" style="cursor:pointer">Upload depth chart + stats<input type="file" id="fbdepthpick" accept=".xlsx,.xlsm,.csv" style="display:none"></label>
          <button class="ghost" id="fbdepthbuild">Build now</button></div>
        <div class="muted" style="margin-top:6px">One Excel or CSV per opponent with POS, NO, NAME and GS (starts) plus carries, attempts or catches. Every Monday Depth builds that week's sheet and asks for your OK.</div>
        <div class="msg" id="fbdepthmsg"></div>
      </section>
      <section id="fbtags"><h2>🏷️ Tag sheet</h2><div id="fbtagbody"></div>
        <div class="drop" id="fbtagdrop">Drop your sheet of all your tags here (Excel, CSV or text), or <label>pick a file<input type="file" id="fbtagpick"
          accept=".xlsx,.xlsm,.csv,.md,.txt"></label>. Captain reads it, and Ref won't flag a word that's on it.</div>
        <div class="msg" id="fbtagmsg"></div>
      </section>
      <section id="fbrules"><h2>Rulebook and folders</h2><div id="fbrulebody"></div>
        <div class="row"><button class="ghost" id="fbrulesedit">View or edit the rulebook</button></div>
        <div id="fbruleedit"></div>
      </section>
    </div>`;
  const $ = id => document.getElementById(id);
  let data = null;
  const shown = {};
  const changed = (key, value) => { const s = JSON.stringify(value); if (shown[key] === s) return false; shown[key] = s; return true; };

  async function post(url, body, isForm) {
    const opts = {method: "POST", headers: {"X-HQ": "1"}};
    if (isForm) opts.body = body;
    else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    let r;
    try { r = await fetch(url, opts); } catch (e) { return {ok: false, message: "Couldn't reach HQ. Is it running?"}; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return {ok: false, message: typeof j.detail === "string" ? j.detail : "That didn't work."};
    return {ok: true, ...j};
  }

  // ---- the team ----
  function drawTeam(agents) {
    if (!changed("team", agents.map(a => [a.name, a.doing]))) return;
    $("fbagents").innerHTML = window.hqRooms ? window.hqRooms(agents) : agents.map(a => `<div>${esc(a.name)}</div>`).join("");
  }

  // ---- game week ----
  function drawWeek(w) {
    if (!changed("week", w)) return;
    const body = $("fbweekbody"), count = $("fbweekcount");
    if (w.season_over) {
      count.style.display = "none";
      body.innerHTML = `<div class="empty"><span class="big">🏁</span>The season is over. Clock has nothing due.</div>`;
      return;
    }
    const g = w.game, open = w.checklist.filter(x => x.state !== "done").length;
    count.style.display = open ? "" : "none";
    count.textContent = `${open} to do`;
    const when = w.days_to_game === 0 ? "today" : w.days_to_game === 1 ? "tomorrow" : `in ${w.days_to_game} days`;
    body.innerHTML = `
      <div class="fbgame">vs <b>${esc(g.opponent)}</b> · ${esc(g.day)} ${md(g.date)}${g.kickoff ? " · " + esc(g.kickoff) : ""}${g.site ? " · " + esc(g.site) : ""} · ${when}</div>
      ${g.confirmed ? "" : `<div class="warn">⚠ This date is my guess. Tell the Boss the real date (for example "Davenport is Saturday 10/24 at 1pm, home").</div>`}
      ${w.checklist.map(x => `<div class="fbline ${x.state === "done" ? "done" : ""}">
          <input type="checkbox" data-item="${esc(x.item)}" ${x.state === "done" ? "checked" : ""} aria-label="${esc(x.item)} done">
          <span class="what">${esc(x.item)}${STATE[x.state] ? `<span class="st ${x.state}">${STATE[x.state]}</span>` : ""}</span>
          <span class="when">${esc(x.due_day)} ${md(x.due)}</span></div>`).join("")}
      <details><summary>Whole schedule</summary><table class="sched">${w.games.map(x => `<tr class="${x.opponent === g.opponent ? "next" : ""}">
          <td>${esc(x.day)} ${md(x.date)}${x.confirmed ? "" : "?"}</td><td>${esc(x.opponent)}</td><td>${esc(x.site || "")}</td><td>${esc(x.kickoff || "")}</td></tr>`).join("")}</table>
        <div class="muted" style="margin-top:4px">? = date not confirmed yet. Due days are guesses until you tell the Boss yours ("Personnel sheet is due Wednesday").</div></details>`;
    body.querySelectorAll("input[type=checkbox]").forEach(box => box.onchange = async () => {
      box.disabled = true;
      const r = await post("/api/football/checklist", {item: box.dataset.item, done: box.checked, opponent: g.opponent});
      if (!r.ok) { box.checked = !box.checked; toast(esc(r.message)); }
      shown.week = null; box.disabled = false; refresh();
    });
  }

  // ---- the Inbox ----
  function opponentOptions() {
    const games = data?.week?.games || [];
    return `<option value="">Opponent: guess from the file name</option>` +
      games.map(x => `<option value="${esc(x.opponent)}">${esc(x.opponent)}</option>`).join("");
  }
  function drawFiles(list) {
    $("fbfilecount").style.display = list.length ? "" : "none";
    $("fbfilecount").textContent = list.length;
    if (!changed("files", [list, data?.week?.games?.length])) return;
    const openNow = new Set([...$("fbfilelist").querySelectorAll("details[open]")].map(d => d.dataset.id));
    $("fbfilelist").innerHTML = list.length ? list.map(f => `<div class="camp">
        <h3>${esc(f.name)}<span class="st ${esc(f.status)}">${esc(FILE_STATE[f.status] || f.status)}</span></h3>
        <div class="meta">${esc(f.summary || (f.status === "new" ? "Ref will check this in a moment." : ""))}</div>
        ${f.ref_copy ? `<div class="meta">Marked-up copy: <a href="/api/football/outbox/${encodeURIComponent(f.ref_copy)}">${esc(f.ref_copy)}</a> (red = fix, yellow = look at it)</div>` : ""}
        ${f.flags.length ? `<details data-id="${f.id}" ${openNow.has(String(f.id)) ? "open" : ""}><summary>${f.fix || 0} to fix, ${f.check_count || 0} to look at</summary>
          ${f.flags.map(x => `<div class="flag"><b class="${esc(x.level)}">${x.level === "fix" ? "Fix" : "Check"}</b> ${esc(x.label)} · ${esc(x.column)}
            ${x.value ? `<code>${esc(x.value)}</code>` : ""}: ${esc(x.message)}</div>`).join("")}
          ${f.more_flags ? `<div class="muted">…and ${f.more_flags} more in the marked-up copy.</div>` : ""}</details>` : ""}
        <div class="row">
          <select data-opp="${f.id}">${opponentOptions()}</select>
          <button data-report="${f.id}" ${f.status === "checking" ? "disabled" : ""}>📊 Build scouting report</button>
          <button class="ghost" data-check="${f.id}" ${f.status === "checking" ? "disabled" : ""}>Check again</button>
        </div></div>`).join("")
      : `<div class="empty"><span class="big">📭</span>No sheets yet. Export a playlist from Hudl (Excel) and drop it above.</div>`;
    $("fbfilelist").querySelectorAll("[data-check]").forEach(b => b.onclick = async () => {
      b.disabled = true;
      const r = await post(`/api/football/files/${b.dataset.check}/check`);
      toast(r.ok ? "🚩 Ref is checking it again" : esc(r.message));
      shown.files = null; refresh();
    });
    $("fbfilelist").querySelectorAll("[data-report]").forEach(b => b.onclick = async () => {
      b.disabled = true;
      const opp = $("fbfilelist").querySelector(`[data-opp="${b.dataset.report}"]`).value;
      const r = await post(`/api/football/files/${b.dataset.report}/report`, {opponent: opp || null});
      toast(r.ok ? "📊 Tells is building the report. It will wait for your OK in Approvals." : esc(r.message));
      b.disabled = false; refresh();
    });
  }
  async function upload(fileList) {
    const out = [];
    for (const file of fileList) {
      const form = new FormData();
      form.append("file", file);
      const r = await post("/api/football/upload", form, true);
      out.push(`${r.ok ? "✅" : "⚠"} ${file.name}: ${r.message}`);
      $("fbupmsg").textContent = out.join("\n");
    }
    shown.files = null; shown.rules = null; refresh();
  }
  const drop = $("fbdrop");
  $("fbpick").onchange = e => { if (e.target.files.length) upload([...e.target.files]); e.target.value = ""; };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files.length) upload([...e.dataTransfer.files]); };

  // ---- the Outbox ----
  function drawOutbox(list) {
    if (!changed("outbox", list)) return;
    $("fboutlist").innerHTML = list.length ? list.map(f => `<div class="fbline">📄 <a href="/api/football/outbox/${encodeURIComponent(f.name)}">${esc(f.name)}</a>
        <span class="when">${Math.max(1, Math.round(f.bytes / 1024))} KB</span></div>`).join("")
      : `<div class="muted">Empty. Reports you OK and Ref's marked-up copies land here.</div>`;
  }

  // ---- the notebook ----
  function drawNotes(fb) {
    $("fbnotecount").textContent = fb.notes_total ? `${fb.notes_total} entries` : "";
    if (!changed("notes", fb.notes)) return;
    $("fbnotelist").innerHTML = fb.notes.length ? fb.notes.map(n => `<div class="note"><span class="tab">${esc(n.tab)}</span>${esc(n.text)}</div>`).join("")
      : `<div class="muted" style="margin-top:8px">No entries yet. Upload your notebook as a .md file with "notebook" in its name to bring the old entries in.</div>`;
  }
  $("fbnoteform").onsubmit = async e => {
    e.preventDefault();
    const input = $("fbnote"), text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    const r = await post("/api/football/note", {text});
    input.disabled = false;
    $("fbnotemsg").textContent = r.message || "";
    if (r.ok) { input.value = ""; refresh(); }
    input.focus();
  };

  // ---- the rulebook and folders ----
  function drawRules(fb) {
    $("fbspend").textContent = `Football Claude spend today: $${(fb.spend_today_usd || 0).toFixed(2)}` +
      (fb.budget_usd ? ` of $${fb.budget_usd.toFixed(2)}` : " (no daily limit)") +
      (fb.over_budget ? ". Budget reached: Captain and Scribe rest until tomorrow (Clock, Ref and Tells don't use Claude)." : "");
    if (!changed("rules", [fb.rulebook_loaded, fb.inbox_path, fb.outbox_path])) return;
    $("fbrulebody").innerHTML = `
      <div class="fbline">${fb.rulebook_loaded ? "✅ Rulebook loaded. Captain and Scribe read it." :
        "⚠ No rulebook yet. Upload your rulebook .md (it needs \"rulebook\" in the file name) in the Inbox box above."}</div>
      <div class="fbline" style="display:block"><div>📥 Inbox: <span class="path">${esc(fb.inbox_path)}</span></div>
        <div>📤 Outbox: <span class="path">${esc(fb.outbox_path)}</span></div>
        <div class="muted" style="margin-top:4px">To share these with your Mac, set HQ_FOOTBALL_DIR in <a href="/settings">⚙️ Settings</a> to a Google Drive folder, like G:\\My Drive\\HQ Football.</div></div>`;
  }
  // ---- the Thursday print ----
  function drawPrint(fb) {
    const p = fb.print;
    if (!p || !changed("print", p)) return;
    const ready = p.files.filter(f => !f.problem).length;
    $("fbprintcount").style.display = p.files.length ? "" : "none";
    $("fbprintcount").textContent = p.files.length;
    $("fbprintpause").textContent = p.paused ? "Resume" : "Pause";
    const next = new Date(p.next);
    const nextText = next.toLocaleString([], {weekday: "long", hour: "numeric", minute: "2-digit"});
    $("fbprintbody").innerHTML = `
      <div class="fbline" style="display:block">
        <div>${p.paused ? "⏸ Paused. Nothing prints on its own until you press Resume." : `⏰ Prints ${esc(p.when)}. Next: <b>${esc(nextText)}</b>`}</div>
        <div>📁 Folder: <span class="path">${esc(p.folder)}</span> ${p.folder_found ? "" : "(not found)"}</div>
        <div>🏈 This week: <b>${esc(p.opponent || "no game")}</b>${p.opponent ? (p.week_folder ? ` (prints the documents in the "${esc(p.week_folder)}" folder)` : ` — no folder yet, press Make opponent folders`) : ""}</div>
        <div>🖨️ Printer: ${esc(p.printer)}</div></div>
      ${p.files.length ? p.files.map(f => `<div class="fbline">${f.problem ? "⚠" : "📄"} ${esc(f.name)}${f.problem ? ` <span class="muted">${esc(f.problem)}</span>` : ""}</div>`).join("") :
        `<div class="muted">Nothing waiting. Put PDF, Word or Excel files in this week's opponent folder and Clock prints them at the next print time. Files stay in the folder. A file prints once, and again only if you change it.</div>`}
      ${ready && !p.paused ? `<div class="muted">${ready} ready to print.</div>` : ""}
      ${p.log.length ? `<div class="muted" style="margin-top:8px">Recent: ${p.log.slice(0, 4).map(l => esc(l.at.replace("T", " ") + " " + l.text)).join("<br>")}</div>` : ""}`;
  }
  $("fbprintnow").onclick = async () => {
    $("fbprintnow").disabled = true;
    const r = await post("/api/football/print/now");
    $("fbprintmsg").textContent = r.ok ? "Clock is printing. You'll get a text when it's done." : r.message;
    $("fbprintnow").disabled = false;
    if (r.ok) refresh();
  };
  $("fbprintpause").onclick = async () => {
    const r = await post("/api/football/print/pause", {paused: !(data && data.print && data.print.paused)});
    $("fbprintmsg").textContent = r.message || "";
    shown.print = null;
    refresh();
  };
  $("fbprintfolders").onclick = async () => {
    const r = await post("/api/football/print/folders");
    $("fbprintmsg").textContent = r.message || "";
    shown.print = null;
    refresh();
  };

  // ---- the Monday personnel sheet ----
  function drawDepth(fb) {
    const d = fb.depth;
    if (!d || !changed("depth", [d, fb.week && fb.week.game && fb.week.game.opponent])) return;
    const sel = $("fbdepthopp"), cur = sel.value || (fb.week && fb.week.game && fb.week.game.opponent) || "";
    sel.innerHTML = d.map(x => `<option ${x.opponent === cur ? "selected" : ""}>${esc(x.opponent)}</option>`).join("");
    const week = fb.week && fb.week.game && fb.week.game.opponent;
    $("fbdepthbody").innerHTML = d.filter(x => x.opponent === week || x.uploaded).map(x =>
      `<div class="fbline">${x.uploaded ? "✅" : "⚠"} ${esc(x.opponent)}${x.opponent === week ? " (this week)" : ""} — ${x.uploaded ? "uploaded " + esc(x.when.replace("T", " ")) : "needs the depth chart and stats"}</div>`).join("") ||
      `<div class="muted">No game this week.</div>`;
  }
  async function sendDepth(file) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("opponent", $("fbdepthopp").value);
    const r = await post("/api/football/depth/upload", form, true);
    $("fbdepthmsg").textContent = r.message || "";
    if (r.ok) { shown.depth = null; refresh(); }
  }
  $("fbdepthpick").onchange = e => { sendDepth(e.target.files[0]); e.target.value = ""; };
  $("fbdepthbuild").onclick = async () => {
    const r = await post("/api/football/depth/build?opponent=" + encodeURIComponent($("fbdepthopp").value));
    $("fbdepthmsg").textContent = r.ok ? "Depth is building it. It will show up in Approvals." : r.message;
    if (r.ok) refresh();
  };

  // ---- the tag sheet ----
  function drawTags(fb) {
    const t = fb.tagsheet;
    if (!t || !changed("tagsheet", t)) return;
    $("fbtagbody").innerHTML = t.loaded
      ? `<div class="fbline">✅ ${esc(t.name)} loaded (${t.words} words), saved ${esc((t.saved || "").replace("T", " "))}. Captain and Ref use it.</div>`
      : `<div class="fbline">⚠ No tag sheet yet. Upload yours so the agents use your tag names.</div>`;
  }
  async function sendTags(file) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const r = await post("/api/football/tagsheet", form, true);
    $("fbtagmsg").textContent = r.message || "";
    if (r.ok) { shown.tagsheet = null; refresh(); }
  }
  $("fbtagpick").onchange = e => { sendTags(e.target.files[0]); e.target.value = ""; };
  $("fbtagdrop").ondragover = e => e.preventDefault();
  $("fbtagdrop").ondrop = e => { e.preventDefault(); sendTags(e.dataTransfer.files[0]); };
  $("fbrulesedit").onclick = async () => {
    const box = $("fbruleedit");
    if (box.innerHTML) { box.innerHTML = ""; return; }
    let text = "";
    try { text = (await (await fetch("/api/football/rulebook")).json()).text || ""; } catch (e) {}
    box.innerHTML = `<textarea class="rules" id="fbruletext" placeholder="Paste your football rulebook here (Markdown is fine)">${esc(text)}</textarea>
      <div class="row"><button id="fbrulesave">Save rulebook</button></div><div class="msg" id="fbrulemsg"></div>`;
    $("fbrulesave").onclick = async () => {
      const r = await post("/api/football/rulebook", {text: $("fbruletext").value});
      $("fbrulemsg").textContent = r.message;
      if (r.ok) { shown.rules = null; refresh(); }
    };
  };

  window.HQFootball = {
    update(s) {
      const fb = s.football;
      if (!fb) return;
      data = fb;
      drawTeam((s.agents || []).filter(a => a.village === "football"));
      drawWeek(fb.week);
      drawFiles(fb.files);
      drawOutbox(fb.outbox);
      drawNotes(fb);
      drawRules(fb);
      drawPrint(fb);
      drawTags(fb);
      drawDepth(fb);
    },
  };
})();

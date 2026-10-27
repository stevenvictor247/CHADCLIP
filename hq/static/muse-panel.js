// The Ideas tab: Muse, the Creative Director. On top, a box to aim Muse at something and a Brainstorm now button. Then
// Muse's ideas, best first, each with what it could earn, what it costs, how much work it is and why now, and three
// answers: Build it (shows a build brief to paste to Claude), Later, Not for me (with a quick reason Muse learns from).
// Ideas you said yes to sit under "Building" until you mark them built. Fetches /api/muse by itself, so the dashboard
// needs no other wiring.
(function () {
  const root = document.getElementById("muse");
  if (!root) return;
  const css = `
    #muse { padding:0 22px 4px; position:relative; z-index:1; }
    #muse section { margin-bottom:18px; background:linear-gradient(180deg, rgba(232,121,249,.14), var(--panel) 140px); }
    #muse h2 { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
    #muse h2 .muted { font-weight:400; }
    #muse .mu-ask { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0 6px; }
    #muse .mu-ask input { min-width:220px; }
    #muse .mu-meta { font-size:13px; color:var(--muted); line-height:1.5; }
    #muse .mu-meta b { color:var(--text); font-variant-numeric:tabular-nums; }
    #muse .mu-err { color:var(--bad); font-size:13px; }
    #muse .mu-kinds { display:flex; gap:6px; flex-wrap:wrap; margin:12px 0 4px; }
    #muse .mu-kinds button { padding:5px 12px; font-size:13px; border-radius:999px; }
    #muse .mu-kinds button[aria-pressed="false"] { background:transparent; color:var(--muted); border:1px solid var(--line); box-shadow:none; }
    #muse .mu-idea { display:grid; grid-template-columns:44px minmax(0, 1fr); gap:12px; padding:14px 2px; border-top:1px solid var(--line); }
    #muse .mu-idea:first-of-type { border-top:0; }
    #muse .mu-rank { width:40px; height:40px; border-radius:12px; display:grid; place-items:center; font-weight:900; font-size:18px;
                     background:rgba(232,121,249,.16); color:#f0abfc; }
    #muse .mu-idea.top .mu-rank { background:linear-gradient(135deg, #e879f9, #ffb347); color:#2a0d1b; }
    #muse .mu-t { font-weight:800; font-size:16px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
    #muse .mu-kind { font-size:11px; font-weight:800; padding:2px 8px; border-radius:999px; background:#3a3046; color:var(--muted); }
    #muse .mu-kind.business { background:rgba(74,222,128,.16); color:#86efac; } #muse .mu-kind.agent { background:rgba(124,196,255,.16); color:#93c5fd; }
    #muse .mu-kind.addon { background:rgba(255,179,71,.16); color:#fcd34d; } #muse .mu-kind.hq { background:rgba(232,121,249,.16); color:#f0abfc; }
    #muse .mu-score { margin-left:auto; font-size:12px; color:var(--muted); font-weight:700; white-space:nowrap; }
    #muse .mu-score b { color:var(--text); font-size:14px; }
    #muse .mu-pitch { margin-top:4px; font-size:14px; line-height:1.5; }
    #muse .mu-nums { display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:8px; font-size:13px; color:var(--muted); }
    #muse .mu-nums b { color:var(--text); font-variant-numeric:tabular-nums; }
    #muse .mu-why { font-size:13px; margin-top:6px; color:var(--muted); }
    #muse .mu-why::before { content:"Why now: "; font-weight:800; color:var(--accent); }
    #muse details { margin-top:6px; } #muse summary { cursor:pointer; font-weight:800; font-size:13px; color:var(--muted); padding:4px 0; }
    #muse details ol { margin:4px 0 6px; padding-left:20px; font-size:13px; line-height:1.5; }
    #muse .mu-small { font-size:13px; line-height:1.5; margin:4px 0; }
    #muse .mu-small b { color:var(--accent); }
    #muse .mu-acts { display:flex; flex-wrap:wrap; gap:8px; margin-top:10px; align-items:center; }
    #muse .mu-acts button { padding:7px 14px; font-size:13px; }
    #muse .mu-reasons { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; align-items:center; font-size:13px; color:var(--muted); }
    #muse .mu-reasons button { padding:4px 10px; font-size:12px; }
    #muse .mu-brief { width:100%; min-height:150px; margin-top:8px; font:12px/1.45 ui-monospace, Consolas, monospace; }
    #muse .mu-group { margin-top:6px; }
    #muse .mu-group > summary { font-size:14px; padding:8px 0; }
    #muse .mu-note { font-size:13px; color:var(--muted); margin-top:4px; }
    #muse .mu-build { font-size:13px; margin-top:8px; padding:6px 10px; border-radius:8px; background:rgba(148,163,184,.12); }
    #muse .mu-build.ok { background:rgba(34,197,94,.14); }
    #muse .mu-build.bad { background:rgba(239,68,68,.14); }
    #muse .mu-bar { height:8px; border-radius:99px; background:rgba(148,163,184,.25); margin:6px 0 4px; overflow:hidden; }
    #muse .mu-bar > i { display:block; height:100%; background:#22c55e; border-radius:99px; transition:width .6s; }
    #muse .mu-bar.bad > i { background:#ef4444; }
    #muse .mu-steps { display:flex; justify-content:space-between; font-size:11px; opacity:.7; }
    #muse .mu-steps .on { opacity:1; font-weight:600; }
    #muse .mu-empty { padding:18px; text-align:center; color:var(--muted); border:1px dashed var(--line); border-radius:14px; }
    #muse .mu-empty .big { display:block; font-size:34px; margin-bottom:4px; }
    #muse .mu-dropped { font-size:12px; color:var(--muted); margin-top:4px; }
    @media (max-width:900px) { #muse { padding:0 14px 4px; } }
    @media (max-width:600px) { #muse .mu-idea { grid-template-columns:34px minmax(0, 1fr); gap:10px; }
                               #muse .mu-rank { width:32px; height:32px; font-size:15px; border-radius:10px; }
                               #muse .mu-score { margin-left:0; width:100%; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const usd = n => { n = Number(n || 0); return "$" + (n >= 10 || n === Math.round(n) ? Math.round(n).toLocaleString() : n.toFixed(2)); };
  const ago = iso => {
    if (!iso) return "";
    const h = (Date.now() - new Date(iso).getTime()) / 3600000;
    return h < 1 ? "just now" : h < 24 ? Math.round(h) + " h ago" : Math.round(h / 24) + " day(s) ago";
  };
  let data = null, kind = "", busy = "", err = "", askingWhy = null, openBrief = new Set(), openGroups = new Set(), shown = "";
  let focusDraft = "";

  async function call(url, body) {
    const r = await fetch(url, {method: "POST", headers: {"X-HQ": "1", "Content-Type": "application/json"}, body: JSON.stringify(body || {})});
    const out = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(out.detail || "Something went wrong");
    return out;
  }

  function numbers(i) {
    const parts = [
      `💰 <b>${usd(i.profit_low)}–${usd(i.profit_high)}</b>/month`,
      `🧾 <b>${usd(i.start_cost)}</b> to start${i.monthly_cost ? ` + <b>${usd(i.monthly_cost)}</b>/month` : ""}`,
      `⏱️ <b>${esc(i.effort)}</b> build · <b>${Number(i.effort_hours).toFixed(i.effort_hours % 1 ? 1 : 0)} h</b> of your time`,
      `🎯 <b>${Math.round(i.confidence * 100)}%</b> sure`,
    ];
    if (i.months_to_first != null) parts.push(`📅 first dollar in ~<b>${i.months_to_first}</b> mo`);
    if (i.payback_months) parts.push(`↩️ pays back in ~<b>${i.payback_months}</b> mo`);
    return `<div class="mu-nums">${parts.map(p => `<span>${p}</span>`).join("")}</div>`;
  }

  function ideaHtml(i, rank) {
    const k = data.kinds[i.kind] || i.kind;
    const why = askingWhy === i.id;
    let acts = "";
    if (i.status === "proposed") {
      acts = why ? `<div class="mu-reasons">Why not? ${data.reasons.map(r => `<button class="ghost" data-pass="${i.id}" data-reason="${esc(r)}">${esc(r)}</button>`).join("")}
                      <button class="ghost" data-pass="${i.id}" data-reason="">Skip</button></div>`
        : `<div class="mu-acts"><button data-act="build" data-id="${i.id}" ${busy ? "disabled" : ""}>👍 Build it</button>
             <button class="ghost" data-act="later" data-id="${i.id}" ${busy ? "disabled" : ""}>⏸ Later</button>
             <button class="ghost" data-ask="${i.id}" ${busy ? "disabled" : ""}>👎 Not for me</button></div>`;
    } else if (i.status === "approved") {
      const sent = i.build_status === "started", failed = i.build_status === "failed";
      const pg = i.progress, order = ["sent", "building", "pr", "tests", "merged", "live"];
      const at = pg ? Math.max(0, order.indexOf({unknown: "building", closed: "pr", passed: "tests"}[pg.key] || pg.key)) : 0;
      const bar = pg ? `<div class="mu-bar ${pg.bad ? "bad" : ""}"><i style="width:${pg.pct}%"></i></div>
          <div class="mu-steps">${["Sent", "Building", "PR open", "Tests", "Merged", "Live"].map((t, n) => `<span class="${n <= at ? "on" : ""}">${t}</span>`).join("")}</div>` : "";
      const state = sent ? `<div class="mu-build ${pg?.bad ? "bad" : "ok"}">🔨 <b>${esc(pg?.label || "Sent to Claude")}</b> · ${pg?.pct ?? 10}%. ${esc(pg?.detail || "")}
          Sent ${esc(ago(i.build_at))}. ${pg?.pr_url ? `<a href="${esc(pg.pr_url)}" target="_blank" rel="noopener">PR #${pg.pr_number}</a>` : "Its session shows up under Code on claude.ai."}${bar}</div>`
        : failed ? `<div class="mu-build bad">Couldn't send it to Claude: ${esc(i.build_note || "")}</div>`
        : data.build_ready ? "" : `<div class="mu-build">To have Build it start the build in Claude by itself, add HQ_BUILD_TOKEN and HQ_BUILD_URL in Settings. Until then, copy the brief and paste it to Claude.</div>`;
      acts = `${state}<div class="mu-acts">${data.build_ready && !sent ? `<button data-send="${i.id}" ${busy ? "disabled" : ""}>🔨 ${failed ? "Try again" : "Send to Claude to build"}</button>` : ""}
                <button ${data.build_ready && !sent ? 'class="ghost"' : ""} data-copy="${i.id}">📋 Copy build brief</button>
                <button class="ghost" data-brief="${i.id}">${openBrief.has(i.id) ? "Hide brief" : "Show brief"}</button>
                <button class="ghost" data-act="built" data-id="${i.id}">✅ Mark built</button>
                <button class="ghost" data-act="reopen" data-id="${i.id}">Undo</button></div>
              ${openBrief.has(i.id) ? `<textarea class="mu-brief" readonly>${esc(i.brief)}</textarea>` : ""}`;
    } else {
      acts = `<div class="mu-acts">${i.reason ? `<span class="mu-note">You said: ${esc(i.reason)}</span>` : ""}
                <button class="ghost" data-act="reopen" data-id="${i.id}">Bring it back</button></div>`;
    }
    const steps = i.first_steps || [];
    return `<div class="mu-idea ${rank === 1 && i.status === "proposed" ? "top" : ""}">
      <div class="mu-rank">${rank}</div>
      <div>
        <div class="mu-t">${esc(i.title)}<span class="mu-kind ${esc(i.kind)}">${esc(k)}${i.name ? " · " + esc(i.name) : ""}</span>
          <span class="mu-score" title="Expected first-year profit for each hour of work">score <b>${Number(i.score).toLocaleString()}</b></span></div>
        <div class="mu-pitch">${esc(i.pitch)}</div>
        ${numbers(i)}
        ${i.why_now ? `<div class="mu-why">${esc(i.why_now)}</div>` : ""}
        <details><summary>First steps, your part and the risks</summary>
          ${steps.length ? `<ol>${steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol>` : ""}
          ${i.steven_does ? `<p class="mu-small"><b>Your part:</b> ${esc(i.steven_does)}</p>` : ""}
          ${i.risks ? `<p class="mu-small"><b>Watch out:</b> ${esc(i.risks)}</p>` : ""}
          ${(i.builds_on || []).length ? `<p class="mu-small"><b>Builds on:</b> ${i.builds_on.map(esc).join(", ")}</p>` : ""}
          ${i.focus ? `<p class="mu-small"><b>You asked about:</b> ${esc(i.focus)}</p>` : ""}
          <p class="mu-small muted">Thought up ${esc(ago(i.created_at))}.</p>
        </details>
        ${acts}
      </div></div>`;
  }

  function group(id, title, list, open) {
    if (!list.length) return "";
    const isOpen = open || openGroups.has(id);
    return `<details class="mu-group" data-group="${id}" ${isOpen ? "open" : ""}><summary>${title} · ${list.length}</summary>
      ${list.map((i, n) => ideaHtml(i, n + 1)).join("")}</details>`;
  }

  function render() {
    if (!data) return;
    const key = JSON.stringify(data) + kind + busy + err + askingWhy + [...openBrief].join() + [...openGroups].join();
    if (key === shown) return;
    shown = key;
    const pick = s => data.ideas.filter(i => i.status === s && (!kind || i.kind === kind));
    const fresh = pick("proposed"), building = pick("approved"), later = pick("parked"), built = pick("built"), no = pick("rejected");
    const last = data.last_round;
    const kinds = Object.entries(data.kinds);
    const active = document.activeElement?.id === "mu-focus";
    root.innerHTML = `<section>
      <h2>💡 Ideas <span class="muted">from Muse, your Creative Director</span></h2>
      <p class="mu-meta">New businesses, new agents, add-ons to what HQ already does, and HQ upgrades, ranked best first.
        Muse only suggests. Nothing gets built, bought or signed up for unless you say so.</p>
      <details><summary>How Muse ranks</summary><p class="mu-small">${esc(data.how)}</p></details>
      <div class="mu-ask">
        <input id="mu-focus" maxlength="500" placeholder="Point Muse at something (optional), e.g. ways to earn from my clipping accounts" value="${esc(focusDraft)}">
        <button id="mu-run" ${busy || data.running || data.queued || !data.has_llm ? "disabled" : ""}>${data.running || data.queued || busy === "run" ? "Thinking…" : "✨ Brainstorm now"}</button>
      </div>
      <div class="mu-meta">${data.running && !data.queued ? "Muse is thinking. New ideas show here in a minute or two. " : esc(data.next) + " "}
        This month: <b>${usd(data.spent_month)}</b> of <b>${usd(data.monthly_budget)}</b> ·
        the Boss sends Muse about every ${data.every_days} days (half price, up to ${usd(data.weekly_cost)}) ·
        Brainstorm now up to ${usd(data.round_cost)}.
        ${last ? `<br>Last round ${esc(ago(last.at))}${last.focus ? ` on "${esc(last.focus)}"` : ""}: ${last.kept} new${(last.dropped || []).length ? `, ${last.dropped.length} dropped as repeats or against the rules` : ""}.` : ""}</div>
      ${last && (last.dropped || []).length ? `<details><summary>What Muse dropped and why</summary><div class="mu-dropped">${last.dropped.map(esc).join("<br>")}</div></details>` : ""}
      <div class="mu-err">${esc(err)}</div>
      ${data.ideas.length ? `<div class="mu-kinds" role="group" aria-label="Show">
          <button data-kind="" aria-pressed="${!kind}">All</button>
          ${kinds.map(([k, label]) => `<button data-kind="${k}" aria-pressed="${kind === k}">${esc(label)}</button>`).join("")}</div>` : ""}
      ${fresh.length ? `<h3 style="margin:12px 0 0">New ideas for you</h3>${fresh.map((i, n) => ideaHtml(i, n + 1)).join("")}`
        : `<div class="mu-empty" style="margin-top:12px"><span class="big">💡</span>${data.ideas.length
            ? "No new ideas waiting. Muse brings more on its next round, or press Brainstorm now."
            : "Muse hasn't had its first round yet. Press Brainstorm now, or wait for its weekly round."}</div>`}
      ${group("building", "👍 Building", building, true)}
      ${group("later", "⏸ Later", later)}
      ${group("built", "✅ Built", built)}
      ${group("no", "👎 Not for me", no)}
    </section>`;
    const input = root.querySelector("#mu-focus");
    input.addEventListener("input", () => { focusDraft = input.value; });
    input.addEventListener("keydown", e => { if (e.key === "Enter") root.querySelector("#mu-run")?.click(); });
    if (active) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
    root.querySelector("#mu-run")?.addEventListener("click", async () => {
      busy = "run"; err = ""; render();
      try {
        const r = await call("/api/muse/run", {focus: focusDraft.trim() || null});
        focusDraft = "";
        window.toast?.("💡 " + esc(r.message));
      } catch (e) { err = e.message; }
      busy = ""; load();
    });
    root.querySelectorAll("[data-kind]").forEach(b => b.addEventListener("click", () => { kind = b.dataset.kind; render(); }));
    root.querySelectorAll("details[data-group]").forEach(el => el.addEventListener("toggle", () => {
      el.open ? openGroups.add(el.dataset.group) : openGroups.delete(el.dataset.group);
    }));
    const decide = async (id, act, reason) => {
      busy = act; err = ""; askingWhy = null; render();
      try {
        const r = await call(`/api/muse/ideas/${id}/${act}`, {reason: reason || null});
        window.toast?.(esc(r.message));
        if (act === "build") { openBrief.add(id); openGroups.add("building"); }
      } catch (e) { err = e.message; }
      busy = ""; load();
    };
    root.querySelectorAll("[data-act]").forEach(b => b.addEventListener("click", () => decide(+b.dataset.id, b.dataset.act)));
    root.querySelectorAll("[data-ask]").forEach(b => b.addEventListener("click", () => { askingWhy = +b.dataset.ask; render(); }));
    root.querySelectorAll("[data-send]").forEach(b => b.addEventListener("click", () => decide(+b.dataset.send, "send")));
    root.querySelectorAll("[data-pass]").forEach(b => b.addEventListener("click", () => decide(+b.dataset.pass, "pass", b.dataset.reason)));
    root.querySelectorAll("[data-brief]").forEach(b => b.addEventListener("click", () => {
      const id = +b.dataset.brief; openBrief.has(id) ? openBrief.delete(id) : openBrief.add(id); render();
    }));
    root.querySelectorAll("[data-copy]").forEach(b => b.addEventListener("click", async () => {
      const idea = data.ideas.find(i => i.id === +b.dataset.copy);
      try { await navigator.clipboard.writeText(idea.brief); window.toast?.("📋 Build brief copied. Paste it to Claude to build it."); }
      catch (e) { openBrief.add(idea.id); render(); window.toast?.("Select the brief below and copy it."); }
    }));
  }

  async function load() {
    try {
      data = await (await fetch("/api/muse")).json();
      render();
    } catch (e) { /* the dashboard shows its own offline state */ }
  }
  window.hqMuse = {reload: load};
  load();
  setInterval(() => { if (data?.running || document.body.dataset.tab === "ideas") load(); }, 15000);
  setInterval(load, 120000);
})();

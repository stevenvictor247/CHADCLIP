// Splits the dashboard into tabs (Home, Approvals, Boss, Campaigns, Pitch, Clips, Warrior Village, Etsy Village, Sweep, Ideas, Activity) so nothing needs a long scroll.
// The money strip and header stay above the tabs on every page. The last tab is remembered, and links like /#approvals open a tab.
(function () {
  // Each tab lists the ids of things inside the sections it shows. A section is found from any element inside it.
  // A section can be on more than one tab (the villages show on Home and, just Warrior Village, on its own tab).
  const TABS = [
    {id: "home", icon: "🏠", label: "Home", has: ["towns", "setup", "agents"]},
    {id: "approvals", icon: "✅", label: "Approvals", has: ["apprsection", "pending"],
     empty: "Nothing is waiting for your OK."},
    {id: "boss", icon: "👑", label: "Boss", has: ["chatlog"]},
    {id: "campaigns", icon: "🎯", label: "Campaigns", has: ["campsection"]},
    {id: "pitch", icon: "✉️", label: "Pitch", has: ["creatorsection", "leadsection"],
     empty: "No leads or creators to clip yet. Pitch and Scout put them here when they find some."},
    {id: "clips", icon: "🎞️", label: "Clips", has: ["allowedsection", "library"]},
    {id: "football", icon: "🏈", label: "Warrior Village", has: ["towns", "football"]},
    {id: "etsy", icon: "🛍️", label: "Etsy Village", has: ["towns", "etsy"]},
    {id: "sweep", icon: "🧹", label: "Sweep", has: ["sweep"]},
    {id: "ideas", icon: "💡", label: "Ideas", has: ["muse"]},
    {id: "activity", icon: "📜", label: "Activity", has: ["activity"]},
  ];
  const css = `
    #hq-tabs { position:sticky; top:0; z-index:6; display:flex; gap:6px; align-items:center; padding:8px 22px; overflow-x:auto;
               scrollbar-width:none; background:rgba(18,15,26,.88); border-bottom:1px solid var(--line); backdrop-filter:blur(10px); }
    #hq-tabs::-webkit-scrollbar { display:none; }
    #hq-tabs button, #hq-tabs a { flex:none; display:inline-flex; gap:6px; align-items:center; padding:8px 14px; border-radius:999px;
               background:transparent; color:var(--muted); border:1px solid transparent; font:inherit; font-size:14px; font-weight:800;
               text-decoration:none; cursor:pointer; box-shadow:none; transform:none; white-space:nowrap; }
    #hq-tabs button:hover, #hq-tabs a:hover { color:var(--text); border-color:var(--line); box-shadow:none; transform:none; }
    #hq-tabs button[aria-selected="true"] { color:#2a1405; background:linear-gradient(135deg, var(--accent), #ff8a5c); }
    #hq-tabs .badge { min-width:20px; padding:0 6px; border-radius:999px; background:var(--accent2); color:#2a0d1b; font-size:12px; text-align:center; }
    #hq-tabs .badge:empty { display:none; }
    #hq-tabs a { margin-left:auto; }
    #hq-tabs a { display:none; }
    body.tabbed main { display:block; max-width:1200px; margin:0 auto; }
    ${TABS.map(t => `body[data-tab="${t.id}"] [data-tab]:not([data-tab~="${t.id}"]) { display:none !important; }`).join("\n    ")}
    body.tabbed .world[data-tab] { margin-bottom:18px; }
    body.tabbed section { scroll-margin-top:64px; }
    @media (max-width:960px) { #hq-tabs { padding:8px 14px; } }
    @media (max-width:600px) {
      header { gap:8px; } .stats { display:none; } .stat { min-width:0; flex:1 1 40%; padding:6px 8px 6px 34px; } .stat .ico { left:8px; font-size:16px; }
      .stat b { font-size:16px; } .logo .mark { width:30px; height:30px; } header .hqbar-btn { margin-left:auto; }
    }
    @media (max-width:600px) { #hq-tabs button, #hq-tabs a { padding:7px 11px; font-size:13px; gap:4px; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const world = document.getElementById("world"), main = document.querySelector("main");
  if (!main) return;
  const nav = document.createElement("nav");
  nav.id = "hq-tabs";
  nav.setAttribute("role", "tablist");
  nav.setAttribute("aria-label", "HQ sections");
  const key = i => i < 9 ? i + 1 : i === 9 ? 0 : null;   // number keys 1-9, then 0 for the tenth tab
  nav.innerHTML = TABS.map((t, i) => `<button role="tab" data-go="${t.id}" title="${t.label}${key(i) === null ? "" : ` (press ${key(i)})`}">` +
    `<span>${t.icon}</span><span>${t.label}</span><span class="badge" id="tab-badge-${t.id}"></span></button>`).join("") +
    `<a href="/settings" title="API keys, accounts and options">⚙️ Settings</a>`;
  document.body.insertAdjacentElement("afterbegin", nav);   // first thing on the page, so it stays pinned while the rest scrolls

  // Tag every section with its tab. A tab whose sections are all hidden (nothing to show yet) gets a friendly note instead.
  for (const t of TABS) {
    let last = null;
    for (const id of t.has) {
      const el = document.getElementById(id);
      const sec = el && (el.matches("section, #towns, #football, #sweep, #muse") ? el : el.closest("section"));
      if (sec) { sec.dataset.tab = sec.dataset.tab && sec.dataset.tab !== t.id ? sec.dataset.tab + " " + t.id : t.id; last = sec; }
    }
    if (t.empty && last) {
      last.insertAdjacentHTML("afterend", `<section data-tab="${t.id}" class="tab-empty" id="tab-empty-${t.id}">` +
        `<div class="empty"><span class="big">${t.icon}</span>${t.empty}</div></section>`);
    }
  }
  document.body.classList.add("tabbed");

  const shown = el => el && el.style.display !== "none";
  function refresh() {
    for (const t of TABS) {
      const note = document.getElementById("tab-empty-" + t.id);
      if (!note) continue;
      const others = [...document.querySelectorAll(`[data-tab~="${t.id}"]:not(.tab-empty)`)];
      note.style.display = others.some(shown) ? "none" : "";
    }
    // Approvals badge: approval cards plus clips waiting for a yes or no.
    const appr = shown(document.getElementById("apprsection")) ? +document.getElementById("apprcount")?.textContent || 0 : 0;
    const clips = shown(document.getElementById("pendingcount")) ? +document.getElementById("pendingcount").textContent || 0 : 0;
    document.getElementById("tab-badge-approvals").textContent = appr + clips || "";
  }

  const valid = id => TABS.some(t => t.id === id);
  function show(id, remember = true) {
    if (!valid(id)) id = "home";
    document.body.dataset.tab = id;
    nav.querySelectorAll("button[data-go]").forEach(b => {
      const on = b.dataset.go === id;
      b.setAttribute("aria-selected", on);
      if (on) nav.scrollLeft = Math.max(0, b.offsetLeft - (nav.clientWidth - b.offsetWidth) / 2);   // keep it in view on a phone
    });
    if (remember) {
      try { localStorage.setItem("hq-tab", id); } catch (e) {}
      if (location.hash !== "#" + id) history.replaceState(null, "", "#" + id);
    }
    // If the page was scrolled down, jump back to the top of the new tab.
    const first = document.querySelector(`[data-tab~="${id}"]`);
    if (window.scrollY > 0 && first) window.scrollTo({top: Math.max(0, first.getBoundingClientRect().top + window.scrollY - nav.offsetHeight - 10)});
    refresh();
  }
  // Opens the tab holding an element (by id). world.js and the setup card use it before scrolling to something.
  function showFor(elId) {
    const sec = document.getElementById(elId)?.closest("[data-tab]");
    if (sec && !sec.dataset.tab.split(" ").includes(document.body.dataset.tab)) show(sec.dataset.tab.split(" ")[0]);
  }
  window.hqTabs = {show, showFor};

  nav.addEventListener("click", e => { const b = e.target.closest("button[data-go]"); if (b) show(b.dataset.go); });
  window.addEventListener("hashchange", () => valid(location.hash.slice(1)) && show(location.hash.slice(1)));
  // The "Waiting for you" number in the header opens Approvals.
  const waiting = document.getElementById("s-pending");
  if (waiting) { waiting.style.cursor = "pointer"; waiting.title = "Open Approvals"; waiting.onclick = () => show("approvals"); }
  // Number keys 1-9 and 0 switch tabs, unless you're typing.
  document.addEventListener("keydown", e => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
    const t = /^[0-9]$/.test(e.key) ? TABS[e.key === "0" ? 9 : +e.key - 1] : null;
    if (t) show(t.id);
  });

  let start = location.hash.slice(1);
  if (start === "boss") setTimeout(() => document.getElementById("chatinput")?.focus({preventScroll: true}), 300);
  if (!valid(start)) { try { start = localStorage.getItem("hq-tab"); } catch (e) { start = null; } }
  show(start || "home", valid(location.hash.slice(1)));
  setInterval(refresh, 1000);
})();

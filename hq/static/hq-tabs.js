// Splits the dashboard into tabs (Home, Approvals, Boss, Campaigns, Pitch, Clips, Warrior Village, Etsy Village, Sweep, Ideas, Activity) so nothing needs a long scroll.
// The money strip and header stay above the tabs on every page. The last tab is remembered, and links like /#approvals open a tab.
(function () {
  // Each tab lists the ids of things inside the sections it shows. A section is found from any element inside it.
  // A section can be on more than one tab (the villages show on Home and, just Warrior Village, on its own tab).
  const TABS = [
    {id: "home", icon: "🏠", lu: "house", label: "Home", has: ["towns", "setup", "agents"]},
    {id: "approvals", icon: "✅", lu: "circle-check-big", label: "Approvals", has: ["apprsection", "pending", "rerun"],
     empty: "Nothing is waiting for your OK."},
    {id: "boss", icon: "👑", lu: "crown", label: "Boss", has: ["chatlog"]},
    {id: "campaigns", icon: "🎯", lu: "target", label: "Campaigns", has: ["campsection"]},
    {id: "pitch", icon: "✉️", lu: "mail", label: "Pitch", appr: "pitch", has: ["queue", "nudge", "rerun", "creatorsection", "leadsection"],
     empty: "No leads or creators to clip yet. Pitch and Scout put them here when they find some."},
    {id: "clips", icon: "🎞️", lu: "clapperboard", label: "Clips", appr: "clips", has: ["allowedsection", "library"]},
    {id: "football", icon: "🏈", lu: "trophy", label: "Warrior Village", appr: "football", has: ["towns", "football"]},
    {id: "etsy", icon: "🛍️", lu: "shopping-bag", label: "Etsy Village", appr: "etsy", has: ["towns", "etsy"]},
    {id: "sweep", icon: "🧹", lu: "brush", label: "Sweep", appr: "other", has: ["sweep"]},
    {id: "ideas", icon: "💡", lu: "lightbulb", label: "Ideas", appr: "ideas", has: ["muse"]},
    {id: "activity", icon: "📜", lu: "scroll-text", label: "Activity", has: ["activity"]},
  ];
  // Approvals are split by type. Each tab with an `appr` group gets an "Approvals" drop-down option showing only that type;
  // the Approvals tab shows them all, with a chip row to narrow it. index.html's renderApprovals does the sorting (window.hqApprCounts).
  const GROUPS = [
    {id: "all", icon: "✅", lu: "circle-check-big", label: "All approvals"},
    {id: "clips", icon: "🎞️", lu: "clapperboard", label: "Clips"},
    {id: "pitch", icon: "✉️", lu: "mail", label: "Emails"},
    {id: "etsy", icon: "🛍️", lu: "shopping-bag", label: "Etsy"},
    {id: "football", icon: "🏈", lu: "trophy", label: "Football"},
    {id: "ideas", icon: "💡", lu: "lightbulb", label: "Ideas"},
    {id: "other", icon: "🧹", lu: "brush", label: "Other"},
  ];
  // Icons are Lucide line icons (vendor/lucide.min.js); if that file didn't load, the emoji shows instead.
  const ic = x => window.lucide ? `<i data-lucide="${x.lu}" aria-hidden="true"></i>` : x.icon;
  const css = `
    #hq-tabs svg.lucide, .ddmenu svg.lucide, #apprgroups svg.lucide { width:16px; height:16px; stroke-width:2.2; flex:none; vertical-align:-3px; }
    .empty .big svg.lucide { width:34px; height:34px; stroke-width:1.8; }
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
    #hq-tabs .dd { flex:none; }
    .ddmenu { display:none; position:fixed; z-index:9; min-width:190px; padding:6px; border-radius:12px; background:rgba(26,22,38,.97);
               border:1px solid var(--line); box-shadow:0 12px 30px rgba(0,0,0,.45); }
    .ddmenu.open { display:block; }
    .ddmenu button { display:flex; gap:8px; align-items:center; width:100%; padding:9px 12px; border-radius:8px; justify-content:flex-start; background:transparent; color:var(--muted);
               border:1px solid transparent; font:inherit; font-size:14px; font-weight:800; cursor:pointer; box-shadow:none; transform:none; white-space:nowrap; }
    .ddmenu button:hover { color:var(--text); background:rgba(255,255,255,.08); box-shadow:none; transform:none; }
    .ddmenu .badge { min-width:20px; margin-left:auto; padding:0 6px; border-radius:999px; background:var(--accent2); color:#2a0d1b; font-size:12px; text-align:center; }
    .ddmenu button[aria-current="true"] { color:var(--text); background:rgba(255,255,255,.08); }
    .ddmenu .badge:empty { display:none; }
    #apprgroups { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 12px; }
    #apprgroups button { padding:6px 12px; border-radius:999px; font-size:13px; font-weight:800; background:transparent; color:var(--muted); border:1px solid var(--line); box-shadow:none; transform:none; }
    #apprgroups button[aria-pressed="true"] { color:#2a1405; background:linear-gradient(135deg, var(--accent), #ff8a5c); border-color:transparent; }
    #apprgroups .badge { margin-left:4px; padding:0 6px; border-radius:999px; background:var(--accent2); color:#2a0d1b; font-size:12px; }
    #apprgroups .badge:empty { display:none; }
    #apprtitle { display:none; margin:0 0 10px; font-weight:800; color:var(--muted); }
    body[data-sub="approvals"] #apprgroups, body:not([data-tab="approvals"]) #apprgroups { display:none; }
    body[data-sub="approvals"] #apprtitle { display:block; }
    /* On a tab other than Approvals, the approval cards only show from that tab's drop-down, and then they are all that shows. */
    body:not([data-tab="approvals"]):not([data-sub="approvals"]) [data-appr] { display:none !important; }
    body[data-sub="approvals"]:not([data-tab="approvals"]) [data-tab]:not([data-appr]) { display:none !important; }
    body[data-agroup]:not([data-agroup="all"]):not([data-agroup="clips"]) [data-appr="clips"] { display:none !important; }
    body[data-agroup="clips"] [data-appr="list"] { display:none !important; }
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
  const tabBtn = (t, i) => `<button role="tab" data-go="${t.id}" title="${t.label}${key(i) === null ? "" : ` (press ${key(i)})`}">` +
    `<span>${ic(t)}</span><span>${t.label}</span><span class="badge" id="tab-badge-${t.id}"></span></button>`;
  const menuItems = t => t.id === "approvals"
    ? GROUPS.map(g => `<button role="menuitem" data-go="approvals" data-group="${g.id}"><span>${ic(g)}</span><span>${g.label}</span><span class="badge" data-gcount="${g.id}"></span></button>`).join("")
    : `<button role="menuitem" data-go="${t.id}"><span>${ic(t)}</span><span>${t.label}</span></button>` +
      `<button role="menuitem" data-go="${t.id}" data-sub="approvals"><span>${ic(GROUPS[0])}</span><span>Approvals</span><span class="badge" data-gcount="${t.appr}"></span></button>`;
  nav.innerHTML = TABS.map((t, i) => t.appr || t.id === "approvals"
      ? `<div class="dd">${tabBtn(t, i)}<div class="ddmenu" role="menu">${menuItems(t)}</div></div>` : tabBtn(t, i)).join("") +
    `<a href="/settings" title="API keys, accounts and options">${window.lucide ? '<i data-lucide="settings" aria-hidden="true"></i>' : "⚙️"} Settings</a>`;
  document.body.insertAdjacentElement("afterbegin", nav);   // first thing on the page, so it stays pinned while the rest scrolls

  // Tag every section with its tab. A tab whose sections are all hidden (nothing to show yet) gets a friendly note instead.
  for (const t of TABS) {
    let last = null;
    for (const id of t.has) {
      const el = document.getElementById(id);
      const sec = el && (el.matches("section, #towns, #football, #etsy, #queue, #nudge, #rerun, #sweep, #muse") ? el : el.closest("section"));
      if (sec) { sec.dataset.tab = sec.dataset.tab && sec.dataset.tab !== t.id ? sec.dataset.tab + " " + t.id : t.id; last = sec; }
    }
    if (t.empty && last) {
      last.insertAdjacentHTML("afterend", `<section data-tab="${t.id}" class="tab-empty" id="tab-empty-${t.id}">` +
        `<div class="empty"><span class="big">${ic(t)}</span>${t.empty}</div></section>`);
    }
  }
  // The approval cards (everything waiting + clips waiting) also live under every tab that has an Approvals option.
  const apprTabs = TABS.filter(t => t.appr).map(t => t.id);
  for (const [id, kind] of [["apprsection", "list"], ["pending", "clips"]]) {
    const sec = document.getElementById(id)?.closest("section");
    if (sec) { sec.dataset.appr = kind; sec.dataset.tab = [...new Set([...(sec.dataset.tab || "").split(" ").filter(Boolean), ...apprTabs])].join(" "); }
  }
  const apprSec = document.getElementById("apprsection");
  if (apprSec) apprSec.insertAdjacentHTML("afterbegin", `<div id="apprtitle"></div><div id="apprgroups">` +
    GROUPS.map(g => `<button data-group="${g.id}"><span>${ic(g)}</span> ${g.label.replace("All approvals", "All")}<span class="badge" data-gcount="${g.id}"></span></button>`).join("") + `</div>`);
  document.body.classList.add("tabbed");

  const shown = el => el && el.style.display !== "none";
  function refresh() {
    for (const t of TABS) {
      const note = document.getElementById("tab-empty-" + t.id);
      if (!note) continue;
      const others = [...document.querySelectorAll(`[data-tab~="${t.id}"]:not(.tab-empty)`)];
      note.style.display = others.some(shown) ? "none" : "";
    }
    // Approvals badges: every type waiting (cards plus clips waiting for a yes or no) on the Approvals tab, one type on each other tab.
    document.getElementById("tab-badge-approvals").textContent = (window.hqApprCounts || {}).all || "";
    const c = window.hqApprCounts || {};
    document.querySelectorAll("#hq-tabs [data-gcount], .ddmenu [data-gcount]").forEach(b => b.textContent = c[b.dataset.gcount] || "");
    document.querySelectorAll("#apprgroups [data-gcount]").forEach(b => b.textContent = c[b.dataset.gcount] || "");
    for (const t of TABS) if (t.appr) document.getElementById("tab-badge-" + t.id).textContent = c[t.appr] || "";
  }

  const valid = id => TABS.some(t => t.id === id);
  const hasAppr = id => !!TABS.find(t => t.id === id)?.appr;
  let group = "all";   // which type the Approvals tab is narrowed to
  function show(id, remember = true, sub = "", grp) {
    if (!valid(id)) id = "home";
    if (sub === "approvals" && !hasAppr(id)) sub = "";
    if (grp && GROUPS.some(g => g.id === grp)) group = grp;
    document.body.dataset.tab = id;
    document.body.dataset.sub = sub;
    document.body.dataset.agroup = sub ? TABS.find(t => t.id === id).appr : id === "approvals" ? group : "all";
    const t = TABS.find(t => t.id === id);
    const title = document.getElementById("apprtitle");
    if (title) title.textContent = sub ? `${t.icon} ${t.label}: approvals` : "";
    nav.querySelectorAll("[role=tab][data-go]").forEach(b => {
      const on = b.dataset.go === id;
      b.setAttribute("aria-selected", on);
      if (on) nav.scrollLeft = Math.max(0, b.offsetLeft - (nav.clientWidth - b.offsetWidth) / 2);   // keep it in view on a phone
    });
    menuBox.querySelectorAll("[role=menuitem]").forEach(b => b.setAttribute("aria-current",
      b.dataset.go === id && (b.dataset.group ? b.dataset.group === group : (b.dataset.sub || "") === sub)));
    document.querySelectorAll("#apprgroups [data-group]").forEach(b => b.setAttribute("aria-pressed", b.dataset.group === group));
    closeMenus();
    if (remember) {
      try { localStorage.setItem("hq-tab", id + (sub ? "/" + sub : "")); } catch (e) {}
      const h = "#" + id + (sub ? "/" + sub : "");
      if (location.hash !== h) history.replaceState(null, "", h);
    }
    // If the page was scrolled down, jump back to the top of the new tab.
    const first = document.querySelector(`[data-tab~="${id}"]`);
    if (window.scrollY > 0 && first) window.scrollTo({top: Math.max(0, first.getBoundingClientRect().top + window.scrollY - nav.offsetHeight - 10)});
    refresh();
    document.dispatchEvent(new Event("hq-tab"));   // index.html redraws the approval cards for the new type
  }
  // Opens the tab holding an element (by id). world.js and the setup card use it before scrolling to something.
  function showFor(elId) {
    const sec = document.getElementById(elId)?.closest("[data-tab]");
    if (sec?.dataset.appr) { if (document.body.dataset.tab !== "approvals" && document.body.dataset.sub !== "approvals") show("approvals"); return; }
    if (sec && !sec.dataset.tab.split(" ").includes(document.body.dataset.tab)) show(sec.dataset.tab.split(" ")[0]);
  }
  window.hqTabs = {show, showFor, group: () => document.body.dataset.agroup || "all"};

  // Drop-downs: hover opens them on a computer; on a phone (no hover) tapping a tab opens its menu as well as the tab.
  // The menus live outside the nav (it scrolls sideways and clips anything dropping out of it), positioned under their tab.
  const menus = [...nav.querySelectorAll(".ddmenu")];
  const menuBox = document.createElement("div");
  menuBox.id = "hq-menus";
  document.body.appendChild(menuBox);
  menus.forEach(m => { m._dd = m.parentElement; menuBox.appendChild(m); });
  function closeMenus() { menus.forEach(m => m.classList.remove("open")); }
  let openedAt = 0;
  function openMenu(dd) {
    openedAt = Date.now();
    const m = menus.find(x => x._dd === dd), r = dd.getBoundingClientRect();
    closeMenus();
    m.style.top = r.bottom - 2 + "px";
    m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
    m.classList.add("open");
    m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  }
  const canHover = () => matchMedia("(hover: hover)").matches;
  let hideTimer;
  nav.querySelectorAll(".dd").forEach(dd => {
    const m = menus.find(x => x._dd === dd);
    m.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    m.addEventListener("mouseleave", () => { if (canHover()) hideTimer = setTimeout(closeMenus, 180); });
    dd.addEventListener("mouseenter", () => { if (canHover()) { clearTimeout(hideTimer); openMenu(dd); } });
    dd.addEventListener("mouseleave", () => { if (canHover()) hideTimer = setTimeout(closeMenus, 180); });
    dd.addEventListener("focusin", () => { if (canHover()) openMenu(dd); });
  });
  nav.addEventListener("scroll", () => { if (Date.now() - openedAt > 400) closeMenus(); });   // (show() recentres the tab, which also scrolls)
  document.addEventListener("click", e => { if (!e.target.closest(".dd, .ddmenu")) closeMenus(); });
  const onNavClick = e => {
    const b = e.target.closest("button[data-go]");
    if (!b) return;
    const dd = b.closest(".dd");
    if (b.getAttribute("role") === "tab" && dd && !canHover()) {   // phone: show the tab and offer its menu
      show(b.dataset.go, true, "", b.dataset.go === "approvals" ? group : undefined);
      openMenu(dd);
      return;
    }
    show(b.dataset.go, true, b.dataset.sub || "", b.dataset.group);
  };
  nav.addEventListener("click", onNavClick);
  menuBox.addEventListener("click", onNavClick);
  document.addEventListener("click", e => { const g = e.target.closest("#apprgroups [data-group]"); if (g) show("approvals", true, "", g.dataset.group); });
  const parse = h => { const [id, sub] = h.replace(/^#/, "").split("/"); return {id, sub: sub === "approvals" ? "approvals" : ""}; };
  window.addEventListener("hashchange", () => { const h = parse(location.hash); if (valid(h.id)) show(h.id, true, h.sub); });
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
  const startSub = parse(start || "");
  start = startSub.id;
  if (start === "boss") setTimeout(() => document.getElementById("chatinput")?.focus({preventScroll: true}), 300);
  let fromHash = valid(start), sub = startSub.sub;
  if (!fromHash) { try { const p = parse(localStorage.getItem("hq-tab") || ""); start = p.id; sub = p.sub; } catch (e) { start = null; } }
  show(start || "home", fromHash, sub);
  if (window.lucide) lucide.createIcons();   // swaps every <i data-lucide> placed above for its SVG
  setInterval(refresh, 1000);
})();

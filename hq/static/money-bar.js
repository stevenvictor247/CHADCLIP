// The money strip at the very top of the dashboard: spent, made and net, with Add expense / Add income.
// The dashboard calls HQMoney.update(state.money) on each refresh.
(function () {
  const css = `
    #hq-money { position:relative; z-index:2; display:flex; gap:10px; align-items:center; flex-wrap:wrap; padding:10px 22px;
                background:rgba(18,15,26,.85); border-bottom:1px solid var(--line); backdrop-filter:blur(8px); }
    #hq-money .mtile { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:6px 14px; min-width:130px; }
    #hq-money .mtile b { display:block; font-size:20px; font-variant-numeric:tabular-nums; }
    #hq-money .mtile span { color:var(--muted); font-size:12px; }
    #hq-money .spent b { color:#fca5a5; } #hq-money .made b { color:var(--good); }
    #hq-money .net.up b { color:var(--good); } #hq-money .net.down b { color:#fca5a5; }
    #hq-money .mperiod { display:flex; border:1px solid var(--line); border-radius:10px; overflow:hidden; }
    #hq-money .mperiod button, #hq-money .mbtn { background:var(--panel); color:var(--muted); border:0; border-radius:0; padding:6px 10px;
               font:inherit; font-size:13px; font-weight:700; cursor:pointer; box-shadow:none; transform:none; }
    #hq-money .mperiod button.on { background:var(--accent); color:#2a1405; }
    #hq-money .mbtn { border:1px solid var(--line); border-radius:10px; color:var(--text); }
    #hq-money .mbtn:hover { border-color:var(--accent); }
    #hq-money .mright { margin-left:auto; display:flex; gap:8px; flex-wrap:wrap; }
    #hq-money-panel { position:relative; z-index:2; display:none; padding:10px 22px 12px; background:rgba(18,15,26,.92);
                      border-bottom:1px solid var(--line); font-size:13px; }
    #hq-money-panel.open { display:block; }
    #hq-money-panel form { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:6px; }
    #hq-money-panel input { flex:0 1 auto; padding:6px 9px; }
    #hq-money-panel .mamount { width:110px; } #hq-money-panel .mnote { flex:1 1 220px; }
    #hq-money-panel .mrow { display:flex; gap:10px; align-items:center; padding:4px 0; border-top:1px solid var(--line); }
    #hq-money-panel .mrow .amt { font-variant-numeric:tabular-nums; min-width:80px; font-weight:700; }
    #hq-money-panel .mrow .x { margin-left:auto; background:transparent; color:var(--muted); border:1px solid var(--line); padding:2px 8px; }
    #hq-money-panel .merr { color:var(--bad); }
    @media (max-width:960px) { #hq-money, #hq-money-panel { padding-left:14px; padding-right:14px; } #hq-money .mright { margin-left:0; } }`;
  document.head.insertAdjacentHTML("beforeend", `<style>${css}</style>`);

  const LABELS = {today: "today", month: "this month", all: "all time"};
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const usd = n => (n < 0 ? "−$" : "$") + Math.abs(n).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
  let period = "month", data = null, panel = null;   // panel: null, "expense", "income" or "history"
  try { period = localStorage.getItem("hq-money-period") || period; } catch (e) {}

  document.body.insertAdjacentHTML("afterbegin", `
    <div id="hq-money">
      <div class="mtile spent" title=""><b id="m-spent">$0.00</b><span id="m-spent-l">Spent</span></div>
      <div class="mtile made" title=""><b id="m-made">$0.00</b><span id="m-made-l">Made</span></div>
      <div class="mtile net"><b id="m-net">$0.00</b><span id="m-net-l">Net</span></div>
      <div class="mtile won" title="Streamers who replied to a pitch and paid (marked won by Closer)"><b id="m-won">0</b><span>Won clients</span></div>
      <div class="mperiod">${Object.entries({today: "Today", month: "Month", all: "All time"})
        .map(([k, v]) => `<button data-p="${k}">${v}</button>`).join("")}</div>
      <div class="mright">
        <button class="mbtn" data-panel="expense">➖ Add expense</button>
        <button class="mbtn" data-panel="income">➕ Add income</button>
        <button class="mbtn" data-panel="history">🧾 History</button>
      </div>
    </div>
    <div id="hq-money-panel"></div>`);
  const bar = document.getElementById("hq-money"), box = document.getElementById("hq-money-panel");

  bar.querySelectorAll(".mperiod button").forEach(b => b.onclick = () => {
    period = b.dataset.p;
    try { localStorage.setItem("hq-money-period", period); } catch (e) {}
    draw();
  });
  bar.querySelectorAll("[data-panel]").forEach(b => b.onclick = () => {
    panel = panel === b.dataset.panel ? null : b.dataset.panel;
    drawPanel();
  });

  function draw() {
    bar.querySelectorAll(".mperiod button").forEach(b => b.classList.toggle("on", b.dataset.p === period));
    if (!data) return;
    document.getElementById("m-won").textContent = data.won_clients || 0;
    const p = data.periods[period], when = LABELS[period];
    document.getElementById("m-spent").textContent = usd(p.spent);
    document.getElementById("m-made").textContent = usd(p.made);
    document.getElementById("m-net").textContent = usd(p.net);
    document.getElementById("m-spent-l").textContent = "Spent " + when;
    document.getElementById("m-made-l").textContent = "Made " + when;
    document.getElementById("m-net-l").textContent = "Net " + when;
    bar.querySelector(".spent").title = `Claude ${usd(p.claude)} + your logged expenses ${usd(p.expenses)}`;
    bar.querySelector(".made").title = `Campaign earnings ${usd(p.campaigns)} + your logged income ${usd(p.income)}\n` +
      "Only counts money you log here or record on a campaign. HQ can't see your bank or payout accounts.";
    bar.querySelector(".net").className = "mtile net " + (p.net > 0 ? "up" : p.net < 0 ? "down" : "");
  }

  function drawPanel(error) {
    if (!panel) { box.className = ""; box.innerHTML = ""; return; }
    box.className = "open";
    if (panel === "history") {
      const rows = (data?.entries || []).map(e => `<div class="mrow"><span>${esc(e.day)}</span>
        <span class="amt" style="color:${e.kind === "income" ? "var(--good)" : "#fca5a5"}">${e.kind === "income" ? "+" : "−"}${usd(e.amount_usd)}</span>
        <span>${esc(e.note) || "<span class='muted'>no note</span>"}</span>
        <button class="x" data-del="${e.id}" title="Delete this entry">Delete</button></div>`).join("");
      box.innerHTML = `<div class="muted" style="margin-bottom:6px">Expenses and income you've logged (Claude costs and campaign earnings are added automatically).</div>` +
        (rows || `<div class="muted">Nothing logged yet.</div>`);
      box.querySelectorAll("[data-del]").forEach(b => b.onclick = () => send("DELETE", "/api/money/" + b.dataset.del));
      return;
    }
    const income = panel === "income";
    const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    box.innerHTML = `<form id="m-form">
        <b>${income ? "➕ Money you made" : "➖ Money you spent"}</b>
        <input class="mamount" id="m-amount" type="number" min="0.01" step="0.01" placeholder="Amount $" required>
        <input class="mnote" id="m-note" maxlength="200" placeholder="${income ? "Where from, e.g. Whop payout, Etsy sale" : "What for, e.g. CapCut subscription"}">
        <input id="m-day" type="date" value="${today}">
        <button>Save</button>
      </form>
      <div class="muted">${income ? "HQ only knows about money you log here or record on a campaign. It can't see your bank, Whop or Etsy accounts." :
        "Claude costs are counted for you. Log other costs here: subscriptions, tools, ads."}</div>
      ${error ? `<div class="merr">${esc(error)}</div>` : ""}`;
    document.getElementById("m-amount").focus();
    document.getElementById("m-form").onsubmit = e => {
      e.preventDefault();
      send("POST", "/api/money", {kind: panel, amount_usd: parseFloat(document.getElementById("m-amount").value),
                                  note: document.getElementById("m-note").value, day: document.getElementById("m-day").value});
    };
  }

  async function send(method, url, body) {
    let r;
    try {
      r = await fetch(url, {method, headers: {"Content-Type": "application/json", "X-HQ": "1"}, body: body ? JSON.stringify(body) : undefined});
    } catch (e) { return drawPanel("Couldn't reach HQ. Is it running?"); }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return drawPanel(typeof j.detail === "string" ? j.detail : "That didn't save. Check the amount and date.");
    if (method === "POST") panel = null;
    update(j.money);
  }

  function update(money) {
    if (!money) return;
    data = money;
    draw();
    if (panel === "history") drawPanel();   // keep forms untouched while typing
  }
  window.HQMoney = {update};
  draw();
})();

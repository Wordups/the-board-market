const FACTOR_MAX = {
  technical: 20,
  catalyst: 20,
  relative_strength: 15,
  smart_money: 15,
  macro: 15,
  sentiment: 15,
};

const state = {
  data: null,
  tier: "ALL",
  query: "",
  selected: null,
  bankroll: Math.min(1000, Math.max(100, Number(localStorage.getItem("board-bankroll")) || 1000)),
  saved: JSON.parse(localStorage.getItem("board-shortlist") || "[]"),
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const money = (value) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
const compactMoney = (value) => Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const clean = (value) => String(value ?? "").replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
const slug = (value) => String(value).toLowerCase().replaceAll("_", " ");
const HAS_PRIVATE_API = !window.BOARD_PUBLIC_STATIC && ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);

let optionType = "CALL";

function calculateOptionPayoff() {
  const strike = Math.max(0, Number($("#option-strike").value) || 0);
  const premium = Math.max(0, Number($("#option-premium").value) || 0);
  const expiryPrice = Math.max(0, Number($("#option-expiry-price").value) || 0);
  const contracts = Math.min(100, Math.max(1, Math.round(Number($("#option-contracts").value) || 1)));
  const multiplier = 100;
  const intrinsic = optionType === "CALL" ? Math.max(expiryPrice - strike, 0) : Math.max(strike - expiryPrice, 0);
  const cost = premium * multiplier * contracts;
  const pnl = (intrinsic - premium) * multiplier * contracts;
  const breakeven = optionType === "CALL" ? strike + premium : Math.max(strike - premium, 0);
  const returnPct = cost ? pnl / cost * 100 : 0;
  const equation = optionType === "CALL"
    ? `max($${expiryPrice.toFixed(2)} stock − $${strike.toFixed(2)} strike, $0) − $${premium.toFixed(2)} premium`
    : `max($${strike.toFixed(2)} strike − $${expiryPrice.toFixed(2)} stock, $0) − $${premium.toFixed(2)} premium`;

  $("#option-cost").textContent = compactMoney(cost);
  $("#option-breakeven").textContent = money(breakeven);
  $("#option-pnl").textContent = `${pnl >= 0 ? "+" : "−"}${compactMoney(Math.abs(pnl))}`;
  $("#option-return").textContent = `${returnPct >= 0 ? "+" : "−"}${Math.abs(returnPct).toFixed(1)}%`;
  $("#option-equation").textContent = `(${equation}) × 100 shares × ${contracts} contract${contracts === 1 ? "" : "s"}`;
  [$("#option-pnl"), $("#option-return")].forEach(node => {
    node.classList.toggle("gain", pnl >= 0);
    node.classList.toggle("loss", pnl < 0);
  });
}

async function loadPaperPilot() {
  if (!HAS_PRIVATE_API) {
    renderPaperPilot(null);
    $("#pilot-status-label").textContent = "Private backend only";
    $("#pilot-caption").textContent = "Paper state and broker data are intentionally excluded from public Pages.";
    $("#pilot-start").disabled = true;
    return;
  }
  try {
    const response = await fetch("/api/paper-pilot", { cache: "no-store" });
    if (!response.ok) throw new Error("Paper Pilot API unavailable");
    renderPaperPilot(await response.json());
  } catch (error) {
    renderPaperPilot(null, "Paper Pilot requires the local FastAPI server.");
  }
}

async function loadConnectionStatus() {
  if (!HAS_PRIVATE_API) {
    $("#schwab-connection-state").textContent = "PRIVATE BACKEND ONLY";
    $("#schwab-connection-copy").textContent = "The public dashboard never receives Schwab credentials, tokens, balances, or positions. Configure and authorize Schwab only on the private backend.";
    return;
  }
  try {
    const response = await fetch("/api/connections/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Connection status unavailable");
    const status = await response.json();
    const schwab = status.schwab;
    const stateNode = $("#schwab-connection-state");
    if (schwab.configured && schwab.authorized) {
      stateNode.textContent = "READ-ONLY CONNECTED";
      stateNode.classList.add("ready");
      $("#schwab-connection-copy").textContent = "Schwab is authorized for read-only account, position, transaction, and quote sync. Order routing remains disabled.";
    } else if (schwab.configured) {
      stateNode.textContent = "READY TO AUTHORIZE";
      stateNode.classList.add("ready");
      $("#schwab-connection-copy").textContent = "App credentials are configured. The next step is completing Schwab OAuth authorization; order routing remains disabled.";
    } else {
      stateNode.textContent = "NEEDS APP CREDENTIALS";
      $("#schwab-connection-copy").textContent = "The read-only connector is present. Create a personal Schwab developer app, then add its credentials through the local environment file.";
    }
  } catch (error) {
    $("#schwab-connection-state").textContent = "LOCAL API OFFLINE";
  }
}

// Live trading controls — private backend ONLY. The public static page never
// renders these (HAS_PRIVATE_API is false there), so login/order routes are
// unreachable from GitHub Pages.
async function loadLive() {
  const panel = $("#live-controls");
  if (!panel) return;
  if (!HAS_PRIVATE_API) { panel.hidden = true; return; }
  panel.hidden = false;
  try {
    const res = await fetch("/api/live", { cache: "no-store" });
    if (!res.ok) throw new Error("live api");
    renderLive(await res.json());
  } catch (error) {
    $("#live-state").textContent = "local API offline";
  }
}

function renderLive(live) {
  const deployed = Number(live.deployed ?? 0).toFixed(2);
  const cap = Number(live.capital_cap ?? 100).toFixed(0);
  const enabled = Boolean(live.live_trading_enabled);
  $("#live-state").textContent =
    `${enabled ? "LIVE" : "OFF"} · $${deployed}/$${cap} deployed · ${live.authorized ? "logged in" : "not logged in"}`;
  $("#live-run").disabled = !(enabled && live.authorized && live.account_configured);
}

async function runLive(dryRun) {
  if (!dryRun && !window.confirm("Place REAL orders within your $100 cap? This spends real money.")) return;
  try {
    const res = await fetch("/api/live/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dry_run: dryRun }),
    });
    const data = await res.json();
    if (!res.ok) { $("#live-note").textContent = data.detail || "Live run failed."; return; }
    $("#live-note").textContent =
      `${dryRun ? "Preview" : "Placed"}: ${data.last_run_placed ?? 0} setup(s), $${Number(data.deployed ?? 0).toFixed(2)} deployed.`;
    renderLive(data);
  } catch (error) {
    $("#live-note").textContent = "Live run error — is the local backend running?";
  }
}

function renderPaperPilot(pilot, errorMessage = "") {
  const idle = !pilot || pilot.status === "idle";
  const active = pilot && pilot.status === "active";
  const start = pilot?.starting_bankroll ?? 100;
  const totalPnl = pilot ? pilot.equity - start : 0;
  const positions = pilot?.positions || [];
  const statusLabel = idle ? "Not started" : active ? "Paper active" : "Waiting for setup";

  $("#pilot-status-label").textContent = statusLabel;
  $("#pilot-status-dot").className = `pilot-status-dot${active ? " active" : pilot?.status === "waiting" ? " waiting" : ""}`;
  $("#pilot-caption").textContent = idle ? "No account credentials. No order API. No real capital." : `${positions.length} open · ${pilot.history.length} closed · paper only`;
  $("#pilot-equity").textContent = money(pilot?.equity ?? 100);
  $("#pilot-cash").textContent = money(pilot?.cash ?? 100);
  $("#pilot-deployed").textContent = money(pilot?.deployed ?? 0);
  $("#pilot-risk").textContent = money(pilot?.total_risk ?? 0);
  $("#pilot-return").textContent = `${totalPnl >= 0 ? "+" : "−"}${money(Math.abs(totalPnl))} total P/L`;
  $("#pilot-return").className = totalPnl >= 0 ? "gain" : "loss";
  $("#pilot-history-count").textContent = pilot?.history.length ?? 0;
  $("#pilot-as-of").textContent = pilot?.last_reconciled_as_of ? `As of ${pilot.last_reconciled_as_of}` : "Waiting for start";
  $("#pilot-start").disabled = !idle;
  $("#pilot-reconcile").disabled = idle;
  $("#pilot-reset").disabled = idle;
  $("#pilot-error").textContent = errorMessage;
  $("#pilot-error").classList.toggle("visible", Boolean(errorMessage));

  $("#pilot-positions").innerHTML = positions.length ? positions.map(position => `
    <tr>
      <td><div class="ticker-cell"><span class="ticker-badge">${clean(position.ticker.slice(0, 2))}</span><span><strong>${clean(position.ticker)}</strong><small>${clean(position.tier)} · ${Number(position.score).toFixed(0)}</small></span></div></td>
      <td>${money(position.cost_basis)}</td>
      <td>${Number(position.shares).toFixed(5)}</td>
      <td>${money(position.entry_price)}</td>
      <td class="loss">${money(position.stop_price)}</td>
      <td class="gain">${money(position.target_price)}</td>
      <td class="number ${position.unrealized_pnl >= 0 ? "gain" : "loss"}">${position.unrealized_pnl >= 0 ? "+" : "−"}${money(Math.abs(position.unrealized_pnl))}</td>
    </tr>`).join("") : `<tr><td colspan="7" class="pilot-empty">${idle ? "Start the pilot to allocate the top qualifying setups." : "Capital is parked until a setup qualifies."}</td></tr>`;
}

async function paperPilotAction(path, method = "POST") {
  $$(".pilot-actions button").forEach(button => { button.disabled = true; });
  $("#pilot-error").classList.remove("visible");
  try {
    const response = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json" },
      body: path.endsWith("/start") ? JSON.stringify({ bankroll: 100 }) : undefined,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Paper Pilot request failed");
    renderPaperPilot(payload);
  } catch (error) {
    await loadPaperPilot();
    $("#pilot-error").textContent = error.message;
    $("#pilot-error").classList.add("visible");
  }
}

async function loadBoard() {
  try {
    const response = await fetch("data/board_today.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Snapshot unavailable");
    state.data = await response.json();
    normalizeRows();
    renderAll();
  } catch (error) {
    $("#board-rows").innerHTML = `<tr><td class="loading-row" colspan="7">No board snapshot yet. Run <code>python engine/generate_board.py</code> to populate today’s targets.</td></tr>`;
    $("#market-state").textContent = "Snapshot offline";
    $("#result-count").textContent = "0 setups";
  }
}

function normalizeRows() {
  const rows = state.data.setups || state.data.board || [];
  state.data.setups = rows.map(row => {
    const price = Number(row.price || 0);
    return {
      ...row,
      score: Number(row.score || 0),
      price,
      change_pct: Number(row.change_pct || 0),
      entry_low: Number(row.entry_low || price * .995),
      entry_high: Number(row.entry_high || price * 1.005),
      stop: Number(row.stop || price * .92),
      target: Number(row.target || price * 1.16),
      allocation_pct: Number(row.allocation_pct ?? (row.tier === "LOCK" ? 17 : row.tier === "LIVE" ? 8.5 : 0)),
      factors: row.factors || {},
    };
  }).sort((a, b) => b.score - a.score);
}

function renderAll() {
  renderHeader();
  renderMetrics();
  renderRows();
  renderShortlist();
}

function renderHeader() {
  const context = state.data.context || {};
  const stamp = state.data.as_of ? new Date(`${state.data.as_of}T12:00:00`) : new Date();
  $("#as-of").textContent = `As of ${stamp.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}`;
  $("#market-state").textContent = state.data.status === "preview" ? "Preview snapshot" : "Model snapshot";
  $("#regime").textContent = context.regime || state.data.regime || "Unknown";
  $("#vix").textContent = context.vix ? Number(context.vix).toFixed(2) : "—";
  $("#tnx").textContent = context.tnx ? `${Number(context.tnx).toFixed(2)}%` : "—";
  $("#integrity").textContent = state.data.integrity || "Partial inputs";
}

function renderMetrics() {
  const setups = state.data.setups;
  const qualified = setups.filter(row => row.tier === "LOCK" || row.tier === "LIVE");
  const best = setups[0];
  const deployable = qualified.reduce((sum, row) => sum + state.bankroll * row.allocation_pct / 100, 0);
  $("#qualified-count").textContent = qualified.length;
  $("#qualified-caption").textContent = qualified.length ? `${qualified.filter(r => r.tier === "LOCK").length} LOCK · ${qualified.filter(r => r.tier === "LIVE").length} LIVE` : "Capital stays parked";
  $("#best-score").textContent = best ? best.score.toFixed(0) : "—";
  $("#best-ticker").textContent = best ? `${best.ticker} leads today’s board` : "No scored setups";
  $("#deployable").textContent = compactMoney(Math.min(deployable, state.bankroll * .6));
}

function filteredRows() {
  return state.data.setups.filter(row => {
    const tierMatch = state.tier === "ALL" || row.tier === state.tier;
    const queryMatch = row.ticker.toLowerCase().includes(state.query.toLowerCase());
    return tierMatch && queryMatch;
  });
}

function tierMarkup(tier) {
  return `<span class="tier ${tier.toLowerCase()}">${clean(tier)}</span>`;
}

function renderRows() {
  const rows = filteredRows();
  $("#result-count").textContent = `${rows.length} setup${rows.length === 1 ? "" : "s"}`;
  $("#board-rows").innerHTML = rows.length ? rows.map(row => `
    <tr data-ticker="${clean(row.ticker)}" tabindex="0" class="${state.selected === row.ticker ? "selected" : ""}" aria-label="Open ${clean(row.ticker)} setup details">
      <td><div class="ticker-cell"><span class="ticker-badge">${clean(row.ticker.slice(0, 2))}</span><span><strong>${clean(row.ticker)}</strong><small>${clean(slug(row.sector || "unclassified"))}</small></span></div></td>
      <td>${tierMarkup(row.tier)}</td>
      <td class="number"><span class="entry-zone">${money(row.price)}</span><br><small class="${row.change_pct >= 0 ? "gain" : "loss"}">${row.change_pct >= 0 ? "+" : ""}${row.change_pct.toFixed(2)}%</small></td>
      <td><span class="entry-zone">${money(row.entry_low)}–${money(row.entry_high)}</span></td>
      <td class="number loss">${money(row.stop)}</td>
      <td class="number gain">${money(row.target)}</td>
      <td class="number score-cell"><span class="score-value">${row.score.toFixed(0)}</span><div class="score-track"><i style="width:${Math.max(0, Math.min(row.score, 100))}%"></i></div></td>
    </tr>`).join("") : `<tr><td class="loading-row" colspan="7">No setups match this filter.</td></tr>`;

  $$("#board-rows tr[data-ticker]").forEach(row => {
    const select = () => selectSetup(row.dataset.ticker);
    row.addEventListener("click", select);
    row.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
  });
}

function selectSetup(ticker) {
  state.selected = ticker;
  const setup = state.data.setups.find(row => row.ticker === ticker);
  renderRows();
  renderDetail(setup);
  if (window.innerWidth < 1180) $("#detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDetail(setup) {
  const qualified = setup.tier === "LOCK" || setup.tier === "LIVE";
  const allocation = state.bankroll * setup.allocation_pct / 100;
  const shares = setup.price ? allocation / setup.price : 0;
  const factorRows = Object.entries(FACTOR_MAX).map(([name, max]) => {
    const value = Number(setup.factors[name] || 0);
    return `<div class="factor-row"><span>${clean(slug(name))}</span><span>${value.toFixed(0)} / ${max}</span><div class="factor-meter"><i style="width:${Math.min(value / max * 100, 100)}%"></i></div></div>`;
  }).join("");
  const isSaved = state.saved.includes(setup.ticker);

  $("#detail-panel").innerHTML = `<div class="detail-content">
    <div class="detail-head"><div><span class="eyebrow">${clean(slug(setup.sector || "setup"))}</span><h3>${clean(setup.ticker)}</h3><div style="margin-top:7px">${tierMarkup(setup.tier)}</div></div><div class="score-orbit">${setup.score.toFixed(0)}</div></div>
    <div class="detail-price"><div><span class="eyebrow">Last close</span><strong>${money(setup.price)}</strong></div><div><span class="eyebrow">Session</span><strong class="${setup.change_pct >= 0 ? "gain" : "loss"}">${setup.change_pct >= 0 ? "+" : ""}${setup.change_pct.toFixed(2)}%</strong></div></div>
    <div class="plan-box"><div><span class="eyebrow">Ref. entry</span><strong>${money(setup.price)}</strong></div><div><span class="eyebrow">Stop</span><strong class="loss">${money(setup.stop)}</strong></div><div><span class="eyebrow">2R target</span><strong class="gain">${money(setup.target)}</strong></div></div>
    <div class="factor-list">${factorRows}</div>
    <div class="allocation-box">
      <div class="allocation-row"><span class="eyebrow">Model allocation</span><strong>${qualified ? compactMoney(allocation) : "$0"}</strong></div>
      <div class="bankroll-label"><span>${setup.allocation_pct}% of bankroll · ${qualified ? shares.toFixed(2) : "0"} shares</span><input id="bankroll" type="number" min="100" max="1000" step="100" value="${state.bankroll}" aria-label="Planning bankroll"></div>
    </div>
    <div class="detail-actions"><button class="primary-action" id="plan-button" type="button" ${qualified ? "" : "disabled"}>${qualified ? "Add to research plan" : "Below deploy threshold"}</button><button class="icon-action" id="save-button" type="button" aria-label="${isSaved ? "Remove from" : "Add to"} shortlist">${isSaved ? "★" : "☆"}</button></div>
    <p class="detail-warning">${qualified ? "Planning only. Confirm current price, earnings timing, and liquidity before any decision." : "BENCH is observation-only. The system allocates no capital below a score of 71."}</p>
  </div>`;

  const bankrollInput = $("#bankroll");
  bankrollInput.addEventListener("input", event => {
    if (Number(event.target.value) <= 1000) return;
    state.bankroll = 1000;
    localStorage.setItem("board-bankroll", state.bankroll);
    renderMetrics();
    renderDetail(setup);
  });
  bankrollInput.addEventListener("change", event => {
    state.bankroll = Math.min(1000, Math.max(100, Number(event.target.value) || 1000));
    localStorage.setItem("board-bankroll", state.bankroll);
    renderMetrics();
    renderDetail(setup);
  });
  $("#save-button").addEventListener("click", () => toggleSaved(setup.ticker));
  if (qualified) $("#plan-button").addEventListener("click", () => toggleSaved(setup.ticker, true));
}

function toggleSaved(ticker, forceAdd = false) {
  const exists = state.saved.includes(ticker);
  state.saved = exists && !forceAdd ? state.saved.filter(item => item !== ticker) : [...new Set([...state.saved, ticker])];
  localStorage.setItem("board-shortlist", JSON.stringify(state.saved));
  renderShortlist();
  const setup = state.data.setups.find(row => row.ticker === ticker);
  if (setup && state.selected === ticker) renderDetail(setup);
}

function renderShortlist() {
  const rows = state.saved.map(ticker => state.data.setups.find(row => row.ticker === ticker)).filter(Boolean);
  $("#saved-count").textContent = rows.length;
  $("#shortlist").innerHTML = rows.length ? rows.map(row => `<div class="shortlist-item"><strong>${clean(row.ticker)}</strong><span>${clean(row.tier)} · ${row.score.toFixed(0)}</span><span class="loss">${money(row.stop)} stop</span><span class="gain">${money(row.target)} target</span><button type="button" data-remove="${clean(row.ticker)}" aria-label="Remove ${clean(row.ticker)}">×</button></div>`).join("") : `<div class="empty-shortlist">No setups saved yet. Select a row and add it to your shortlist.</div>`;
  $$('[data-remove]').forEach(button => button.addEventListener("click", () => toggleSaved(button.dataset.remove)));
}

$$('[data-tier]').forEach(button => button.addEventListener("click", () => {
  state.tier = button.dataset.tier;
  $$('[data-tier]').forEach(item => item.classList.toggle("active", item === button));
  renderRows();
}));

$("#search").addEventListener("input", event => { state.query = event.target.value.trim(); renderRows(); });
$("#quiet-toggle").addEventListener("click", event => {
  const pressed = event.currentTarget.getAttribute("aria-pressed") === "true";
  event.currentTarget.setAttribute("aria-pressed", String(!pressed));
  document.body.classList.toggle("quiet", !pressed);
});

$$('[data-option-type]').forEach(button => button.addEventListener("click", () => {
  optionType = button.dataset.optionType;
  $$('[data-option-type]').forEach(item => item.classList.toggle("active", item === button));
  calculateOptionPayoff();
}));
$$('#option-calculator input').forEach(input => input.addEventListener("input", calculateOptionPayoff));
calculateOptionPayoff();
$("#pilot-start").addEventListener("click", () => paperPilotAction("/api/paper-pilot/start"));
$("#pilot-reconcile").addEventListener("click", () => paperPilotAction("/api/paper-pilot/reconcile"));
$("#pilot-reset").addEventListener("click", () => paperPilotAction("/api/paper-pilot", "DELETE"));

const navObserver = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    $$('.side-nav a').forEach(link => link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`));
  });
}, { rootMargin: "-30% 0px -60%" });
$$('section[id]').forEach(section => navObserver.observe(section));

loadBoard();
loadPaperPilot();
loadConnectionStatus();
loadLive();
{
  const liveDry = $("#live-dry");
  const liveRun = $("#live-run");
  if (liveDry) liveDry.addEventListener("click", () => runLive(true));
  if (liveRun) liveRun.addEventListener("click", () => runLive(false));
}

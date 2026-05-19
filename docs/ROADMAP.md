# ROADMAP.md

> Six phases. Each is a checkpoint with concrete deliverables and acceptance criteria.
> Do not skip ahead. Each phase de-risks the next.

---

## Phase 1: Backtest Engine ✅ (DONE)

**Status:** Scaffolded. Awaiting Brian's first run + results review.

**Deliverables:**
- [x] Universe, data pull, scoring, backtest modules
- [x] Pre-committed pass/fail criteria
- [ ] First backtest run by Brian
- [ ] Tuning iteration (if needed, max 2)

**Acceptance:** Backtest passes all 5 criteria OR fails clearly and we move to tuning.

---

## Phase 2: Catalyst Layer (Smart Money + Earnings + FOMC)

**Why this is next:** Phase 1's biggest gap. Three downgrade/booster systems are stubbed. This is where the model gets real signal.

**Deliverables:**
- `engine/calendars/earnings.py` — daily pull from Nasdaq earnings calendar (or yfinance earnings_dates). Cache to `data/earnings_calendar.json`. Function: `days_to_next_earnings(ticker, as_of) -> int | None`.
- `engine/calendars/fomc.py` — hardcoded Fed meeting dates (8/year, known a year out). Function: `is_fomc_week(date) -> bool`.
- `engine/signals/insider.py` — SEC EDGAR Form 4 scraper. Net insider buying over last 30/90 days. Score contribution to Smart Money factor.
- `engine/signals/congressional.py` — CapitolTrades scraper or RSS. Detect cluster events (3+ members buying same ticker in 30 days). Score contribution.
- `engine/signals/institutional.py` — 13F adds in last quarter. Lower priority (90-day lag).
- Re-wire `score.py` Smart Money factor to use real signals.
- Re-wire `score.py` downgrades to consume real calendars.
- Re-run backtest with full catalyst layer enabled.

**Acceptance:**
- Smart Money scoring shows real differentiation (range 0–15 across universe, not flat 7)
- Earnings downgrade fires on tickers within 5 days of report
- Backtest results materially different from Phase 1 (better or worse, but different — proves signals are active)

---

## Phase 2.6: Stateless Trigger Router

**Why this is next:** Phase 2 generates events worth notifying about. The
router establishes the notification layer AND becomes the inter-product event
bus for all of Takeoff LLC. See `docs/EVENTS.md` for the full contract.

**Deliverables:**
- `docs/EVENTS.md` — the event contract for all Takeoff products ✅
- `triggers/` — Board Market publisher package (emit, types, HMAC signing) ✅
- `router/` — Cloudflare Worker that receives, verifies, routes ✅ (deploy pending)
- Web Push (VAPID) channel implementation
- Email (Resend) channel — implemented, needs API key
- `emit()` calls wired into ledger close_play, future board lifecycle jobs
- Quiet Day toggle in profile settings
- Observability without storing event content

**Acceptance:**
- Closing a play with `exit_reason="STOP"` on a CRITICAL severity event
  triggers email delivery
- Quiet Day toggle silences everything except CRITICAL
- Router compromise yields nothing useful (no stored event content)
- Backtest produces zero notifications (1000+ emits would spam)

**Future hook:** Phase 4.5+ adds inter-product subscription (Command Center
auto-logs trading income from `play.target_hit` events, etc).

---

## Phase 3: Profile System + Local Web UI

**Why this is next:** Brian needs to interact with the system, log plays, see results. Phase 1+2 are CLI only.

**Deliverables:**
- `profiles/db.py` — SQLite schema and ORM (see SCHEMA.md)
- `profiles/auth.py` — single-user auth for Phase 3 (email + password, bcrypt). Multi-user deferred.
- `profiles/ledger.py` — open positions, closed plays, performance tracking
- `profiles/preferences.py` — custom watchlist additions, universe exclusions, notification settings
- `app.py` — FastAPI backend exposing `/api/score/today`, `/api/ledger`, `/api/positions`, `/api/profile`
- `assets/` — frontend dashboard (HTML/CSS/JS, no framework). Renders today's board, ledger, equity curve.
- Local dev: `uvicorn app:app --reload`, browse to `localhost:8000`

**Acceptance:**
- Brian can log in, see today's scored board, log a play, see it appear in ledger
- Performance metrics (win rate, R/R, equity curve) compute correctly from ledger
- Frontend matches Board System aesthetic (see DESIGN.md)

---

## Phase 4: GitHub Actions + Public Deployment

**Why this is next:** Manual runs don't scale. The pre-market refresh needs to happen every day at 8 AM ET whether Brian remembers or not.

**Deliverables:**
- `.github/workflows/premarket-refresh.yml` — runs 8:00 AM ET (12:00 UTC during ET DST, 13:00 UTC EST). Pulls data, scores universe, publishes `data/board_today.json` to repo.
- `.github/workflows/freeze-gate.yml` — runs 9:30 AM ET. Marks board frozen, no further scoring updates that day.
- `.github/workflows/eod-resolve.yml` — runs 4:15 PM ET. Updates open positions, marks resolved plays, recalculates equity curve.
- Frontend hosted on GitHub Pages at `wordups.github.io/the-board-market`
- Backend hosted on Render (free tier) for profiles/auth endpoints

**Acceptance:**
- Board updates daily without manual intervention for 5 consecutive trading days
- Freeze gate visibly locks board at 9:30 AM
- EOD resolution correctly closes plays at stop/target/time

---

## Phase 5: Schwab Broker Integration

**Why this is next:** Real positions, real P/L, no manual entry.

**Deliverables:**
- `connectors/schwab.py` — Schwab Trader API client (OAuth 2.0 with refresh tokens)
- `connectors/schwab_sync.py` — periodic sync of positions, balances, transactions
- `connectors/plaid.py` — Plaid integration for Roth balance tracking (read-only)
- `connectors/manual_csv.py` — Fidelity CSV import fallback
- Brian's broker positions visible in dashboard, distinguished from paper plays
- **Conflict detection:** if a real position exists that the model would score BENCH, flag it.

**Critical constraint:** Phase 5 is **READ-ONLY**. No order placement. Order placement is Phase 6 only if backtest pass + 8 weeks of clean Phase 4 operation.

**Acceptance:**
- Schwab positions sync automatically every 15 min during market hours
- Plaid balance shows in dashboard
- Manual CSV import works for Fidelity
- Read-only verification: confirm no order placement endpoints are wired

---

## Phase 6: Options Scoring + Order Placement (Conditional)

**This phase only happens if:**
1. Phase 1 backtest passed
2. Phases 2–5 have been live and stable for 8+ weeks
3. Brian's ledger shows 60%+ win rate consistent with backtest
4. No data pipeline failures in last 30 days

**Deliverables:**
- `engine/options.py` — IV percentile, term structure, defined-risk spread scoring
- `connectors/schwab_orders.py` — order placement with mandatory confirmation step
- Order placement requires:
  - Manual approval click in UI per order
  - 2nd confirmation modal with size, stop, target
  - SMS or email notification on order fills
- `profiles/risk_guard.py` — hard limits on daily order count, total exposure, max single position

**Acceptance:** Hard sequence — never place an order without:
1. UI approval click
2. Confirmation modal acknowledgment
3. Risk guard pass
4. Active backtest pass status

---

## Anti-roadmap (things we are NOT building)

- **Multi-user SaaS.** Single-user only until Brian explicitly says otherwise.
- **Crypto exchange integration.** IBIT/MSTR/COIN give equity-market BTC exposure. That's enough.
- **Day trading / 0DTE.** Multi-horizon swing/position only. No scalping infrastructure.
- **Social features.** This isn't a community platform. Other Board System modules can be social; this one is private.
- **AI-generated trade ideas outside the model.** The model is the system. No "what does ChatGPT think about NVDA today" features.
- **Mobile app.** Mobile-responsive web is enough.
- **Real-time streaming quotes.** 15-min delayed is fine for the horizons we trade.

If a feature request comes in that's on the anti-roadmap, decline and explain why.

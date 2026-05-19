# TASKS.md

> Discrete, sequenced tasks for Claude Code. Each task should be picked up
> independently, with the doc references it needs called out explicitly.
>
> Task ID format: `Px.NN` where x = phase, NN = task number.
> Status: 🔵 TODO · 🟡 IN PROGRESS · 🟢 DONE · ⚫ BLOCKED

---

## Phase 1 — Tuning / Validation

### P1.01 🟢 Build core scoring + backtest engine
*Already done by Claude in chat. Files: `engine/universe.py`, `engine/data_pull.py`, `engine/score.py`, `engine/backtest.py`.*

### P1.02 🔵 Run first backtest, report results
**Owner:** Brian.
**Acceptance:** `data/backtest_results.json` exists, full report printed to terminal.
**Deliverable:** Brian shares console output back.

### P1.03 ⚫ Tune scoring weights (BLOCKED on P1.02 results)
**Trigger:** Only if P1.02 fails any pre-committed criteria.
**Approach:** Adjust factor weights in `engine/score.py` ONE category at a time. Re-run backtest. Max 2 iterations before reassessment.
**DO NOT:** Change the pre-committed pass criteria. Change the model, not the goalposts.

---

## Phase 2 — Catalyst Layer

### P2.01 🔵 Earnings calendar puller
**File:** `engine/calendars/earnings.py`
**Source:** Try `yfinance` `ticker.earnings_dates` first. Fallback: Nasdaq earnings calendar API or scrape.
**Cache:** `data/earnings_calendar.json`, refreshed daily 6 AM ET via GitHub Action.
**Function:** `days_to_next_earnings(ticker: str, as_of: date) -> int | None`
**Reference:** CONTEXT.md (Phase 1 omissions), score.py (the downgrade is already wired, just needs data).

### P2.02 🔵 FOMC calendar
**File:** `engine/calendars/fomc.py`
**Source:** Hardcode the 8 FOMC meeting dates per year (publicly available a year out).
**Function:** `is_fomc_week(date) -> bool`
**Reference:** SCHEMA.md (no DB table needed, this is static config).

### P2.03 🔵 SEC EDGAR Form 4 scraper
**File:** `engine/signals/insider.py`
**Source:** SEC EDGAR full-text search or RSS feed for Form 4 filings.
**Approach:** For each universe ticker, get last 90 days of Form 4s. Compute net insider buying (purchases - sales by insiders). Score 0–7 of Smart Money's 15-point budget.
**Function:** `insider_signal(ticker: str, as_of: date) -> tuple[float, list[str]]`

### P2.04 🔵 Congressional trade cluster detector
**File:** `engine/signals/congressional.py`
**Source:** CapitolTrades RSS feed. Backup: scrape clerk.house.gov PTR pages.
**Logic:** For each universe ticker, count distinct members buying in last 30 days. 1 member = 0 pts, 2 = 3 pts, 3+ = 6 pts. Score contributes to Smart Money's 15-point budget.
**Function:** `congressional_signal(ticker: str, as_of: date) -> tuple[float, list[str]]`
**Note:** 45-day disclosure lag is acknowledged. This is signal, not real-time edge.

### P2.05 🔵 13F institutional adds (low priority)
**File:** `engine/signals/institutional.py`
**Source:** SEC EDGAR 13F filings, quarterly.
**Score:** 0–2 of Smart Money budget. Lower weight because of 90-day lag.

### P2.06 🔵 Rewire score.py Smart Money factor
**File:** `engine/score.py` (modify existing `smart_money_score` function).
**Logic:** Combine P2.03 (max 7) + P2.04 (max 6) + P2.05 (max 2) = 15 total.
**Acceptance:** Smart Money scores show real differentiation across universe (not flat 7 for everyone).

### P2.07 🔵 Re-run backtest with full Phase 2 signals enabled
**Acceptance:** Results materially different from P1.02 baseline. Document changes in `data/phase2_backtest_delta.md`.

---

## Phase 2.6 — Stateless Trigger Router (Takeoff nervous system)

> This phase establishes the inter-product event bus for ALL Takeoff LLC products.
> Designed to evolve from "notify Brian about his trades" into "the postal
> service for every Takeoff product." See `docs/EVENTS.md` for the contract.

### P2.61 🟢 Event contract spec (`docs/EVENTS.md`)
*Done. Reviewed and approved.*
**Notes for CC:** Read this BEFORE writing any router or emit code. The
envelope shape, source registry, type registry, severity tiers, and HMAC
discipline are all spec'd. Don't invent fields not in the spec.

### P2.62 🟢 Publisher: triggers package (`triggers/`)
*Done. Reviewed and approved.*
- `triggers/emit.py` — fire-and-forget HMAC-signed POST
- `triggers/types.py` — registered event types for board-market
- `triggers/__init__.py` — package exports
**Notes for CC:** Pattern is reusable for other Takeoff products. When wiring
into Command Center/Midnight/etc., copy `emit.py` shape but change `SOURCE`
constant and use that product's HMAC secret env var name.

### P2.63 🟢 Router: Cloudflare Worker scaffold (`router/`)
*Done. Awaiting Brian to deploy.*
- `router/src/index.ts` — Worker entry, HMAC verification, routing rules
- `router/wrangler.toml` — deploy config
- `router/package.json` — npm config
- `router/tsconfig.json` — TypeScript config
- `router/README.md` — setup and deploy instructions
**Notes for CC:** Two stub TODOs in `src/index.ts`:
1. `deliverPush()` — VAPID web push (P2.64 below)
2. The actual quiet-hours-then-fall-through-to-email logic for HIGH severity
   could be cleaner. Current routing rules order works but it's brittle if
   someone adds rules. Worth refactoring to a function that returns channels
   based on (sev, time, quietDay) tuple.

### P2.64 🔵 Web Push (VAPID) implementation
**File:** `router/src/push.ts`
**Library:** `@negrel/webpush` or hand-roll VAPID signing (Workers env is limited)
**Setup steps Brian needs:**
1. Generate VAPID keys: `npx web-push generate-vapid-keys`
2. Store private key as `VAPID_PRIVATE_KEY` Worker secret
3. Frontend registers service worker (Phase 3 task), subscribes to push,
   sends subscription JSON to a small endpoint that stores it in
   `USER_PUSH_SUBSCRIPTION` secret (one-time setup, can be CLI-driven)
**Acceptance:** CRITICAL event with desktop browser open fires native OS notification.

### P2.65 🔵 Email channel (Resend)
**Status:** Implemented in `deliverEmail()` already. Needs Resend account setup.
**Setup:** Brian creates Resend account (free tier: 3000 emails/mo, plenty), sets
`RESEND_API_KEY` and `USER_EMAIL` secrets in Worker.
**Acceptance:** Test event with email channel triggers actual email receipt.

### P2.66 🔵 Wire `emit()` calls into Board lifecycle
**Files to modify:**
- `profiles/ledger.py` — emit on `create_play`, `close_play`, `cancel_play`
- `engine/backtest.py` — NO emits (backtest is silent by design)
- Future: `engine/eod_resolve.py` (Phase 4) emits `board.eod_closed`
- Future: `engine/freeze_gate.py` (Phase 4) emits `board.frozen`
- Future: `engine/news/correlate.py` (Phase 2) emits `signal.*` events

**Pattern:**
```python
from triggers import emit

# in close_play() after computing pnl:
if exit_reason == "STOP":
    emit(
        type="play.stop_hit",
        title=f"{ticker} stop hit",
        body=f"Exited at ${exit_price}. P/L: ${dollar_pnl:+.2f}.",
        payload={
            "play_id": play_id,
            "ticker": ticker,
            "tier": tier,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "held_days": held_days,
            "pct_return": pct_return,
            "r_multiple": r_multiple,
            "dollar_pnl": dollar_pnl,
        },
        deeplink=f"https://wordups.github.io/the-board-market/plays/{play_id}",
    )
```

**Acceptance:** Closing a play in the ledger triggers an email (if router deployed
with email configured). Backtest does NOT trigger emails (would spam 1000+ during
5yr run).

### P2.67 🔵 Quiet Day toggle
**Backend:** Add `quiet_day_until` (DATE) column to `users` table in profiles DB.
**Endpoint:** `GET /api/profile/quiet-day` returns `{"quiet_day": bool}` based on
whether `quiet_day_until >= today`.
**Worker integration:** Set `QUIET_DAY_FLAG_URL` secret to that endpoint URL.
**UI:** Single toggle in dashboard settings: "Quiet Day — silence everything
except CRITICAL until end of day". Optional: "Quiet Day +N days" picker.

### P2.68 🔵 Production observability without storing event data
**Goal:** Brian needs to know when the router is failing without the router
storing event contents.
**Approach:**
1. Cloudflare Worker logs status codes only (no envelope body)
2. Failed deliveries log channel + error type only (e.g., "email_failed",
   "push_failed") — no event content
3. Daily summary metric: total events received, by source, by severity, by
   channel — counts only, NOT contents
4. Health check endpoint: `GET /health` returns 200, used by uptime monitor

### P2.69 🔵 Inter-product subscription (DEFERRED to Phase 4.5)
**Vision:** Other Takeoff products subscribe to Board Market events via the same
router. E.g., Command Center subscribes to `play.target_hit` and auto-logs
trading income.
**Status:** Architectural foundation is in place via EVENTS.md. Implementation
deferred — get the publisher + End User delivery solid first, evolve into
subscription later when a real second use case appears.

---

## Phase 3 — Profile + Local Web UI

### P3.01 🔵 SQLite schema migration script
**File:** `profiles/db.py` and `profiles/migrations/001_initial.sql`
**Reference:** SCHEMA.md
**Tables:** users, accounts, positions, plays, daily_boards, equity_curve, preferences.
**Use:** `sqlite3` stdlib, no ORM unless needed. Simple is better than clever.

### P3.02 🔵 Auth (single-user)
**File:** `profiles/auth.py`
**Stack:** FastAPI + python-jose for JWT + passlib for bcrypt.
**Endpoints:** `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`.
**Note:** Single-user means first registration is the owner. Subsequent registration attempts return 403 until multi-user is enabled.

### P3.03 🔵 Ledger CRUD
**File:** `profiles/ledger.py`
**Endpoints:**
- `POST /api/plays` — log a new play (paper or live)
- `GET /api/plays` — list with filters (status, tier, mode, date range)
- `PATCH /api/plays/{id}/close` — close play with exit price/reason
- `GET /api/plays/{id}` — single play with full factors
**Auto-compute on close:** pct_return, r_multiple, dollar_pnl, held_days.

### P3.04 🔵 Performance metrics endpoint
**File:** `profiles/performance.py`
**Endpoint:** `GET /api/performance?period=30d|90d|ytd|all`
**Returns:** win_rate, avg_r, expectancy_pct, total_pnl, max_drawdown, breakdown by tier.

### P3.05 🔵 Today's board endpoint
**File:** `app.py` (main FastAPI app)
**Endpoint:** `GET /api/board/today`
**Logic:** Reads `data/board_today.json` (written by GH Action in Phase 4) OR generates on demand if file is stale/missing.
**Returns:** ranked universe with tier, score, factors, regime context.

### P3.06 🔵 Frontend dashboard — board view
**Files:** `index.html`, `assets/js/board.js`, `assets/css/pages/board.css`
**Reference:** DESIGN.md (component spec — Today's Board)
**Renders:** LOCK / LIVE / BENCH sections. Score bars. Factor breakdown on hover. Freeze gate indicator.

### P3.07 🔵 Frontend dashboard — ledger view
**Files:** `ledger.html`, `assets/js/ledger.js`, `assets/css/pages/ledger.css`
**Reference:** DESIGN.md (Ledger view)
**Renders:** Table with filters. Click row for full factor history.

### P3.08 🔵 Frontend dashboard — equity curve + metrics
**Files:** `assets/js/equity-curve.js` (using d3 or chart.js)
**Reference:** DESIGN.md (Equity curve + Performance metrics card)

### P3.09 🔵 Local dev runner
**File:** `Makefile` or `dev.sh`
**Targets:** `make dev` (starts uvicorn + watches assets), `make backtest`, `make refresh-data`.

---

## Phase 4 — GitHub Actions + Public Deploy

### P4.01 🔵 Pre-market refresh workflow
**File:** `.github/workflows/premarket-refresh.yml`
**Schedule:** `0 12 * * 1-5` (8 AM ET during DST; adjust for EST/EDT)
**Steps:** Run data_pull, run scoring, write `data/board_today.json`, commit and push.

### P4.02 🔵 Freeze gate workflow
**File:** `.github/workflows/freeze-gate.yml`
**Schedule:** `30 13 * * 1-5` (9:30 AM ET DST)
**Steps:** Set `frozen_at` timestamp in `data/board_today.json`. No further scoring updates that day.

### P4.03 🔵 End-of-day resolve workflow
**File:** `.github/workflows/eod-resolve.yml`
**Schedule:** `15 20 * * 1-5` (4:15 PM ET DST)
**Steps:** For each open play in ledger: check if stop/target hit during day, mark resolved, update equity curve.

### P4.04 🔵 Frontend deployment (GitHub Pages)
**Setup:** GH Pages enabled on `main` branch, `/` root.
**Files:** Static frontend deploys automatically on push to main.
**URL:** `wordups.github.io/the-board-market`

### P4.05 🔵 Backend deployment (Render)
**Setup:** Render web service, free tier, autodeploy from main.
**Env vars:** Database URL (SQLite file in persistent disk), JWT secret, future Schwab/Plaid keys.

---

## Phase 5 — Broker Integration (READ ONLY)

### P5.01 ⚫ Schwab API approval (BLOCKED on Brian applying)
**Owner:** Brian. Apply at developer.schwab.com. 1–4 week processing.
**Status:** Not started.

### P5.02 🔵 Schwab OAuth flow
**File:** `connectors/schwab.py`
**Reference:** CONNECTORS.md (full OAuth spec).
**Endpoints:** `/api/connectors/schwab/authorize`, `/api/connectors/schwab/callback`.

### P5.03 🔵 Schwab position sync
**File:** `connectors/schwab_sync.py`
**Schedule:** Every 15 min during market hours via cron.
**Writes:** `positions` table.

### P5.04 🔵 Plaid integration (Roth tracking)
**File:** `connectors/plaid.py`
**Reuse:** Existing Plaid client_id/secret from Poof E Gone Command Center setup.

### P5.05 🔵 Fidelity manual CSV import
**File:** `connectors/manual_csv.py`
**Endpoint:** `POST /api/connectors/fidelity/upload`
**Reference:** CONNECTORS.md (expected columns).

### P5.06 🔵 Conflict detection
**File:** `profiles/conflict_detector.py`
**Logic:** For each real position, score the ticker with current model. If model says BENCH, flag in UI as "Position scored BENCH — review."

### P5.07 🔵 Connection status UI
**Files:** Frontend additions to all pages — footer status chip.
**Reference:** DESIGN.md (Connection status).

---

## Phase 6 — Options + Order Placement (CONDITIONAL)

### P6.00 ⚫ HARD GATE — do not start until ALL conditions met
- [ ] Phase 1 backtest passed all 5 criteria
- [ ] Phases 2–5 live and stable for ≥ 8 weeks
- [ ] Brian's live ledger shows 60%+ win rate consistent with backtest
- [ ] Zero data pipeline failures in last 30 days
- [ ] Brian explicit go-ahead

If any of the above is false, **do not start Phase 6 tasks**. Surface concern to Brian.

### P6.01 ⚫ Options chain integration
### P6.02 ⚫ IV percentile + term structure scoring
### P6.03 ⚫ Defined-risk spread scoring (calls/puts/verticals only)
### P6.04 ⚫ Order placement endpoints with confirmation modal
### P6.05 ⚫ Risk guard (daily order limits, exposure caps)

---

## Cross-phase principles for Claude Code

1. **Read CONTEXT.md before any task.** Re-read the philosophical core before tuning the model.
2. **Match the existing aesthetic.** DESIGN.md is the source of truth. Don't invent.
3. **Point-in-time discipline in any backtest code.** Lookahead bias = invalid results.
4. **Test before pushing.** Especially for the scoring engine and ledger logic.
5. **Encrypt all tokens.** No exceptions.
6. **Commit messages reference task IDs.** Example: `P2.04: add congressional cluster detector`.
7. **When in doubt, ask Brian.** Don't guess on capital allocation, risk parameters, or scope changes.

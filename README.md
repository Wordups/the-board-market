# The Board Market

> Equities sibling to [the-board-system](https://wordups.github.io/the-board-system).
> Same discipline framework, ported to stocks/ETFs/crypto wrappers.
> Trading capital cap: **$1K** until backtest passes AND 2 weeks live execution validates.

---

## What this is

A stock market intelligence and execution discipline system. It scores ~45 curated tickers daily on a 100-point composite model, tiers them (Lock 85+ / Live 71–84 / Bench <71), tracks plays in a personal ledger, and connects to brokerage accounts for real-position visibility.

## What this isn't

Not a tip service. Not auto-trading. Not a get-rich app. The system enforces discipline. Discipline doesn't guarantee profit. Read the pass/fail criteria below before deploying any capital.

## Directory map

```
the-board-market/
├── engine/           # scoring, backtest, universe, data pull
├── profiles/         # auth, ledger, performance, SQLite schema
├── connectors/       # Schwab API, Plaid, manual CSV import
├── triggers/         # event publisher (fires to router)
├── router/           # Cloudflare Worker — stateless event router
├── docs/             # CONTEXT, ROADMAP, SCHEMA, CONNECTORS, DESIGN, EVENTS, TASKS
├── data/             # cache + SQLite DB (gitignored)
├── assets/           # frontend (Phase 3+)
├── reports/          # generated backtest reports
└── .github/workflows/  # daily refresh, freeze gate, EOD resolve (Phase 4)
```

## Build status

- **Phase 1 — Backtest engine:** ✅ Scaffolded, awaiting first run
- **Phase 2 — Catalyst layer:** 🔵 Todo (earnings calendar, Form 4, congressional)
- **Phase 2.6 — Trigger router (Takeoff nervous system):** 🟡 Scaffolded (publisher + Worker built, deploy pending)
- **Phase 3 — Profile + Web UI:** 🟡 Scaffolded (db, auth, ledger, performance modules ready)
- **Phase 4 — GitHub Actions deploy:** 🔵 Todo
- **Phase 5 — Broker integration:** 🟡 Scaffolded (Schwab/Plaid/CSV clients ready, not wired)
- **Phase 6 — Options + orders:** ⚫ Gated on Phase 1 pass + 8 weeks stable

## Pre-committed pass/fail criteria

Model ships to live trading **only if** the 5-year backtest shows all of:
- LOCK win rate ≥ 65%
- LIVE win rate ≥ 55%
- Average R ≥ 1.8 (net of slippage)
- Max drawdown ≤ 25%
- Positive returns in ≥ 4 of 5 years

If it fails: tune scoring weights, re-backtest. Max 2 iterations before reassessing approach.

## Quickstart

```bash
# Install
pip install -r requirements.txt

# Phase 1: backtest
cd engine
python data_pull.py     # ~2-3 min first time, cached after
python backtest.py      # 5-year simulation

# Phase 3: initialize profile DB
cd ..
python -m profiles.db    # runs migrations
```

## For Claude Code

Pick up where this scaffold left off. Start with `docs/CONTEXT.md`, then `docs/TASKS.md`. Each task is scoped and references the relevant docs. Commit messages should include task IDs (e.g., `P2.04: add congressional cluster detector`).

## Not financial advice

Build, measure, learn. Capital at risk. Discipline first.

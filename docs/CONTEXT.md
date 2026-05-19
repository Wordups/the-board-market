# CONTEXT.md

> Read this first. Every other doc assumes you've internalized this one.

## What is The Board Market?

A stock market intelligence and execution discipline system. Built by Brian Word, owner of the related sports analytics system [the-board-system](https://wordups.github.io/the-board-system). This is the equities sibling — same architectural DNA, ported to a different signal regime.

## Who built it and how to think about the owner

Brian is a Senior Security Engineer (Cortex XSIAM SOC builder) with a multi-product venture portfolio under Takeoff LLC: Midnight (policy intelligence), STITCHem (subscription box), Poof E Gone (IT asset disposal), CourtFlow Pro (basketball trainer PWA), WordUp (prompt-to-build OS). He ships fast, expects direct outputs, and builds systems that enforce discipline rather than relying on willpower.

**Operating principles when working on this codebase:**
- Outcomes over theory. If it can't be implemented, it's not valuable.
- Frame around SLA, performance, cost, risk — not tools.
- Default to system-building, automation, repeatability.
- He is an expert in XSIAM detection engineering. Speak to him at expert level on security/automation topics, not novice level.

## The philosophical core

Brian's sports parlay formula works because it enforces discipline:
- Model prop score 71+ required
- Cross-check vs prior averages
- Eye-test layer
- Tier (Lock 85%+ / Live 75–84% / Fade below)
- 1.4x+ multiplier + 85%+ hit rate per leg
- 65-pt auto-downgrade for 3PT props (variance penalty)

The Board Market ports this discipline to equities. **Critical difference:** markets are noisier than props. The system targets 60–65% win rates, not 85%. R/R targets are higher (2:1 minimum) to compensate. **This recalibration is non-negotiable** — anyone who tries to copy sports-level win-rate targets to stocks will design a model that promises something it cannot deliver.

## What's already built (Phase 1)

`engine/universe.py` — 45-ticker curated universe across mega-cap, growth momentum, financials, energy, defense, sector ETFs, macro instruments, and crypto wrappers (IBIT, MSTR, COIN). Includes sector map for downgrade logic.

`engine/data_pull.py` — yfinance OHLCV puller with 24h CSV cache. Critical: includes `get_point_in_time_slice()` function. **All backtest scoring MUST use point-in-time slicing.** Lookahead bias is the #1 retail backtest mistake.

`engine/score.py` — 100-point composite scoring engine:
- Technical (20): trend alignment, MA structure, volume
- Catalyst (20): sector tailwind baseline (earnings via downgrade)
- Relative Strength (15): 5d + 20d vs SPY
- Smart Money (15): **currently 7/15 placeholder for ALL tickers**
- Macro (15): VIX regime, yields, sector × regime fit
- Sentiment (15): RSI(14), volatility contraction

Auto-downgrades: Earnings ≤5d (−30), VIX >25 (−15), FOMC week Mon-Wed (−20), Crypto in VIX >30 (−20).

Tiers: LOCK 85+ / LIVE 71–84 / BENCH <71.

`engine/backtest.py` — 5-year simulation:
- Realistic next-day-open entries with 0.15% stock slippage per side
- Gap-down stop handling (fills at open if open <= stop)
- −8% stop, +16% target (2R), 20-day max hold
- Concurrency limits: 1 LOCK, 2 LIVE concurrent
- Position sizing: 17% bankroll for LOCK, 8.5% for LIVE, 40% cash floor
- Auto pass/fail check against pre-committed criteria

## What's NOT built — known omissions Phase 1 ships with

| Gap | Impact | Fix in |
|---|---|---|
| No earnings calendar feed | Earnings downgrade does nothing | Phase 2 |
| No Form 4 / 13F / congressional data | Smart Money is flat 7/15 for all | Phase 2 |
| No FOMC calendar | FOMC downgrade does nothing | Phase 2 |
| No notification layer | Player has to check dashboard manually | Phase 2.6 |
| No inter-product event bus | Products are silos | Phase 2.6 (foundation) / 4.5 (subscribers) |
| No options scoring | Phase 1 backtest is shares-only | Phase 6 |
| No frontend | CLI output only | Phase 4 |
| No user profile / auth | Single-user, local-only | Phase 3 (scaffolded) |
| No broker connection | Manual trade entry only | Phase 5 (scaffolded) |

Phase 1 backtest results are therefore **conservative** — every play scores without catalyst boosters. If the model passes anyway, that's a strong signal.

## Pre-committed pass/fail criteria

**Do not modify these without Brian's explicit approval.** The whole point is to commit before seeing results.

The model ships to live trading only if 5-year backtest shows ALL of:
- LOCK win rate ≥ 65%
- LIVE win rate ≥ 55%
- Average R ≥ 1.8 net of slippage
- Max drawdown ≤ 25%
- Positive returns in ≥ 4 of 5 years

If it fails: tune scoring weights, re-backtest. Max 2 tuning iterations before reassessing the entire approach.

## Capital and risk parameters

- **Roth IRA portfolio is untouchable.** Separate system, separate thesis (SCHD/VYM/VTI/SCHH/SGOV at Schwab Roth, ~$5K).
- **Trading capital ≤ $1K** until backtest passes AND 2 weeks of live execution validate plumbing.
- **Hard pause at $700** (−30%). Full stop at $500 (−50%).
- **Every play logged.** No memory ledger. The discipline depends on the record.

## The relationship to The Board System

Same aesthetic, same vocabulary, same discipline framework. Different repo, different domain, different signal regime. Cross-pollinate visual design and naming conventions but **do not share data or coupling.** They are independent systems that happen to be built by the same person with the same philosophy.

## Owner's existing stack (relevant context)

- **GitHub:** Wordups
- **Repos:** the-board-system (sports), the-board-market (this one), command-center (financial dashboard), Midnight (policy AI), Poof E Gone (e-waste business site)
- **Hosting:** GitHub Pages for static frontends, Render for FastAPI backends
- **Broker:** Schwab (trading + Roth), Fidelity (secondary)
- **Financial data integrations:** Plaid (via Poof E Gone for Command Center)
- **Style:** dark editorial, structured, no fluff

## When you're stuck

If a design decision is ambiguous, default to:
1. **Simpler.** This is a $1K trading lab, not a hedge fund. SQLite over Postgres. CSV over API when API is fragile.
2. **More transparent.** Every score should be inspectable. Every trade should be auditable.
3. **More disciplined.** When in doubt, add a guardrail, not a feature.
4. **Closer to the sports system's aesthetic.** Brian has a strong visual identity already — match it, don't reinvent.

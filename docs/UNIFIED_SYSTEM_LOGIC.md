# The Board — Unified System Logic (v3 proposal)

Drafted 2026-07-17. Combines the-board-market (signal brain) + agentic-trader (execution spine)
into one system, and restores the pre-simplification scoring philosophy from the-board-system.

## 1. What the "oversimplification" actually was (the-board-system, MLB HR)

Commit `19fa632` (2026-06-19) replaced a ~20-factor deterministic HR edge score
(richest at `37bab91`, 2026-05-25) with a bare `sim_prob × 100`, and deleted three guardrails:

1. **Rule-48 rookie cap** — career_games < 25 → capped at C-tier.
2. **Calibration hold** — quarantined picks whose sim probability drifted from realized
   baselines (~174 picks held; now 0).
3. **Value-zone rejection** — auto-rejected chalk (p ≥ 0.80) and longshots (p ≤ 0.10).

The rich factor machinery (platoon, vs-pitcher, power indices, lineup confidence, sample
reliability, quality-adjustment stack) still computes but no longer moves the published score.
Lesson: **never let one opaque number replace a legible multi-factor score plus hard guardrails.**

## 2. The market engine never had the richness — it was born reduced

`engine/score.py` (single commit, never edited): 6 factors / 100 pts, but two are stubs:
- Smart Money: hard-coded 7/15 for every ticker.
- Catalyst: sector-baseline lookup (max ~15/20), no real events.
Consequence: real ceiling ≈ 80 → LOCK (85+) unreachable. The board has literally never
produced a LOCK. The feeds to fix this are ALREADY COMMITTED but unwired:
earnings calendar (`cd8469d`), FOMC calendar (`661d4e5`), SEC EDGAR Form 4 insider
scraper (`be8258a`, `engine/signals/insider.py`).

## 3. Scoring restoration (the "un-simplification", ported to equities)

Keep the deterministic 6-factor composite as THE score. A sim/backtest number may exist
as a cross-check column but must NEVER overwrite the score (that was the 19fa632 mistake).

### 3a. Wire the stub factors (Phase 2 work, feeds exist)
- **Smart Money 0-15 (real)**: from Form 4 data — cluster buying (≥2 insiders, 90d) +8,
  officer/director open-market buy +4, net-selling regime −0 baseline cap 4, dollar-size
  scaled. Cache daily; degrade gracefully to 7/15 neutral when EDGAR unavailable.
- **Catalyst 0-20 (real)**: sector baseline (existing, rescaled to 0-8) + event layer 0-12:
  confirmed upcoming catalyst (product launch, guidance raise, post-earnings-beat drift
  window 2-10 sessions) +6-12, verified via runner-scan web check. Earnings-proximity
  RISK stays in downgrades (unchanged).

### 3b. Restore the three guardrails as market analogs
1. **Listing cap (Rule 48 analog)**: < 25 trading sessions of history → tier capped at BENCH
   regardless of score. (SPCX is currently inside this window — correctly held out of the
   signal sleeve; it lives only in the owner-designated core slice.)
2. **Calibration hold**: weekly job compares tier hit-rates (rolling 20 closed signals) to
   targets (LIVE ≥ 55% toward the 60-65% goal). A tier that drifts below floor is
   quarantined to paper until it re-qualifies. Predicted-vs-realized logged per signal in
   the unified journal — this is the dataset that earns capital increases.
3. **Entry-zone rejection (chalk/longshot analog)**: reject entries (regardless of score) when
   price > +10% above 20MA (chalk/chasing) OR close < 200MA in a stacked-bear alignment or
   RSI(14) < 25 (falling knife). Logged as `REJECT_ZONE` with reason.

### 3c. Quality-adjustment stack (HR-stack analog, small deterministic nudges)
- Liquidity (PA analog): 30d avg dollar-volume > $50M → +1.5; < $5M → −2.
- Short-interest > 20% float (squeeze/vol risk): −1.5 unless breakout-confirmed.
- Sample reliability: < 60 sessions listed → −1 (in addition to listing cap).
Bounded ±5 total so the six factors stay dominant.

## 4. Execution spine merge (agentic-trader → automation/ v3)

One brain, one pair of hands, one journal:
- **Signal source**: `data/board_today.json` (public Pages build) — replaces ad-hoc watchlists.
- **Executor**: the Stockbroker agent (`~/.claude/agents/stockbroker.md`) via Robinhood MCP,
  account 901401059 only. agentic-trader's premarket/postmarket scheduled routines become the
  runner for contract v3; `C:\dev\agentic-trader\` journal/guardrails merge INTO this repo's
  `automation/` (single source of truth; agentic-trader dir then retires to a thin launcher).
- **Sleeves (per existing v2, kept)**: CORE = VOO sweep + owner slice SPCX (10% of cap,
  never score-managed — Brian's discretionary tranche plan applies); SATELLITE ≤ 20% of cap,
  score ≥ 60 entries, −8%/+16% exits, thesis exit < 55; breakout fast lane ≤ half satellite.
- **Fix the floor bug**: journal applied 71 while contract v2 says 60 — v3 contract states 60
  once, and the runner must echo the floor it used in every entry.
- **Caps**: `automation/cap.txt` is the single cap (currently $100 = funded account).
  MSFT position grandfathers into SATELLITE at next board scoring.
- **Kill switches (all kept)**: LIVE_ENABLED file, cap.txt, HALT file (from agentic-trader),
  score floor, listing cap, calibration hold, entry-zone rejection, order-alert abort.

## 5. Phases
- P1: contract v3 file + move agentic-trader routines to this repo (no scoring change).
- P2: wire Smart Money + Catalyst (feeds committed; task P2.06 already on ROADMAP).
- P3: guardrails 3b (listing cap trivial; calibration hold needs closed-signal history;
  entry-zone rejection pure function of existing chart data).
- P4: quality stack 3c + backtest the whole thing on the 519-name universe before raising cap.

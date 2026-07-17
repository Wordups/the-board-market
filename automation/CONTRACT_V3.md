# The Board — Runner Contract v3 (supersedes robinhood_daily.md v2)

Adopted 2026-07-17 on Brian's "full go". One system: board scores decide, the Stockbroker
agent executes, one journal grades everything. Runner: scheduled headless sessions
(premarket 7:57 ET / postmarket 16:33 ET) using the Stockbroker constitution
(`~/.claude/agents/stockbroker.md`).

## Hard gates — checked in order, any failure = log + stop
1. Kill switch: real orders ONLY if `automation/LIVE_ENABLED` exists (owner-created, never
   by the agent). Otherwise DRY-RUN everything.
2. HALT file: `automation/HALT` exists → research/exits-analysis only, zero orders (even dry).
3. Capital cap: `automation/cap.txt` (missing → $100). Total cost basis never exceeds it.
4. Market hours: weekend/holiday → SKIP.
5. Robinhood account 901401059 ONLY. Regulatory blocks (investor profile etc.) → notify
   Brian with the link, stop. Never retried around.
6. Order alerts: EQUITY_SUITABILITY on board-universe or owner-approved symbols → proceed
   and log. Any other alert → abort + notify.

## Sleeves (unchanged economics, restated once)
- CORE (~80% of cap): VOO sweep (headroom > $1 always parked, last step of every run) +
  owner slice SPCX 10% of cap (Brian's 3-tranche DCA plan; never score-managed, never
  stop-sold; tranche gates per watchlist plan).
- SATELLITE (≤20% of cap): board signals, floor **score ≥ 60** (echo the floor used in every
  journal entry — v2 journal bug applied 71). Exits: stop −8% / target +16% / thesis < 55.
  Breakout fast lane: breakout.confirmed AND score ≥ 60, ≤ half satellite budget, one at a
  time, extra exit on close back below trigger.
- Grandfathered: MSFT position (2026-07-17, $50 @ $395.08) joins SATELLITE at next scoring;
  manage by its journal thesis until the board scores it.

## Guardrails from the un-simplification (v3 additions)
- LISTING CAP: symbol with < 25 trading sessions → BENCH max, ineligible for satellite
  (owner core slice exempt because it is owner-designated, not signal-driven).
- ENTRY-ZONE REJECTION: no satellite entry when price > +10% above 20MA (chalk) or
  close < 200MA in stacked-bear / RSI(14) < 25 (longshot). Log REJECT_ZONE + reason.
- CALIBRATION HOLD: once ≥20 closed signals exist, a tier with rolling hit-rate < 55%
  is quarantined to DRY until it re-qualifies. Until then: log predicted-vs-realized on
  every closed signal (this history is the unlock).

## Profit outlook (report in every brief + journal entry)
Per setup: stop/target dollars at intended size, R/R (satellite standard = 2:1 — the
"+200" structure: risk 1 to win 2), and EV per $100 at the tier's target win rate
(e.g. LIVE @60%: 0.60×16 − 0.40×8 = **+$6.40 per $100 per signal**). Portfolio view in the
postmarket recap: realized P&L, open P&L per sleeve, hit-rate vs target, EV run-rate vs
Brian's $150/day goal with the capital math stated honestly (EV ≥ $150/day needs ≥ ~$47k
deployed at LIVE-tier EV·2 signals/wk cadence — deposits remain the growth engine).

## Journal + ledger (single source of truth, this repo)
- `automation/ledger.jsonl` (schema per v2) + `automation/journal.md` per run.
- Every order: thesis BEFORE placement, review before place, fresh UUID ref_id.
- `C:\dev\agentic-trader\journal\` is retired; its entries remain as history. That dir's
  run-routine.ps1 now points here (thin launcher only).

## Prohibitions (carried, non-negotiable)
No options, crypto, margin, shorting, averaging down. No venue but Robinhood until Brian
connects one (Kalshi/Polymarket forbidden to simulate). Agent never edits: this file,
LIVE_ENABLED, HALT, cap.txt, GUARDRAILS, score floors.

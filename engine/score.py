"""
The Board: Markets — Scoring Engine
Composite 100-point setup model. Calibrated for 60-65% win rate target.

Factor weights:
  - Technical (20):     trend, S/R, volume pattern
  - Catalyst (20):      earnings proximity, news flow
  - Rel Strength (15):  vs SPY and sector ETF
  - Smart Money (15):   placeholder for Form 4 / 13F (Phase 2)
  - Macro (15):         VIX regime, yields, sector tailwind
  - Sentiment (15):     RSI extremes, distance from MA

Auto-downgrades:
  - Earnings within 5 days:  -30
  - VIX > 25:                -15
  - FOMC week (Mon-Wed):     -20
  - Crypto in VIX>30:        -20

Tiers:
  - LOCK:  85+
  - LIVE:  71-84
  - BENCH: <71
"""

import pandas as pd
import numpy as np
from datetime import datetime

from universe import SECTOR_MAP, UNIVERSE


# ─────────────────────────── Technical (20 pts) ───────────────────────────

def technical_score(df: pd.DataFrame) -> tuple[float, list]:
    """Trend + structure + volume. Max 20."""
    if len(df) < 200:
        return 0, ["INSUFFICIENT_HISTORY"]

    score = 0
    notes = []
    close = df["Close"].iloc[-1]
    ma20 = df["Close"].rolling(20).mean().iloc[-1]
    ma50 = df["Close"].rolling(50).mean().iloc[-1]
    ma200 = df["Close"].rolling(200).mean().iloc[-1]

    # Trend alignment (8 pts)
    if close > ma20 > ma50 > ma200:
        score += 8
        notes.append("STACKED_BULL")
    elif close > ma50 > ma200:
        score += 5
        notes.append("BULL_TREND")
    elif close < ma20 < ma50 < ma200:
        score += 0
        notes.append("STACKED_BEAR")
    else:
        score += 3
        notes.append("MIXED_TREND")

    # Volume confirmation (6 pts)
    avg_vol = df["Volume"].rolling(20).mean().iloc[-1]
    recent_vol = df["Volume"].iloc[-5:].mean()
    if recent_vol > avg_vol * 1.3:
        score += 6
        notes.append("VOL_EXPANSION")
    elif recent_vol > avg_vol:
        score += 3

    # Distance from 20MA — too extended = exhausted, too far below = falling knife
    pct_from_ma20 = (close - ma20) / ma20
    if -0.03 < pct_from_ma20 < 0.05:
        score += 6  # sweet spot
        notes.append("NEAR_20MA")
    elif pct_from_ma20 > 0.10:
        score += 1
        notes.append("EXTENDED")

    return min(score, 20), notes


# ─────────────────────────── Catalyst (20 pts) ───────────────────────────

def catalyst_score(ticker: str, as_of: datetime, earnings_calendar: dict = None) -> tuple[float, list]:
    """Catalyst proximity. Earnings is the main driver; macro events handled in macro score."""
    notes = []

    # Without an earnings feed (Phase 2), score based on sector tailwind
    sector = SECTOR_MAP.get(ticker, "unknown")

    # Default catalyst score — sector-tilted baseline
    base = {
        "tech_mega": 12,
        "tech_growth": 14,
        "energy": 13,   # current geopolitical tailwind
        "defense": 13,  # current geopolitical tailwind
        "financials": 10,
        "healthcare": 10,
        "consumer": 9,
        "etf_sector": 8,
        "etf_macro": 6,
        "crypto": 15,   # high vol = high catalyst density
        "unknown": 8,
    }

    score = base.get(sector, 8)
    notes.append(f"SECTOR_BASE_{sector}")

    # Earnings proximity penalty handled in downgrades, not here
    return score, notes


# ─────────────────── Relative Strength (15 pts) ───────────────────

def relative_strength_score(df: pd.DataFrame, spy_df: pd.DataFrame) -> tuple[float, list]:
    """Performance vs SPY over 5d and 20d windows."""
    if len(df) < 20 or len(spy_df) < 20:
        return 0, ["INSUFFICIENT_HISTORY"]

    notes = []
    score = 0

    def ret(d, periods):
        if len(d) < periods + 1:
            return 0
        return (d["Close"].iloc[-1] / d["Close"].iloc[-periods - 1]) - 1

    rs_5 = ret(df, 5) - ret(spy_df, 5)
    rs_20 = ret(df, 20) - ret(spy_df, 20)

    # 5-day relative strength (7 pts)
    if rs_5 > 0.03:
        score += 7
        notes.append("RS5_STRONG")
    elif rs_5 > 0.01:
        score += 4
    elif rs_5 > 0:
        score += 2

    # 20-day relative strength (8 pts)
    if rs_20 > 0.05:
        score += 8
        notes.append("RS20_STRONG")
    elif rs_20 > 0.02:
        score += 5
    elif rs_20 > 0:
        score += 2

    return min(score, 15), notes


# ─────────────────── Smart Money (15 pts) — Phase 2 placeholder ───────────────────

def smart_money_score(ticker: str) -> tuple[float, list]:
    """
    Phase 2: parses Form 4 insider buys + 13F institutional adds + congressional cluster.
    Phase 1: returns neutral 7/15.
    """
    return 7, ["PHASE_2_PLACEHOLDER"]


# ─────────────────── Macro (15 pts) ───────────────────

def macro_score(ticker: str, vix: float, tnx: float, spy_trend: str) -> tuple[float, list]:
    """Regime fit. Different sectors thrive in different regimes."""
    notes = []
    score = 0
    sector = SECTOR_MAP.get(ticker, "unknown")

    # SPY trend alignment (8 pts)
    if spy_trend == "BULL" and sector in ("tech_mega", "tech_growth", "consumer", "crypto"):
        score += 8
        notes.append("REGIME_FIT_BULL")
    elif spy_trend == "BEAR" and sector in ("defense", "etf_macro"):
        score += 8
        notes.append("REGIME_FIT_BEAR")
    elif spy_trend == "SIDEWAYS":
        score += 4
    else:
        score += 2

    # VIX context (4 pts)
    if vix < 15:
        if sector in ("tech_mega", "tech_growth", "crypto"):
            score += 4
            notes.append("LOW_VIX_GROWTH")
        else:
            score += 2
    elif vix < 20:
        score += 3
    elif vix < 25:
        score += 2
    else:
        score += 0
        notes.append("HIGH_VIX")

    # Yields (3 pts)
    if tnx > 4.5:
        if sector == "financials":
            score += 3
            notes.append("HIGH_YIELDS_BANKS")
        elif sector in ("tech_growth", "crypto"):
            score += 0
            notes.append("HIGH_YIELDS_DRAG")
        else:
            score += 2
    else:
        score += 2

    return min(score, 15), notes


# ─────────────────── Sentiment (15 pts) ───────────────────

def sentiment_score(df: pd.DataFrame) -> tuple[float, list]:
    """RSI + distance from MA = mean-reversion / continuation read."""
    if len(df) < 50:
        return 0, ["INSUFFICIENT_HISTORY"]

    notes = []
    score = 0

    # RSI(14)
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    rsi = (100 - (100 / (1 + rs))).iloc[-1]

    if 50 <= rsi <= 65:
        score += 10  # bullish but not extended
        notes.append("RSI_HEALTHY_BULL")
    elif 40 <= rsi < 50:
        score += 7   # potential reversal zone
        notes.append("RSI_REVERSAL_ZONE")
    elif 65 < rsi <= 75:
        score += 5   # extended but trending
    elif rsi > 75:
        score += 1   # overbought
        notes.append("RSI_OVERBOUGHT")
    elif 30 <= rsi < 40:
        score += 3   # weak
    else:
        score += 0   # oversold, possible bounce but no entry signal

    # Volatility regime within the ticker
    returns = df["Close"].pct_change()
    vol_20 = returns.rolling(20).std().iloc[-1]
    vol_60 = returns.rolling(60).std().iloc[-1]
    if vol_20 < vol_60 * 0.8:
        score += 5   # vol contraction = setup forming
        notes.append("VOL_CONTRACTION")
    elif vol_20 > vol_60 * 1.5:
        score += 0
        notes.append("VOL_EXPANSION_DANGER")
    else:
        score += 3

    return min(score, 15), notes


# ─────────────────── Downgrades ───────────────────

def apply_downgrades(score: float, ticker: str, as_of: datetime,
                     vix: float, earnings_days: int | None = None,
                     fomc_week: bool = False) -> tuple[float, list]:
    """Variance penalties — the equivalent of the 3PT auto-downgrade."""
    flags = []
    sector = SECTOR_MAP.get(ticker, "unknown")

    # Earnings within 5 days
    if earnings_days is not None and 0 <= earnings_days <= 5:
        score -= 30
        flags.append(f"EARNINGS_IN_{earnings_days}D")

    # High VIX regime
    if vix > 25:
        score -= 15
        flags.append("HIGH_VOL_REGIME")

    # Crypto in extreme vol
    if sector == "crypto" and vix > 30:
        score -= 20
        flags.append("CRYPTO_VOL_EXTREME")

    # FOMC week Mon-Wed
    if fomc_week and as_of.weekday() in (0, 1, 2):
        score -= 20
        flags.append("FOMC_PRE")

    return score, flags


# ─────────────────── Composite ───────────────────

def score_setup(ticker: str, df: pd.DataFrame, spy_df: pd.DataFrame,
                vix: float, tnx: float, as_of: datetime,
                earnings_days: int | None = None,
                fomc_week: bool = False) -> dict:
    """Full composite scoring. Returns dict with tier, score, factor breakdown, flags."""

    # Determine SPY trend
    if len(spy_df) >= 50:
        spy_close = spy_df["Close"].iloc[-1]
        spy_ma50 = spy_df["Close"].rolling(50).mean().iloc[-1]
        spy_ma200 = spy_df["Close"].rolling(200).mean().iloc[-1] if len(spy_df) >= 200 else spy_ma50
        if spy_close > spy_ma50 > spy_ma200:
            spy_trend = "BULL"
        elif spy_close < spy_ma50 < spy_ma200:
            spy_trend = "BEAR"
        else:
            spy_trend = "SIDEWAYS"
    else:
        spy_trend = "UNKNOWN"

    # Factor scores
    tech, tech_notes = technical_score(df)
    cat, cat_notes = catalyst_score(ticker, as_of)
    rs, rs_notes = relative_strength_score(df, spy_df)
    sm, sm_notes = smart_money_score(ticker)
    macro, macro_notes = macro_score(ticker, vix, tnx, spy_trend)
    sent, sent_notes = sentiment_score(df)

    raw_score = tech + cat + rs + sm + macro + sent

    # Apply downgrades
    final_score, flags = apply_downgrades(
        raw_score, ticker, as_of, vix, earnings_days, fomc_week
    )

    # Tier assignment.
    # Phase 1 note: Smart Money is a 7/15 stub and Catalyst is sector-baseline
    # only (max 15/20). That removes ~13–16 points from the achievable ceiling
    # depending on sector, capping realistic scores at ~80 across the universe
    # (theoretical max ~86 for crypto, ~85 for tech_growth — both require every
    # other factor to max simultaneously with zero downgrades). LOCK at 85 is
    # therefore near-unreachable until Phase 2 wires real Form 4 / 13F and
    # earnings/news feeds. This is intentional: the system should refuse
    # high-conviction calls when load-bearing signals don't exist yet. Do not
    # lower the threshold to compensate.
    if final_score >= 85:
        tier = "LOCK"
    elif final_score >= 71:
        tier = "LIVE"
    else:
        tier = "BENCH"

    return {
        "ticker": ticker,
        "as_of": as_of.strftime("%Y-%m-%d") if isinstance(as_of, datetime) else str(as_of),
        "tier": tier,
        "score": round(final_score, 1),
        "raw_score": round(raw_score, 1),
        "factors": {
            "technical": round(tech, 1),
            "catalyst": round(cat, 1),
            "relative_strength": round(rs, 1),
            "smart_money": round(sm, 1),
            "macro": round(macro, 1),
            "sentiment": round(sent, 1),
        },
        "flags": flags,
        "notes": {
            "technical": tech_notes,
            "catalyst": cat_notes,
            "relative_strength": rs_notes,
            "macro": macro_notes,
            "sentiment": sent_notes,
        },
        "regime": spy_trend,
        "price": float(df["Close"].iloc[-1]) if len(df) else None,
    }

"""
The Board: Markets — Scoring Engine
Composite 100-point setup model. Calibrated for 60-65% win rate target.

Factor weights:
  - Technical (20):     trend, S/R, volume pattern
  - Catalyst (20):      sector baseline (0-8) + event layer (0-12: post-earnings
                        -beat drift, scheduled earnings catalysts)
  - Rel Strength (15):  vs SPY and sector ETF
  - Smart Money (15):   SEC EDGAR Form 4 insider buying (neutral 7 when
                        data unavailable)
  - Macro (15):         VIX regime, yields, sector tailwind
  - Sentiment (15):     RSI extremes, distance from MA

Guardrails (v3, report-side):
  - Listing cap:  < 25 trading sessions of history -> tier capped at BENCH.
  - reject_zone:  "chalk" (close > 1.10x MA20) / "longshot" (close < MA200 in
                  stacked-bear or RSI(14) < 25) / None. Enforcement is
                  runner-side; the engine only flags.

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

# Sector-tilted baseline, legacy 0-15 weights (rescaled to 0-8 in v3).
SECTOR_CATALYST_BASE = {
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


def _to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and not isinstance(value, datetime):
        return value
    try:
        return pd.Timestamp(value).date()
    except Exception:
        return None


def _earnings_event_layer(ticker: str, as_of: datetime, df: pd.DataFrame,
                          earnings_dates: list | None) -> tuple[float, list]:
    """
    Event layer 0-12 from the earnings calendar:
      - Post-earnings-beat drift window: 2-10 sessions after a beat -> +6..+12.
        Beat proxy = first-session price reaction (calendar carries dates only,
        no EPS surprise): >= +3% -> +6, >= +5% -> +9, >= +8% -> +12.
      - Confirmed upcoming earnings 6-30 days out -> +3 (scheduled catalyst
        outside the <=5-day risk window, which stays in apply_downgrades).
    Graceful degradation: unknown calendar -> 0 with an UNAVAILABLE note.
    """
    notes = []
    if earnings_dates is None:
        return 0.0, ["CATALYST_EVENTS_UNAVAILABLE"]
    if df is None or len(df) < 3:
        return 0.0, []

    as_of_d = _to_date(as_of)
    dates = sorted(d for d in (_to_date(x) for x in earnings_dates) if d is not None)
    past = [d for d in dates if d <= as_of_d]
    event = 0.0

    if past:
        last_e = past[-1]
        after_mask = df.index > pd.Timestamp(last_e)
        sessions_after = int(after_mask.sum())
        pre_pos = len(df) - sessions_after - 1
        if 2 <= sessions_after <= 10 and pre_pos >= 0:
            pre_close = float(df["Close"].iloc[pre_pos])
            post_close = float(df["Close"].iloc[pre_pos + 1])
            reaction = (post_close / pre_close - 1) if pre_close else 0.0
            if reaction >= 0.08:
                event = 12.0
            elif reaction >= 0.05:
                event = 9.0
            elif reaction >= 0.03:
                event = 6.0
            if event:
                notes.append(f"PED_DRIFT_S{sessions_after}_R{reaction * 100:.1f}PCT")

    if event == 0.0:
        upcoming = [(d - as_of_d).days for d in dates if d >= as_of_d]
        if upcoming and 6 <= upcoming[0] <= 30:
            event = 3.0
            notes.append(f"EARNINGS_AHEAD_{upcoming[0]}D")

    return event, notes


def catalyst_score(ticker: str, as_of: datetime, df: pd.DataFrame = None,
                   earnings_dates: list | None = None) -> tuple[float, list]:
    """
    Catalyst 0-20 (v3): sector baseline rescaled to 0-8 + event layer 0-12.
    Earnings-PROXIMITY risk stays in apply_downgrades — never scored here.
    """
    notes = []
    sector = SECTOR_MAP.get(ticker, "unknown")
    base = round(SECTOR_CATALYST_BASE.get(sector, 8) * 8 / 15, 1)
    notes.append(f"SECTOR_BASE_{sector}")

    if earnings_dates is None:
        try:
            try:
                from calendars.earnings import get_earnings_dates
            except ImportError:
                from engine.calendars.earnings import get_earnings_dates
            earnings_dates = get_earnings_dates(ticker)
        except Exception:
            earnings_dates = None

    event, event_notes = _earnings_event_layer(ticker, as_of, df, earnings_dates)
    notes.extend(event_notes)

    return min(base + event, 20.0), notes


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


# ─────────────────── Smart Money (15 pts) — SEC EDGAR Form 4 ───────────────────

def smart_money_score(ticker: str, as_of: datetime | None = None) -> tuple[float, list]:
    """
    Real Smart Money factor from the Form 4 insider scraper
    (engine/signals/insider.py, cached daily under data/).
    Degrades to neutral 7/15 whenever the feed is unavailable — a
    network-degraded run must never crash or zero out scores.
    """
    try:
        try:
            from signals.insider import smart_money_signal
        except ImportError:
            from engine.signals.insider import smart_money_signal
        return smart_money_signal(ticker, as_of or datetime.now())
    except Exception:
        return 7.0, ["SMART_MONEY_UNAVAILABLE"]


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

def rsi14(df: pd.DataFrame) -> float:
    """Latest RSI(14) value for the frame."""
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    return float((100 - (100 / (1 + rs))).iloc[-1])


def sentiment_score(df: pd.DataFrame) -> tuple[float, list]:
    """RSI + distance from MA = mean-reversion / continuation read."""
    if len(df) < 50:
        return 0, ["INSUFFICIENT_HISTORY"]

    notes = []
    score = 0

    rsi = rsi14(df)

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


# ─────────────────── Entry-zone rejection (v3 guardrail) ───────────────────

LISTING_CAP_SESSIONS = 25
LISTING_CAP_FLAG = "LISTING_CAP (<25 sessions)"


def entry_reject_zone(df: pd.DataFrame) -> str | None:
    """
    Chalk/longshot analog of the value-zone rejection:
      "chalk"    — close > 1.10 x MA20 (chasing an extended move)
      "longshot" — close < MA200 AND (stacked-bear alignment OR RSI(14) < 25)
      None       — entry zone acceptable
    Engine-side flag only; enforcement is runner-side.
    """
    if df is None or len(df) < 20:
        return None
    close = float(df["Close"].iloc[-1])
    ma20 = float(df["Close"].rolling(20).mean().iloc[-1])
    if ma20 and close > 1.10 * ma20:
        return "chalk"

    if len(df) < 200:
        return None
    ma50 = float(df["Close"].rolling(50).mean().iloc[-1])
    ma200 = float(df["Close"].rolling(200).mean().iloc[-1])
    if close < ma200:
        stacked_bear = close < ma20 < ma50 < ma200
        if stacked_bear or rsi14(df) < 25:
            return "longshot"
    return None


# ─────────────────── Composite ───────────────────

def score_setup(ticker: str, df: pd.DataFrame, spy_df: pd.DataFrame,
                vix: float, tnx: float, as_of: datetime,
                earnings_days: int | None = None,
                fomc_week: bool = False,
                earnings_dates: list | None = None) -> dict:
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
    cat, cat_notes = catalyst_score(ticker, as_of, df=df, earnings_dates=earnings_dates)
    rs, rs_notes = relative_strength_score(df, spy_df)
    sm, sm_notes = smart_money_score(ticker, as_of)
    macro, macro_notes = macro_score(ticker, vix, tnx, spy_trend)
    sent, sent_notes = sentiment_score(df)

    raw_score = tech + cat + rs + sm + macro + sent

    # Apply downgrades
    final_score, flags = apply_downgrades(
        raw_score, ticker, as_of, vix, earnings_days, fomc_week
    )

    # Tier assignment.
    # v3 note: Smart Money (Form 4) and the Catalyst event layer are wired, so
    # the theoretical ceiling is a true 100 and LOCK (85+) is reachable — but
    # only when real insider buying and a real catalyst coincide with strong
    # technicals. When feeds are unavailable the factors degrade to neutral
    # (Smart Money 7/15) or baseline (Catalyst 0-8), reverting to the Phase-1
    # ~80 ceiling. Do not lower the thresholds to compensate.
    if final_score >= 85:
        tier = "LOCK"
    elif final_score >= 71:
        tier = "LIVE"
    else:
        tier = "BENCH"

    # Listing cap (Rule-48 analog): < 25 trading sessions of price history
    # -> tier capped at BENCH regardless of score.
    listing_capped = len(df) < LISTING_CAP_SESSIONS
    if listing_capped:
        tier = "BENCH"
        flags.append(LISTING_CAP_FLAG)

    # Entry-zone rejection flag (chalk/longshot). Runner enforces; engine flags.
    reject_zone = entry_reject_zone(df)
    if reject_zone:
        flags.append(f"REJECT_ZONE_{reject_zone.upper()}")

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
        "listing_capped": listing_capped,
        "reject_zone": reject_zone,
        "notes": {
            "technical": tech_notes,
            "catalyst": cat_notes,
            "relative_strength": rs_notes,
            "smart_money": sm_notes,
            "macro": macro_notes,
            "sentiment": sent_notes,
        },
        "regime": spy_trend,
        "price": float(df["Close"].iloc[-1]) if len(df) else None,
    }

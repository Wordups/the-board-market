"""
The Board: Markets — Insider Signal Audit (P2.03.1)

Generates a universe-wide cross-section of the insider signal for a given
as_of date. Used to verify that insider_signal() actually differentiates
across tickers and across market regimes before we wire it into score.py
(P2.06).

Output: a markdown report with
  1. Per-ticker table (ticker, sector, score, raw net $, buyers, sellers, top note)
  2. Histogram of score buckets across the universe
  3. Sector breakdown (avg score)
  4. Outliers (score >= 5 or unusual patterns)

Public API:
    audit(as_of, tickers=None) -> dict  (full diagnostic structure)
    write_audit_md(audit_result, out_path)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .insider import (
    _load_cache, _to_date, BUY_CODES, SELL_CODES, _band_score
)

try:
    from universe import ALL_TICKERS, SECTOR_MAP
except ImportError:
    from engine.universe import ALL_TICKERS, SECTOR_MAP


def _per_ticker_diag(ticker: str, as_of_d: date, cache: dict) -> dict:
    """
    Compute full diagnostics for one ticker. Returns a row dict.
    """
    entry = cache.get(ticker.upper()) or cache.get(ticker) or {}
    txns = entry.get("filings") or []
    cik = entry.get("cik")

    window_start = as_of_d - timedelta(days=90)
    buy_dollars = 0.0
    sell_dollars = 0.0
    buyers: set[str] = set()
    sellers: set[str] = set()
    in_window_buys = []
    in_window_sells = []

    for row in txns:
        rd = _to_date(row.get("date") or row.get("filing_date"))
        if rd is None or rd > as_of_d or rd < window_start:
            continue
        code = row.get("code") or ""
        value = float(row.get("value") or 0.0)
        owner = row.get("owner") or ""
        if code in BUY_CODES and value > 0:
            buy_dollars += value
            if owner:
                buyers.add(owner)
            in_window_buys.append(row)
        elif code in SELL_CODES and value > 0:
            sell_dollars += value
            if owner:
                sellers.add(owner)
            in_window_sells.append(row)

    net = buy_dollars - sell_dollars

    # Replicate scoring logic (kept in sync with insider_signal()).
    score = _band_score(net)
    if len(buyers) >= 3:
        score = min(7, score + 2)
    elif len(buyers) == 2:
        score = min(7, score + 1)

    # Top note: largest single transaction in window.
    all_in_window = in_window_buys + in_window_sells
    top_note = "—"
    if all_in_window:
        top = max(all_in_window, key=lambda r: float(r.get("value") or 0.0))
        side = "BUY" if top.get("code") in BUY_CODES else "SELL"
        owner_short = (top.get("owner") or "?").split(" ")[0][:12]
        top_note = f"{side} ${float(top.get('value') or 0):,.0f} ({owner_short})"

    return {
        "ticker": ticker,
        "sector": SECTOR_MAP.get(ticker, "unknown"),
        "score": int(score),
        "net_dollars": int(net),
        "buy_dollars": int(buy_dollars),
        "sell_dollars": int(sell_dollars),
        "distinct_buyers": len(buyers),
        "distinct_sellers": len(sellers),
        "in_window_txns": len(all_in_window),
        "top_note": top_note,
        "cik": cik or "—",
        "has_filings": bool(txns),
    }


def audit(as_of: date | datetime, tickers: Iterable[str] | None = None) -> dict:
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        raise ValueError(f"Invalid as_of: {as_of!r}")

    cache = _load_cache()
    tickers = list(tickers) if tickers is not None else list(ALL_TICKERS)

    rows = [_per_ticker_diag(t, as_of_d, cache) for t in tickers]

    # Histogram of scores
    hist = Counter(r["score"] for r in rows)
    hist_full = {i: hist.get(i, 0) for i in range(0, 8)}

    # Sector breakdown — avg score per sector
    sector_scores: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        sector_scores[r["sector"]].append(r["score"])
    sector_avg = {
        s: round(sum(v) / len(v), 2) if v else 0
        for s, v in sector_scores.items()
    }

    # Outliers
    outliers_high = sorted(
        [r for r in rows if r["score"] >= 5],
        key=lambda r: (-r["score"], -r["net_dollars"]),
    )
    outliers_low = sorted(
        [r for r in rows if r["net_dollars"] <= -5_000_000],
        key=lambda r: r["net_dollars"],
    )[:5]

    diff_summary = {
        "tickers_with_filings": sum(1 for r in rows if r["has_filings"]),
        "tickers_with_window_activity": sum(1 for r in rows if r["in_window_txns"] > 0),
        "tickers_net_buying": sum(1 for r in rows if r["net_dollars"] > 0),
        "tickers_net_selling": sum(1 for r in rows if r["net_dollars"] < 0),
        "score_std": round(_std([r["score"] for r in rows]), 3),
        "min_score": min((r["score"] for r in rows), default=0),
        "max_score": max((r["score"] for r in rows), default=0),
    }

    return {
        "as_of": as_of_d.isoformat(),
        "rows": rows,
        "histogram": hist_full,
        "sector_avg": sector_avg,
        "outliers_high": outliers_high,
        "outliers_low": outliers_low,
        "summary": diff_summary,
    }


def _std(values: list[int | float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return var ** 0.5


# ─────────────────────────── Markdown rendering ───────────────────────────

def _fmt_dollars(n: int) -> str:
    sign = "-" if n < 0 else ""
    a = abs(n)
    if a >= 1_000_000:
        return f"{sign}${a/1_000_000:.2f}M"
    if a >= 1_000:
        return f"{sign}${a/1_000:.0f}k"
    return f"{sign}${a}"


def write_audit_md(result: dict, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    lines: list[str] = []

    lines.append(f"# Insider Signal Audit — as_of {result['as_of']}")
    lines.append("")
    lines.append("Generated by `engine.signals.insider_audit` (P2.03.1).")
    lines.append("Scoring: 0–7 of Smart Money's 15-pt budget. 90-day trailing window. "
                 "Open-market only (codes P/S). Cluster bonus +1 for 2 buyers, +2 for 3+.")
    lines.append("")

    s = result["summary"]
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Universe: **{len(result['rows'])}** tickers")
    lines.append(f"- Have any Form 4s cached: **{s['tickers_with_filings']}**")
    lines.append(f"- Have activity in 90-day window: **{s['tickers_with_window_activity']}**")
    lines.append(f"- Net buying: **{s['tickers_net_buying']}**  •  Net selling: **{s['tickers_net_selling']}**")
    lines.append(f"- Score range: **{s['min_score']}–{s['max_score']}**  •  Std dev: **{s['score_std']}**")
    lines.append("")

    lines.append("## Score histogram")
    lines.append("")
    lines.append("| Score | Count | Bar |")
    lines.append("|------:|------:|:----|")
    for k in sorted(result["histogram"]):
        v = result["histogram"][k]
        bar = "█" * v
        lines.append(f"| {k} | {v} | {bar} |")
    lines.append("")

    lines.append("## Sector averages")
    lines.append("")
    lines.append("| Sector | Avg score | N tickers |")
    lines.append("|:-------|----------:|----------:|")
    sector_counts: dict[str, int] = defaultdict(int)
    for r in result["rows"]:
        sector_counts[r["sector"]] += 1
    for sec in sorted(result["sector_avg"], key=lambda x: -result["sector_avg"][x]):
        lines.append(f"| {sec} | {result['sector_avg'][sec]:.2f} | {sector_counts[sec]} |")
    lines.append("")

    lines.append("## Per-ticker (sorted by score desc, then net $ desc)")
    lines.append("")
    lines.append("| Ticker | Sector | Score | Net $ | Buyers | Sellers | Txns | Top |")
    lines.append("|:-------|:-------|------:|------:|------:|------:|----:|:----|")
    sorted_rows = sorted(
        result["rows"],
        key=lambda r: (-r["score"], -r["net_dollars"]),
    )
    for r in sorted_rows:
        lines.append(
            f"| {r['ticker']} | {r['sector']} | {r['score']} | "
            f"{_fmt_dollars(r['net_dollars'])} | {r['distinct_buyers']} | "
            f"{r['distinct_sellers']} | {r['in_window_txns']} | {r['top_note']} |"
        )
    lines.append("")

    lines.append("## Outliers — high conviction (score ≥ 5)")
    lines.append("")
    if not result["outliers_high"]:
        lines.append("_None._")
    else:
        for r in result["outliers_high"]:
            lines.append(
                f"- **{r['ticker']}** ({r['sector']}) — score {r['score']}, "
                f"net {_fmt_dollars(r['net_dollars'])} across {r['distinct_buyers']} buyers / "
                f"{r['distinct_sellers']} sellers. Top: {r['top_note']}"
            )
    lines.append("")

    lines.append("## Outliers — heaviest net selling (top 5)")
    lines.append("")
    if not result["outliers_low"]:
        lines.append("_None._")
    else:
        for r in result["outliers_low"]:
            lines.append(
                f"- **{r['ticker']}** ({r['sector']}) — net {_fmt_dollars(r['net_dollars'])} "
                f"across {r['distinct_sellers']} sellers."
            )
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path

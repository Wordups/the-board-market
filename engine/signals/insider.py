"""
The Board: Markets — SEC EDGAR Form 4 insider scraper
P2.03

Pulls Form 4 (insider transaction) filings from SEC EDGAR for each universe
ticker, parses the transaction lines, and scores net open-market insider
buying over a trailing 90-day window.

Scoring band (0–7 of Smart Money's 15-pt budget):
    net_dollars <= 0                : 0   (net selling or no activity)
    0      <  net <  100_000        : 1   (token amount)
    100k   <= net <  500_000        : 3   (a single insider with conviction)
    500k   <= net < 2_000_000       : 5   (multiple insiders / large buy)
    2M     <= net                   : 7   (cluster of high-conviction buys)

We also award a small bonus for multiple distinct buyers (cluster signal):
    +1 if 2 distinct insiders buying, +2 if 3+ (capped at 7 total).

Only transactionCode == 'P' (open-market purchase) and 'S' (open-market sale)
are counted. Grants ('A'), option exercises ('M'), and other non-discretionary
codes are ignored — they don't reflect conviction.

Cache: data/insider_filings.json
       { "<TICKER>": { "cik": "...", "filings": [ {txn rows...} ] }, "_fetched_at": "..." }

Network notes:
  SEC EDGAR requires a User-Agent with contact info. Rate limit ~10 req/sec.
  All endpoints used: data.sec.gov/submissions, www.sec.gov/Archives/edgar/data.

Public API:
    refresh_insider_filings(tickers=None, force=False) -> dict
    insider_signal(ticker, as_of) -> (score, notes)
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / "insider_filings.json"
CIK_CACHE = DATA_DIR / "sec_company_tickers.json"
CACHE_TTL_HOURS = 24
LOOKBACK_DAYS = 180  # we cache 180 days; scoring window is 90

USER_AGENT = "the-board-market research word.brian1@gmail.com"
REQ_INTERVAL_SEC = 0.12  # ~8 req/sec, under SEC's 10/sec ceiling

# Transaction codes that count as discretionary open-market activity
BUY_CODES = {"P"}
SELL_CODES = {"S"}


# ─────────────────────────── HTTP helpers ───────────────────────────

def _get(url: str) -> bytes | None:
    """Single GET with SEC-compliant headers. Returns None on failure."""
    try:
        import httpx
    except ImportError:
        return None
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    try:
        with httpx.Client(timeout=15, headers=headers, follow_redirects=True) as c:
            r = c.get(url)
            if r.status_code == 200:
                return r.content
    except Exception:
        return None
    return None


def _throttled_get(url: str) -> bytes | None:
    time.sleep(REQ_INTERVAL_SEC)
    return _get(url)


# ─────────────────────────── CIK lookup ───────────────────────────

def _load_cik_map() -> dict[str, str]:
    """Ticker -> zero-padded 10-digit CIK string."""
    if CIK_CACHE.exists():
        age = (datetime.utcnow().timestamp() - CIK_CACHE.stat().st_mtime) / 3600
        if age < 24 * 30:  # CIK map is very stable; refresh monthly
            with open(CIK_CACHE) as f:
                return json.load(f)

    body = _get("https://www.sec.gov/files/company_tickers.json")
    if not body:
        if CIK_CACHE.exists():
            with open(CIK_CACHE) as f:
                return json.load(f)
        return {}

    raw = json.loads(body)
    mapping: dict[str, str] = {}
    for entry in raw.values():
        ticker = (entry.get("ticker") or "").upper()
        cik = entry.get("cik_str")
        if ticker and cik:
            mapping[ticker] = str(cik).zfill(10)

    with open(CIK_CACHE, "w") as f:
        json.dump(mapping, f)
    return mapping


# ─────────────────────────── Filing index ───────────────────────────

def _fetch_form4_index(cik: str) -> list[dict]:
    """
    Returns a list of {accession_no, filing_date, primary_doc} for Form 4
    filings, newest first, from data.sec.gov/submissions/CIK{cik}.json.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    body = _throttled_get(url)
    if not body:
        return []
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        return []

    recent = (doc.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    dates = recent.get("filingDate") or []
    primary = recent.get("primaryDocument") or []

    out = []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        if i >= len(accessions) or i >= len(dates):
            continue
        out.append({
            "accession_no": accessions[i],
            "filing_date": dates[i],
            "primary_doc": primary[i] if i < len(primary) else "",
        })
    return out


# ─────────────────────────── Form 4 XML parser ───────────────────────────

def _parse_form4(xml_bytes: bytes) -> list[dict]:
    """
    Returns a list of transaction rows extracted from a Form 4 XML document.
    Each row: {date, code, shares, price, value, owner_name}.
    Only includes nonDerivativeTransaction rows (the actual stock buys/sells,
    not derivative grants).
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    def _txt(elem, path) -> str:
        if elem is None:
            return ""
        node = elem.find(path)
        if node is None:
            return ""
        return (node.text or "").strip()

    # Reporter name (the insider). May be multiple reportingOwner elements;
    # we use the first for labeling.
    owner_name = ""
    owner_node = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    if owner_node is not None and owner_node.text:
        owner_name = owner_node.text.strip()

    rows = []
    for tx in root.findall(".//nonDerivativeTable/nonDerivativeTransaction"):
        code = _txt(tx, "transactionCoding/transactionCode")
        date_str = _txt(tx, "transactionDate/value")
        shares = _txt(tx, "transactionAmounts/transactionShares/value")
        price = _txt(tx, "transactionAmounts/transactionPricePerShare/value")
        # A/D flag: A = acquired (buy direction), D = disposed (sell direction).
        # We rely on transactionCode for buy/sell classification but capture it
        # for diagnostics.
        ad = _txt(tx, "transactionAmounts/transactionAcquiredDisposedCode/value")

        try:
            shares_f = float(shares) if shares else 0.0
        except ValueError:
            shares_f = 0.0
        try:
            price_f = float(price) if price else 0.0
        except ValueError:
            price_f = 0.0

        rows.append({
            "date": date_str,
            "code": code,
            "ad": ad,
            "shares": shares_f,
            "price": price_f,
            "value": shares_f * price_f,
            "owner": owner_name,
        })
    return rows


def _fetch_filing_xml(cik: str, accession_no: str, primary_doc: str) -> bytes | None:
    """
    Build the Form 4 XML URL. EDGAR's `primaryDocument` for Form 4 often points
    at an XSL-rendered viewer path like `xslF345X06/wk-form4_NNN.xml`, which
    returns HTML. The raw XML lives at the sibling `wk-form4_NNN.xml`. Strip
    any xsl viewer prefix and force a .xml extension.
    """
    doc = primary_doc
    # Drop the xsl viewer subdirectory if present (xslF345X02, X03, X05, X06 ...)
    if "/" in doc:
        head, tail = doc.rsplit("/", 1)
        if head.lower().startswith("xsl"):
            doc = tail
    if not doc.endswith(".xml"):
        doc = doc.rsplit(".", 1)[0] + ".xml"
    cik_int = str(int(cik))
    acc_clean = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{doc}"
    return _throttled_get(url)


# ─────────────────────────── Cache orchestration ───────────────────────────

def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    cache["_fetched_at"] = datetime.utcnow().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _cache_age_hours(cache: dict) -> float:
    ts = cache.get("_fetched_at")
    if not ts:
        return float("inf")
    try:
        return (datetime.utcnow() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except ValueError:
        return float("inf")


def _refresh_ticker(ticker: str, cik: str) -> dict:
    """Pull Form 4 filings for ticker, parse the recent ones, return cache entry."""
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    index = _fetch_form4_index(cik)

    txns: list[dict] = []
    for entry in index:
        try:
            fdate = datetime.strptime(entry["filing_date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate < cutoff:
            break  # index is newest-first
        xml = _fetch_filing_xml(cik, entry["accession_no"], entry["primary_doc"])
        if not xml:
            continue
        for row in _parse_form4(xml):
            row["filing_date"] = entry["filing_date"]
            row["accession"] = entry["accession_no"]
            txns.append(row)

    return {"cik": cik, "filings": txns}


def refresh_insider_filings(tickers: Iterable[str] | None = None,
                            force: bool = False) -> dict:
    """Refresh the cached Form 4 transaction list."""
    cache = _load_cache()
    if not force and _cache_age_hours(cache) < CACHE_TTL_HOURS:
        return cache

    if tickers is None:
        try:
            from universe import ALL_TICKERS
        except ImportError:
            from engine.universe import ALL_TICKERS
        tickers = ALL_TICKERS

    cik_map = _load_cik_map()
    for ticker in tickers:
        cik = cik_map.get(ticker.upper())
        if not cik:
            cache[ticker] = {"cik": None, "filings": []}
            continue
        cache[ticker] = _refresh_ticker(ticker, cik)

    _save_cache(cache)
    return cache


# ─────────────────────────── Scoring ───────────────────────────

def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _band_score(net_dollars: float) -> int:
    if net_dollars <= 0:
        return 0
    if net_dollars < 100_000:
        return 1
    if net_dollars < 500_000:
        return 3
    if net_dollars < 2_000_000:
        return 5
    return 7


def insider_signal(ticker: str, as_of: date | datetime) -> tuple[float, list[str]]:
    """
    Score 0–7 reflecting net open-market insider buying in the trailing 90 days
    relative to `as_of`. Returns (score, notes).

    Point-in-time safe: only counts transactions strictly on or before as_of.
    """
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return 0.0, ["INVALID_AS_OF"]

    cache = _load_cache()
    entry = cache.get(ticker.upper()) or cache.get(ticker) or {}
    txns = entry.get("filings") or []
    if not txns:
        return 0.0, ["NO_FILINGS"]

    window_start = as_of_d - timedelta(days=90)
    buy_dollars = 0.0
    sell_dollars = 0.0
    buyers: set[str] = set()

    for row in txns:
        rd = _to_date(row.get("date") or row.get("filing_date"))
        if rd is None or rd > as_of_d or rd < window_start:
            continue
        code = row.get("code") or ""
        value = float(row.get("value") or 0.0)
        if code in BUY_CODES and value > 0:
            buy_dollars += value
            owner = row.get("owner") or ""
            if owner:
                buyers.add(owner)
        elif code in SELL_CODES and value > 0:
            sell_dollars += value

    net = buy_dollars - sell_dollars
    score = _band_score(net)

    notes: list[str] = []
    if net > 0:
        notes.append(f"NET_BUY_${int(net):,}")
    elif net < 0:
        notes.append(f"NET_SELL_${int(-net):,}")
    else:
        notes.append("FLAT")

    if len(buyers) >= 3:
        score = min(7, score + 2)
        notes.append(f"CLUSTER_{len(buyers)}_BUYERS")
    elif len(buyers) == 2:
        score = min(7, score + 1)
        notes.append("CLUSTER_2_BUYERS")

    return float(score), notes


if __name__ == "__main__":
    import sys

    sample = ["NVDA", "MSFT", "AAPL", "JPM", "META"]
    if "--refresh" in sys.argv:
        print("Refreshing insider filings from SEC EDGAR...")
        refresh_insider_filings(tickers=sample, force=True)

    today = date.today()
    print(f"\nInsider signal as of {today}:")
    for t in sample:
        score, notes = insider_signal(t, today)
        print(f"  {t:6s}  score={score:.0f}  notes={notes}")

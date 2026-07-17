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
    insider_signal(ticker, as_of) -> (score, notes)          # legacy 0-7 band
    smart_money_signal(ticker, as_of) -> (score, notes)      # v3 0-15 factor
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
LOOKBACK_DAYS = 180  # default cache window; scoring window is 90.
# Audits at historical as_of values can pass lookback_days to refresh_insider_filings
# to extend the window.

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

def _extract_form4_rows(block: dict) -> list[dict]:
    """Pick Form 4 entries out of an EDGAR submissions block (recent or older)."""
    forms = block.get("form") or []
    accessions = block.get("accessionNumber") or []
    dates = block.get("filingDate") or []
    primary = block.get("primaryDocument") or []
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


def _fetch_form4_index(cik: str, cutoff_date: date | None = None) -> list[dict] | None:
    """
    Returns a list of {accession_no, filing_date, primary_doc} for Form 4
    filings, newest first — or None when EDGAR could not be reached (so
    callers can distinguish network failure from a genuinely empty index. Walks the `recent` block from
    data.sec.gov/submissions/CIK{cik}.json AND, if `cutoff_date` is older
    than the oldest `recent` entry, follows the `files` array for archived
    submissions blocks.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    body = _throttled_get(url)
    if not body:
        return None  # network / EDGAR unavailable — distinct from "no Form 4s"
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        return None

    filings = doc.get("filings") or {}
    out = _extract_form4_rows(filings.get("recent") or {})

    # Decide whether to load older archive blocks.
    if cutoff_date is not None:
        oldest_in_recent: date | None = None
        if out:
            try:
                oldest_in_recent = datetime.strptime(out[-1]["filing_date"], "%Y-%m-%d").date()
            except ValueError:
                pass
        # Walk older `files` if we still need data before what `recent` has.
        if oldest_in_recent is None or oldest_in_recent > cutoff_date:
            for archive in filings.get("files") or []:
                # Each archive entry has filingFrom / filingTo / name
                try:
                    a_to = datetime.strptime(archive.get("filingTo", ""), "%Y-%m-%d").date()
                except ValueError:
                    a_to = None
                # Skip archives entirely newer than cutoff is irrelevant — they're older blocks.
                # Stop once an archive's newest entry is older than our cutoff.
                a_url = f"https://data.sec.gov/submissions/{archive.get('name')}"
                a_body = _throttled_get(a_url)
                if not a_body:
                    continue
                try:
                    a_doc = json.loads(a_body)
                except json.JSONDecodeError:
                    continue
                out.extend(_extract_form4_rows(a_doc))
                # If this archive's oldest entry is already before cutoff, stop.
                try:
                    a_from = datetime.strptime(archive.get("filingFrom", ""), "%Y-%m-%d").date()
                    if a_from <= cutoff_date:
                        break
                except ValueError:
                    continue

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

    # Role flags — officer/director conviction matters for Smart Money v3.
    def _flag(path: str) -> bool:
        node = root.find(path)
        if node is None or node.text is None:
            return False
        return node.text.strip().lower() in ("1", "true")

    is_officer = _flag(".//reportingOwner/reportingOwnerRelationship/isOfficer")
    is_director = _flag(".//reportingOwner/reportingOwnerRelationship/isDirector")

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
            "is_officer": is_officer,
            "is_director": is_director,
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


def _refresh_ticker(ticker: str, cik: str, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """Pull Form 4 filings for ticker, parse them, return cache entry."""
    cutoff = date.today() - timedelta(days=lookback_days)
    index = _fetch_form4_index(cik, cutoff_date=cutoff)
    if index is None:
        # EDGAR unreachable — mark the entry so scoring falls back to neutral
        # instead of reading "no filings" as a real (bearish) signal.
        return {"cik": cik, "filings": [], "lookback_days": lookback_days,
                "error": "FETCH_FAILED"}

    txns: list[dict] = []
    for entry in index:
        try:
            fdate = datetime.strptime(entry["filing_date"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if fdate < cutoff:
            continue  # may not be in date order across archive boundaries
        xml = _fetch_filing_xml(cik, entry["accession_no"], entry["primary_doc"])
        if not xml:
            continue
        for row in _parse_form4(xml):
            row["filing_date"] = entry["filing_date"]
            row["accession"] = entry["accession_no"]
            txns.append(row)

    return {"cik": cik, "filings": txns, "lookback_days": lookback_days}


def refresh_insider_filings(tickers: Iterable[str] | None = None,
                            force: bool = False,
                            lookback_days: int = LOOKBACK_DAYS) -> dict:
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
            # No CIK: either an index/ETF (no Form 4s exist) or the CIK map
            # itself failed to download. If the map is empty, treat as a fetch
            # failure so scoring degrades to neutral instead of bearish.
            entry = {"cik": None, "filings": [], "lookback_days": lookback_days}
            if not cik_map:
                entry["error"] = "FETCH_FAILED"
            if ticker not in cache or not cik_map:
                cache[ticker] = entry
            continue
        fresh = _refresh_ticker(ticker, cik, lookback_days=lookback_days)
        if fresh.get("error") and (cache.get(ticker) or {}).get("filings"):
            continue  # keep the last good pull rather than clobbering it
        cache[ticker] = fresh

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


# ─────────────────────────── Smart Money v3 (0-15) ───────────────────────────

SMART_MONEY_NEUTRAL = 7.0   # fallback when EDGAR data is unavailable
SMART_MONEY_BASE = 4.0      # baseline when data IS available (net-selling cap)


def _dollar_scale(net_dollars: float) -> float:
    """Dollar-size scaling applied to the buy bonuses."""
    if net_dollars < 100_000:
        return 0.4
    if net_dollars < 500_000:
        return 0.7
    return 1.0


def smart_money_signal(ticker: str, as_of: date | datetime) -> tuple[float, list[str]]:
    """
    Smart Money factor on the full 0-15 scale (v3, replaces the 7/15 stub).

    Scale:
        unavailable data           -> 7.0 neutral (never crash / never zero out)
        available, no net buying   -> 4.0 baseline (net-selling regime cap)
        cluster buying             -> +6 (2 distinct insiders) / +8 (3+), 90d window
        officer/director OM buy    -> +4
        dollar-size scaling        -> bonuses x0.4 (<$100k) / x0.7 (<$500k) / x1.0
        cap                        -> 15

    Legacy cache rows predate the is_officer/is_director fields; any Form 4
    filer is an insider by definition, so rows missing the fields still earn
    the officer/director credit.
    """
    as_of_d = _to_date(as_of)
    if as_of_d is None:
        return SMART_MONEY_NEUTRAL, ["SMART_MONEY_UNAVAILABLE", "INVALID_AS_OF"]

    cache = _load_cache()
    entry = cache.get(ticker.upper()) or cache.get(ticker)
    if not entry or entry.get("error"):
        return SMART_MONEY_NEUTRAL, ["SMART_MONEY_UNAVAILABLE"]
    if entry.get("cik") is None:
        # Ticker has no EDGAR identity (index/ETF/crypto proxy) — no Form 4
        # universe exists for it, so stay neutral rather than bearish.
        return SMART_MONEY_NEUTRAL, ["SMART_MONEY_NO_CIK"]

    txns = entry.get("filings") or []
    window_start = as_of_d - timedelta(days=90)

    buy_dollars = 0.0
    sell_dollars = 0.0
    buyers: set[str] = set()
    officer_buy = False

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
            if ("is_officer" not in row and "is_director" not in row) or \
                    row.get("is_officer") or row.get("is_director"):
                officer_buy = True
        elif code in SELL_CODES and value > 0:
            sell_dollars += value

    net = buy_dollars - sell_dollars
    notes: list[str] = []

    if buy_dollars <= 0 or net <= 0:
        if sell_dollars > 0:
            notes.append(f"NET_SELL_${int(sell_dollars - buy_dollars):,}")
        else:
            notes.append("NO_OPEN_MARKET_BUYS")
        return SMART_MONEY_BASE, notes

    notes.append(f"NET_BUY_${int(net):,}")
    bonus = 0.0
    if len(buyers) >= 3:
        bonus += 8.0
        notes.append(f"CLUSTER_{len(buyers)}_BUYERS")
    elif len(buyers) == 2:
        bonus += 6.0
        notes.append("CLUSTER_2_BUYERS")
    if officer_buy:
        bonus += 4.0
        notes.append("OFFICER_DIRECTOR_BUY")

    scale = _dollar_scale(net)
    if scale < 1.0:
        notes.append(f"DOLLAR_SCALE_{scale}")

    score = min(15.0, SMART_MONEY_BASE + bonus * scale)
    return round(score, 1), notes


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

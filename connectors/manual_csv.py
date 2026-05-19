"""
The Board Market — Manual CSV Import

Phase 5 fallback for accounts without an API (Fidelity, etc).
Parses Fidelity transaction CSV exports, dedupes against existing transactions.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from profiles.db import db_cursor


# Fidelity's CSV export columns (validate on import; format changes occasionally)
EXPECTED_FIDELITY_COLUMNS = {
    "Run Date", "Action", "Symbol", "Description",
    "Quantity", "Price", "Amount", "Settlement Date",
}


class CSVImportError(Exception):
    """CSV format unexpected or unparseable."""


def parse_fidelity_csv(file_path: str | Path) -> list[dict]:
    """Parse a Fidelity transaction CSV. Validate columns first."""
    file_path = Path(file_path)

    if not file_path.exists():
        raise CSVImportError(f"File not found: {file_path}")

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        # Fidelity sometimes prepends header lines — skip until we find the data header
        sample = f.read(4096)
        f.seek(0)
        if "Run Date" not in sample:
            raise CSVImportError("File doesn't look like a Fidelity transaction export")

        # Skip preamble lines until header row
        lines = []
        capturing = False
        for line in f:
            if "Run Date" in line and "Action" in line:
                capturing = True
            if capturing:
                lines.append(line)

        if not lines:
            raise CSVImportError("Couldn't find data header row")

        reader = csv.DictReader(lines)
        cols = set(reader.fieldnames or [])
        missing = EXPECTED_FIDELITY_COLUMNS - cols
        if missing:
            raise CSVImportError(
                f"Missing expected columns: {missing}. "
                f"Got: {cols}. Fidelity may have changed their export format."
            )

        transactions = []
        for row in reader:
            symbol = (row.get("Symbol") or "").strip().upper()
            if not symbol:
                continue  # skip non-equity rows (dividends, interest, etc)

            try:
                tx = {
                    "run_date": _parse_date(row["Run Date"]),
                    "action": (row.get("Action") or "").strip(),
                    "symbol": symbol,
                    "description": (row.get("Description") or "").strip(),
                    "quantity": _safe_float(row.get("Quantity")),
                    "price": _safe_float(row.get("Price")),
                    "amount": _safe_float(row.get("Amount")),
                    "settlement_date": _parse_date(row.get("Settlement Date")),
                }
                transactions.append(tx)
            except Exception as e:
                # Skip unparseable rows but don't fail the whole import
                print(f"  ⚠️  Skipping row: {e}")

        return transactions


def _parse_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _safe_float(s: Optional[str]) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def import_to_ledger(account_id: int, transactions: list[dict]) -> dict:
    """
    Import parsed transactions to the positions/plays tables.
    Phase 5 implementation: writes only to positions table as point-in-time snapshot.
    """
    # Phase 5: aggregate transactions into current positions
    # Phase 6: also derive matched buy/sell pairs as historical plays

    positions = {}  # ticker -> {qty, cost_basis}

    for tx in transactions:
        sym = tx["symbol"]
        action = tx["action"].upper()
        qty = tx["quantity"] or 0
        amount = abs(tx["amount"] or 0)

        if sym not in positions:
            positions[sym] = {"qty": 0, "cost_basis": 0}

        if "BUY" in action or "BOUGHT" in action:
            positions[sym]["qty"] += qty
            positions[sym]["cost_basis"] += amount
        elif "SELL" in action or "SOLD" in action:
            positions[sym]["qty"] -= qty
            # Don't subtract cost basis on partial sells — needs FIFO/LIFO logic later

    # Write current positions
    inserted = 0
    with db_cursor() as c:
        for sym, p in positions.items():
            if p["qty"] <= 0:
                continue
            avg_cost = p["cost_basis"] / p["qty"] if p["qty"] else 0
            c.execute(
                """
                INSERT INTO positions (account_id, ticker, quantity, avg_cost, as_of)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (account_id, sym, p["qty"], round(avg_cost, 4)),
            )
            inserted += 1

    return {
        "transactions_parsed": len(transactions),
        "positions_inserted": inserted,
        "symbols": list(positions.keys()),
    }

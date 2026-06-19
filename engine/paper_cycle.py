"""One-command daily snapshot + paper reconciliation cycle."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from generate_board import generate  # noqa: E402
from profiles.paper_pilot import get_pilot, reconcile_pilot  # noqa: E402


if __name__ == "__main__":
    board = generate()
    pilot = get_pilot()
    if pilot["status"] != "idle":
        pilot = reconcile_pilot()
        print(
            f"Paper Pilot: ${pilot['equity']:.2f} equity | "
            f"{len(pilot['positions'])} open | {len(pilot['history'])} closed"
        )
    else:
        print(f"Board refreshed for {board['as_of']}; Paper Pilot has not been started")

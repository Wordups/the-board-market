import json
import tempfile
import unittest
from pathlib import Path

from profiles import paper_pilot


class PaperPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_board_path = paper_pilot.BOARD_PATH
        self.original_state_path = paper_pilot.STATE_PATH
        paper_pilot.BOARD_PATH = root / "board_today.json"
        paper_pilot.STATE_PATH = root / "paper_pilot.json"
        self.write_board("2026-01-02", [
            self.setup("AAA", "LOCK", 90, 100),
            self.setup("BBB", "LIVE", 80, 50),
            self.setup("CCC", "LIVE", 75, 25),
            self.setup("DDD", "LIVE", 72, 10),
        ])

    def tearDown(self):
        paper_pilot.BOARD_PATH = self.original_board_path
        paper_pilot.STATE_PATH = self.original_state_path
        self.temp_dir.cleanup()

    @staticmethod
    def setup(ticker, tier, score, price):
        return {
            "ticker": ticker,
            "tier": tier,
            "score": score,
            "price": price,
            "stop": round(price * 0.92, 2),
            "target": round(price * 1.16, 2),
        }

    def write_board(self, as_of, setups):
        paper_pilot.BOARD_PATH.write_text(
            json.dumps({"as_of": as_of, "setups": setups}),
            encoding="utf-8",
        )

    def test_start_enforces_slots_sizing_and_cash_floor(self):
        state = paper_pilot.start_pilot(100)

        self.assertEqual(["AAA", "BBB", "CCC"], [p["ticker"] for p in state["positions"]])
        self.assertEqual([17.0, 8.5, 8.5], [p["cost_basis"] for p in state["positions"]])
        self.assertEqual(66.0, state["cash"])
        self.assertEqual(34.0, state["deployed"])
        self.assertEqual(2.72, state["total_risk"])

    def test_reconcile_closes_target_and_stop_on_new_snapshot(self):
        self.write_board("2026-01-02", [
            self.setup("AAA", "LOCK", 90, 100),
            self.setup("BBB", "LIVE", 80, 50),
            self.setup("CCC", "LIVE", 75, 25),
        ])
        paper_pilot.start_pilot(100)
        self.write_board("2026-01-03", [
            self.setup("AAA", "LOCK", 90, 116),
            self.setup("BBB", "LIVE", 80, 45),
            self.setup("CCC", "LIVE", 75, 25),
        ])

        state = paper_pilot.reconcile_pilot()

        self.assertEqual(["CCC"], [p["ticker"] for p in state["positions"]])
        self.assertEqual({"TARGET", "STOP_CLOSE"}, {t["exit_reason"] for t in state["history"]})
        self.assertAlmostEqual(101.87, state["equity"], places=2)


if __name__ == "__main__":
    unittest.main()

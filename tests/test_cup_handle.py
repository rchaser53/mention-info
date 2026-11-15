import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from mention_info.cup_handle import Bar, Stock, detect_cup_and_handle, load_state, run_once, save_state


def sample_bars(right_index=72, count=80):
    bars = [Bar(i * 7 * 86400, 77, 80, 75, 78, 1000) for i in range(count)]
    # Prior rise from 70 to the left rim at 100.
    bars[10] = Bar(bars[10].timestamp, 75, 82, 70, 80, 1000)
    bars[40] = Bar(bars[40].timestamp, 95, 100, 94, 98, 1000)
    bars[39] = Bar(bars[39].timestamp, 90, 95, 88, 94, 1000)
    bars[41] = Bar(bars[41].timestamp, 92, 96, 90, 94, 1000)
    # Rounded cup bottom, with several weeks within 5% of the trough.
    for i, low in zip(range(53, 59), (82, 78, 76, 75, 76, 78)):
        bars[i] = Bar(bars[i].timestamp, low + 2, low + 5, low, low + 3, 1000)
    # Right rim and a recent shallow handle.
    bars[right_index] = Bar(bars[right_index].timestamp, 98, 102, 96, 100, 1000)
    if right_index + 1 < count:
        bars[right_index + 1] = Bar(bars[right_index + 1].timestamp, 97, 98, 95, 96, 1000)
    if right_index + 2 < count:
        bars[right_index + 2] = Bar(bars[right_index + 2].timestamp, 96, 97, 93, 95, 1000)
    if right_index + 3 < count:
        bars[right_index + 3] = Bar(bars[right_index + 3].timestamp, 96, 98, 94, 97, 1000)
    if right_index + 4 < count:
        bars[right_index + 4] = Bar(bars[right_index + 4].timestamp, 97, 98.5, 96, 98, 1000)
    for i in range(right_index + 5, count):
        bars[i] = Bar(bars[i].timestamp, 98, 99, 97, 99, 1000)
    return bars


class CupHandleTests(unittest.TestCase):
    def test_detects_recent_cup_and_handle(self):
        result = detect_cup_and_handle(sample_bars())
        self.assertIsNotNone(result)
        self.assertEqual(result["left_rim"]["price"], 100)
        self.assertEqual(result["right_rim"]["price"], 102)
        self.assertAlmostEqual(result["depth_pct"], 25.0)
        self.assertLessEqual(result["handle_pullback_pct"], 15)

    def test_ignores_old_handle(self):
        bars = sample_bars(right_index=68)
        for index in range(71, len(bars)):
            bars[index] = Bar(bars[index].timestamp, 80, 82, 79, 81, 1000)
        result = detect_cup_and_handle(bars)
        self.assertIsNone(result)

    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"schema_version": 1, "next_index": 100, "notified_candidates": []}
            save_state(state, path)
            self.assertEqual(load_state(path), state)

    def test_run_processes_at_most_100_and_advances_cursor(self):
        stocks = [Stock(f"{1000 + i}", f"Company {i}", "プライム（内国株式）") for i in range(101)]
        bars = sample_bars()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch("mention_info.cup_handle.load_jpx_stocks", return_value=(stocks, "20261031")), patch("mention_info.cup_handle.fetch_weekly_bars", return_value=bars):
                result = run_once(state_path=path, notify=False)
            self.assertEqual(result["processed"], 100)
            self.assertEqual(result["next_index"], 100)
            self.assertEqual(result["next_code"], "1100")

    def test_failed_ticker_keeps_state_at_batch_start(self):
        stocks = [Stock(f"{1000 + i}", f"Company {i}", "プライム（内国株式）") for i in range(101)]
        bars = sample_bars()
        calls = 0

        def fetch(stock, **kwargs):
            nonlocal calls
            calls += 1
            if stock.code == "1003":
                raise RuntimeError("temporary fetch error")
            return bars

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with patch("mention_info.cup_handle.load_jpx_stocks", return_value=(stocks, "20261031")), patch("mention_info.cup_handle.fetch_weekly_bars", side_effect=fetch):
                result = run_once(state_path=path, notify=False)
            self.assertIn("1003", result["failures"])
            self.assertFalse(result["state_advanced"])
            self.assertFalse(path.exists())

    def test_missing_state_starts_at_first_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            state = load_state(Path(directory) / "missing.json")
            self.assertEqual(state["next_index"], 0)
            self.assertEqual(state["notified_candidates"], [])


if __name__ == "__main__":
    unittest.main()

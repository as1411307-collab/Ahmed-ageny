from __future__ import annotations

import unittest

from persistence import normalize_metrics_window


class ObservabilityTests(unittest.TestCase):
    def test_default_metrics_window_is_one_day(self) -> None:
        self.assertEqual(normalize_metrics_window(None), 24)
        self.assertEqual(normalize_metrics_window("24"), 24)

    def test_metrics_window_has_a_bounded_range(self) -> None:
        self.assertEqual(normalize_metrics_window(1), 1)
        self.assertEqual(normalize_metrics_window(720), 720)
        with self.assertRaises(ValueError):
            normalize_metrics_window(0)
        with self.assertRaises(ValueError):
            normalize_metrics_window(721)
        with self.assertRaises(ValueError):
            normalize_metrics_window("not-a-number")


if __name__ == "__main__":
    unittest.main()
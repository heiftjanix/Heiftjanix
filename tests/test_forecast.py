import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from forecast import forecast_month_end


class TestForecast(unittest.TestCase):
    def test_on_track_is_green(self):
        # Halber Monat, halbes Ziel bereits erreicht, Baseline == Lauf-Rate.
        r = forecast_month_end(mtd=50000, bd_elapsed=11, bd_total=22,
                               baseline_daily=50000 / 11, target=100000)
        self.assertAlmostEqual(r.forecast, 100000, delta=1)
        self.assertEqual(r.status, "green")
        self.assertAlmostEqual(r.gap, 0, delta=1)

    def test_behind_target_is_red(self):
        r = forecast_month_end(mtd=10000, bd_elapsed=11, bd_total=22,
                               baseline_daily=10000 / 11, target=100000)
        self.assertLess(r.forecast, 85000)
        self.assertEqual(r.status, "red")
        self.assertGreater(r.gap, 0)

    def test_early_month_leans_on_baseline(self):
        # Tag 1: eine große Rechnung soll die Prognose NICHT explodieren lassen.
        r = forecast_month_end(mtd=20000, bd_elapsed=1, bd_total=20,
                               baseline_daily=4000, target=100000, K=5)
        self.assertAlmostEqual(r.weight, 0.2, places=4)
        # runrate=20000, baseline=4000 -> blended = .2*20000 + .8*4000 = 7200
        self.assertAlmostEqual(r.blended_daily, 7200, delta=1)
        self.assertLess(r.forecast, 20000 + 20000 * 19)  # deutlich gedämpft

    def test_zero_elapsed_uses_baseline(self):
        r = forecast_month_end(mtd=0, bd_elapsed=0, bd_total=20,
                               baseline_daily=5000, target=100000)
        self.assertEqual(r.weight, 0.0)
        self.assertAlmostEqual(r.forecast, 100000, delta=1)

    def test_required_daily_never_negative(self):
        r = forecast_month_end(mtd=150000, bd_elapsed=10, bd_total=20,
                               baseline_daily=15000, target=100000)
        self.assertEqual(r.required_daily, 0.0)
        self.assertLess(r.gap, 0)  # Ziel übertroffen

    def test_band_ordering(self):
        r = forecast_month_end(mtd=30000, bd_elapsed=6, bd_total=22,
                               baseline_daily=5000, target=100000)
        self.assertLessEqual(r.forecast_low, r.forecast)
        self.assertLessEqual(r.forecast, r.forecast_high)
        self.assertGreaterEqual(r.forecast_low, r.mtd)


if __name__ == "__main__":
    unittest.main()

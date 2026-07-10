import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcb_board import calendar_utils as cal


class TestEaster(unittest.TestCase):
    def test_known_easter_sundays(self):
        self.assertEqual(cal.easter_sunday(2024), date(2024, 3, 31))
        self.assertEqual(cal.easter_sunday(2025), date(2025, 4, 20))
        self.assertEqual(cal.easter_sunday(2026), date(2026, 4, 5))


class TestHolidays(unittest.TestCase):
    def test_bavaria_specific_days(self):
        h = cal.german_holidays(2026, "BY")
        self.assertIn(date(2026, 1, 6), h)
        self.assertIn(date(2026, 11, 1), h)
        self.assertIn(date(2026, 12, 25), h)

    def test_national_not_regional(self):
        h = cal.german_holidays(2026, "XX")
        self.assertNotIn(date(2026, 1, 6), h)
        self.assertIn(date(2026, 10, 3), h)


class TestBusinessDays(unittest.TestCase):
    def test_add_business_days_skips_weekend(self):
        self.assertEqual(cal.add_business_days(date(2026, 7, 3), 1), date(2026, 7, 6))

    def test_elapsed_le_total(self):
        elapsed = cal.business_days_elapsed(date(2026, 7, 15))
        total = cal.business_days_in_month(2026, 7)
        self.assertLessEqual(elapsed, total)
        self.assertGreater(elapsed, 0)

    def test_january_excludes_holidays(self):
        total = cal.business_days_in_month(2026, 1, "BY")
        self.assertEqual(total, 20)


if __name__ == "__main__":
    unittest.main()

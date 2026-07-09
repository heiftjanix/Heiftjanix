import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import calendar_utils as cal


class TestEaster(unittest.TestCase):
    def test_known_easter_sundays(self):
        self.assertEqual(cal.easter_sunday(2024), date(2024, 3, 31))
        self.assertEqual(cal.easter_sunday(2025), date(2025, 4, 20))
        self.assertEqual(cal.easter_sunday(2026), date(2026, 4, 5))


class TestHolidays(unittest.TestCase):
    def test_bavaria_specific_days(self):
        h = cal.german_holidays(2026, "BY")
        self.assertIn(date(2026, 1, 6), h)    # Heilige Drei Könige
        self.assertIn(date(2026, 11, 1), h)   # Allerheiligen
        self.assertIn(date(2026, 12, 25), h)  # 1. Weihnachtstag

    def test_national_not_regional(self):
        h = cal.german_holidays(2026, "XX")
        self.assertNotIn(date(2026, 1, 6), h)
        self.assertIn(date(2026, 10, 3), h)   # Tag der Deutschen Einheit


class TestBusinessDays(unittest.TestCase):
    def test_add_business_days_skips_weekend(self):
        # Fr 2026-07-03 + 1 Werktag -> Mo 2026-07-06
        self.assertEqual(cal.add_business_days(date(2026, 7, 3), 1), date(2026, 7, 6))

    def test_add_business_days_within_week(self):
        # Mi 2026-07-01 + 2 Werktage -> Fr 2026-07-03
        self.assertEqual(cal.add_business_days(date(2026, 7, 1), 2), date(2026, 7, 3))

    def test_elapsed_le_total(self):
        elapsed = cal.business_days_elapsed(date(2026, 7, 15))
        total = cal.business_days_in_month(2026, 7)
        self.assertLessEqual(elapsed, total)
        self.assertGreater(elapsed, 0)

    def test_january_excludes_holidays(self):
        # Jan 2026: Neujahr (1.) und Hl. Drei Könige (6.) sind Werktage-Feiertage.
        total = cal.business_days_in_month(2026, 1, "BY")
        self.assertEqual(total, 20)


if __name__ == "__main__":
    unittest.main()

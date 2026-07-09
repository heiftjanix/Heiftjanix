import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import revenue_aggregate as ra
from lib import io_utils as io

CONFIG = io.load_config()


class TestRevenueAggregate(unittest.TestCase):
    def _data(self):
        return {
            "as_of": "2026-07-15",
            "invoices": [
                {"name": "RE-1", "base_net_total": 12000, "posting_date": "2026-07-02"},
                {"name": "RE-2", "base_net_total": 8000, "posting_date": "2026-07-10"},
                # Vormonat -> zählt zur Baseline, nicht zu MTD
                {"name": "RE-0", "base_net_total": 90000, "posting_date": "2026-06-15"},
            ],
            "to_bill_delivery_notes": [
                {"name": "LS-A", "customer_name": "Kunde A", "base_net_total": 5000,
                 "per_billed": 0, "posting_date": "2026-07-11", "tracking_number": "1Z1",
                 "arrival_status": "delivered", "delivered_date": "2026-07-13",
                 "arrival_method": "ups"},
                {"name": "LS-B", "customer_name": "Kunde B", "base_net_total": 2000,
                 "per_billed": 0, "posting_date": "2026-07-14", "tracking_number": "1Z2",
                 "arrival_status": "in_transit", "arrival_method": "ups"},
                {"name": "LS-OLD", "customer_name": "Kunde C", "base_net_total": 1000,
                 "per_billed": 0, "posting_date": "2025-05-01", "tracking_number": None,
                 "arrival_status": "unknown", "arrival_method": "none"},
            ],
            "open_sales_orders": [{"name": "AB-1", "net_open": 25000}],
        }

    def test_mtd_excludes_other_months(self):
        m = ra.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        self.assertAlmostEqual(m["forecast"]["mtd"], 20000, delta=0.01)

    def test_billing_split(self):
        m = ra.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        b = m["billing"]
        self.assertEqual(b["ready_count"], 1)
        self.assertEqual(b["ready"][0]["name"], "LS-A")
        self.assertEqual(len(b["in_transit"]), 1)
        self.assertEqual(len(b["stale"]), 1)   # LS-OLD aus 2025
        self.assertEqual(b["stale"][0]["name"], "LS-OLD")

    def test_pipeline_sums(self):
        m = ra.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        self.assertAlmostEqual(m["pipeline"]["ready_net"], 5000, delta=0.01)
        self.assertAlmostEqual(m["pipeline"]["in_transit_net"], 2000, delta=0.01)
        self.assertAlmostEqual(m["pipeline"]["open_so_net"], 25000, delta=0.01)

    def test_per_billed_reduces_open_net(self):
        data = self._data()
        data["to_bill_delivery_notes"][0]["per_billed"] = 40  # 60% offen
        m = ra.build_metrics(data, CONFIG, date(2026, 7, 15))
        self.assertAlmostEqual(m["pipeline"]["ready_net"], 3000, delta=0.01)

    def test_mail_summary_empty(self):
        m = ra.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        self.assertEqual(m["mail"]["total"], 0)
        self.assertEqual(m["mail"]["items"], [])

    def test_mail_summary_counts_and_sort(self):
        data = self._data()
        data["mail"] = {"window_hours": 24, "items": [
            {"mailbox": "a@x.de", "category": "info", "priority": "normal", "subject": "Newsletter"},
            {"mailbox": "a@x.de", "category": "relevant", "priority": "normal", "subject": "Frage"},
            {"mailbox": "a@x.de", "category": "relevant", "priority": "high", "subject": "Dringend"},
        ]}
        m = ra.build_metrics(data, CONFIG, date(2026, 7, 15))
        mail = m["mail"]
        self.assertEqual((mail["total"], mail["relevant"], mail["info"], mail["high_priority"]),
                         (3, 2, 1, 1))
        # relevant zuerst, dringend ganz oben
        self.assertEqual(mail["items"][0]["subject"], "Dringend")
        self.assertEqual(mail["items"][-1]["category"], "info")
        self.assertEqual(len(mail["mailboxes"]), 1)


if __name__ == "__main__":
    unittest.main()

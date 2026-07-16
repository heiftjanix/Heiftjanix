import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcb_board import metrics as m

CONFIG = {
    "company": "Musterfirma GmbH",
    "currency": "EUR",
    "revenue_target": 100000,
    "forecast": {"baseline_months": 3, "confidence_days_K": 5,
                 "uncertainty_pct": 0.15, "amber_threshold": 0.85},
    "holidays": {"region": "BY", "extra": []},
    "billing": {"ups_transit_days": 2, "stale_delivery_note_days": 60},
}


class TestForecastMonthEnd(unittest.TestCase):
    def test_on_track_is_green(self):
        r = m.forecast_month_end(mtd=50000, bd_elapsed=11, bd_total=22,
                                  baseline_daily=50000 / 11, target=100000)
        self.assertAlmostEqual(r.forecast, 100000, delta=1)
        self.assertEqual(r.status, "green")

    def test_early_month_leans_on_baseline(self):
        r = m.forecast_month_end(mtd=20000, bd_elapsed=1, bd_total=20,
                                  baseline_daily=4000, target=100000, K=5)
        self.assertAlmostEqual(r.weight, 0.2, places=4)
        self.assertAlmostEqual(r.blended_daily, 7200, delta=1)

    def test_required_daily_never_negative(self):
        r = m.forecast_month_end(mtd=150000, bd_elapsed=10, bd_total=20,
                                  baseline_daily=15000, target=100000)
        self.assertEqual(r.required_daily, 0.0)


class TestBuildMetrics(unittest.TestCase):
    def _data(self):
        return {
            "as_of": "2026-07-15",
            "invoices": [
                {"name": "RE-1", "base_net_total": 12000, "posting_date": "2026-07-02"},
                {"name": "RE-2", "base_net_total": 8000, "posting_date": "2026-07-10"},
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
            "purchase_receipts": [
                {"name": "PR-1", "base_net_total": 3000, "posting_date": "2026-07-05"},
                {"name": "PR-2", "base_net_total": 1500, "posting_date": "2026-07-12"},
                {"name": "PR-0", "base_net_total": 9000, "posting_date": "2026-06-20"},
            ],
            "invoice_items": [
                {"item_code": "PCB-A", "item_name": "Platine A", "base_net_amount": 5000},
                {"item_code": "PCB-B", "item_name": "Platine B", "base_net_amount": 3000},
                {"item_code": "PCB-A", "item_name": "Platine A", "base_net_amount": 2000},
                {"item_code": "PCB-C", "item_name": "Platine C", "base_net_amount": 500},
                {"item_code": "PCB-D", "item_name": "Platine D", "base_net_amount": 400},
                {"item_code": "PCB-E", "item_name": "Platine E", "base_net_amount": 300},
                {"item_code": "PCB-F", "item_name": "Platine F", "base_net_amount": 100},
            ],
        }

    def test_top_products_aggregates_and_limits_to_five(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        top = metrics["top_products"]
        self.assertEqual(len(top), 5)
        self.assertEqual(top[0]["item_code"], "PCB-A")
        self.assertAlmostEqual(top[0]["net_total"], 7000, delta=0.01)
        self.assertEqual(top[1]["item_code"], "PCB-B")
        self.assertEqual([p["item_code"] for p in top], ["PCB-A", "PCB-B", "PCB-C", "PCB-D", "PCB-E"])

    def test_mtd_excludes_other_months(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        self.assertAlmostEqual(metrics["forecast"]["mtd"], 20000, delta=0.01)

    def test_billing_split(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        b = metrics["billing"]
        self.assertEqual(b["ready_count"], 1)
        self.assertEqual(b["ready"][0]["name"], "LS-A")
        self.assertEqual(len(b["in_transit"]), 1)
        self.assertEqual(len(b["stale"]), 1)

    def test_pipeline_sums(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        self.assertAlmostEqual(metrics["pipeline"]["ready_net"], 5000, delta=0.01)
        self.assertAlmostEqual(metrics["pipeline"]["in_transit_net"], 2000, delta=0.01)
        self.assertAlmostEqual(metrics["pipeline"]["open_so_net"], 25000, delta=0.01)

    def test_costs_mtd_plus_fixed_items(self):
        config = dict(CONFIG, personnel_costs_monthly=6000, rent_monthly=1200)
        metrics = m.build_metrics(self._data(), config, date(2026, 7, 15))
        costs = metrics["costs"]
        self.assertAlmostEqual(costs["goods_receipts"], 4500, delta=0.01)
        self.assertAlmostEqual(costs["personnel_costs"], 6000, delta=0.01)
        self.assertAlmostEqual(costs["rent"], 1200, delta=0.01)
        self.assertAlmostEqual(costs["total"], 11700, delta=0.01)

    def test_costs_default_to_zero_without_settings(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        costs = metrics["costs"]
        self.assertAlmostEqual(costs["personnel_costs"], 0, delta=0.01)
        self.assertAlmostEqual(costs["rent"], 0, delta=0.01)
        self.assertAlmostEqual(costs["total"], 4500, delta=0.01)

    def test_todo_orders_split_overdue_and_this_week(self):
        # 2026-07-15 ist ein Mittwoch — Woche = Mo 13.07. bis So 19.07.
        data = self._data()
        data["open_sales_orders"] = [
            {"name": "AB-ALT", "customer_name": "Kunde Alt", "delivery_date": "2026-07-01", "net_open": 500},
            {"name": "AB-HEUTE", "customer_name": "Kunde Heute", "delivery_date": "2026-07-15", "net_open": 300},
            {"name": "AB-FR", "customer_name": "Kunde Freitag", "delivery_date": "2026-07-17", "net_open": 200},
            {"name": "AB-NAECHSTE", "customer_name": "Kunde Später", "delivery_date": "2026-07-25", "net_open": 900},
            {"name": "AB-OHNE", "customer_name": "Ohne Termin", "delivery_date": None, "net_open": 100},
            {"name": "AB-LEER", "customer_name": "Voll berechnet", "delivery_date": "2026-07-01", "net_open": 0},
        ]
        todo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["todo"]
        self.assertEqual([o["name"] for o in todo["overdue"]], ["AB-ALT", "AB-HEUTE"])
        self.assertEqual([o["name"] for o in todo["due_this_week"]], ["AB-FR"])
        self.assertEqual(todo["overdue"][0]["days_overdue"], 14)
        self.assertEqual(todo["overdue"][1]["days_overdue"], 0)
        self.assertAlmostEqual(todo["overdue_net"], 800, delta=0.01)
        self.assertAlmostEqual(todo["due_this_week_net"], 200, delta=0.01)

    def test_top_purchases_aggregates_and_limits(self):
        data = self._data()
        data["purchase_receipt_items"] = [
            {"item_code": "BT-A", "item_name": "Bauteil A", "base_net_amount": 900},
            {"item_code": "BT-B", "item_name": "Bauteil B", "base_net_amount": 2000},
            {"item_code": "BT-A", "item_name": "Bauteil A", "base_net_amount": 600},
            {"item_code": "BT-C", "item_name": "Bauteil C", "base_net_amount": 400},
            {"item_code": "BT-D", "item_name": "Bauteil D", "base_net_amount": 300},
            {"item_code": "BT-E", "item_name": "Bauteil E", "base_net_amount": 200},
            {"item_code": "BT-F", "item_name": "Bauteil F", "base_net_amount": 100},
        ]
        top = m.build_metrics(data, CONFIG, date(2026, 7, 15))["top_purchases"]
        self.assertEqual(len(top), 5)
        self.assertEqual(top[0]["item_code"], "BT-B")
        self.assertEqual(top[1]["item_code"], "BT-A")
        self.assertAlmostEqual(top[1]["net_total"], 1500, delta=0.01)
        self.assertEqual([p["item_code"] for p in top], ["BT-B", "BT-A", "BT-C", "BT-D", "BT-E"])

    def test_profit_history_year_months_and_carry_forward(self):
        config = dict(CONFIG, personnel_costs_monthly=6000, rent_monthly=1200)
        ph = m.build_metrics(self._data(), config, date(2026, 7, 15))["profit_history"]
        self.assertEqual(len(ph["months"]), 7)
        self.assertEqual(ph["months"][0]["month"], "2026-01")
        # Jan–Mai: keine Umsätze/Wareneingänge in den Fixtures -> je -7200 (Fixkosten)
        self.assertAlmostEqual(ph["months"][0]["profit"], -7200, delta=0.01)
        # Juni: 90000 Umsatz - 9000 Wareneingang - 7200 fix = 73800
        self.assertAlmostEqual(ph["months"][5]["profit"], 73800, delta=0.01)
        # Juli (läuft): 20000 - 4500 - 7200 = 8300
        jul = ph["months"][6]
        self.assertTrue(jul["is_current"])
        self.assertAlmostEqual(jul["profit"], 8300, delta=0.01)
        # Vortrag = abgeschlossene Monate: 5*(-7200) + 73800 = 37800
        self.assertAlmostEqual(ph["carry_forward"], 37800, delta=0.01)
        self.assertAlmostEqual(ph["ytd_profit"], 46100, delta=0.01)

    def test_mail_summary_counts_and_sort(self):
        data = self._data()
        data["mail"] = {"window_hours": 24, "items": [
            {"mailbox": "a@x.de", "category": "info", "priority": "normal", "subject": "Newsletter"},
            {"mailbox": "a@x.de", "category": "relevant", "priority": "normal", "subject": "Frage"},
            {"mailbox": "a@x.de", "category": "relevant", "priority": "high", "subject": "Dringend"},
        ]}
        metrics = m.build_metrics(data, CONFIG, date(2026, 7, 15))
        mail = metrics["mail"]
        self.assertEqual((mail["total"], mail["relevant"], mail["info"], mail["high_priority"]),
                         (3, 2, 1, 1))
        self.assertEqual(mail["items"][0]["subject"], "Dringend")


if __name__ == "__main__":
    unittest.main()

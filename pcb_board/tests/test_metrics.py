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

    def test_profit_history_cumulative_since_prev_year(self):
        config = dict(CONFIG, personnel_costs_monthly=6000, rent_monthly=1200)
        ph = m.build_metrics(self._data(), config, date(2026, 7, 15))["profit_history"]
        # 12 Monate 2025 + 7 Monate 2026 (Jan–Jul) = 19; kumuliert seit 2025.
        self.assertEqual(len(ph["months"]), 19)
        self.assertEqual(ph["months"][0]["month"], "2025-01")
        self.assertEqual(ph["prev_year"], 2025)
        self.assertEqual(ph["months"][-1]["month"], "2026-07")
        # 2025 komplett leer (keine Fixtures) -> je -7200 Fixkosten, 12 Monate.
        self.assertAlmostEqual(ph["months"][0]["profit"], -7200, delta=0.01)
        # Juni 2026 (Index 12 + 5 = 17): 90000 - 9000 - 7200 = 73800
        jun = ph["months"][17]
        self.assertEqual(jun["month"], "2026-06")
        self.assertAlmostEqual(jun["profit"], 73800, delta=0.01)
        # Juli 2026 (läuft): 20000 - 4500 - 7200 = 8300
        jul = ph["months"][18]
        self.assertTrue(jul["is_current"])
        self.assertAlmostEqual(jul["profit"], 8300, delta=0.01)
        # Vortrag = abgeschlossene Monate LAUFENDES JAHR: 5*(-7200) + 73800 = 37800
        self.assertAlmostEqual(ph["carry_forward"], 37800, delta=0.01)
        # kumuliert bis heute (inkl. Juli): 12*(-7200) + 37800 + 8300 = -40300
        self.assertAlmostEqual(ph["since_prev_total"], -40300, delta=0.01)
        # abgeschlossen (ohne laufenden Juli): -40300 - 8300 = -48600
        self.assertAlmostEqual(ph["since_prev_completed"], -48600, delta=0.01)
        # kumulierte Spalte des letzten Eintrags == since_prev_total
        self.assertAlmostEqual(ph["months"][-1]["cumulative"], -40300, delta=0.01)
        # Trend = letzter abgeschlossener Monat (Juni 2026)
        self.assertEqual(ph["trend_last_month"], "2026-06")
        self.assertAlmostEqual(ph["trend_value"], 73800, delta=0.01)
        # Ranking: Juni 2026 bestes Verhältnis -> Rang 1
        self.assertEqual(jun["rank"], 1)
        self.assertEqual(jul["rank"], 2)

    def test_top_customers_share_of_mtd(self):
        data = self._data()
        data["invoices"] = [
            {"customer_name": "Kunde A", "base_net_total": 6000, "posting_date": "2026-07-02"},
            {"customer_name": "Kunde B", "base_net_total": 3000, "posting_date": "2026-07-10"},
            {"customer_name": "Kunde A", "base_net_total": 1000, "posting_date": "2026-07-12"},
            {"customer_name": "Vormonat", "base_net_total": 99999, "posting_date": "2026-06-15"},
        ]
        top = m.build_metrics(data, CONFIG, date(2026, 7, 15))["top_customers"]
        self.assertEqual(top[0]["customer"], "Kunde A")
        self.assertAlmostEqual(top[0]["net_total"], 7000, delta=0.01)
        self.assertAlmostEqual(top[0]["share_pct"], 0.7, places=4)
        self.assertEqual(top[1]["customer"], "Kunde B")
        self.assertAlmostEqual(top[1]["share_pct"], 0.3, places=4)

    def test_top_suppliers_share_of_month(self):
        data = self._data()
        data["purchase_receipts"] = [
            {"supplier_name": "Lieferant X", "base_net_total": 1500, "posting_date": "2026-07-05"},
            {"supplier_name": "Lieferant Y", "base_net_total": 500, "posting_date": "2026-07-12"},
            {"supplier_name": "Lieferant X", "base_net_total": 500, "posting_date": "2026-07-13"},
            {"supplier_name": "Vormonat", "base_net_total": 7777, "posting_date": "2026-06-20"},
        ]
        top = m.build_metrics(data, CONFIG, date(2026, 7, 15))["top_suppliers"]
        self.assertEqual(top[0]["supplier"], "Lieferant X")
        self.assertAlmostEqual(top[0]["net_total"], 2000, delta=0.01)
        self.assertAlmostEqual(top[0]["share_pct"], 0.8, places=4)
        self.assertEqual(top[1]["supplier"], "Lieferant Y")

    def test_product_margins_ek_bom_fallback_and_empty(self):
        data = self._data()
        data["invoice_items"] = [
            {"item_code": "PCB-A", "item_name": "Platine A", "base_net_amount": 5000, "qty": 100},
            {"item_code": "PCB-A", "item_name": "Platine A", "base_net_amount": 2000, "qty": 40},
            {"item_code": "PCB-B", "item_name": "Platine B", "base_net_amount": 3000, "qty": 10},
            {"item_code": "PCB-C", "item_name": "Platine C", "base_net_amount": 1000, "qty": 5},
        ]
        data["item_purchase_rates"] = [
            {"name": "PCB-A", "item_code": "PCB-A", "last_purchase_rate": 30},
            {"name": "PCB-B", "item_code": "PCB-B", "last_purchase_rate": 0},
            {"name": "PCB-C", "item_code": "PCB-C", "last_purchase_rate": 0},
        ]
        # PCB-B ohne EK, aber mit Stückliste: 200 €/Einheit
        data["item_bom_costs"] = [{"item_code": "PCB-B", "cost_per_unit": 200}]
        margins = m.build_metrics(data, CONFIG, date(2026, 7, 15))["product_margins"]
        a = margins[0]
        self.assertEqual(a["item_code"], "PCB-A")
        self.assertAlmostEqual(a["cost"], 4200, delta=0.01)       # 140 Stk × 30 € EK
        self.assertAlmostEqual(a["margin"], 2800, delta=0.01)     # 7000 − 4200
        self.assertAlmostEqual(a["margin_pct"], 0.4, places=4)
        self.assertEqual(a["cost_source"], "ek")
        b = margins[1]
        self.assertEqual(b["item_code"], "PCB-B")
        self.assertAlmostEqual(b["cost"], 2000, delta=0.01)       # 10 Stk × 200 € Stückliste
        self.assertAlmostEqual(b["margin"], 1000, delta=0.01)
        self.assertEqual(b["cost_source"], "bom")
        c = margins[2]
        self.assertEqual(c["item_code"], "PCB-C")
        self.assertIsNone(c["cost"])
        self.assertIsNone(c["margin"])
        self.assertIsNone(c["cost_source"])

    def test_prev_year_month_total_same_day_ytd_and_full_year(self):
        data = self._data()
        data["prev_year_invoices"] = [
            {"base_net_total": 9000, "posting_date": "2025-02-10"},
            {"base_net_total": 4000, "posting_date": "2025-07-03"},
            {"base_net_total": 2000, "posting_date": "2025-07-15"},
            {"base_net_total": 5000, "posting_date": "2025-07-28"},
            {"base_net_total": 30000, "posting_date": "2025-11-20"},
        ]
        # Wareneingänge 2025 für den Vorjahres-Gewinn (Fixtures enthalten nur 2026er)
        data["purchase_receipts"] = list(data["purchase_receipts"]) + [
            {"name": "PR-PY", "base_net_total": 8000, "posting_date": "2025-05-10"},
        ]
        config = dict(CONFIG, personnel_costs_monthly=1000, rent_monthly=500)
        py = m.build_metrics(data, config, date(2026, 7, 15))["prev_year"]
        self.assertEqual((py["year"], py["month"]), (2025, 7))
        self.assertAlmostEqual(py["total"], 11000, delta=0.01)          # nur Juli 2025
        self.assertAlmostEqual(py["mtd_same_day"], 6000, delta=0.01)    # Juli bis 15.
        self.assertAlmostEqual(py["ytd_through_month_end"], 20000, delta=0.01)  # bis Ende Juli
        # bis zum selben Tag (15.): Feb 9000 + Juli≤15. 6000 = 15000
        self.assertAlmostEqual(py["ytd_same_day"], 15000, delta=0.01)
        self.assertAlmostEqual(py["full_year_total"], 50000, delta=0.01)        # inkl. November
        # G/V 2025 = 50000 − 8000 Wareneingänge − 12 × 1500 fix = 24000
        self.assertAlmostEqual(py["full_year_profit"], 24000, delta=0.01)

    def test_recent_receipts_sorted_with_positions(self):
        data = self._data()
        data["receipt_positions"] = {"PR-2": 3, "PR-1": 1}
        rr = m.build_metrics(data, CONFIG, date(2026, 7, 15))["recent_receipts"]
        self.assertEqual([r["name"] for r in rr], ["PR-2", "PR-1", "PR-0"])
        self.assertEqual(rr[0]["positions"], 3)
        self.assertAlmostEqual(rr[0]["net_total"], 1500, delta=0.01)
        self.assertIsNone(rr[2]["positions"])   # keine Angabe -> None

    def test_billing_throughput_open_age(self):
        tp = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))["billing"]["throughput"]
        # offene Lieferscheine: LS-A (4 T.), LS-B (1 T.), LS-OLD (440 T.)
        self.assertEqual(tp["open_count"], 3)
        self.assertAlmostEqual(tp["avg_open_age_days"], (1 + 4 + 440) / 3, delta=0.05)
        self.assertAlmostEqual(tp["median_open_age_days"], 4, delta=0.01)
        self.assertEqual(tp["max_open_age_days"], 440)

    def test_todo_avg_overdue_days(self):
        data = self._data()
        data["open_sales_orders"] = [
            {"name": "AB-A", "delivery_date": "2026-07-05", "net_open": 500},   # 10 T. überfällig
            {"name": "AB-B", "delivery_date": "2026-07-13", "net_open": 300},   # 2 T. überfällig
        ]
        todo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["todo"]
        self.assertAlmostEqual(todo["avg_overdue_days"], 6.0, delta=0.01)

    def test_ytd_revenue_sums_current_year_only(self):
        metrics = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))
        # Fixtures: 12000 + 8000 (Juli) + 90000 (Juni) — alles 2026
        self.assertAlmostEqual(metrics["ytd_revenue"], 110000, delta=0.01)

    def _purchasing_data(self):
        """Lieferzeit-Historie: LF-A liefert in 5/7/9 Tagen (Median 7), LF-B in 30.
        Bei BE-ALT zwei Wareneingänge — nur der erste zählt."""
        data = self._data()
        data["po_receipt_pairs"] = [
            {"purchase_order": "BE-H1", "supplier": "LF-A", "order_date": "2026-05-01",
             "receipt_date": "2026-05-06"},                                  # 5 T.
            {"purchase_order": "BE-H2", "supplier": "LF-A", "order_date": "2026-05-10",
             "receipt_date": "2026-05-17"},                                  # 7 T.
            {"purchase_order": "BE-H3", "supplier": "LF-A", "order_date": "2026-06-01",
             "receipt_date": "2026-06-10"},                                  # 9 T.
            {"purchase_order": "BE-ALT", "supplier": "LF-A", "order_date": "2026-04-01",
             "receipt_date": "2026-04-08"},                                  # erster WE: 7 T.
            {"purchase_order": "BE-ALT", "supplier": "LF-A", "order_date": "2026-04-01",
             "receipt_date": "2026-06-30"},                                  # Teillieferung -> ignoriert
            {"purchase_order": "BE-H4", "supplier": "LF-B", "order_date": "2026-05-01",
             "receipt_date": "2026-05-31"},                                  # 30 T.
        ]
        data["open_purchase_orders"] = [
            # LF-A, Median 7 T. -> erwartet 2026-07-10 -> 5 Tage überfällig
            {"name": "BE-SPAET", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive and Bill", "transaction_date": "2026-07-03",
             "base_net_total": 4000, "net_open": 4000, "per_received": 0, "positions": 2,
             "items": [{"item_name": "Platine A", "open_qty": 10},
                       {"item_name": "Widerstand", "open_qty": 500}]},
            # LF-A, bestellt 2026-07-08 -> erwartet 2026-07-15 = heute
            {"name": "BE-HEUTE", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-08",
             "base_net_total": 900, "net_open": 900, "per_received": 0, "positions": 1,
             "items": [{"item_name": "Stecker", "open_qty": 20}]},
            # LF-B, Median 30 T. -> erwartet 2026-08-09 -> künftig
            {"name": "BE-KUENFTIG", "supplier": "LF-B", "supplier_name": "Lieferant B",
             "status": "To Receive", "transaction_date": "2026-07-10",
             "base_net_total": 2000, "net_open": 2000, "per_received": 0, "positions": 1,
             "items": [{"item_name": "Gehäuse", "open_qty": 5}]},
            # unbekannter Lieferant -> Median über alle (7 T.) -> 2026-07-08, überfällig
            {"name": "BE-NEULF", "supplier": "LF-NEU", "supplier_name": "Lieferant Neu",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "base_net_total": 500, "net_open": 500, "per_received": 0, "positions": 1,
             "items": []},
            # pausiert -> sichtbar, aber nicht anmahnen
            {"name": "BE-HOLD", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "On Hold", "transaction_date": "2026-06-01",
             "base_net_total": 700, "net_open": 700, "per_received": 0, "positions": 1,
             "items": []},
        ]
        return data

    def test_supplier_lead_times_median_per_supplier(self):
        lt = m.supplier_lead_times(self._purchasing_data())
        self.assertEqual(lt["per_supplier"]["LF-A"]["median_days"], 7.0)
        self.assertEqual(lt["per_supplier"]["LF-A"]["samples"], 4)   # BE-ALT nur einmal
        self.assertEqual(lt["per_supplier"]["LF-B"]["median_days"], 30.0)
        self.assertEqual(lt["samples"], 5)
        self.assertEqual(lt["overall_median_days"], 7.0)

    def test_supplier_lead_times_ignores_receipt_before_order(self):
        data = self._data()
        data["po_receipt_pairs"] = [
            {"purchase_order": "BE-X", "supplier": "LF-A", "order_date": "2026-06-10",
             "receipt_date": "2026-06-01"},
            {"purchase_order": "BE-Y", "supplier": "LF-A", "order_date": None,
             "receipt_date": "2026-06-05"},
        ]
        lt = m.supplier_lead_times(data)
        self.assertEqual(lt["samples"], 0)
        self.assertIsNone(lt["overall_median_days"])

    def test_purchase_orders_expected_date_and_follow_up(self):
        p = m.build_metrics(self._purchasing_data(), CONFIG, date(2026, 7, 15))["purchasing"]
        by_name = {r["name"]: r for r in p["open"]}
        self.assertEqual(by_name["BE-SPAET"]["expected_date"], "2026-07-10")
        self.assertEqual(by_name["BE-SPAET"]["days_late"], 5)
        self.assertEqual(by_name["BE-SPAET"]["expected_source"], "supplier")
        self.assertEqual(by_name["BE-HEUTE"]["expected_date"], "2026-07-15")
        self.assertEqual(by_name["BE-HEUTE"]["days_until"], 0)
        self.assertEqual(by_name["BE-KUENFTIG"]["expected_date"], "2026-08-09")
        self.assertEqual(by_name["BE-KUENFTIG"]["days_until"], 25)
        # unbekannter Lieferant fällt auf den Gesamt-Median zurück
        self.assertEqual(by_name["BE-NEULF"]["expected_source"], "overall")
        self.assertEqual(by_name["BE-NEULF"]["expected_date"], "2026-07-08")
        # nachzuhaken: nur überfällige, „On Hold" nicht — längste Verspätung zuerst
        self.assertEqual([r["name"] for r in p["follow_up"]], ["BE-NEULF", "BE-SPAET"])
        self.assertAlmostEqual(p["follow_up_net"], 4500, delta=0.01)
        self.assertEqual(p["open_count"], 5)
        self.assertAlmostEqual(p["open_net"], 8100, delta=0.01)
        # nach erwartetem Termin sortiert (BE-HOLD: 01.06. + 7 T. = frühester Termin)
        self.assertEqual([r["name"] for r in p["open"]],
                         ["BE-HOLD", "BE-NEULF", "BE-SPAET", "BE-HEUTE", "BE-KUENFTIG"])
        self.assertTrue(by_name["BE-HOLD"]["on_hold"])
        self.assertGreater(by_name["BE-HOLD"]["days_late"], 0)   # überfällig, aber kein Nachhaken

    def test_purchase_orders_expected_today_tile(self):
        et = m.build_metrics(self._purchasing_data(), CONFIG,
                             date(2026, 7, 15))["purchasing"]["expected_today"]
        self.assertEqual((et["orders"], et["positions"]), (1, 1))
        self.assertAlmostEqual(et["net"], 900, delta=0.01)
        self.assertEqual([i["item_name"] for i in et["items"]], ["Stecker"])
        self.assertEqual(et["items"][0]["purchase_order"], "BE-HEUTE")

    def test_purchase_orders_without_history_use_schedule_date(self):
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = [
            {"name": "BE-1", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": "2026-07-12", "net_open": 100, "positions": 1, "items": []},
            {"name": "BE-2", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": None, "net_open": 100, "positions": 1, "items": []},
        ]
        p = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]
        by_name = {r["name"]: r for r in p["open"]}
        self.assertEqual(by_name["BE-1"]["expected_source"], "schedule")
        self.assertEqual(by_name["BE-1"]["days_late"], 3)
        self.assertEqual([r["name"] for r in p["follow_up"]], ["BE-1"])
        # ohne jeden Termin: nichts erwartet, nichts anzumahnen
        self.assertIsNone(by_name["BE-2"]["expected_date"])
        self.assertEqual(by_name["BE-2"]["days_late"], 0)
        self.assertIsNone(by_name["BE-2"]["expected_source"])

    def test_purchasing_empty_without_purchase_data(self):
        p = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))["purchasing"]
        self.assertEqual((p["open_count"], p["follow_up_count"]), (0, 0))
        self.assertEqual(p["expected_today"]["positions"], 0)
        self.assertIsNone(p["lead_times"]["overall_median_days"])

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

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
             "items": [{"item_code": "PL-A", "item_name": "Platine A", "open_qty": 10},
                       {"item_code": "R-500", "item_name": "Widerstand", "open_qty": 500}]},
            # LF-A, bestellt 2026-07-08 -> erwartet 2026-07-15 = heute
            {"name": "BE-HEUTE", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-08",
             "base_net_total": 900, "net_open": 900, "per_received": 0, "positions": 1,
             "items": [{"item_code": "ST-20", "item_name": "Stecker", "open_qty": 20}]},
            # LF-B, Median 30 T. -> erwartet 2026-08-09 -> künftig
            {"name": "BE-KUENFTIG", "supplier": "LF-B", "supplier_name": "Lieferant B",
             "status": "To Receive", "transaction_date": "2026-07-10",
             "base_net_total": 2000, "net_open": 2000, "per_received": 0, "positions": 1,
             "items": [{"item_code": "GH-5", "item_name": "Gehäuse", "open_qty": 5}]},
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
        self.assertEqual([i["item_code"] for i in et["items"]], ["ST-20"])
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

    def _crm_data(self):
        """Angebote in allen Zuständen, plus Kundenhistorie über zwei Jahre."""
        data = self._data()
        data["crm"] = {
            "quotations": [
                # offen, Frist schon vorbei -> nachfassen, rot
                {"name": "AN-1", "customer": "Kunde A", "status": "Open", "is_draft": False,
                 "date": "2026-06-01", "valid_till": "2026-07-01", "net_total": 5000},
                # offen, läuft in 3 Tagen ab -> nachfassen
                {"name": "AN-2", "customer": "Kunde B", "status": "Replied", "is_draft": False,
                 "date": "2026-06-20", "valid_till": "2026-07-18", "net_total": 2000},
                # offen, noch lange gültig
                {"name": "AN-3", "customer": "Kunde A", "status": "Open", "is_draft": False,
                 "date": "2026-07-10", "valid_till": "2026-09-30", "net_total": 8000},
                # Entwurf: noch nicht beim Kunden
                {"name": "AN-4", "customer": "Kunde C", "status": "Draft", "is_draft": True,
                 "date": "2026-07-14", "valid_till": "2026-08-14", "net_total": 1000},
                # entschieden 2026
                {"name": "AN-5", "customer": "Kunde A", "status": "Ordered", "is_draft": False,
                 "date": "2026-03-01", "valid_till": "2026-04-01", "net_total": 10000},
                {"name": "AN-6", "customer": "Kunde B", "status": "Partially Ordered",
                 "is_draft": False, "date": "2026-03-05", "valid_till": "2026-04-05",
                 "net_total": 4000},
                {"name": "AN-7", "customer": "Kunde D", "status": "Lost", "is_draft": False,
                 "date": "2026-02-01", "valid_till": "2026-03-01", "net_total": 6000},
                {"name": "AN-8", "customer": "Kunde D", "status": "Expired", "is_draft": False,
                 "date": "2026-01-15", "valid_till": "2026-02-15", "net_total": 2000},
                # Vorjahr: 1 gewonnen, 3 verloren -> Quote 25 %
                {"name": "AN-V1", "customer": "Kunde A", "status": "Ordered", "is_draft": False,
                 "date": "2025-05-01", "valid_till": "2025-06-01", "net_total": 3000},
                {"name": "AN-V2", "customer": "Kunde A", "status": "Lost", "is_draft": False,
                 "date": "2025-05-02", "valid_till": "2025-06-02", "net_total": 1000},
                {"name": "AN-V3", "customer": "Kunde B", "status": "Lost", "is_draft": False,
                 "date": "2025-05-03", "valid_till": "2025-06-03", "net_total": 1000},
                {"name": "AN-V4", "customer": "Kunde B", "status": "Lost", "is_draft": False,
                 "date": "2025-05-04", "valid_till": "2025-06-04", "net_total": 1000},
            ],
            "leads": [
                {"name": "L-1", "lead_name": "Interessent 1", "status": "Lead", "created": "2026-07-01"},
                {"name": "L-2", "lead_name": "Interessent 2", "status": "Converted", "created": "2026-06-01"},
                {"name": "L-3", "lead_name": "Interessent 3", "status": "Lead", "created": "2026-05-01"},
            ],
            "opportunities": [
                {"name": "OPP-1", "customer": "Kunde E", "status": "Open", "stage": "Prospecting",
                 "date": "2026-06-24", "amount": 2000},
                {"name": "OPP-2", "customer": "Kunde F", "status": "Converted",
                 "stage": "Prospecting", "date": "2026-06-24", "amount": 500},
            ],
        }
        # Kundenhistorie: Neu (nur 2026), schlafend (nur 2025), laufend (beide Jahre)
        data["invoices"] = [
            {"name": "RE-N", "customer_name": "Kunde Neu", "base_net_total": 4000,
             "posting_date": "2026-05-10"},
            {"name": "RE-L", "customer_name": "Kunde Laufend", "base_net_total": 9000,
             "posting_date": "2026-07-01"},
        ]
        data["prev_year_invoices"] = [
            {"name": "RE-S", "customer_name": "Kunde Schlaeft", "base_net_total": 20000,
             "posting_date": "2025-06-01"},
            {"name": "RE-L0", "customer_name": "Kunde Laufend", "base_net_total": 5000,
             "posting_date": "2025-11-01"},
        ]
        return data

    def test_crm_quotation_follow_up_and_open(self):
        crm = m.build_metrics(self._crm_data(), CONFIG, date(2026, 7, 15))["crm"]
        q = crm["quotations"]
        # offen = eingereichte Angebote im Status Open/Replied, nach Frist sortiert
        self.assertEqual([r["name"] for r in q["open"]], ["AN-1", "AN-2", "AN-3"])
        self.assertAlmostEqual(q["open_net"], 15000, delta=0.01)
        # Entwuerfe zaehlen separat, nicht als "beim Kunden"
        self.assertEqual(q["draft_count"], 1)
        self.assertAlmostEqual(q["draft_net"], 1000, delta=0.01)
        # nachfassen: abgelaufen + laeuft in <= 14 Tagen ab
        self.assertEqual([r["name"] for r in q["expiring"]], ["AN-1", "AN-2"])
        self.assertEqual(q["overdue_count"], 1)
        self.assertEqual(q["open"][0]["days_left"], -14)      # AN-1: 14 Tage drueber
        self.assertTrue(q["open"][0]["overdue"])
        self.assertEqual(q["open"][1]["days_left"], 3)        # AN-2
        self.assertFalse(q["open"][2]["expiring"])            # AN-3 noch lange gueltig
        self.assertEqual(q["open"][0]["age_days"], 44)

    def test_crm_conversion_rate_only_counts_decided(self):
        crm = m.build_metrics(self._crm_data(), CONFIG, date(2026, 7, 15))["crm"]
        cur = crm["quotations"]["conversion"]
        # 2026 entschieden: AN-5 + AN-6 gewonnen, AN-7 verloren, AN-8 abgelaufen
        self.assertEqual((cur["won"], cur["lost"], cur["expired"], cur["decided"]), (2, 1, 1, 4))
        self.assertAlmostEqual(cur["rate"], 0.5, delta=0.0001)
        # Wertquote: 14000 von 22000
        self.assertAlmostEqual(cur["rate_net"], 14000 / 22000, delta=0.0001)
        # offene Angebote gehen NICHT in die Quote ein
        self.assertEqual(cur["open"], 3)
        prev = crm["quotations"]["conversion_prev"]
        self.assertEqual((prev["year"], prev["won"], prev["lost"]), (2025, 1, 3))
        self.assertAlmostEqual(prev["rate"], 0.25, delta=0.0001)

    def test_crm_quotations_by_customer_share(self):
        q = m.build_metrics(self._crm_data(), CONFIG, date(2026, 7, 15))["crm"]["quotations"]
        top = q["by_customer"]
        self.assertEqual(top[0]["customer"], "Kunde A")
        self.assertAlmostEqual(top[0]["net"], 13000, delta=0.01)   # AN-1 + AN-3
        self.assertEqual(top[0]["count"], 2)

    def test_crm_customer_development(self):
        c = m.build_metrics(self._crm_data(), CONFIG, date(2026, 7, 15))["crm"]["customers"]
        self.assertEqual([r["customer"] for r in c["new"]], ["Kunde Neu"])
        self.assertAlmostEqual(c["new"][0]["revenue_year"], 4000, delta=0.01)
        # schlafend: Vorjahresumsatz, letzte Rechnung > 180 Tage her
        self.assertEqual([r["customer"] for r in c["dormant"]], ["Kunde Schlaeft"])
        self.assertAlmostEqual(c["dormant"][0]["revenue_prev_year"], 20000, delta=0.01)
        self.assertEqual(c["dormant"][0]["days_since"], 409)
        # laufender Kunde ist weder neu noch schlafend
        self.assertEqual(c["active_count"], 2)

    def test_crm_leads_and_opportunities(self):
        crm = m.build_metrics(self._crm_data(), CONFIG, date(2026, 7, 15))["crm"]
        self.assertEqual((crm["leads"]["total"], crm["leads"]["open_count"]), (3, 2))
        self.assertEqual(dict(crm["leads"]["by_status"]), {"Lead": 2, "Converted": 1})
        self.assertEqual(crm["opportunities"]["open_count"], 1)
        self.assertAlmostEqual(crm["opportunities"]["open_amount"], 2000, delta=0.01)
        self.assertEqual(crm["opportunities"]["rows"][0]["name"], "OPP-1")

    def test_crm_empty_without_crm_data(self):
        crm = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))["crm"]
        self.assertEqual(crm["quotations"]["open_count"], 0)
        self.assertIsNone(crm["quotations"]["conversion"]["rate"])
        self.assertEqual(crm["leads"]["total"], 0)
        self.assertEqual(crm["customers"]["dormant"], [])

    def _margin_data(self):
        """Vier Artikel mit EK: A gut, B knapp, C Verlust, D grosser Verlust.
        E ohne EK/Stückliste — nicht bewertbar."""
        data = self._data()
        data["invoice_items"] = [
            {"item_code": "A", "item_name": "Artikel A", "base_net_amount": 1000, "qty": 10},
            {"item_code": "B", "item_name": "Artikel B", "base_net_amount": 500, "qty": 10},
            {"item_code": "C", "item_name": "Artikel C", "base_net_amount": 100, "qty": 10},
            {"item_code": "D", "item_name": "Artikel D", "base_net_amount": 900, "qty": 100},
            {"item_code": "E", "item_name": "Artikel E", "base_net_amount": 700, "qty": 5},
        ]
        data["item_purchase_rates"] = [
            {"item_code": "A", "last_purchase_rate": 40},    # DB +600
            {"item_code": "B", "last_purchase_rate": 48},    # DB  +20
            {"item_code": "C", "last_purchase_rate": 15},    # DB -50
            {"item_code": "D", "last_purchase_rate": 12},    # DB -300
        ]
        return data

    def test_product_flops_worst_absolute_margin_first(self):
        flops = m.build_metrics(self._margin_data(), CONFIG, date(2026, 7, 15))["product_flops"]
        self.assertEqual([p["item_code"] for p in flops], ["D", "C", "B", "A"])
        self.assertAlmostEqual(flops[0]["margin"], -300, delta=0.01)
        self.assertAlmostEqual(flops[1]["margin"], -50, delta=0.01)
        # nicht bewertbare Artikel (kein EK, keine Stückliste) bleiben aussen vor
        self.assertNotIn("E", [p["item_code"] for p in flops])

    def test_product_flops_limited_to_five(self):
        data = self._margin_data()
        data["invoice_items"] = [
            {"item_code": "I%d" % i, "item_name": "Artikel %d" % i,
             "base_net_amount": 100, "qty": 10} for i in range(8)
        ]
        data["item_purchase_rates"] = [
            {"item_code": "I%d" % i, "last_purchase_rate": 20 + i} for i in range(8)
        ]
        flops = m.build_metrics(data, CONFIG, date(2026, 7, 15))["product_flops"]
        self.assertEqual(len(flops), 5)
        # groesster Verlust zuerst: hoechster EK = I7
        self.assertEqual(flops[0]["item_code"], "I7")

    def test_product_margins_year_compares_with_prev_year(self):
        data = self._margin_data()
        # vorsummierte Zeilen, wie refresh.py sie liefert (net_total statt base_net_amount)
        data["invoice_items_year"] = [
            {"item_code": "A", "item_name": "Artikel A", "net_total": 2000, "qty": 20},
            {"item_code": "B", "item_name": "Artikel B", "net_total": 1000, "qty": 20},
            {"item_code": "C", "item_name": "Artikel C", "net_total": 300, "qty": 30},
        ]
        data["invoice_items_prev_year"] = [
            {"item_code": "A", "item_name": "Artikel A", "net_total": 1500, "qty": 15},
            {"item_code": "C", "item_name": "Artikel C", "net_total": 400, "qty": 40},
        ]
        d = m.build_metrics(data, CONFIG, date(2026, 7, 15))["product_margins_year"]
        self.assertEqual((d["year"], d["prev_year"]), (2026, 2025))
        # DB 2026: A 2000-800=1200, B 1000-960=40, C 300-450=-150 -> nach DB sortiert
        self.assertEqual([r["item_code"] for r in d["rows"]], ["A", "B", "C"])
        a = d["rows"][0]
        self.assertAlmostEqual(a["margin"], 1200, delta=0.01)
        self.assertAlmostEqual(a["prev_margin"], 900, delta=0.01)   # 1500-600
        self.assertAlmostEqual(a["delta_margin"], 300, delta=0.01)
        self.assertAlmostEqual(a["prev_revenue"], 1500, delta=0.01)
        # B gab es im Vorjahr nicht -> kein Vorjahreswert, keine Veraenderung
        b = d["rows"][1]
        self.assertIsNone(b["prev_margin"])
        self.assertIsNone(b["delta_margin"])

    def test_product_margins_year_empty_without_year_items(self):
        d = m.build_metrics(self._data(), CONFIG, date(2026, 7, 15))["product_margins_year"]
        self.assertEqual(d["rows"], [])
        self.assertEqual(d["prev_year"], 2025)

    def test_mail_dedupe_shared_mailbox_across_users(self):
        # Dasselbe geteilte Postfach wird von zwei verbundenen Nutzern gelesen —
        # die Mail darf nur einmal erscheinen.
        items = [
            {"mailbox": "bestellung@x.de", "mailbox_email": "bestellung@x.de",
             "internet_message_id": "<a@x>", "subject": "Bestellung"},
            {"mailbox": "bestellung@x.de", "mailbox_email": "Bestellung@X.de",
             "internet_message_id": "<a@x>", "subject": "Bestellung"},
            # gleiche Mail in einem ANDEREN Postfach: bleibt (liegt dort auch)
            {"mailbox": "anfrage@x.de", "mailbox_email": "anfrage@x.de",
             "internet_message_id": "<a@x>", "subject": "Bestellung"},
            # eigenes Postfach zweier Nutzer, gleiche ID -> zwei echte Vorgänge
            {"mailbox": "anna@x.de", "internet_message_id": "<b@x>", "subject": "CC"},
            {"mailbox": "ben@x.de", "internet_message_id": "<b@x>", "subject": "CC"},
            # ohne ID nicht anfassen
            {"mailbox": "bestellung@x.de", "subject": "ohne ID"},
            {"mailbox": "bestellung@x.de", "subject": "ohne ID"},
        ]
        out = m.dedupe_mail_items(items)
        self.assertEqual(len(out), 6)
        boxes = [(i.get("mailbox"), i.get("internet_message_id")) for i in out]
        self.assertEqual(boxes.count(("bestellung@x.de", "<a@x>")), 1)
        self.assertEqual(boxes.count(("anfrage@x.de", "<a@x>")), 1)
        self.assertEqual(boxes.count(("bestellung@x.de", None)), 2)

    def test_mail_summary_counts_deduped(self):
        data = self._data()
        dup = {"mailbox": "bestellung@x.de", "mailbox_email": "bestellung@x.de",
               "internet_message_id": "<a@x>", "category": "relevant", "priority": "high",
               "subject": "Doppelt"}
        data["mail"] = {"window_hours": 24, "items": [dict(dup), dict(dup), dict(dup)]}
        mail = m.build_metrics(data, CONFIG, date(2026, 7, 15))["mail"]
        self.assertEqual((mail["total"], mail["relevant"], mail["high_priority"]), (1, 1, 1))
        self.assertEqual(mail["mailboxes"][0]["total"], 1)

    def _wo_data(self):
        """Zwei Bestellungen, zwei Fertigungsaufträge.
        FA-1 (Start 20.07.) fehlen A (2 Stk, kein Bestand) und B (1 Stk, kein Bestand):
        A kommt mit BE-1 (erwartet 10.07.), B mit BE-2 (erwartet 22.07.) -> BE-2 ist
        die letzte fehlende Lieferung. FA-2 (Start 25.07.) braucht C, das nirgends
        bestellt ist -> bleibt blockiert."""
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = [
            {"name": "BE-1", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": "2026-07-10", "net_open": 1000, "positions": 1,
             "items": [{"item_code": "A", "item_name": "Artikel A", "open_qty": 2}]},
            {"name": "BE-2", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-02",
             "schedule_date": "2026-07-22", "net_open": 500, "positions": 1,
             "items": [{"item_code": "B", "item_name": "Artikel B", "open_qty": 1}]},
        ]
        data["work_orders"] = [
            {"name": "FA-1", "item_name": "Baugruppe 1", "qty": 1, "status": "Not Started",
             "sales_order": "AB-1", "planned_start_date": "2026-07-20",
             "expected_delivery_date": "2026-07-30",
             "required_items": [
                 {"item_code": "A", "item_name": "Artikel A", "required_qty": 2,
                  "transferred_qty": 0, "available_qty": 0},
                 {"item_code": "B", "item_name": "Artikel B", "required_qty": 1,
                  "transferred_qty": 0, "available_qty": 0},
             ]},
            {"name": "FA-2", "item_name": "Baugruppe 2", "qty": 1, "status": "Not Started",
             "sales_order": "AB-2", "planned_start_date": "2026-07-25",
             "expected_delivery_date": "2026-08-05",
             "required_items": [
                 {"item_code": "C", "item_name": "Artikel C", "required_qty": 5,
                  "transferred_qty": 0, "available_qty": 1},
             ]},
        ]
        return data

    def test_work_orders_last_delivery_unblocks(self):
        p = m.build_metrics(self._wo_data(), CONFIG, date(2026, 7, 15))["purchasing"]
        by_name = {r["name"]: r for r in p["open"]}
        # beide Bestellungen liefern für FA-1, aber nur die SPÄTERE macht ihn komplett
        self.assertEqual(by_name["BE-1"]["unblocks"], [])
        self.assertEqual(by_name["BE-2"]["unblocks"], ["FA-1"])
        self.assertEqual(by_name["BE-1"]["work_orders_count"], 1)
        wos_be1 = by_name["BE-1"]["items"][0]["work_orders"]
        self.assertEqual([w["name"] for w in wos_be1], ["FA-1"])
        self.assertFalse(wos_be1[0]["is_last"])
        self.assertTrue(by_name["BE-2"]["items"][0]["work_orders"][0]["is_last"])

        wo = {w["name"]: w for w in p["work_orders"]}
        self.assertEqual(wo["FA-1"]["complete_on"], "2026-07-22")
        self.assertEqual(wo["FA-1"]["complete_po"], "BE-2")
        self.assertEqual(wo["FA-1"]["missing_items"], [])
        # FA-2: 5 gebraucht, 1 am Lager, nichts bestellt -> 4 fehlen, kein Termin
        self.assertIsNone(wo["FA-2"]["complete_on"])
        self.assertEqual(wo["FA-2"]["missing_items"][0]["short_qty"], 4)
        self.assertEqual((p["wo_waiting_count"], p["wo_unblockable_count"],
                          p["wo_need_order_count"]), (2, 1, 1))

    def test_work_orders_scarce_stock_allocated_once(self):
        """Zwei Aufträge brauchen denselben Artikel, geliefert wird nur für einen:
        der früher startende Auftrag bekommt die Menge, der zweite bleibt blockiert."""
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = [
            {"name": "BE-1", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": "2026-07-20", "net_open": 100, "positions": 1,
             "items": [{"item_code": "A", "item_name": "Artikel A", "open_qty": 10}]},
        ]
        common = {"item_name": "Baugruppe", "qty": 1, "status": "Not Started",
                  "required_items": [{"item_code": "A", "item_name": "Artikel A",
                                      "required_qty": 10, "transferred_qty": 0,
                                      "available_qty": 0}]}
        data["work_orders"] = [
            dict(common, name="FA-FRUEH", planned_start_date="2026-07-21"),
            dict(common, name="FA-SPAET", planned_start_date="2026-07-28"),
        ]
        p = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]
        wo = {w["name"]: w for w in p["work_orders"]}
        self.assertEqual(wo["FA-FRUEH"]["complete_po"], "BE-1")
        self.assertIsNone(wo["FA-SPAET"]["complete_po"])
        self.assertEqual(wo["FA-SPAET"]["missing_items"][0]["short_qty"], 10)
        # die Bestellung macht nur den früheren Auftrag komplett
        self.assertEqual(p["open"][0]["unblocks"], ["FA-FRUEH"])

    def test_work_orders_partially_covered_is_not_marked_as_last(self):
        """Die Bestellung deckt einen Artikel des Auftrags, ein zweiter ist gar nicht
        bestellt: der Auftrag wird dadurch NICHT bearbeitbar — kein 🔓, aber der
        Bezug bleibt sichtbar (⌛ im Board)."""
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = [
            {"name": "BE-1", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": "2026-07-20", "net_open": 100, "positions": 1,
             "items": [{"item_code": "A", "item_name": "Artikel A", "open_qty": 5}]},
        ]
        data["work_orders"] = [
            {"name": "FA-1", "item_name": "Baugruppe", "qty": 1, "status": "Not Started",
             "planned_start_date": "2026-07-25",
             "required_items": [
                 {"item_code": "A", "item_name": "Artikel A", "required_qty": 5,
                  "transferred_qty": 0, "available_qty": 0},
                 {"item_code": "Z", "item_name": "Artikel Z", "required_qty": 2,
                  "transferred_qty": 0, "available_qty": 0},
             ]},
        ]
        p = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]
        row = p["open"][0]
        self.assertEqual(row["unblocks"], [])                      # kein 🔓
        self.assertEqual(row["work_orders_count"], 1)              # Bezug sichtbar
        link = row["items"][0]["work_orders"][0]
        self.assertFalse(link["is_last"])
        self.assertEqual(link["still_missing"], 1)                 # -> ⌛
        self.assertIsNone(p["work_orders"][0]["complete_on"])

    def _bin_data(self, bins, required, wh="Lager - PCB"):
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = []
        data["stock_bins"] = bins
        data["work_orders"] = [{
            "name": "FA-1", "item_name": "Baugruppe", "qty": 1, "status": "Not Started",
            "planned_start_date": "2026-07-20", "required_items": required,
        }]
        return data

    def test_stock_comes_from_bin_not_from_stale_work_order_snapshot(self):
        """Regression: available_qty_at_source_warehouse am Fertigungsauftrag ist nur
        ein Schnappschuss vom letzten Speichern. Ein danach gebuchter Wareneingang
        stand dort nie drin — das Board hielt gelieferte Artikel für fehlend."""
        data = self._bin_data(
            bins=[{"item_code": "R.1215", "warehouse": "Lager - PCB", "actual_qty": 100}],
            required=[{"item_code": "R.1215", "item_name": "Widerstand", "required_qty": 20,
                       "transferred_qty": 0,
                       # veralteter Schnappschuss aus dem Auftrag
                       "available_qty": 0, "source_warehouse": "Lager - PCB"}],
        )
        wo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"][0]
        pos = wo["positions"][0]
        self.assertEqual(pos["state"], "stock")
        self.assertEqual(pos["from_stock"], 20)
        self.assertEqual(pos["short_qty"], 0)
        self.assertTrue(wo["material_ok"])
        self.assertAlmostEqual(wo["ready_pct"], 1.0, delta=0.0001)
        self.assertEqual(wo["missing_items"], [])

    def test_stock_counts_only_the_source_warehouse(self):
        """Bestand in einem anderen Lager deckt die Position nicht."""
        data = self._bin_data(
            bins=[{"item_code": "R.1215", "warehouse": "Anderes Lager", "actual_qty": 100}],
            required=[{"item_code": "R.1215", "item_name": "Widerstand", "required_qty": 20,
                       "transferred_qty": 0, "available_qty": 0,
                       "source_warehouse": "Lager - PCB"}],
        )
        pos = m.build_metrics(data, CONFIG, date(2026, 7, 15))[
            "purchasing"]["work_orders"][0]["positions"][0]
        self.assertEqual(pos["state"], "missing")
        self.assertEqual(pos["short_qty"], 20)

    def test_stock_without_source_warehouse_uses_all_warehouses(self):
        data = self._bin_data(
            bins=[{"item_code": "R.1215", "warehouse": "Lager A", "actual_qty": 8},
                  {"item_code": "R.1215", "warehouse": "Lager B", "actual_qty": 12}],
            required=[{"item_code": "R.1215", "item_name": "Widerstand", "required_qty": 20,
                       "transferred_qty": 0, "available_qty": 0, "source_warehouse": None}],
        )
        pos = m.build_metrics(data, CONFIG, date(2026, 7, 15))[
            "purchasing"]["work_orders"][0]["positions"][0]
        self.assertEqual(pos["state"], "stock")
        self.assertEqual(pos["from_stock"], 20)

    def test_bin_stock_is_shared_between_work_orders(self):
        """Der Live-Bestand darf nicht zweimal verplant werden: der frühere Bedarf
        bekommt ihn, der spätere bleibt offen."""
        data = self._bin_data(
            bins=[{"item_code": "R.1215", "warehouse": "Lager - PCB", "actual_qty": 10}],
            required=[],
        )
        common = {"item_name": "Baugruppe", "qty": 1, "status": "Not Started",
                  "required_items": [{"item_code": "R.1215", "item_name": "Widerstand",
                                      "required_qty": 10, "transferred_qty": 0,
                                      "available_qty": 0,
                                      "source_warehouse": "Lager - PCB"}]}
        data["work_orders"] = [dict(common, name="FA-FRUEH", planned_start_date="2026-07-21"),
                               dict(common, name="FA-SPAET", planned_start_date="2026-07-28")]
        wos = {w["name"]: w for w in
               m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]}
        self.assertEqual(wos["FA-FRUEH"]["positions"][0]["state"], "stock")
        self.assertEqual(wos["FA-SPAET"]["positions"][0]["state"], "missing")

    def test_without_bin_data_snapshot_is_used_as_fallback(self):
        """Fällt die Bin-Abfrage aus, rechnet das Board mit dem Auftragswert weiter,
        statt alles als fehlend zu melden."""
        data = self._bin_data(
            bins=[],
            required=[{"item_code": "R.1215", "item_name": "Widerstand", "required_qty": 20,
                       "transferred_qty": 0, "available_qty": 50,
                       "source_warehouse": "Lager - PCB"}],
        )
        pos = m.build_metrics(data, CONFIG, date(2026, 7, 15))[
            "purchasing"]["work_orders"][0]["positions"][0]
        self.assertEqual(pos["state"], "stock")
        self.assertEqual(pos["from_stock"], 20)

    def test_work_order_positions_states_and_completeness(self):
        """Jede Stücklistenposition bekommt ihren Zustand, daraus die
        Vollständigkeit: 2 von 4 greifbar = 50 %."""
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = [
            {"name": "BE-1", "supplier": "LF-A", "supplier_name": "Lieferant A",
             "status": "To Receive", "transaction_date": "2026-07-01",
             "schedule_date": "2026-07-25", "net_open": 100, "positions": 1,
             "items": [{"item_code": "C", "item_name": "Artikel C", "open_qty": 5}]},
        ]
        data["work_orders"] = [{
            "name": "FA-1", "item_name": "Baugruppe", "production_item": "BG.1",
            "qty": 1, "status": "Not Started", "planned_start_date": "2026-07-20",
            "required_items": [
                # schon vollständig in die Fertigung umgelagert -> vorhanden
                {"item_code": "A", "item_name": "Artikel A", "required_qty": 4,
                 "transferred_qty": 4, "available_qty": 0},
                # liegt am Lager -> vorhanden
                {"item_code": "B", "item_name": "Artikel B", "required_qty": 2,
                 "transferred_qty": 0, "available_qty": 10},
                # kommt mit BE-1 -> im Zulauf
                {"item_code": "C", "item_name": "Artikel C", "required_qty": 5,
                 "transferred_qty": 0, "available_qty": 0},
                # nirgends gedeckt -> fehlt
                {"item_code": "D", "item_name": "Artikel D", "required_qty": 3,
                 "transferred_qty": 1, "available_qty": 0},
            ],
        }]
        wo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"][0]
        states = {p["item_code"]: p["state"] for p in wo["positions"]}
        self.assertEqual(states, {"A": "done", "B": "stock", "C": "incoming", "D": "missing"})
        self.assertEqual((wo["positions_total"], wo["positions_ready"]), (4, 2))
        self.assertEqual((wo["positions_incoming"], wo["positions_missing"]), (1, 1))
        self.assertAlmostEqual(wo["ready_pct"], 0.5, delta=0.0001)
        # mengengewichtet: A 4 + B 2 + D 1 (schon umgelagert) von 4+2+5+3 = 7/14.
        # Teilmengen zählen hier mit — anders als bei der Positionsquote, wo eine
        # angebrochene Position noch keine fertige Position ist.
        self.assertAlmostEqual(wo["qty_ready_pct"], 7 / 14, delta=0.0001)

        by_code = {p["item_code"]: p for p in wo["positions"]}
        self.assertEqual(by_code["B"]["from_stock"], 2)
        self.assertEqual(by_code["C"]["incoming"][0]["po"], "BE-1")
        self.assertEqual(by_code["C"]["incoming"][0]["supplier"], "Lieferant A")
        self.assertEqual(by_code["C"]["incoming"][0]["qty"], 5)
        self.assertEqual(by_code["D"]["short_qty"], 2)      # 3 gebraucht, 1 umgelagert
        self.assertEqual(by_code["A"]["open_qty"], 0)

    def test_work_order_positions_full_when_everything_available(self):
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = []
        data["work_orders"] = [{
            "name": "FA-OK", "item_name": "Baugruppe", "qty": 1, "status": "Not Started",
            "planned_start_date": "2026-07-20",
            "required_items": [
                {"item_code": "A", "item_name": "Artikel A", "required_qty": 2,
                 "transferred_qty": 2, "available_qty": 0},
                {"item_code": "B", "item_name": "Artikel B", "required_qty": 1,
                 "transferred_qty": 0, "available_qty": 5},
            ],
        }]
        wo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"][0]
        self.assertAlmostEqual(wo["ready_pct"], 1.0, delta=0.0001)
        self.assertTrue(wo["material_ok"])
        self.assertEqual(wo["positions_missing"], 0)

    def test_work_order_positions_marks_last_delivery(self):
        """Der 🔓-Hinweis muss auch an der Position hängen, nicht nur am Auftrag."""
        wo = {w["name"]: w for w in m.build_metrics(
            self._wo_data(), CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]}
        pos = {p["item_code"]: p for p in wo["FA-1"]["positions"]}
        # FA-1 wird durch BE-2 (Artikel B, spätester Termin) komplett
        self.assertTrue(pos["B"]["incoming"][0]["is_last"])
        self.assertFalse(pos["A"]["incoming"][0]["is_last"])

    def test_work_orders_awaiting_lists_suppliers(self):
        p = m.build_metrics(self._wo_data(), CONFIG, date(2026, 7, 15))["purchasing"]
        wo = {w["name"]: w for w in p["work_orders"]}
        aw = wo["FA-1"]["awaiting"]
        # zwei Bestellungen, nach erwartetem Termin sortiert, mit Lieferant und Artikel
        self.assertEqual([a["po"] for a in aw], ["BE-1", "BE-2"])
        self.assertEqual([a["supplier"] for a in aw], ["Lieferant A", "Lieferant A"])
        self.assertEqual([i["item_code"] for i in aw[0]["items"]], ["A"])
        self.assertEqual([i["item_name"] for i in aw[0]["items"]], ["Artikel A"])
        self.assertEqual(aw[1]["expected_date"], "2026-07-22")
        self.assertFalse(aw[0]["is_last"])
        self.assertTrue(aw[1]["is_last"])
        self.assertFalse(wo["FA-1"]["material_ok"])
        # FA-2 wartet nicht auf eine Bestellung, ihm fehlt schlicht Material
        self.assertEqual(wo["FA-2"]["awaiting"], [])
        self.assertEqual(len(wo["FA-2"]["missing_items"]), 1)

    def test_todo_orders_attach_work_orders_and_material_flag(self):
        data = self._wo_data()
        data["open_sales_orders"] = [
            {"name": "AB-1", "customer_name": "Kunde 1", "delivery_date": "2026-07-16",
             "net_open": 5000},
            {"name": "AB-2", "customer_name": "Kunde 2", "delivery_date": "2026-07-17",
             "net_open": 3000},
            {"name": "AB-OHNE", "customer_name": "Handelsware", "delivery_date": "2026-07-17",
             "net_open": 100},
        ]
        # FA-2 (blockiert) auf einen anderen Kundenauftrag umhängen, damit AB-2 hier
        # den reinen ✅-Fall zeigt; der gemischte Fall steckt im nächsten Test.
        data["work_orders"][1]["sales_order"] = "AB-9"
        # FA-3 zu AB-2 ergänzen: Material vollständig aus dem Bestand
        data["work_orders"].append({
            "name": "FA-3", "item_name": "Baugruppe 3", "qty": 1, "status": "Not Started",
            "sales_order": "AB-2", "planned_start_date": "2026-07-18",
            "required_items": [{"item_code": "D", "item_name": "Artikel D",
                                "required_qty": 2, "transferred_qty": 0, "available_qty": 9}],
        })
        todo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["todo"]
        by_name = {r["name"]: r for r in todo["due_this_week"]}
        self.assertEqual([w["name"] for w in by_name["AB-1"]["work_orders"]], ["FA-1"])
        self.assertFalse(by_name["AB-1"]["material_ok"])          # wartet auf BE-1/BE-2
        self.assertEqual(by_name["AB-1"]["work_orders"][0]["missing_count"], 0)
        self.assertEqual([a["supplier"] for a in by_name["AB-1"]["work_orders"][0]["awaiting"]],
                         ["Lieferant A", "Lieferant A"])
        self.assertEqual([w["name"] for w in by_name["AB-2"]["work_orders"]], ["FA-3"])
        self.assertTrue(by_name["AB-2"]["material_ok"])            # ✅ aus Bestand gedeckt
        # ohne verknüpften Produktionsauftrag (Handelsware): kein Häkchen
        self.assertEqual(by_name["AB-OHNE"]["work_orders"], [])
        self.assertFalse(by_name["AB-OHNE"]["material_ok"])

    def test_todo_orders_material_ok_needs_all_work_orders_complete(self):
        data = self._wo_data()
        data["open_sales_orders"] = [
            {"name": "AB-1", "customer_name": "Kunde 1", "delivery_date": "2026-07-16",
             "net_open": 5000},
        ]
        # zweiter Auftrag zum selben Kundenauftrag, vollständig — einer wartet noch,
        # also darf der Kundenauftrag KEIN Häkchen bekommen.
        data["work_orders"].append({
            "name": "FA-1B", "item_name": "Baugruppe 1b", "qty": 1, "status": "Not Started",
            "sales_order": "AB-1", "planned_start_date": "2026-07-19",
            "required_items": [{"item_code": "D", "item_name": "Artikel D",
                                "required_qty": 1, "transferred_qty": 0, "available_qty": 4}],
        })
        todo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["todo"]
        row = todo["due_this_week"][0]
        self.assertEqual(sorted(w["name"] for w in row["work_orders"]), ["FA-1", "FA-1B"])
        self.assertFalse(row["material_ok"])
        self.assertEqual([w["material_ok"] for w in row["work_orders"]
                          if w["name"] == "FA-1B"], [True])

    def test_work_orders_customer_due_date_and_beistellung_passthrough(self):
        data = self._wo_data()
        # refresh.py filtert Beistellungen aus required_items heraus und zählt sie
        # nur — hier ist der Auftrag deshalb material-komplett, obwohl eine
        # Beistellung offen ist.
        data["work_orders"] = [{
            "name": "FA-B", "item_name": "Baugruppe B", "production_item": "BG.0001",
            "qty": 3, "status": "Not Started", "sales_order": "AB-7",
            "planned_start_date": "2026-07-20", "customer_due_date": "2026-08-14",
            "beistellung_count": 2,
            "required_items": [{"item_code": "A", "item_name": "Artikel A",
                                "required_qty": 1, "transferred_qty": 0, "available_qty": 5}],
        }]
        wo = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"][0]
        self.assertEqual(wo["customer_due_date"], "2026-08-14")
        self.assertEqual(wo["beistellung_count"], 2)
        self.assertTrue(wo["material_ok"])
        self.assertEqual(wo["missing_items"], [])

    def test_work_orders_customer_due_date_missing_stays_none(self):
        data = self._wo_data()
        for wo in data["work_orders"]:
            wo.pop("customer_due_date", None)
        wos = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]
        self.assertTrue(all(w["customer_due_date"] is None for w in wos))
        self.assertTrue(all(w["beistellung_count"] == 0 for w in wos))

    def test_missing_items_carry_ekt_number(self):
        """Fehlender Artikel ohne Bestellung: die EKT-Nummer der passenden
        Einkaufstool-Anfrage kommt mit. Bevorzugt wird die Anfrage, in der der
        Fertigungsauftrag ausdrücklich steht — sonst die neueste."""
        data = self._wo_data()
        data["ekt_components"] = [
            {"ekt": "EKT-0100", "item_code": "C", "work_orders_text": "P-99999 (X)",
             "required_quantity": 10, "created": "2026-07-01"},
            {"ekt": "EKT-0169", "item_code": "C", "work_orders_text": "FA-2 (BG.1), P-50256 (BG.2)",
             "required_quantity": 4, "created": "2026-06-01"},
            {"ekt": "EKT-0170", "item_code": "C", "work_orders_text": "",
             "required_quantity": 4, "created": "2026-08-01"},
        ]
        wo = {w["name"]: w for w in
              m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]}
        miss = wo["FA-2"]["missing_items"][0]
        # FA-2 steht in EKT-0169 -> gewinnt trotz aelterem Datum
        self.assertEqual(miss["ekt"], "EKT-0169")
        self.assertEqual(miss["ekt_match"], "work_order")
        self.assertEqual(miss["ekt_created"], "2026-06-01")

    def test_missing_items_ekt_falls_back_to_newest(self):
        data = self._wo_data()
        data["ekt_components"] = [
            {"ekt": "EKT-0100", "item_code": "C", "work_orders_text": "P-1 (X)",
             "required_quantity": 10, "created": "2026-07-01"},
            {"ekt": "EKT-0170", "item_code": "C", "work_orders_text": "P-2 (Y)",
             "required_quantity": 4, "created": "2026-08-01"},
        ]
        wo = {w["name"]: w for w in
              m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]}
        miss = wo["FA-2"]["missing_items"][0]
        self.assertEqual(miss["ekt"], "EKT-0170")
        self.assertEqual(miss["ekt_match"], "item")

    def test_missing_items_without_ekt_stay_none(self):
        wo = {w["name"]: w for w in
              m.build_metrics(self._wo_data(), CONFIG, date(2026, 7, 15))["purchasing"]["work_orders"]}
        miss = wo["FA-2"]["missing_items"][0]
        self.assertIsNone(miss["ekt"])
        self.assertIsNone(miss["ekt_match"])

    def test_work_orders_covered_from_stock_needs_no_delivery(self):
        data = self._data()
        data["po_receipt_pairs"] = []
        data["open_purchase_orders"] = []
        data["work_orders"] = [
            {"name": "FA-OK", "item_name": "Baugruppe", "qty": 1, "status": "Not Started",
             "planned_start_date": "2026-07-20",
             "required_items": [{"item_code": "A", "item_name": "Artikel A",
                                 "required_qty": 3, "transferred_qty": 1,
                                 "available_qty": 5}]},
        ]
        p = m.build_metrics(data, CONFIG, date(2026, 7, 15))["purchasing"]
        wo = p["work_orders"][0]
        self.assertTrue(wo["from_stock_only"])
        self.assertFalse(wo["waiting"])
        self.assertEqual(p["wo_waiting_count"], 0)

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

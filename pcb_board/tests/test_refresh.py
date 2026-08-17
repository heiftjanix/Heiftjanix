"""Tests für den ERPNext-Datenabruf — ohne laufendes Bench.

Anlass: eine Abfrage mit "sum(x) as y" im fields-Parameter hat den kompletten
Refresh abgebrochen (diese Frappe-Version verbietet SQL-Funktionen als
Zeichenkette im SELECT). Das ist erst auf der Instanz aufgefallen. Diese Tests
stubben frappe und prüfen deshalb (a) dass keine Abfrage unerlaubte
Feldausdrücke verwendet und (b) dass ein fehlschlagender Zusatzblock nur seinen
eigenen Abschnitt kostet statt das ganze Board.
"""
import sys
import types
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _install_frappe_stub(get_all, exists=lambda *a, **k: True):
    """Minimaler frappe-Ersatz; refresh.py importiert ihn auf Modulebene."""
    frappe = types.ModuleType("frappe")
    frappe.get_all = get_all
    frappe.db = types.SimpleNamespace(exists=exists)
    frappe.logged = []
    frappe.log_error = lambda title=None, message=None: frappe.logged.append(title)
    frappe.get_traceback = lambda: "traceback"
    frappe.conf = {}
    frappe.session = types.SimpleNamespace(user="test@example.com")
    frappe.utils = types.SimpleNamespace(now=lambda: "2026-08-12 00:00:00",
                                         get_fullname=lambda u: u)
    frappe.cache = lambda: types.SimpleNamespace(get_value=lambda k: None,
                                                 set_value=lambda k, v: None)
    frappe.defaults = types.SimpleNamespace(get_global_default=lambda k: "Musterfirma")
    frappe.enqueue = lambda *a, **k: None
    frappe.get_single = lambda dt: None
    frappe.get_doc = lambda *a, **k: None
    frappe.new_doc = lambda dt: None
    frappe.delete_doc = lambda *a, **k: None
    sys.modules["frappe"] = frappe
    # msal/pydantic hängen an auth.py bzw. triage.py und werden hier nicht gebraucht.
    for name, attrs in (("msal", {"ConfidentialClientApplication": object}),
                        ("pydantic", {"BaseModel": object, "Field": lambda *a, **k: None})):
        if name not in sys.modules:
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[name] = mod
    return frappe


class TestFetchErpnext(unittest.TestCase):
    CONFIG = {"forecast": {"baseline_months": 3}}

    def _run(self, failing_doctypes=()):
        """Ruft _fetch_erpnext mit protokollierendem get_all auf."""
        calls = []

        def get_all(doctype, **kwargs):
            calls.append({"doctype": doctype, **kwargs})
            if doctype in failing_doctypes:
                raise ValueError("Abfrage fehlgeschlagen: %s" % doctype)
            if doctype == "Sales Invoice":
                return [{"name": "RE-1", "base_net_total": 100,
                         "posting_date": date.today().replace(month=1, day=5).isoformat()}]
            if doctype == "Sales Invoice Item":
                return [{"item_code": "A", "item_name": "Artikel A",
                         "base_net_amount": 60, "qty": 3},
                        {"item_code": "A", "item_name": "Artikel A",
                         "base_net_amount": 40, "qty": 2}]
            return []

        frappe = _install_frappe_stub(get_all)
        for mod in [m for m in sys.modules if m.startswith("pcb_board")]:
            del sys.modules[mod]
        from pcb_board import refresh
        return refresh._fetch_erpnext(self.CONFIG), calls, frappe

    def test_no_sql_function_in_select_fields(self):
        """Kein fields-Eintrag darf eine SQL-Funktion als Zeichenkette enthalten —
        genau daran ist der Refresh auf der Instanz gescheitert."""
        _, calls, _ = self._run()
        offenders = []
        for call in calls:
            for field in call.get("fields") or []:
                if isinstance(field, str) and "(" in field:
                    offenders.append((call["doctype"], field))
        self.assertEqual(offenders, [], "SQL-Funktionen im fields-Parameter: %r" % offenders)

    def test_year_items_are_summed_per_item(self):
        data, _, _ = self._run()
        year = {r["item_code"]: r for r in data["invoice_items_year"]}
        self.assertEqual(year["A"]["net_total"], 100)     # 60 + 40
        self.assertEqual(year["A"]["qty"], 5)             # 3 + 2
        self.assertEqual(year["A"]["item_name"], "Artikel A")

    def test_core_keys_always_present(self):
        data, _, _ = self._run()
        for key in ("as_of", "invoices", "to_bill_delivery_notes", "open_sales_orders",
                    "purchase_receipts", "work_orders", "ekt_components", "crm", "stock_bins",
                    "invoice_items_year", "invoice_items_prev_year"):
            self.assertIn(key, data)
        for key in ("quotations", "leads", "opportunities"):
            self.assertIn(key, data["crm"])

    def test_failing_production_block_does_not_kill_refresh(self):
        """Fällt die Fertigungsabfrage aus, fehlt nur dieser Abschnitt."""
        data, _, frappe = self._run(failing_doctypes=("Work Order",))
        self.assertEqual(data["work_orders"], [])
        self.assertEqual(data["ekt_components"], [])
        self.assertEqual(data["stock_bins"], [])
        self.assertIn("as_of", data)
        self.assertTrue(any("übersprungen" in t for t in frappe.logged))

    def test_failing_item_rows_do_not_kill_refresh(self):
        """Positionsdaten speisen nur die Produkt-Tabellen — fallen sie aus,
        bleiben Umsatz, Prognose und Kosten trotzdem stehen."""
        data, _, frappe = self._run(failing_doctypes=("Sales Invoice Item",))
        self.assertEqual(data["invoice_items"], [])
        self.assertEqual(data["invoice_items_year"], [])
        self.assertEqual(data["invoice_items_prev_year"], [])
        self.assertEqual(data["invoices"][0]["name"], "RE-1")
        self.assertTrue(any("übersprungen" in t for t in frappe.logged))

    def test_failing_crm_block_does_not_kill_refresh(self):
        """Ohne CRM-Daten bleibt der Reiter leer, das Board laeuft weiter."""
        data, _, frappe = self._run(failing_doctypes=("Quotation",))
        self.assertEqual(data["crm"]["quotations"], [])
        self.assertEqual(data["crm"]["leads"], [])
        self.assertIn("as_of", data)
        self.assertTrue(any("übersprungen" in t for t in frappe.logged))

    def test_failing_unit_costs_do_not_kill_refresh(self):
        data, _, frappe = self._run(failing_doctypes=("Item",))
        self.assertEqual(data["item_purchase_rates"], [])
        self.assertEqual(data["item_bom_costs"], [])
        self.assertIn("as_of", data)
        self.assertTrue(any("übersprungen" in t for t in frappe.logged))


class TestMailSyncStatus(unittest.TestCase):
    """Der Mail-Sync muss den Zeitstempel im Status mitziehen.

    Sonst weichen Status und gecachte Kennzahlen dauerhaft voneinander ab, das
    Board hält seinen Stand für veraltet und lädt sich im Poll-Takt (4 s) endlos
    neu — was im Betrieb den Fokus aus jedem Eingabefeld geworfen hat.
    """

    def test_mail_sync_keeps_status_and_metrics_in_sync(self):
        store = {"pcb_board_status": {"state": "idle", "generated_at": "2026-08-12 09:00:00"},
                 "pcb_board_metrics": {"generated_at": "2026-08-12 09:00:00", "mail": {}}}
        frappe = _install_frappe_stub(lambda *a, **k: [])
        frappe.cache = lambda: types.SimpleNamespace(
            get_value=lambda k: store.get(k),
            set_value=lambda k, v: store.__setitem__(k, v),
        )
        frappe.utils = types.SimpleNamespace(now=lambda: "2026-08-12 09:05:00",
                                             get_fullname=lambda u: u)
        for mod in [m for m in sys.modules if m.startswith("pcb_board")]:
            del sys.modules[mod]
        from pcb_board import refresh

        refresh._settings = lambda: {"mail_lookback_hours": 24, "anthropic_model": "x",
                                     "extra_mailboxes": []}
        refresh._fetch_mail = lambda config, key: []
        refresh.scheduled_mail_sync()

        self.assertEqual(store["pcb_board_metrics"]["generated_at"], "2026-08-12 09:05:00")
        self.assertEqual(store["pcb_board_status"]["generated_at"], "2026-08-12 09:05:00",
                         "Status muss dem neuen Stand folgen, sonst lädt das Board endlos neu")


class TestWorkOrderNotes(unittest.TestCase):
    """Notizen und die Sperre werden beim LESEN angehängt — und müssen in beiden
    Listen ankommen: Produktionsübersicht und den Kopien an den Kundenaufträgen."""

    def _attach(self, view, note_rows):
        def get_all(doctype, **kwargs):
            return note_rows if doctype == "PCB Board Work Order Note" else []

        _install_frappe_stub(get_all)
        for mod in [m for m in sys.modules if m.startswith("pcb_board")]:
            del sys.modules[mod]
        from pcb_board import refresh
        refresh.attach_work_order_notes(view)
        return view

    def test_hold_and_note_reach_both_lists(self):
        view = {
            "purchasing": {"work_orders": [{"name": "FA-1"}, {"name": "FA-2"}]},
            "todo": {
                "overdue": [{"name": "AB-1", "work_orders": [{"name": "FA-1"}]}],
                "due_this_week": [{"name": "AB-2", "work_orders": [{"name": "FA-2"}]}],
            },
        }
        self._attach(view, [{"work_order": "FA-1", "revised_date": "2026-08-20",
                             "remark": "Kunde informiert", "updated_by": "u@x",
                             "on_hold": 1, "on_hold_since": "2026-07-10"}])
        prod = {w["name"]: w for w in view["purchasing"]["work_orders"]}
        self.assertTrue(prod["FA-1"]["on_hold"])
        self.assertEqual(prod["FA-1"]["on_hold_since"], "2026-07-10")
        self.assertEqual(prod["FA-1"]["note_date"], "2026-08-20")
        self.assertEqual(prod["FA-1"]["note_remark"], "Kunde informiert")
        self.assertFalse(prod["FA-2"]["on_hold"])
        self.assertIsNone(prod["FA-2"]["note_date"])
        # dieselbe Sperre muss auch an der Liefertermin-Liste haengen
        self.assertTrue(view["todo"]["overdue"][0]["work_orders"][0]["on_hold"])
        self.assertFalse(view["todo"]["due_this_week"][0]["work_orders"][0]["on_hold"])

    def test_attach_without_work_orders_is_noop(self):
        view = {"purchasing": {"work_orders": []}}
        self._attach(view, [{"work_order": "FA-1", "on_hold": 1}])
        self.assertEqual(view["purchasing"]["work_orders"], [])


class TestFetchFeedsMetrics(TestFetchErpnext):
    """Der Abruf muss genau das liefern, was build_metrics erwartet — der Bruch
    zwischen beiden ist auf der Instanz erst als leeres Board aufgefallen."""

    METRICS_CONFIG = {
        "company": "Musterfirma GmbH",
        "currency": "EUR",
        "revenue_target": 100000,
        "forecast": {"baseline_months": 3, "confidence_days_K": 5,
                     "uncertainty_pct": 0.15, "amber_threshold": 0.85},
        "holidays": {"region": "BY", "extra": []},
        "billing": {"ups_transit_days": 2, "stale_delivery_note_days": 60},
    }

    def test_build_metrics_runs_on_fetched_shape(self):
        data, _, _ = self._run()
        from pcb_board import metrics
        out = metrics.build_metrics(data, self.METRICS_CONFIG, date(2026, 7, 15))
        for key in ("forecast", "costs", "todo", "purchasing", "profit_history",
                    "product_flops", "product_margins_year", "billing", "pipeline", "crm"):
            self.assertIn(key, out)
        self.assertEqual(out["purchasing"]["open_count"], 0)
        self.assertEqual(out["product_margins_year"]["prev_year"], 2025)

    def test_build_metrics_survives_skipped_blocks(self):
        data, _, _ = self._run(failing_doctypes=("Work Order", "Sales Invoice Item", "Item"))
        from pcb_board import metrics
        out = metrics.build_metrics(data, self.METRICS_CONFIG, date(2026, 7, 15))
        self.assertEqual(out["product_flops"], [])
        self.assertEqual(out["product_margins_year"]["rows"], [])
        self.assertEqual(out["purchasing"]["work_orders"], [])
        # Kernzahlen bleiben trotzdem berechnet
        self.assertIn("mtd", out["forecast"])


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import revenue_aggregate as ra
import render_dashboard as rd
from lib import io_utils as io

CONFIG = io.load_config()


class TestRender(unittest.TestCase):
    def _html(self):
        data = {
            "as_of": "2026-07-06",
            "invoices": [{"name": "RE-1", "base_net_total": 5000, "posting_date": "2026-07-02"}],
            "to_bill_delivery_notes": [
                {"name": "LS-A", "customer_name": "Kunde A", "base_net_total": 900, "per_billed": 0,
                 "posting_date": "2026-07-01", "arrival_status": "delivered",
                 "delivered_date": "2026-07-03", "arrival_method": "ups"}],
            "open_sales_orders": [{"name": "AB-1", "net_open": 12000}],
            "mail": {"window_hours": 72, "items": [
                {"mailbox": "m.mustermann@example.com", "sender_name": "esmo AG",
                 "sender": "x@esmo.de", "subject": "Liefererinnerung", "category": "relevant",
                 "priority": "high", "reason": "Termin?", "draft": "Sehr geehrte Damen und Herren,\n…"},
                {"mailbox": "bestellung@example.com", "sender_name": "Werbung",
                 "sender": "spam@x.de", "subject": "Angebot", "category": "info", "priority": "normal"},
            ]},
        }
        m = ra.build_metrics(data, CONFIG, date(2026, 7, 6))
        m["dashboard_title"] = "Musterfirma Team-Board"
        m["company"] = "Musterfirma GmbH"
        m["generated_at"] = "2026-07-06T15:09:00+02:00"
        m["auto_refresh_minutes"] = 30
        return rd.render(m)

    def test_board_structure_present(self):
        h = self._html()
        for token in ['class="pcb-logo', 'id="refreshBtn"', 'id="tab-mail"', 'id="tab-revenue"',
                      'id="tab-billing"', 'id="mbChips"', 'class="overlay"', 'pulsing',
                      'data-refresh="30"', 'Stand 06.07.2026 15:09']:
            self.assertIn(token, h, f"fehlt: {token}")

    def test_draft_and_copy_rendered(self):
        h = self._html()
        self.assertIn("copybtn", h)              # Kopieren-Button für relevante Mail
        self.assertIn("Sehr geehrte Damen und Herren", h)  # Entwurf eingebettet
        self.assertIn("has-draft", h)

    def test_mailbox_chip_and_draft_only_for_relevant(self):
        h = self._html()
        self.assertIn('data-mb="m.mustermann@example.com"', h)
        # Info-Mail hat keinen Entwurf -> genau ein Kopieren-Button
        self.assertEqual(h.count('<button class="copybtn"'), 1)

    def test_logo_has_red_segment(self):
        self.assertIn("pcb-red", rd.pcb_logo_svg())


if __name__ == "__main__":
    unittest.main()

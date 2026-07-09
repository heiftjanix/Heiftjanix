import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pcb_board import triage


class TestKeywordFallback(unittest.TestCase):
    def _run(self, subject, body=""):
        msg = {"mailbox": "m.mustermann@example.com", "sender_name": "Test",
               "sender": "x@y.de", "subject": subject, "body_preview": body,
               "internet_message_id": f"test-{subject}"}
        return triage.triage_message(msg)

    def test_angebotsanfrage_gets_standard_draft(self):
        r = self._run("Angebotsanfrage Leiterplatten")
        self.assertEqual(r["category"], "relevant")
        self.assertEqual(r["draft"], triage.STANDARD_ANGEBOT_DRAFT)

    def test_newsletter_is_info_even_with_angebot_word(self):
        r = self._run("Unser Angebot der Woche")
        self.assertEqual(r["category"], "info")

    def test_urgent_order_is_high_priority(self):
        r = self._run("Dringend: Bestellung 12345")
        self.assertEqual(r["category"], "relevant")
        self.assertEqual(r["priority"], "high")

    def test_unrelated_is_info(self):
        r = self._run("Wetter heute")
        self.assertEqual(r["category"], "info")


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _msg(subject, msg_id):
    return {"mailbox": "m.mustermann@example.com", "sender_name": "Test",
            "sender": "x@y.de", "subject": subject, "body_preview": "",
            "internet_message_id": msg_id}


class TestTriageAllBatching(unittest.TestCase):
    def setUp(self):
        triage._CACHE.clear()

    def _mock_anthropic(self, results):
        mock_module = MagicMock()
        parsed = triage.MailTriageBatch(results=results)
        mock_module.Anthropic.return_value.messages.parse.return_value.parsed_output = parsed
        return patch.dict(sys.modules, {"anthropic": mock_module})

    def test_batch_call_preserves_order_and_populates_cache(self):
        msgs = [_msg("Mail A", "id-a"), _msg("Mail B", "id-b")]
        results = [
            triage.MailTriage(category="relevant", priority="high", reason="A", draft="draft-a"),
            triage.MailTriage(category="info", priority="normal", reason="B"),
        ]
        with self._mock_anthropic(results):
            out = triage.triage_all(msgs, api_key="sk-test")
        self.assertEqual(out[0]["subject"], "Mail A")
        self.assertEqual(out[0]["category"], "relevant")
        self.assertEqual(out[0]["draft"], "draft-a")
        self.assertEqual(out[1]["subject"], "Mail B")
        self.assertEqual(out[1]["category"], "info")
        self.assertIn("id-a", triage._CACHE)
        self.assertIn("id-b", triage._CACHE)

    def test_already_cached_messages_are_not_resent(self):
        triage._CACHE["id-a"] = {"category": "info", "priority": "normal", "reason": "cached"}
        msgs = [_msg("Mail A", "id-a")]
        mock_module = MagicMock()
        with patch.dict(sys.modules, {"anthropic": mock_module}):
            out = triage.triage_all(msgs, api_key="sk-test")
        mock_module.Anthropic.assert_not_called()
        self.assertEqual(out[0]["reason"], "cached")

    def test_batch_failure_falls_back_to_keyword_per_mail(self):
        msgs = [_msg("Dringend: Bestellung 1", "id-x")]
        mock_module = MagicMock()
        mock_module.Anthropic.return_value.messages.parse.side_effect = RuntimeError("429")
        with patch.dict(sys.modules, {"anthropic": mock_module}):
            out = triage.triage_all(msgs, api_key="sk-test")
        self.assertEqual(out[0]["category"], "relevant")
        self.assertEqual(out[0]["priority"], "high")

    def test_rate_limit_retries_once_then_succeeds(self):
        class _RateLimitError(Exception):
            status_code = 429

        msgs = [_msg("Mail A", "id-a")]
        good_result = triage.MailTriageBatch(
            results=[triage.MailTriage(category="relevant", priority="normal", reason="ok")]
        )
        mock_module = MagicMock()
        mock_module.Anthropic.return_value.messages.parse.side_effect = [
            _RateLimitError("rate limited"),
            MagicMock(parsed_output=good_result),
        ]
        with patch.dict(sys.modules, {"anthropic": mock_module}), patch("time.sleep") as mock_sleep:
            out = triage.triage_all(msgs, api_key="sk-test")
        mock_sleep.assert_called_once_with(triage.RATE_LIMIT_BACKOFF_SECONDS)
        self.assertEqual(out[0]["category"], "relevant")
        self.assertEqual(out[0]["reason"], "ok")

    def test_non_rate_limit_error_does_not_retry(self):
        msgs = [_msg("Mail A", "id-a")]
        mock_module = MagicMock()
        mock_module.Anthropic.return_value.messages.parse.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"anthropic": mock_module}), patch("time.sleep") as mock_sleep:
            triage.triage_all(msgs, api_key="sk-test")
        mock_sleep.assert_not_called()
        self.assertEqual(mock_module.Anthropic.return_value.messages.parse.call_count, 1)


if __name__ == "__main__":
    unittest.main()

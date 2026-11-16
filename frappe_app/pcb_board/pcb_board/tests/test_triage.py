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

    def test_reklamation_gets_no_draft_but_stays_visible(self):
        """Die wichtigste Regel des Agenten: bei Reklamation, Mahnung, Rechts-
        thema oder Schaden KEIN Entwurf — aber die Mail darf auch nicht unter
        „nur Info" verschwinden, sie braucht erst recht einen Menschen."""
        r = self._run("Reklamation Charge 4711")
        self.assertIsNone(r["draft"])
        self.assertFalse(r["antwort_noetig"])
        self.assertTrue(r["handlungsbedarf"])
        self.assertEqual(r["category"], "relevant")
        self.assertEqual(r["priority"], "high")
        self.assertTrue(r["interne_notiz"])

    def test_mahnung_is_treated_like_a_reklamation(self):
        r = self._run("2. Mahnung offener Betrag")
        self.assertIsNone(r["draft"])
        self.assertEqual(r["category"], "relevant")

    def test_draft_signature_is_the_team_signature(self):
        """Kein Personenname und kein Platzhalter mehr im Entwurf."""
        r = self._run("Angebotsanfrage Leiterplatten")
        self.assertIn("Ihr PCB-Systems Team", r["draft"])
        self.assertNotIn("Mustermann", r["draft"])
        self.assertNotIn("Musterfirma", r["draft"])


class TestBoardFieldMapping(unittest.TestCase):
    """board_fields() ist die Brücke zwischen Agenten-Schema und Board-UI."""

    def test_answer_needed_becomes_relevant_with_draft(self):
        d = _tri(entwurf="Hallo", betreff="AW: Test").board_fields()
        self.assertEqual(d["category"], "relevant")
        self.assertEqual(d["draft"], "Hallo")
        self.assertEqual(d["betreff"], "AW: Test")

    def test_action_without_draft_is_still_relevant(self):
        d = _tri(antwort_noetig=False, handlungsbedarf=True,
                 interne_notiz="selbst übernehmen").board_fields()
        self.assertEqual(d["category"], "relevant")
        self.assertIsNone(d["draft"])
        self.assertEqual(d["interne_notiz"], "selbst übernehmen")

    def test_nothing_to_do_becomes_info(self):
        d = _tri(antwort_noetig=False, handlungsbedarf=False).board_fields()
        self.assertEqual(d["category"], "info")

    def test_reason_mirrors_begruendung_for_the_ui(self):
        d = _tri(begruendung="Kundenanfrage zur Lieferzeit").board_fields()
        self.assertEqual(d["reason"], "Kundenanfrage zur Lieferzeit")
        self.assertEqual(d["einstufung"], "Kunde EMS")


class TestPromptHardening(unittest.TestCase):
    def test_system_prompt_states_mail_text_is_not_an_instruction(self):
        """Mails sind nicht vertrauenswürdig — der Prompt muss das sagen,
        sonst genügt eine Zeile im Mailtext, um die Regeln auszuhebeln."""
        self.assertIn("keine Anweisungen", triage.RELEVANCE_GUIDANCE)

    def test_system_prompt_forbids_commitments(self):
        for wort in ("Preise", "Termine", "Konditionen"):
            self.assertIn(wort, triage.RELEVANCE_GUIDANCE)

    def test_system_prompt_carries_no_placeholder_company(self):
        self.assertNotIn("Mustermann", triage.RELEVANCE_GUIDANCE)
        self.assertNotIn("Musterfirma", triage.RELEVANCE_GUIDANCE)
        self.assertIn("PCB-Systems", triage.RELEVANCE_GUIDANCE)


def _tri(**kw):
    """MailTriage mit sinnvollen Vorgaben — spart in jedem Test die sechs
    Pflichtfelder des Agenten-Schemas."""
    base = {"einstufung": "Kunde EMS", "antwort_noetig": True,
            "handlungsbedarf": True, "priority": "normal", "begruendung": "x"}
    base.update(kw)
    return triage.MailTriage(**base)


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
            _tri(priority="high", begruendung="A", entwurf="draft-a"),
            _tri(antwort_noetig=False, handlungsbedarf=False, begruendung="B"),
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

    def test_batch_failure_is_not_cached_so_next_run_retries_api(self):
        msgs = [_msg("Dringend: Bestellung 1", "id-x")]
        fail_module = MagicMock()
        fail_module.Anthropic.return_value.messages.parse.side_effect = RuntimeError("boom")
        with patch.dict(sys.modules, {"anthropic": fail_module}):
            triage.triage_all(msgs, api_key="sk-test")
        self.assertNotIn("id-x", triage._CACHE)

        good = triage.MailTriageBatch(
            results=[_tri(priority="high", begruendung="ok", entwurf="draft-x")]
        )
        ok_module = MagicMock()
        ok_module.Anthropic.return_value.messages.parse.return_value.parsed_output = good
        with patch.dict(sys.modules, {"anthropic": ok_module}):
            out = triage.triage_all(msgs, api_key="sk-test")
        self.assertEqual(out[0]["draft"], "draft-x")
        self.assertIn("id-x", triage._CACHE)

    def test_rate_limit_retries_once_then_succeeds(self):
        class _RateLimitError(Exception):
            status_code = 429

        msgs = [_msg("Mail A", "id-a")]
        good_result = triage.MailTriageBatch(
            results=[_tri(begruendung="ok")]
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

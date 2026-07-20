"""Tests für Prompt-Konstruktion, Demo-Fallback und Refusal-Handling."""
import json
import unittest
from unittest import mock

from ai_systems import claude_gen, prompts
from ai_systems.workflow_validate import validate_structure


class PromptTest(unittest.TestCase):
    def test_static_block_is_cached(self):
        blocks = prompts.system_blocks("Sekretariat", ["m365"], ["graph.microsoft.com"])
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", blocks[1])
        self.assertIn("n8n-nodes-base.httpRequest", blocks[0]["text"])

    def test_context_contains_only_allowed_snippets(self):
        ctx = prompts.department_context("Buchhaltung", ["erpnext"], ["erp.example.com"])
        self.assertIn("ERPNext", ctx)
        self.assertIn("erp.example.com", ctx)
        # Nicht freigegebene Systeme tauchen nur in der Verbotsliste auf.
        self.assertNotIn("api.github.com", ctx)
        self.assertIn("NICHT verwenden", ctx)
        self.assertIn("GitHub", ctx)

    def test_context_embeds_existing_workflow(self):
        ctx = prompts.department_context("X", [], [], current_workflow_json='{"name": "Alt"}')
        self.assertIn("EXISTIERT BEREITS", ctx)
        self.assertIn('{"name": "Alt"}', ctx)


class RunsFeedbackTest(unittest.TestCase):
    def test_runs_summary_lands_in_context(self):
        ctx = prompts.department_context("Sekretariat", [], [],
                                         runs_summary="- 2026-07-18: error\nFehlerdetails: 401")
        self.assertIn("LETZTE LÄUFE", ctx)
        self.assertIn("401", ctx)

    def test_history_is_capped_and_starts_with_user(self):
        fake_resp = mock.Mock()
        fake_resp.stop_reason = "end_turn"
        fake_resp.parsed_output = claude_gen.AgentProposal(reply="ok")
        fake_client = mock.Mock()
        fake_client.messages.parse.return_value = fake_resp
        history = []
        for i in range(40):  # 80 Nachrichten, abwechselnd
            history.append({"role": "user", "content": f"u{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        env = {"ANTHROPIC_API_KEY": "sk-test", "N8N_URL": "https://n8n.example.com",
               "DEMO_MODE": "0"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch("anthropic.Anthropic", return_value=fake_client):
            claude_gen.generate("X", [], [], history)
        sent = fake_client.messages.parse.call_args.kwargs["messages"]
        self.assertLessEqual(len(sent), claude_gen.MAX_HISTORY_MESSAGES)
        self.assertEqual(sent[0]["role"], "user")
        self.assertEqual(sent[-1]["content"], "a39")


class DemoFallbackTest(unittest.TestCase):
    def test_first_message_asks_question(self):
        with mock.patch.dict("os.environ", {"DEMO_MODE": "1"}, clear=False):
            prop = claude_gen.generate("Sekretariat", [], [],
                                       [{"role": "user", "content": "Bau mir einen Agenten"}])
        self.assertIsNone(prop.workflow_json)
        self.assertTrue(prop.reply)

    def test_second_message_yields_valid_workflow(self):
        history = [
            {"role": "user", "content": "Bau mir einen Agenten"},
            {"role": "assistant", "content": "Rückfrage"},
            {"role": "user", "content": "Werktags um 7, per Mail"},
        ]
        with mock.patch.dict("os.environ", {"DEMO_MODE": "1"}, clear=False):
            prop = claude_gen.generate("Sekretariat", [], [], history)
        self.assertEqual(prop.agent_name, "Emil Eilig")
        workflow = json.loads(prop.workflow_json)
        self.assertEqual(validate_structure(workflow), [])


class FriendlyErrorTest(unittest.TestCase):
    def _err(self, status, message):
        exc = RuntimeError(message)
        exc.status_code = status
        exc.body = {"error": {"message": message}}
        return exc

    def test_credit_balance(self):
        msg = claude_gen.friendly_error(
            self._err(400, "Your credit balance is too low to access the API."), "claude-fable-5")
        self.assertIn("Guthaben", msg)

    def test_invalid_key(self):
        msg = claude_gen.friendly_error(self._err(401, "invalid x-api-key"), "claude-fable-5")
        self.assertIn("API-Key", msg)

    def test_unknown_model_mentions_model_name(self):
        msg = claude_gen.friendly_error(
            self._err(404, "model: claude-fable-5 not found"), "claude-fable-5")
        self.assertIn("claude-fable-5", msg)
        self.assertIn("AI_SYSTEMS_MODEL", msg)

    def test_overloaded(self):
        msg = claude_gen.friendly_error(self._err(529, "Overloaded"), "m")
        self.assertIn("überlastet", msg)

    def test_generic_includes_real_message(self):
        msg = claude_gen.friendly_error(self._err(400, "some odd validation problem"), "m")
        self.assertIn("some odd validation problem", msg)


class RefusalTest(unittest.TestCase):
    def test_refusal_stop_reason_handled(self):
        fake_resp = mock.Mock()
        fake_resp.stop_reason = "refusal"
        fake_client = mock.Mock()
        fake_client.messages.parse.return_value = fake_resp
        env = {"ANTHROPIC_API_KEY": "sk-test", "N8N_URL": "https://n8n.example.com",
               "DEMO_MODE": "0"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch("anthropic.Anthropic", return_value=fake_client):
            prop = claude_gen.generate("X", [], [], [{"role": "user", "content": "hi"}])
        self.assertIn("Sicherheitsgründen", prop.reply)
        self.assertIsNone(prop.workflow_json)

    def test_api_error_yields_german_message(self):
        env = {"ANTHROPIC_API_KEY": "sk-test", "N8N_URL": "https://n8n.example.com",
               "DEMO_MODE": "0"}
        with mock.patch.dict("os.environ", env, clear=False), \
             mock.patch("anthropic.Anthropic", side_effect=RuntimeError("kaputt")):
            prop = claude_gen.generate("X", [], [], [{"role": "user", "content": "hi"}])
        self.assertIn("fehlgeschlagen", prop.reply)


if __name__ == "__main__":
    unittest.main()

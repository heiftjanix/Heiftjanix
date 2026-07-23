"""Tests für die laienverständliche Aufgaben-Visualisierung eines Workflows."""
import unittest

from ai_systems.workflow_steps import describe_workflow


def linear_workflow():
    return {
        "name": "Test",
        "nodes": [
            {"name": "Start", "type": "n8n-nodes-base.scheduleTrigger",
             "parameters": {"rule": {"interval": [{"field": "cronExpression",
                                                   "expression": "0 7 * * 1-5"}]}}},
            {"name": "Abruf", "type": "n8n-nodes-base.httpRequest",
             "parameters": {"method": "GET", "url": "https://api.example.com/x"}},
            {"name": "Senden", "type": "n8n-nodes-base.emailSend",
             "parameters": {"toEmail": "a@example.com", "subject": "Bericht"}},
        ],
        "connections": {
            "Start": {"main": [[{"node": "Abruf", "type": "main", "index": 0}]]},
            "Abruf": {"main": [[{"node": "Senden", "type": "main", "index": 0}]]},
        },
    }


class WorkflowStepsTest(unittest.TestCase):
    def test_order_follows_trigger_first(self):
        steps = describe_workflow(linear_workflow())
        self.assertEqual([s["name"] for s in steps], ["Start", "Abruf", "Senden"])

    def test_labels_and_icons_present(self):
        steps = describe_workflow(linear_workflow())
        self.assertEqual(steps[0]["label"], "Zeitplan-Start")
        self.assertTrue(steps[0]["icon"])
        self.assertIn("Startet automatisch", steps[0]["description"])

    def test_schedule_detail_shows_cron(self):
        steps = describe_workflow(linear_workflow())
        self.assertIn("0 7 * * 1-5", steps[0]["detail"])

    def test_http_detail_shows_method_and_url(self):
        steps = describe_workflow(linear_workflow())
        self.assertIn("GET", steps[1]["detail"])
        self.assertIn("api.example.com", steps[1]["detail"])

    def test_emailsend_detail_shows_recipient_and_subject(self):
        steps = describe_workflow(linear_workflow())
        self.assertIn("a@example.com", steps[2]["detail"])
        self.assertIn("Bericht", steps[2]["detail"])

    def test_unknown_node_type_gets_default(self):
        wf = linear_workflow()
        wf["nodes"][1]["type"] = "n8n-nodes-base.somethingNew"
        steps = describe_workflow(wf)
        self.assertEqual(steps[1]["label"], "Verarbeitungsschritt")

    def test_empty_workflow_yields_no_steps(self):
        self.assertEqual(describe_workflow({}), [])
        self.assertEqual(describe_workflow({"nodes": []}), [])

    def test_disconnected_node_still_included(self):
        wf = linear_workflow()
        wf["nodes"].append({"name": "Verwaist", "type": "n8n-nodes-base.noOp", "parameters": {}})
        steps = describe_workflow(wf)
        self.assertIn("Verwaist", [s["name"] for s in steps])
        self.assertEqual(len(steps), 4)


if __name__ == "__main__":
    unittest.main()

"""Tests für die n8n-Workflow-Strukturvalidierung."""
import unittest

from ai_systems.workflow_validate import validate_structure


def minimal_workflow():
    return {
        "name": "Test",
        "nodes": [
            {"id": "a", "name": "Start", "type": "n8n-nodes-base.manualTrigger",
             "typeVersion": 1, "position": [0, 0], "parameters": {}},
            {"id": "b", "name": "Abruf", "type": "n8n-nodes-base.httpRequest",
             "typeVersion": 4, "position": [200, 0],
             "parameters": {"url": "https://api.example.com/x"}},
        ],
        "connections": {"Start": {"main": [[{"node": "Abruf", "type": "main", "index": 0}]]}},
        "settings": {},
    }


class ValidateTest(unittest.TestCase):
    def test_valid_minimal(self):
        self.assertEqual(validate_structure(minimal_workflow()), [])

    def test_missing_fields(self):
        errors = validate_structure({"nodes": []})
        self.assertTrue(any("'name'" in e for e in errors))
        self.assertTrue(any("'nodes'" in e for e in errors))

    def test_forbidden_node_type(self):
        wf = minimal_workflow()
        wf["nodes"][1]["type"] = "n8n-nodes-base.executeCommand"
        errors = validate_structure(wf)
        self.assertTrue(any("executeCommand" in e and "nicht erlaubt" in e for e in errors))

    def test_duplicate_node_names(self):
        wf = minimal_workflow()
        wf["nodes"][1]["name"] = "Start"
        errors = validate_structure(wf)
        self.assertTrue(any("doppelt" in e for e in errors))

    def test_missing_trigger(self):
        wf = minimal_workflow()
        wf["nodes"][0]["type"] = "n8n-nodes-base.set"
        wf["connections"] = {}
        errors = validate_structure(wf)
        self.assertTrue(any("Trigger" in e for e in errors))

    def test_connection_to_unknown_node(self):
        wf = minimal_workflow()
        wf["connections"]["Start"]["main"][0][0]["node"] = "Gibtsnicht"
        errors = validate_structure(wf)
        self.assertTrue(any("Gibtsnicht" in e for e in errors))

    def test_connection_from_unknown_source(self):
        wf = minimal_workflow()
        wf["connections"]["Phantom"] = {"main": [[{"node": "Abruf", "type": "main", "index": 0}]]}
        errors = validate_structure(wf)
        self.assertTrue(any("Phantom" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

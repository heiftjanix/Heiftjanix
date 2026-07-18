"""Tests für den n8n-REST-Client (gefakte Session) und DemoN8n."""
import unittest

from ai_systems.n8n_client import DemoN8n, N8nClient, N8nError


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = b"x" if payload is not None else b""

    def json(self):
        if self._payload is None:
            raise ValueError("kein JSON")
        return self._payload


class FakeSession:
    """Zeichnet Aufrufe auf und liefert vorbereitete Antworten."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


class N8nClientTest(unittest.TestCase):
    def test_create_sends_only_writable_fields(self):
        session = FakeSession([FakeResponse(payload={"id": "7", "name": "X"})])
        client = N8nClient("https://n8n.example.com/", "key", session=session)
        client.create_workflow({"name": "X", "nodes": [], "connections": {},
                                "active": True, "id": "sollte-weg", "tags": ["a"]})
        call = session.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["url"], "https://n8n.example.com/api/v1/workflows")
        self.assertEqual(set(call["json"].keys()), {"name", "nodes", "connections", "settings"})

    def test_auth_header_set(self):
        session = FakeSession([])
        N8nClient("https://n8n.example.com", "geheim", session=session)
        self.assertEqual(session.headers["X-N8N-API-KEY"], "geheim")

    def test_activate_uses_post_endpoint(self):
        session = FakeSession([FakeResponse(payload={"id": "7", "active": True})])
        client = N8nClient("https://n8n.example.com", "k", session=session)
        client.activate("7")
        self.assertEqual(session.calls[0]["url"],
                         "https://n8n.example.com/api/v1/workflows/7/activate")

    def test_error_raises_n8nerror_with_status(self):
        session = FakeSession([FakeResponse(status_code=401,
                                            payload={"message": "unauthorized"})])
        client = N8nClient("https://n8n.example.com", "k", session=session)
        with self.assertRaises(N8nError) as ctx:
            client.get_workflow("7")
        self.assertEqual(ctx.exception.status, 401)
        self.assertIn("401", str(ctx.exception))

    def test_list_workflows_follows_cursor(self):
        session = FakeSession([
            FakeResponse(payload={"data": [{"id": "1"}], "nextCursor": "abc"}),
            FakeResponse(payload={"data": [{"id": "2"}]}),
        ])
        client = N8nClient("https://n8n.example.com", "k", session=session)
        items = client.list_workflows()
        self.assertEqual([w["id"] for w in items], ["1", "2"])
        self.assertEqual(session.calls[1]["params"]["cursor"], "abc")


class DemoN8nTest(unittest.TestCase):
    def test_demo_lifecycle(self):
        demo = DemoN8n()
        before = len(demo.list_workflows())
        created = demo.create_workflow({"name": "Neu", "nodes": [], "connections": {}})
        self.assertEqual(len(demo.list_workflows()), before + 1)
        self.assertFalse(created["active"])
        demo.activate(created["id"])
        self.assertTrue(demo.get_workflow(created["id"])["active"])
        demo.rename_workflow(created["id"], "Umbenannt")
        self.assertEqual(demo.get_workflow(created["id"])["name"], "Umbenannt")
        demo.delete_workflow(created["id"])
        with self.assertRaises(N8nError):
            demo.get_workflow(created["id"])

    def test_demo_executions_seeded(self):
        demo = DemoN8n()
        runs = demo.executions("demo-wf-1")
        self.assertTrue(runs)
        self.assertIn(runs[0]["status"], ("success", "error"))


if __name__ == "__main__":
    unittest.main()

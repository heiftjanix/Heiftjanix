import os
import sys
import time
import unittest
from pathlib import Path

os.environ["DEMO_MODE"] = "1"
os.environ.setdefault("SESSION_SECRET", "test-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from webapp import auth, service  # noqa: E402
from webapp.app import app         # noqa: E402


def _wait_idle(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if service.status()["state"] == "idle" and service.get_last_metrics() is not None:
            return
        time.sleep(0.05)
    raise AssertionError("Refresh nicht rechtzeitig abgeschlossen")


class TestWebapp(unittest.TestCase):
    def setUp(self):
        auth.SESSIONS.clear()
        service._METRICS = None
        service._STATUS.update({"state": "idle", "started_by": None,
                                 "started_at": None, "generated_at": None})
        service.triage._CACHE.clear()
        self.client = TestClient(app)

    def _login(self):
        resp = self.client.get("/login", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers["location"], "/")

    def test_root_redirects_to_login_when_anonymous(self):
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers["location"], "/login")

    def test_demo_login_then_board_loading_then_ready(self):
        self._login()
        first = self.client.get("/")
        self.assertIn("Erster Datenabruf", first.text)
        _wait_idle()
        board = self.client.get("/")
        self.assertIn('data-mode="webapp"', board.text)
        self.assertIn("Max Mustermann (Demo)", board.text)
        self.assertIn("Abmelden", board.text)

    def test_api_status_requires_login(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 401)

    def test_api_status_shape_after_login(self):
        self._login()
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("state", "started_by", "started_at", "generated_at"):
            self.assertIn(key, body)

    def test_refresh_cycle_sets_generated_at(self):
        self._login()
        resp = self.client.post("/api/refresh")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])
        _wait_idle()
        metrics = service.get_last_metrics()
        self.assertIsNotNone(metrics["generated_at"])

    def test_mailbox_filtering_limits_view_to_allowed_boxes(self):
        self._login()
        self.client.post("/api/refresh")
        _wait_idle()
        metrics = service.get_last_metrics()
        allowed = {"m.mustermann@example.com", "bestellung@example.com",
                   "anfrage@example.com", "webshop@example.com"}
        view = service.view_for_mailboxes(metrics, allowed)
        boxes = {b["name"] for b in view["mail"]["mailboxes"]}
        self.assertTrue(boxes.issubset(allowed))

    def test_logout_clears_session(self):
        self._login()
        self.client.get("/logout", follow_redirects=False)
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 307)
        self.assertEqual(resp.headers["location"], "/login")


if __name__ == "__main__":
    unittest.main()

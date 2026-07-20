"""End-to-End-Tests der FastAPI-App im DEMO_MODE (TestClient, ohne Zugangsdaten)."""
import os
import unittest

os.environ["DEMO_MODE"] = "1"
os.environ["AI_SYSTEMS_DB"] = ":memory:"

from fastapi.testclient import TestClient  # noqa: E402

from ai_systems import db, n8n_client  # noqa: E402
from ai_systems.app import app  # noqa: E402


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.reset_conn()
        n8n_client.reset_demo()
        # Startup-Events (Demo-Seed) laufen nur im Kontextmanager des TestClients.
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        db.reset_conn()
        n8n_client.reset_demo()

    def test_index_serves_german_spa(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("AI-Systems", resp.text)
        self.assertIn("Virtuelle Firma", resp.text)
        self.assertIn("Mitarbeiter einstellen", resp.text)

    def test_healthz_reports_demo(self):
        data = self.client.get("/healthz").json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["demo_mode"])

    def test_demo_seed_present(self):
        deps = self.client.get("/api/departments").json()
        names = {d["name"] for d in deps}
        self.assertIn("Sekretariat", names)
        self.assertIn("Buchhaltung", names)

    def test_department_crud_roundtrip(self):
        created = self.client.post("/api/departments",
                                   json={"name": "Testabteilung", "icon": "🧪"}).json()
        self.assertEqual(created["icon"], "🧪")
        dup = self.client.post("/api/departments", json={"name": "Testabteilung"})
        self.assertEqual(dup.status_code, 409)
        patched = self.client.patch(f"/api/departments/{created['id']}",
                                    json={"description": "geändert"}).json()
        self.assertEqual(patched["description"], "geändert")
        self.assertEqual(
            self.client.delete(f"/api/departments/{created['id']}").json(), {"ok": True})

    def test_connector_assignment_endpoint(self):
        dep = self.client.post("/api/departments", json={"name": "Konnektor-Test"}).json()
        updated = self.client.put(f"/api/departments/{dep['id']}/connectors",
                                  json={"keys": ["github"]}).json()
        github = next(c for c in updated if c["key"] == "github")
        self.assertTrue(github["allowed"])
        bad = self.client.put(f"/api/departments/{dep['id']}/connectors",
                              json={"keys": ["gibtsnicht"]})
        self.assertEqual(bad.status_code, 400)
        self.client.delete(f"/api/departments/{dep['id']}")

    def test_chat_to_deploy_happy_path(self):
        deps = self.client.get("/api/departments").json()
        sekretariat = next(d for d in deps if d["name"] == "Sekretariat")
        sess = self.client.post("/api/chat/sessions",
                                json={"department_id": sekretariat["id"]}).json()
        # 1. Nachricht -> Rückfrage ohne Vorschlag
        first = self.client.post(f"/api/chat/sessions/{sess['id']}/message",
                                 json={"text": "Bau mir einen Mail-Agenten"}).json()
        self.assertIsNone(first["proposal"])
        # 2. Nachricht -> Vorschlag mit Workflow
        second = self.client.post(f"/api/chat/sessions/{sess['id']}/message",
                                  json={"text": "Werktags 7 Uhr, per Mail an mich"}).json()
        self.assertEqual(second["problems"], [])
        self.assertEqual(second["proposal"]["agent_name"], "Emil Eilig")
        # Deploy -> Agent angelegt, DemoN8n kennt den Workflow
        deployed = self.client.post(f"/api/chat/sessions/{sess['id']}/deploy").json()
        agent = deployed["agent"]
        self.assertEqual(agent["name"], "Emil Eilig")
        self.assertTrue(agent["n8n_workflow_id"])
        detail = self.client.get(f"/api/agents/{agent['id']}").json()
        self.assertEqual(detail["role"], "E-Mail-Zusammenfasser")
        # Aktivieren über n8n und wieder entlassen
        self.assertEqual(
            self.client.post(f"/api/agents/{agent['id']}/activate").json()["active"], 1)
        self.assertEqual(self.client.delete(f"/api/agents/{agent['id']}").json(), {"ok": True})

    def test_deploy_rejected_when_host_not_allowed(self):
        # Versand hat keine Microsoft-Freigabe -> der gecannte Workflow verletzt die Regeln.
        deps = self.client.get("/api/departments").json()
        versand = next(d for d in deps if d["name"] == "Versand")
        sess = self.client.post("/api/chat/sessions",
                                json={"department_id": versand["id"]}).json()
        self.client.post(f"/api/chat/sessions/{sess['id']}/message", json={"text": "hi"})
        second = self.client.post(f"/api/chat/sessions/{sess['id']}/message",
                                  json={"text": "mach mal"}).json()
        # Vorschlag fällt schon im Chat durch die Prüfung (auch nach Korrekturrunde).
        self.assertTrue(second["problems"])
        resp = self.client.post(f"/api/chat/sessions/{sess['id']}/deploy")
        self.assertEqual(resp.status_code, 422)
        self.assertIn("violations", resp.json())

    def test_rules_endpoint_lists_implicit_hosts(self):
        deps = self.client.get("/api/departments").json()
        sekretariat = next(d for d in deps if d["name"] == "Sekretariat")
        rules = self.client.get(f"/api/departments/{sekretariat['id']}/rules").json()
        self.assertIn("api.anthropic.com", rules["implicit_hosts"])

    def test_import_existing_workflow_as_agent(self):
        # Der unverwaltete Demo-Workflow taucht als Import-Kandidat auf …
        candidates = self.client.get("/api/n8n/workflows").json()
        ids = [w["id"] for w in candidates]
        self.assertIn("demo-wf-frei-1", ids)
        # … und wird als benannter Mitarbeiter übernommen.
        deps = self.client.get("/api/departments").json()
        versand = next(d for d in deps if d["name"] == "Versand")
        agent = self.client.post("/api/agents/import", json={
            "department_id": versand["id"], "n8n_workflow_id": "demo-wf-frei-1",
            "name": "Berta Bestellung", "role": "Bestellbestätigerin"}).json()
        self.assertEqual(agent["n8n_workflow_id"], "demo-wf-frei-1")
        self.assertEqual(agent["active"], 1)  # Aktiv-Status aus n8n übernommen
        # Doppelter Import desselben Workflows wird abgelehnt.
        dup = self.client.post("/api/agents/import", json={
            "department_id": versand["id"], "n8n_workflow_id": "demo-wf-frei-1",
            "name": "Nochmal"})
        self.assertEqual(dup.status_code, 422)
        # Nach dem Import ist der Workflow kein Kandidat mehr.
        ids = [w["id"] for w in self.client.get("/api/n8n/workflows").json()]
        self.assertNotIn("demo-wf-frei-1", ids)
        self.client.delete(f"/api/agents/{agent['id']}")

    def test_agent_chat_session_is_continuous(self):
        deps = self.client.get("/api/departments").json()
        sekretariat = next(d for d in deps if d["name"] == "Sekretariat")
        agents = self.client.get(f"/api/agents?department_id={sekretariat['id']}").json()
        paula = next(a for a in agents if a["name"] == "Paula Post")
        s1 = self.client.post("/api/chat/sessions", json={
            "department_id": sekretariat["id"], "agent_id": paula["id"]}).json()
        self.client.post(f"/api/chat/sessions/{s1['id']}/message", json={"text": "Hallo"})
        # Erneutes Öffnen liefert DIESELBE Sitzung samt Verlauf.
        s2 = self.client.post("/api/chat/sessions", json={
            "department_id": sekretariat["id"], "agent_id": paula["id"]}).json()
        self.assertEqual(s2["id"], s1["id"])
        self.assertEqual(len(s2["messages"]), 2)  # Nutzerfrage + Antwort
        # Abteilungs-Chats (neuer Mitarbeiter) bleiben dagegen frisch.
        d1 = self.client.post("/api/chat/sessions",
                              json={"department_id": sekretariat["id"]}).json()
        d2 = self.client.post("/api/chat/sessions",
                              json={"department_id": sekretariat["id"]}).json()
        self.assertNotEqual(d1["id"], d2["id"])

    def test_model_setting_roundtrip(self):
        s = self.client.get("/api/settings").json()
        self.assertIn("model", s)
        self.assertIn("claude-fable-5", s["suggestions"])
        # Modell setzen
        updated = self.client.put("/api/settings", json={"model": "claude-sonnet-5"}).json()
        self.assertEqual(updated["model"], "claude-sonnet-5")
        self.assertEqual(updated["model_override"], "claude-sonnet-5")
        self.assertEqual(self.client.get("/api/settings").json()["model"], "claude-sonnet-5")
        # Leeren -> zurück auf Standard
        cleared = self.client.put("/api/settings", json={"model": ""}).json()
        self.assertIsNone(cleared["model_override"])
        self.assertEqual(cleared["model"], cleared["default_model"])

    def test_connector_catalog_hides_secrets(self):
        catalog = self.client.get("/api/connectors").json()
        text = str(catalog)
        for var in ("ERPNEXT_API_SECRET", "GITHUB_TOKEN"):
            # Variablen-NAMEN dürfen erscheinen, Werte nie — hier: keine Werte gesetzt.
            self.assertNotIn(os.environ.get(var, "\x00nie"), text)


if __name__ == "__main__":
    unittest.main()

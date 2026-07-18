"""Tests für den SQLite-Store von AI-Systems (In-Memory-Datenbank)."""
import unittest

from ai_systems import db


class DbTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.open_db(":memory:")

    def tearDown(self):
        self.conn.close()

    def test_department_crud(self):
        dep = db.create_department(self.conn, "Vertrieb", "Angebote", icon="📞")
        self.assertEqual(dep["name"], "Vertrieb")
        self.assertEqual(dep["icon"], "📞")
        db.update_department(self.conn, dep["id"], name="Vertrieb & Marketing")
        self.assertEqual(db.get_department(self.conn, dep["id"])["name"], "Vertrieb & Marketing")
        deps = db.list_departments(self.conn)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["agent_count"], 0)
        db.delete_department(self.conn, dep["id"])
        self.assertIsNone(db.get_department(self.conn, dep["id"]))

    def test_agent_crud_and_cascade(self):
        dep = db.create_department(self.conn, "Buchhaltung")
        agent = db.create_agent(self.conn, dep["id"], "Frieda Faktura", role="Rechnungsprüferin")
        self.assertIsNone(agent["n8n_workflow_id"])
        db.update_agent(self.conn, agent["id"], n8n_workflow_id="wf-1", active=1)
        agent = db.get_agent(self.conn, agent["id"])
        self.assertEqual(agent["n8n_workflow_id"], "wf-1")
        self.assertEqual(agent["active"], 1)
        self.assertEqual(db.list_departments(self.conn)[0]["agent_count"], 1)
        # Cascade: Abteilung löschen entfernt Agenten und Regeln mit.
        db.add_rule(self.conn, dep["id"], "erp.example.com")
        db.delete_department(self.conn, dep["id"])
        self.assertEqual(db.list_agents(self.conn), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM network_rules").fetchone()[0], 0)

    def test_connector_assignment(self):
        dep = db.create_department(self.conn, "Sekretariat")
        db.set_allowed_connectors(self.conn, dep["id"], ["m365", "anthropic", "m365"])
        self.assertEqual(db.allowed_connectors(self.conn, dep["id"]), ["anthropic", "m365"])
        db.set_allowed_connectors(self.conn, dep["id"], [])
        self.assertEqual(db.allowed_connectors(self.conn, dep["id"]), [])

    def test_effective_rules(self):
        dep = db.create_department(self.conn, "Versand")
        agent = db.create_agent(self.conn, dep["id"], "Paula Paket")
        other = db.create_agent(self.conn, dep["id"], "Otto Ohne")
        db.add_rule(self.conn, dep["id"], "Onlinetools.UPS.com")  # wird lowercased
        db.add_rule(self.conn, dep["id"], "*.example.com", agent_id=agent["id"])
        self.assertEqual(db.effective_rule_patterns(self.conn, dep["id"], agent["id"]),
                         ["*.example.com", "onlinetools.ups.com"])
        self.assertEqual(db.effective_rule_patterns(self.conn, dep["id"], other["id"]),
                         ["onlinetools.ups.com"])
        self.assertEqual(db.effective_rule_patterns(self.conn, dep["id"], None),
                         ["onlinetools.ups.com"])

    def test_chat_history_and_latest_proposal(self):
        dep = db.create_department(self.conn, "Sekretariat")
        sess = db.create_chat_session(self.conn, dep["id"])
        db.add_chat_message(self.conn, sess["id"], "user", "Bau mir einen Agenten")
        db.add_chat_message(self.conn, sess["id"], "assistant", "Rückfrage?")
        self.assertIsNone(db.latest_proposal(self.conn, sess["id"]))
        db.add_chat_message(self.conn, sess["id"], "assistant", "Vorschlag",
                            proposal_json='{"name": "x"}', agent_name="Emil", agent_role="Bote")
        prop = db.latest_proposal(self.conn, sess["id"])
        self.assertEqual(prop["agent_name"], "Emil")
        self.assertEqual(len(db.list_chat_messages(self.conn, sess["id"])), 3)


if __name__ == "__main__":
    unittest.main()

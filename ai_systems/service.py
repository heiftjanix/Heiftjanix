"""Orchestrierung: Chat-Schritt -> Claude-Vorschlag -> Validierung -> Deploy nach n8n.

Hier laufen Datenbank, Konnektoren, Netzwerkregeln, Claude-Generator und
n8n-Client zusammen. Ein globaler Busy-Status versorgt das pulsierende Logo
im UI, während Claude generiert.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from . import claude_gen, config, connectors, db, n8n_client, netrules, workflow_validate

_STATUS_LOCK = threading.Lock()
_STATUS = {"state": "idle"}


class DeployError(Exception):
    """Deployment abgelehnt — trägt strukturierte Verstöße/Fehler fürs UI."""

    def __init__(self, message: str, violations: list[dict] | None = None):
        super().__init__(message)
        self.violations = violations or []


def status() -> dict:
    with _STATUS_LOCK:
        return dict(_STATUS)


def _set_status(state: str) -> None:
    with _STATUS_LOCK:
        _STATUS["state"] = state


def seed_demo(conn: sqlite3.Connection) -> None:
    """Befüllt eine leere Datenbank im DEMO_MODE mit der Demo-Firma."""
    if not config.is_demo_mode():
        return
    if conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]:
        return
    data = json.loads((Path(__file__).parent / "demo_data.json").read_text(encoding="utf-8"))
    for dep_spec in data.get("departments", []):
        dep = db.create_department(conn, dep_spec["name"], dep_spec.get("description", ""),
                                   dep_spec.get("icon", "🏢"))
        db.set_allowed_connectors(conn, dep["id"], dep_spec.get("connectors", []))
        for rule in dep_spec.get("rules", []):
            db.add_rule(conn, dep["id"], rule["pattern"], rule.get("note", ""))
        for agent_spec in dep_spec.get("agents", []):
            agent = db.create_agent(conn, dep["id"], agent_spec["name"],
                                    agent_spec.get("role", ""),
                                    agent_spec.get("description", ""),
                                    agent_spec.get("n8n_workflow_id"))
            if agent_spec.get("active"):
                db.update_agent(conn, agent["id"], active=1)


def effective_patterns(conn: sqlite3.Connection, dep_id: int,
                       agent_id: int | None = None) -> list[str]:
    """Allowlist = Abteilungs-/Agentenregeln ∪ implizite Hosts der Konnektoren."""
    patterns = set(db.effective_rule_patterns(conn, dep_id, agent_id))
    patterns.update(connectors.implicit_hosts(db.allowed_connectors(conn, dep_id)))
    return sorted(patterns)


def validate_workflow(conn: sqlite3.Connection, workflow: dict, dep_id: int,
                      agent_id: int | None = None) -> list[dict]:
    """Struktur- und Netzregel-Prüfung; Rückgabe strukturiert fürs UI/den Reprompt."""
    problems = [{"node": None, "host": None, "reason": e}
                for e in workflow_validate.validate_structure(workflow)]
    if not problems:
        problems = netrules.validate_against_rules(
            workflow, effective_patterns(conn, dep_id, agent_id))
    return problems


def _current_workflow_json(session: dict, conn: sqlite3.Connection) -> str | None:
    """Beim Bearbeiten eines bestehenden Agenten: dessen Workflow aus n8n holen."""
    if not session.get("agent_id"):
        return None
    agent = db.get_agent(conn, session["agent_id"])
    if not agent or not agent.get("n8n_workflow_id"):
        return None
    try:
        wf = n8n_client.get_client().get_workflow(agent["n8n_workflow_id"])
        return json.dumps({k: wf.get(k) for k in ("name", "nodes", "connections", "settings")},
                          ensure_ascii=False)
    except n8n_client.N8nError:
        return None


def chat_step(conn: sqlite3.Connection, session_id: int, text: str) -> dict:
    """Nutzernachricht verarbeiten: Claude fragen, Vorschlag validieren (mit einer
    automatischen Korrekturrunde) und die Assistant-Antwort speichern."""
    session = db.get_chat_session(conn, session_id)
    if not session:
        raise KeyError("Chat-Sitzung nicht gefunden.")
    dep = db.get_department(conn, session["department_id"])
    if not dep:
        raise KeyError("Abteilung nicht gefunden.")

    db.add_chat_message(conn, session_id, "user", text)
    history = [{"role": m["role"], "content": m["content"]}
               for m in db.list_chat_messages(conn, session_id)]

    allowed = db.allowed_connectors(conn, dep["id"])
    patterns = effective_patterns(conn, dep["id"], session.get("agent_id"))
    current_json = _current_workflow_json(session, conn)

    _set_status("working")
    try:
        proposal = claude_gen.generate(dep["name"], allowed, patterns, history, current_json)
        problems: list[dict] = []
        if proposal.workflow_json:
            problems = _check_proposal_json(conn, proposal.workflow_json, dep["id"],
                                            session.get("agent_id"))
            if problems:
                # Eine automatische Korrekturrunde mit den Fehlermeldungen.
                feedback = ("Der Workflow-Vorschlag wurde von der Validierung abgelehnt. "
                            "Bitte korrigiere ihn und gib das vollständige JSON erneut aus. "
                            "Fehler:\n" + "\n".join(f"- {p['reason']}" for p in problems))
                retry_history = history + [
                    {"role": "assistant", "content": proposal.reply},
                    {"role": "user", "content": feedback},
                ]
                retry = claude_gen.generate(dep["name"], allowed, patterns,
                                            retry_history, current_json)
                if retry.workflow_json:
                    retry_problems = _check_proposal_json(conn, retry.workflow_json, dep["id"],
                                                          session.get("agent_id"))
                    proposal, problems = retry, retry_problems
    finally:
        _set_status("idle")

    msg = db.add_chat_message(
        conn, session_id, "assistant", proposal.reply,
        proposal_json=proposal.workflow_json if proposal.workflow_json and not problems else None,
        agent_name=proposal.agent_name, agent_role=proposal.agent_role,
    )
    msg["problems"] = problems
    return msg


def _check_proposal_json(conn: sqlite3.Connection, workflow_json: str, dep_id: int,
                         agent_id: int | None) -> list[dict]:
    try:
        workflow = json.loads(workflow_json)
    except json.JSONDecodeError as exc:
        return [{"node": None, "host": None,
                 "reason": f"Workflow-JSON ist nicht parsebar: {exc}"}]
    return validate_workflow(conn, workflow, dep_id, agent_id)


def deploy_proposal(conn: sqlite3.Connection, session_id: int) -> dict:
    """Jüngsten Vorschlag der Sitzung validieren und nach n8n deployen.

    Neuer Agent (Session ohne agent_id): Workflow anlegen + Mitarbeiter in der DB
    einstellen. Bestehender Agent: Workflow aktualisieren.
    """
    session = db.get_chat_session(conn, session_id)
    if not session:
        raise KeyError("Chat-Sitzung nicht gefunden.")
    prop = db.latest_proposal(conn, session_id)
    if not prop:
        raise DeployError("Es liegt noch kein Workflow-Vorschlag zum Deployen vor.")

    workflow = json.loads(prop["proposal_json"])
    violations = validate_workflow(conn, workflow, session["department_id"],
                                   session.get("agent_id"))
    if violations:
        raise DeployError("Deployment abgelehnt.", violations)

    client = n8n_client.get_client()
    if session.get("agent_id"):
        agent = db.get_agent(conn, session["agent_id"])
        if not agent:
            raise DeployError("Agent nicht mehr vorhanden.")
        if agent.get("n8n_workflow_id"):
            client.update_workflow(agent["n8n_workflow_id"], workflow)
        else:
            created = client.create_workflow(workflow)
            db.update_agent(conn, agent["id"], n8n_workflow_id=str(created.get("id")))
        return db.get_agent(conn, agent["id"])  # type: ignore[return-value]

    created = client.create_workflow(workflow)
    return db.create_agent(
        conn, session["department_id"],
        name=prop.get("agent_name") or workflow.get("name", "Neuer Mitarbeiter"),
        role=prop.get("agent_role") or "",
        description="",
        n8n_workflow_id=str(created.get("id")),
    )


def agent_with_status(conn: sqlite3.Connection, agent: dict, limit: int = 10) -> dict:
    """Agent um n8n-Laufdaten anreichern (letzte Executions, letzter Status)."""
    out = dict(agent)
    out["executions"] = []
    out["last_status"] = None
    if agent.get("n8n_workflow_id"):
        try:
            runs = n8n_client.get_client().executions(agent["n8n_workflow_id"], limit=limit)
            out["executions"] = runs
            if runs:
                out["last_status"] = runs[0].get("status")
        except n8n_client.N8nError:
            out["last_status"] = "unbekannt"
    return out

"""AI-Systems — FastAPI-App: eine HTML-Route (deutsche SPA) plus JSON-API.

Kein Benutzer-Login (Betrieb im internen Netz); die Zugriffssteuerung liegt in
den Netzwerkregeln der Agenten (siehe netrules.py). Fehler kommen durchgängig
als {"error": "<deutsche Meldung>"}; Netzregel-Verstöße als 422 mit
strukturierter violations-Liste.
"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import config, connectors, db, n8n_client, render_ui, service

app = FastAPI(title="AI-Systems", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    service.seed_demo(db.get_conn())


@app.exception_handler(service.DeployError)
def _deploy_error(_req: Request, exc: service.DeployError):
    return JSONResponse(status_code=422,
                        content={"error": str(exc), "violations": exc.violations})


@app.exception_handler(n8n_client.N8nError)
def _n8n_error(_req: Request, exc: n8n_client.N8nError):
    return JSONResponse(status_code=502, content={"error": str(exc)})


@app.exception_handler(KeyError)
def _key_error(_req: Request, exc: KeyError):
    return JSONResponse(status_code=404, content={"error": str(exc.args[0]) if exc.args else "Nicht gefunden."})


@app.exception_handler(Exception)
def _unhandled_error(_req: Request, exc: Exception):
    """Letzte Absicherung: jeder unerwartete Fehler kommt als JSON zurück (nie als
    Klartext-„Internal Server Error"), damit die Oberfläche eine lesbare Meldung
    zeigen kann statt eines JSON-Parserfehlers."""
    import sys
    sys.stderr.write(f"[ai-systems] Unerwarteter Fehler: {type(exc).__name__}: {exc}\n")
    return JSONResponse(status_code=500,
                        content={"error": f"Unerwarteter Serverfehler: {type(exc).__name__}. "
                                          "Details im Server-Protokoll (Datei-Menü)."})


def _json_body(payload, *keys, required=()):
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON-Objekt erwartet.")
    for key in required:
        value = payload.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise HTTPException(400, f"Feld '{key}' fehlt.")
    return {k: payload.get(k) for k in keys}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return render_ui.render()


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(render_ui.logo_svg(32), media_type="image/svg+xml")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "demo_mode": config.is_demo_mode(), "version": config.VERSION}


@app.get("/api/status")
def api_status() -> dict:
    return {**service.status(), "demo_mode": config.is_demo_mode(), "version": config.VERSION}


# --- Abteilungen -----------------------------------------------------------

@app.get("/api/departments")
def list_departments() -> list:
    return db.list_departments(db.get_conn())


@app.post("/api/departments")
async def create_department(request: Request):
    data = _json_body(await request.json(), "name", "description", "icon", required=("name",))
    conn = db.get_conn()
    if any(d["name"] == data["name"].strip() for d in db.list_departments(conn)):
        raise HTTPException(409, "Eine Abteilung mit diesem Namen existiert bereits.")
    return db.create_department(conn, data["name"], data["description"] or "",
                                data["icon"] or "🏢")


@app.patch("/api/departments/{dep_id}")
async def update_department(dep_id: int, request: Request):
    data = _json_body(await request.json(), "name", "description", "icon")
    dep = db.update_department(db.get_conn(), dep_id, **data)
    if not dep:
        raise HTTPException(404, "Abteilung nicht gefunden.")
    return dep


@app.delete("/api/departments/{dep_id}")
def delete_department(dep_id: int) -> dict:
    conn = db.get_conn()
    if not db.get_department(conn, dep_id):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    # Deployte Workflows der Abteilung in n8n mitlöschen (best effort).
    client = n8n_client.get_client()
    for agent in db.list_agents(conn, dep_id):
        if agent.get("n8n_workflow_id"):
            try:
                client.delete_workflow(agent["n8n_workflow_id"])
            except n8n_client.N8nError:
                pass
    db.delete_department(conn, dep_id)
    return {"ok": True}


@app.get("/api/departments/{dep_id}/connectors")
def department_connectors(dep_id: int) -> list:
    conn = db.get_conn()
    if not db.get_department(conn, dep_id):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    return connectors.catalog(db.allowed_connectors(conn, dep_id))


@app.put("/api/departments/{dep_id}/connectors")
async def set_department_connectors(dep_id: int, request: Request):
    data = _json_body(await request.json(), "keys", required=("keys",))
    keys = data["keys"]
    if not isinstance(keys, list):
        raise HTTPException(400, "Feld 'keys' muss eine Liste sein.")
    unknown = [k for k in keys if k not in connectors.CONNECTORS]
    if unknown:
        raise HTTPException(400, f"Unbekannte Konnektoren: {', '.join(unknown)}.")
    conn = db.get_conn()
    if not db.get_department(conn, dep_id):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    db.set_allowed_connectors(conn, dep_id, keys)
    return connectors.catalog(db.allowed_connectors(conn, dep_id))


@app.get("/api/departments/{dep_id}/rules")
def department_rules(dep_id: int) -> dict:
    conn = db.get_conn()
    if not db.get_department(conn, dep_id):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    return {"rules": db.list_rules(conn, dep_id),
            "implicit_hosts": connectors.implicit_hosts(db.allowed_connectors(conn, dep_id))}


@app.post("/api/departments/{dep_id}/rules")
async def add_department_rule(dep_id: int, request: Request):
    data = _json_body(await request.json(), "pattern", "note", "agent_id", required=("pattern",))
    conn = db.get_conn()
    if not db.get_department(conn, dep_id):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    return db.add_rule(conn, dep_id, data["pattern"], data["note"] or "", data["agent_id"])


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int) -> dict:
    db.delete_rule(db.get_conn(), rule_id)
    return {"ok": True}


# --- Agenten ---------------------------------------------------------------

@app.get("/api/agents")
def list_agents(department_id: int | None = None) -> list:
    conn = db.get_conn()
    return [service.agent_with_status(conn, a, limit=1)
            for a in db.list_agents(conn, department_id)]


@app.get("/api/agents/{agent_id}")
def get_agent(agent_id: int) -> dict:
    conn = db.get_conn()
    agent = db.get_agent(conn, agent_id)
    if not agent:
        raise HTTPException(404, "Agent nicht gefunden.")
    return service.agent_with_status(conn, agent, limit=10)


@app.patch("/api/agents/{agent_id}")
async def update_agent(agent_id: int, request: Request):
    data = _json_body(await request.json(), "name", "role", "description")
    conn = db.get_conn()
    agent = db.get_agent(conn, agent_id)
    if not agent:
        raise HTTPException(404, "Agent nicht gefunden.")
    agent = db.update_agent(conn, agent_id, **data)
    if data.get("name") and agent.get("n8n_workflow_id"):
        n8n_client.get_client().rename_workflow(agent["n8n_workflow_id"], data["name"])
    return agent


@app.post("/api/agents/{agent_id}/activate")
def activate_agent(agent_id: int) -> dict:
    return _toggle_agent(agent_id, active=True)


@app.post("/api/agents/{agent_id}/deactivate")
def deactivate_agent(agent_id: int) -> dict:
    return _toggle_agent(agent_id, active=False)


def _toggle_agent(agent_id: int, active: bool) -> dict:
    conn = db.get_conn()
    agent = db.get_agent(conn, agent_id)
    if not agent:
        raise HTTPException(404, "Agent nicht gefunden.")
    if not agent.get("n8n_workflow_id"):
        raise HTTPException(409, "Agent ist noch nicht deployt (kein n8n-Workflow).")
    client = n8n_client.get_client()
    if active:
        client.activate(agent["n8n_workflow_id"])
    else:
        client.deactivate(agent["n8n_workflow_id"])
    return db.update_agent(conn, agent_id, active=1 if active else 0)


@app.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: int) -> dict:
    conn = db.get_conn()
    agent = db.get_agent(conn, agent_id)
    if not agent:
        raise HTTPException(404, "Agent nicht gefunden.")
    if agent.get("n8n_workflow_id"):
        try:
            n8n_client.get_client().delete_workflow(agent["n8n_workflow_id"])
        except n8n_client.N8nError:
            pass  # n8n kennt den Workflow nicht mehr — DB trotzdem aufräumen
    db.delete_agent(conn, agent_id)
    return {"ok": True}


@app.get("/api/agents/{agent_id}/executions")
def agent_executions(agent_id: int) -> list:
    conn = db.get_conn()
    agent = db.get_agent(conn, agent_id)
    if not agent:
        raise HTTPException(404, "Agent nicht gefunden.")
    if not agent.get("n8n_workflow_id"):
        return []
    return n8n_client.get_client().executions(agent["n8n_workflow_id"], limit=20)


# --- Chat („Agent bauen/bearbeiten") ----------------------------------------

@app.post("/api/chat/sessions")
async def create_chat_session(request: Request):
    data = _json_body(await request.json(), "department_id", "agent_id",
                      required=("department_id",))
    conn = db.get_conn()
    if not db.get_department(conn, data["department_id"]):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    if data.get("agent_id"):
        if not db.get_agent(conn, data["agent_id"]):
            raise HTTPException(404, "Agent nicht gefunden.")
        # Agenten-Chats sind fortlaufend: vorhandene Sitzung samt Verlauf
        # weiterführen — der Kontext des Mitarbeiters wächst mit.
        existing = db.latest_session_for_agent(conn, data["agent_id"])
        if existing:
            return {**existing, "messages": db.list_chat_messages(conn, existing["id"])}
    session = db.create_chat_session(conn, data["department_id"], data.get("agent_id"))
    return {**session, "messages": []}


@app.get("/api/chat/sessions/{session_id}")
def get_chat_session(session_id: int) -> dict:
    conn = db.get_conn()
    session = db.get_chat_session(conn, session_id)
    if not session:
        raise HTTPException(404, "Chat-Sitzung nicht gefunden.")
    return {**session, "messages": db.list_chat_messages(conn, session_id)}


@app.post("/api/chat/sessions/{session_id}/message")
async def post_chat_message(session_id: int, request: Request):
    data = _json_body(await request.json(), "text", required=("text",))
    msg = service.chat_step(db.get_conn(), session_id, data["text"])
    proposal = None
    if msg.get("proposal_json"):
        proposal = {"agent_name": msg.get("agent_name"), "agent_role": msg.get("agent_role"),
                    "workflow": json.loads(msg["proposal_json"])}
    return {"reply": msg["content"], "proposal": proposal, "problems": msg.get("problems", [])}


@app.post("/api/chat/sessions/{session_id}/deploy")
def deploy_chat_proposal(session_id: int) -> dict:
    return {"agent": service.deploy_proposal(db.get_conn(), session_id)}


# --- n8n-Workflows übernehmen -------------------------------------------------

@app.get("/api/n8n/workflows")
def n8n_unassigned_workflows() -> list:
    """Noch keinem Mitarbeiter zugeordnete n8n-Workflows (Import-Kandidaten)."""
    return service.unassigned_workflows(db.get_conn())


@app.post("/api/agents/import")
async def import_agent(request: Request):
    data = _json_body(await request.json(), "department_id", "n8n_workflow_id",
                      "name", "role", required=("department_id", "n8n_workflow_id", "name"))
    conn = db.get_conn()
    if not db.get_department(conn, data["department_id"]):
        raise HTTPException(404, "Abteilung nicht gefunden.")
    return service.import_workflow(conn, data["department_id"],
                                   str(data["n8n_workflow_id"]),
                                   data["name"].strip(), (data["role"] or "").strip())


# --- Einstellungen (Claude-Modell) -------------------------------------------

# Vorschläge fürs Modell-Feld; freie Eingabe bleibt möglich (Verfügbarkeit
# hängt vom jeweiligen Anthropic-API-Key ab).
MODEL_SUGGESTIONS = [
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
]


@app.get("/api/settings")
def get_settings() -> dict:
    conn = db.get_conn()
    override = db.get_setting(conn, "model")
    return {
        "model": service.active_model(conn),
        "model_override": override,
        "default_model": config.model(),
        "suggestions": MODEL_SUGGESTIONS,
        "demo_mode": config.is_demo_mode(),
    }


@app.put("/api/settings")
async def update_settings(request: Request):
    data = _json_body(await request.json(), "model")
    model = (data.get("model") or "").strip()
    db.set_setting(db.get_conn(), "model", model or None)  # leer = auf Standard zurück
    return get_settings()


@app.post("/api/claude/test")
def claude_test() -> dict:
    """Verbindungstest zu Claude mit dem aktiven Modell (für die Diagnose im UI)."""
    from . import claude_gen
    return claude_gen.test_connection(service.active_model(db.get_conn()))


@app.get("/api/diagnostics")
def diagnostics() -> dict:
    """Sammel-Diagnose aller Schnittstellen — ohne Secret-Werte. Nützlich für IT:
    n8n erreichbar? Claude-Key/-Modell ok? welche Konnektoren sind konfiguriert?"""
    from . import claude_gen
    conn = db.get_conn()
    return {
        "version": config.VERSION,
        "demo_mode": config.is_demo_mode(),
        "model": service.active_model(conn),
        "n8n": service.n8n_status(),
        "claude": claude_gen.test_connection(service.active_model(conn)),
        "connectors": [{"key": c["key"], "label": c["label"], "configured": c["configured"]}
                       for c in connectors.catalog()],
    }


# --- Konnektoren-Katalog -----------------------------------------------------

@app.get("/api/connectors")
def connector_catalog() -> list:
    return connectors.catalog()

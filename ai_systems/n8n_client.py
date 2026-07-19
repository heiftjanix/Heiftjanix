"""n8n-REST-Client (Public API v1) plus DemoN8n für den Betrieb ohne Instanz.

Beim Anlegen/Aktualisieren werden bewusst nur die Felder name/nodes/connections/
settings gesendet — die n8n-Public-API lehnt read-only-Felder (z. B. `active`)
ab; aktiv/inaktiv läuft ausschließlich über die activate/deactivate-Endpoints.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import requests

from . import config

_WRITABLE_FIELDS = ("name", "nodes", "connections", "settings")
_TIMEOUT = 30


class N8nError(RuntimeError):
    """Fehler der n8n-API mit deutscher Meldung und HTTP-Status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _writable(workflow: dict) -> dict:
    payload = {k: workflow[k] for k in _WRITABLE_FIELDS if k in workflow}
    payload.setdefault("settings", {})
    return payload


class N8nClient:
    """Dünner Client für {N8N_URL}/api/v1 mit X-N8N-API-KEY-Auth."""

    def __init__(self, base_url: str, api_key: str, session: requests.Session | None = None):
        self.base = base_url.rstrip("/") + "/api/v1"
        self.session = session or requests.Session()
        self.session.headers.update({"X-N8N-API-KEY": api_key, "Accept": "application/json"})

    def _request(self, method: str, path: str, **kwargs):
        try:
            resp = self.session.request(method, self.base + path, timeout=_TIMEOUT, **kwargs)
        except requests.RequestException as exc:
            raise N8nError(f"n8n nicht erreichbar: {exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("message", "")
            except Exception:
                detail = resp.text[:200]
            raise N8nError(
                f"n8n-API-Fehler {resp.status_code} bei {method} {path}: {detail}",
                status=resp.status_code,
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def list_workflows(self) -> list[dict]:
        items, cursor = [], None
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", "/workflows", params=params)
            items.extend(data.get("data", []))
            cursor = data.get("nextCursor")
            if not cursor:
                return items

    def get_workflow(self, workflow_id: str) -> dict:
        return self._request("GET", f"/workflows/{workflow_id}")

    def create_workflow(self, workflow: dict) -> dict:
        return self._request("POST", "/workflows", json=_writable(workflow))

    def update_workflow(self, workflow_id: str, workflow: dict) -> dict:
        return self._request("PUT", f"/workflows/{workflow_id}", json=_writable(workflow))

    def rename_workflow(self, workflow_id: str, name: str) -> dict:
        current = self.get_workflow(workflow_id)
        current["name"] = name
        return self.update_workflow(workflow_id, current)

    def activate(self, workflow_id: str) -> dict:
        return self._request("POST", f"/workflows/{workflow_id}/activate")

    def deactivate(self, workflow_id: str) -> dict:
        return self._request("POST", f"/workflows/{workflow_id}/deactivate")

    def delete_workflow(self, workflow_id: str) -> None:
        self._request("DELETE", f"/workflows/{workflow_id}")

    def executions(self, workflow_id: str, limit: int = 20) -> list[dict]:
        data = self._request("GET", "/executions",
                             params={"workflowId": workflow_id, "limit": limit})
        return data.get("data", [])

    def get_execution(self, execution_id: str) -> dict:
        """Einzelne Ausführung inkl. Daten — für Fehlerdetails im Agenten-Feedback."""
        return self._request("GET", f"/executions/{execution_id}",
                             params={"includeData": "true"})


class DemoN8n:
    """In-Memory-n8n mit identischer Schnittstelle, gespeist aus demo_data.json.

    Änderungen (anlegen/aktivieren/löschen) wirken für die Laufzeit des
    Prozesses, damit sich das Demo wie eine echte Instanz anfühlt.
    """

    def __init__(self):
        data = json.loads((Path(__file__).parent / "demo_data.json").read_text(encoding="utf-8"))
        self._executions: dict[str, list[dict]] = copy.deepcopy(data.get("executions", {}))
        self._workflows: dict[str, dict] = {}
        self._counter = 0
        for dep in data.get("departments", []):
            for agent in dep.get("agents", []):
                wf_id = agent.get("n8n_workflow_id")
                if wf_id:
                    self._workflows[wf_id] = {
                        "id": wf_id, "name": agent["name"], "active": bool(agent.get("active")),
                        "nodes": [], "connections": {}, "settings": {},
                    }
        # Unverwaltete Demo-Workflows (für „Mitarbeiter übernehmen")
        for wf in data.get("extra_workflows", []):
            self._workflows[wf["id"]] = {
                "id": wf["id"], "name": wf["name"], "active": bool(wf.get("active")),
                "nodes": wf.get("nodes", []), "connections": wf.get("connections", {}),
                "settings": {},
            }

    def list_workflows(self) -> list[dict]:
        return [copy.deepcopy(wf) for wf in self._workflows.values()]

    def get_workflow(self, workflow_id: str) -> dict:
        if workflow_id not in self._workflows:
            raise N8nError(f"Workflow '{workflow_id}' nicht gefunden.", status=404)
        return copy.deepcopy(self._workflows[workflow_id])

    def create_workflow(self, workflow: dict) -> dict:
        self._counter += 1
        wf_id = f"demo-wf-neu-{self._counter}"
        stored = _writable(workflow)
        stored.update({"id": wf_id, "active": False})
        self._workflows[wf_id] = stored
        self._executions.setdefault(wf_id, [])
        return copy.deepcopy(stored)

    def update_workflow(self, workflow_id: str, workflow: dict) -> dict:
        existing = self.get_workflow(workflow_id)
        existing.update(_writable(workflow))
        self._workflows[workflow_id] = existing
        return copy.deepcopy(existing)

    def rename_workflow(self, workflow_id: str, name: str) -> dict:
        wf = self.get_workflow(workflow_id)
        wf["name"] = name
        self._workflows[workflow_id] = wf
        return copy.deepcopy(wf)

    def activate(self, workflow_id: str) -> dict:
        self.get_workflow(workflow_id)
        self._workflows[workflow_id]["active"] = True
        return self.get_workflow(workflow_id)

    def deactivate(self, workflow_id: str) -> dict:
        self.get_workflow(workflow_id)
        self._workflows[workflow_id]["active"] = False
        return self.get_workflow(workflow_id)

    def delete_workflow(self, workflow_id: str) -> None:
        self.get_workflow(workflow_id)
        del self._workflows[workflow_id]

    def executions(self, workflow_id: str, limit: int = 20) -> list[dict]:
        return copy.deepcopy(self._executions.get(workflow_id, [])[:limit])

    def get_execution(self, execution_id: str) -> dict:
        for runs in self._executions.values():
            for run in runs:
                if run.get("id") == execution_id:
                    return copy.deepcopy(run)
        raise N8nError(f"Ausführung '{execution_id}' nicht gefunden.", status=404)


_DEMO: DemoN8n | None = None


def get_client():
    """DemoN8n im DEMO_MODE (prozessweit eine Instanz), sonst echter Client."""
    global _DEMO
    if config.is_demo_mode():
        if _DEMO is None:
            _DEMO = DemoN8n()
        return _DEMO
    return N8nClient(config.n8n_url(), config.n8n_api_key())


def reset_demo() -> None:
    """Nur für Tests: Demo-Instanz zurücksetzen."""
    global _DEMO
    _DEMO = None

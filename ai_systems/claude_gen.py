"""Claude-Anbindung für „Agent bauen/bearbeiten": ruft die Anthropic Messages API
mit strukturierter Ausgabe auf (Muster wie webapp/triage.py).

Ohne ANTHROPIC_API_KEY oder im DEMO_MODE liefert ein gecanntes Szenario aus
demo_data.json deterministische Antworten (Rückfrage, dann kompletter
Beispiel-Workflow), damit die App ohne Zugangsdaten vorführbar bleibt.
Fable-5-Besonderheiten: kein thinking-Parameter, keine temperature, kein
Prefill; stop_reason == "refusal" wird abgefangen und deutsch gemeldet.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from pydantic import BaseModel

from . import config, prompts

MAX_TOKENS = 16000
# Fortlaufende Agenten-Chats wachsen unbegrenzt — an die API gehen nur die
# jüngsten Nachrichten (das aktuelle Workflow-JSON steckt ohnehin im System-
# Kontext, ältere Chat-Runden sind dadurch verzichtbar).
MAX_HISTORY_MESSAGES = 24
REFUSAL_REPLY = ("Diese Anfrage wurde aus Sicherheitsgründen abgelehnt. "
                 "Bitte formuliere um, was der Agent tun soll.")


class AgentProposal(BaseModel):
    reply: str
    agent_name: str | None = None
    agent_role: str | None = None
    workflow_json: str | None = None


def _canned() -> dict:
    return json.loads(
        (Path(__file__).parent / "demo_data.json").read_text(encoding="utf-8")
    )["canned_chat"]


def _demo_generate(history: list[dict]) -> AgentProposal:
    """Deterministisch: erste Nutzernachricht -> Rückfrage, danach Vorschlag."""
    canned = _canned()
    user_turns = sum(1 for m in history if m["role"] == "user")
    if user_turns <= 1:
        return AgentProposal(reply=canned["question"])
    prop = canned["proposal"]
    return AgentProposal(
        reply=prop["reply"],
        agent_name=prop["agent_name"],
        agent_role=prop["agent_role"],
        workflow_json=json.dumps(prop["workflow"], ensure_ascii=False),
    )


def _use_llm() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and not config.is_demo_mode()


def _api_message(exc: Exception) -> str:
    """Extrahiert die eigentliche Fehlermeldung aus einer Anthropic-Exception."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(exc)


def friendly_error(exc: Exception, model: str) -> str:
    """Übersetzt einen Claude-API-Fehler in eine verständliche deutsche Meldung —
    inklusive der echten API-Meldung, damit die Ursache erkennbar bleibt."""
    status = getattr(exc, "status_code", None)
    detail = _api_message(exc)
    low = detail.lower()

    if "credit balance" in low or "insufficient" in low or "billing" in low:
        return ("Claude meldet für DIESEN API-Key „zu geringes Guthaben“. Wenn dein "
                "Konto Guthaben hat (aber es trotzdem nicht klappt), gehört der Key "
                "meist zu einer ANDEREN Organisation oder einem Workspace ohne Budget. "
                "Bitte im Anthropic-Console oben links die Organisation prüfen, in der "
                "das Guthaben liegt, und dort einen neuen API-Key erzeugen — diesen dann "
                "unter „Datei → Server-Konfiguration (.env)“ eintragen. "
                f"(Originalmeldung von Claude: {detail[:160]})")
    if status == 401 or "authentication" in low or "x-api-key" in low or "invalid api key" in low:
        return ("Der Claude-API-Key ist ungültig. Bitte in der Server-Konfiguration "
                "(Datei → Server-Konfiguration (.env) öffnen) den ANTHROPIC_API_KEY prüfen.")
    if status == 404 or ("model" in low and ("not found" in low or "not_found" in low
                                             or "does not exist" in low or "unknown" in low)):
        return (f"Das eingestellte Claude-Modell „{model}“ ist für deinen API-Key nicht "
                f"verfügbar. Bitte AI_SYSTEMS_MODEL in der Server-Konfiguration auf ein "
                f"freigeschaltetes Modell setzen. (Claude meldet: {detail[:200]})")
    if status == 429 or "rate limit" in low:
        return "Zu viele Anfragen an Claude in kurzer Zeit. Bitte kurz warten und erneut senden."
    if status == 529 or "overloaded" in low:
        return "Claude ist momentan überlastet. Bitte in ein bis zwei Minuten erneut versuchen."
    if "max_tokens" in low:
        return f"Anfrage-Parameter ungültig ({detail[:200]}). Bitte den Support kontaktieren."
    if "connection" in low or "timeout" in low or "connect" in low:
        return ("Keine Verbindung zu Claude (Netzwerk oder Firewall). Bitte die "
                "Internetverbindung prüfen und erneut versuchen.")
    return f"Die Claude-Anfrage ist fehlgeschlagen: {detail[:250]}"


def test_connection(model: str) -> dict:
    """Minimaler echter Claude-Aufruf zur Diagnose. Liefert {ok, model, message}
    und bei Fehlern zusätzlich die rohe API-Meldung (raw)."""
    if config.is_demo_mode():
        return {"ok": False, "model": model,
                "message": "Demo-Modus aktiv (kein echter Claude-Aufruf). "
                           "Für den Test N8N_URL/ANTHROPIC_API_KEY in der "
                           "Server-Konfiguration setzen."}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"ok": False, "model": model,
                "message": "Kein ANTHROPIC_API_KEY gesetzt (Datei → Server-Konfiguration)."}
    import anthropic
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=model, max_tokens=8,
            messages=[{"role": "user", "content": "Antworte nur mit dem Wort: OK"}],
        )
        text = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return {"ok": True, "model": model,
                "message": f"Verbindung ok — Claude ({model}) antwortet: {text or 'OK'}"}
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[ai-systems] Verbindungstest fehlgeschlagen: "
                         f"{type(exc).__name__}: {exc}\n")
        return {"ok": False, "model": model,
                "message": friendly_error(exc, model), "raw": _api_message(exc)}


def generate(dep_name: str, allowed_keys: list[str], host_patterns: list[str],
             history: list[dict], current_workflow_json: str | None = None,
             runs_summary: str | None = None, model: str | None = None) -> AgentProposal:
    """history: [{role: 'user'|'assistant', content: str}, ...] — letzter Eintrag
    ist die aktuelle Nutzernachricht. `model` überschreibt das Standardmodell."""
    if not _use_llm():
        return _demo_generate(history)

    import anthropic

    active_model = model or config.model()
    recent = history[-MAX_HISTORY_MESSAGES:]
    # Die Messages API verlangt einen user-Turn am Anfang.
    while recent and recent[0]["role"] != "user":
        recent = recent[1:]

    try:
        client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=active_model,
            max_tokens=MAX_TOKENS,
            system=prompts.system_blocks(dep_name, allowed_keys, host_patterns,
                                         current_workflow_json, runs_summary),
            messages=[{"role": m["role"], "content": m["content"]} for m in recent],
            output_format=AgentProposal,
        )
        if getattr(resp, "stop_reason", None) == "refusal":
            return AgentProposal(reply=REFUSAL_REPLY)
        return resp.parsed_output
    except Exception as exc:  # noqa: BLE001 — API-Störung sauber im Chat melden
        sys.stderr.write(f"[ai-systems] Anthropic-API fehlgeschlagen: "
                         f"{type(exc).__name__}: {exc}\n")
        return AgentProposal(reply=friendly_error(exc, active_model))

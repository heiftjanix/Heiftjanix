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


def generate(dep_name: str, allowed_keys: list[str], host_patterns: list[str],
             history: list[dict], current_workflow_json: str | None = None,
             runs_summary: str | None = None) -> AgentProposal:
    """history: [{role: 'user'|'assistant', content: str}, ...] — letzter Eintrag
    ist die aktuelle Nutzernachricht."""
    if not _use_llm():
        return _demo_generate(history)

    import anthropic

    recent = history[-MAX_HISTORY_MESSAGES:]
    # Die Messages API verlangt einen user-Turn am Anfang.
    while recent and recent[0]["role"] != "user":
        recent = recent[1:]

    try:
        client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=config.model(),
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
        sys.stderr.write(f"[ai-systems] Anthropic-API fehlgeschlagen: {exc}\n")
        return AgentProposal(
            reply=("Die Claude-Anfrage ist fehlgeschlagen "
                   f"({type(exc).__name__}). Bitte später erneut versuchen.")
        )

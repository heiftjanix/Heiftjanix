"""Zentrale Konfiguration für AI-Systems — alles kommt aus Umgebungsvariablen.

DEMO_MODE ist automatisch aktiv, wenn keine n8n-Instanz konfiguriert ist
(N8N_URL fehlt) oder DEMO_MODE=1 gesetzt wurde — die App bleibt damit ohne
jegliche Zugangsdaten lauffähig (Demo-Firma, gecannte Claude-Antworten).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODEL = "claude-fable-5"
DEFAULT_PORT = 8010


def n8n_url() -> str:
    return os.environ.get("N8N_URL", "").strip().rstrip("/")


def n8n_api_key() -> str:
    return os.environ.get("N8N_API_KEY", "").strip()


def anthropic_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def model() -> str:
    return os.environ.get("AI_SYSTEMS_MODEL", "").strip() or DEFAULT_MODEL


def db_path() -> str:
    return os.environ.get("AI_SYSTEMS_DB", "").strip() or str(ROOT / "state" / "ai_systems.db")


def is_demo_mode() -> bool:
    """DEMO_MODE=1 erzwingt Demo; ohne N8N_URL fällt die App ebenfalls auf Demo zurück."""
    flag = os.environ.get("DEMO_MODE", "").strip()
    if flag in ("1", "true", "True"):
        return True
    return not n8n_url()

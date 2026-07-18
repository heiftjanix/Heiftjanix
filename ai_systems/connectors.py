"""Fester Konnektoren-Katalog der Firma: ERPNext, Microsoft 365/Outlook, GitHub,
UPS und die Anthropic-API selbst — bewusst KEIN generischer Katalog.

Pro Konnektor: deutsches Label, benötigte Umgebungsvariablen (Secrets bleiben
in ENV, nie in der Datenbank oder im Workflow-JSON), implizit erlaubte Hosts
für die Netzwerkregeln und ein Prompt-Snippet, das Claude erklärt, wie der
Konnektor in n8n verdrahtet wird (Zugangsdaten stets als n8n-Expression
``{{$env.NAME}}`` — die Variablen müssen auf der n8n-Instanz gesetzt sein).
"""
from __future__ import annotations

import os
from urllib.parse import urlparse


def _host_of(url: str) -> str | None:
    host = urlparse(url).hostname if url else None
    return host.lower() if host else None


def _erpnext_hosts() -> list[str]:
    host = _host_of(os.environ.get("ERPNEXT_URL", ""))
    return [host] if host else []


CONNECTORS: dict[str, dict] = {
    "erpnext": {
        "label": "ERPNext",
        "env": ["ERPNEXT_URL", "ERPNEXT_API_KEY", "ERPNEXT_API_SECRET"],
        "hosts": _erpnext_hosts,
        "snippet": (
            "ERPNext: REST-Aufrufe per n8n-nodes-base.httpRequest an {{$env.ERPNEXT_URL}}"
            "/api/resource/<DocType>. Authentifizierung über den Header "
            "'Authorization: token {{$env.ERPNEXT_API_KEY}}:{{$env.ERPNEXT_API_SECRET}}'. "
            "Filter als URL-Parameter filters=[[...]], Felder als fields=[...]."
        ),
    },
    "m365": {
        "label": "Microsoft 365 / Outlook",
        "env": ["AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_TENANT_ID"],
        "hosts": ["graph.microsoft.com", "login.microsoftonline.com"],
        "snippet": (
            "Microsoft 365: zuerst ein n8n-nodes-base.httpRequest (POST) an "
            "https://login.microsoftonline.com/{{$env.AZURE_TENANT_ID}}/oauth2/v2.0/token "
            "mit grant_type=client_credentials, client_id={{$env.AZURE_CLIENT_ID}}, "
            "client_secret={{$env.AZURE_CLIENT_SECRET}}, scope=https://graph.microsoft.com/.default "
            "(Content-Type application/x-www-form-urlencoded). Danach Graph-Aufrufe an "
            "https://graph.microsoft.com/v1.0/... mit Header "
            "'Authorization: Bearer {{$json.access_token}}'."
        ),
    },
    "github": {
        "label": "GitHub",
        "env": ["GITHUB_TOKEN"],
        "hosts": ["api.github.com"],
        "snippet": (
            "GitHub: n8n-nodes-base.httpRequest an https://api.github.com/... mit den Headern "
            "'Authorization: Bearer {{$env.GITHUB_TOKEN}}', 'Accept: application/vnd.github+json' "
            "und 'User-Agent: ai-systems'."
        ),
    },
    "ups": {
        "label": "UPS",
        "env": ["UPS_CLIENT_ID", "UPS_CLIENT_SECRET"],
        "hosts": ["onlinetools.ups.com", "wwwcie.ups.com"],
        "snippet": (
            "UPS: zuerst ein n8n-nodes-base.httpRequest (POST) an "
            "https://onlinetools.ups.com/security/v1/oauth/token mit Basic-Auth aus "
            "{{$env.UPS_CLIENT_ID}}/{{$env.UPS_CLIENT_SECRET}} und grant_type=client_credentials; "
            "danach Tracking-Aufrufe an https://onlinetools.ups.com/api/track/v1/details/<nr> "
            "mit 'Authorization: Bearer {{$json.access_token}}' und Header 'transId'/'transactionSrc'."
        ),
    },
    "anthropic": {
        "label": "Anthropic API (Claude)",
        "env": ["ANTHROPIC_API_KEY"],
        "hosts": ["api.anthropic.com"],
        "snippet": (
            "Anthropic: n8n-nodes-base.httpRequest (POST) an https://api.anthropic.com/v1/messages "
            "mit den Headern 'x-api-key: {{$env.ANTHROPIC_API_KEY}}', "
            "'anthropic-version: 2023-06-01' und 'content-type: application/json'; Body mit "
            "model, max_tokens und messages. Für Textaufgaben innerhalb des Workflows."
        ),
    },
}


def connector_hosts(key: str) -> list[str]:
    """Implizit erlaubte Hosts eines Konnektors (leer, wenn unkonfiguriert)."""
    spec = CONNECTORS.get(key)
    if not spec:
        return []
    hosts = spec["hosts"]
    return list(hosts() if callable(hosts) else hosts)


def implicit_hosts(keys: list[str]) -> list[str]:
    """Vereinigte Hosts aller freigegebenen Konnektoren einer Abteilung."""
    out: set[str] = set()
    for key in keys:
        out.update(connector_hosts(key))
    return sorted(out)


def is_configured(key: str) -> bool:
    spec = CONNECTORS.get(key)
    if not spec:
        return False
    return all(os.environ.get(var, "").strip() for var in spec["env"])


def catalog(allowed: list[str] | None = None) -> list[dict]:
    """Katalog fürs UI — nur Status, niemals Secret-Werte."""
    out = []
    for key, spec in CONNECTORS.items():
        out.append({
            "key": key,
            "label": spec["label"],
            "env": spec["env"],
            "configured": is_configured(key),
            "hosts": connector_hosts(key),
            "allowed": (key in allowed) if allowed is not None else None,
        })
    return out


def snippets(keys: list[str]) -> list[str]:
    """Prompt-Snippets der freigegebenen Konnektoren (für den Generator)."""
    return [CONNECTORS[k]["snippet"] for k in keys if k in CONNECTORS]


def forbidden_labels(keys: list[str]) -> list[str]:
    """Labels der NICHT freigegebenen Konnektoren (explizite Verbotsliste im Prompt)."""
    return [spec["label"] for key, spec in CONNECTORS.items() if key not in keys]

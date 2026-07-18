"""Netzwerk-Zugriffsregeln: Host-Allowlist pro Abteilung/Agent und deren
Durchsetzung beim Deployment (Deploy-Time-Validierung).

Aus dem Workflow-JSON werden alle erreichbaren Hosts extrahiert — auch aus
n8n-Expressions, solange der Host-Teil ein statisches Literal ist. Ist ein
Ziel-Host nicht statisch prüfbar (z. B. ``={{ $json.url }}``), wird das
Deployment konservativ abgelehnt. Eine Laufzeit-Durchsetzung (Egress-Proxy)
ist bewusst außerhalb des Umfangs — siehe README.
"""
from __future__ import annotations

import re

# Authority-Teil nach http(s):// bis zum ersten Trennzeichen.
_URL_RE = re.compile(r"https?://([^/\s\"'`<>()]+)", re.IGNORECASE)
# Schlüssel in Node-Parametern, die typischerweise eine URL/einen Host tragen.
_URL_KEYS = {"url", "baseurl", "endpoint", "requesturl", "host", "hostname"}
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


def normalize_host(hostport: str) -> str:
    """Kleinschreibung, Userinfo und Port entfernen."""
    host = hostport.strip().lower()
    if "@" in host:  # https://gut.de@boese.de/ -> tatsächlicher Host ist boese.de
        host = host.rsplit("@", 1)[1]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host


def host_matches(host: str, pattern: str) -> bool:
    """'*.example.com' matcht alle Subdomains (nicht example.com selbst),
    alles andere matcht exakt. Ports werden beidseitig ignoriert."""
    host = normalize_host(host)
    pattern = normalize_host(pattern)
    if not host or not pattern:
        return False
    if pattern.startswith("*."):
        return host.endswith(pattern[1:]) and len(host) > len(pattern[1:])
    return host == pattern


def _is_static_host(hostport: str) -> bool:
    return not any(ch in hostport for ch in "{}$")


def _iter_strings(value, path=""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_strings(v, f"{path}[{i}]")


def extract_host_findings(workflow: dict) -> list[dict]:
    """Alle Host-Befunde eines Workflows: {node, host|None, raw, verifiable}.

    - Jede http(s)-URL in einem beliebigen String-Parameter zählt (auch mitten
      in Expressions).
    - URL-tragende Schlüssel (url, endpoint, …) werden zusätzlich geprüft:
      Expressions ohne statisch extrahierbaren Host gelten als nicht prüfbar.
    """
    findings: list[dict] = []
    for node in workflow.get("nodes", []) if isinstance(workflow, dict) else []:
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name", "?"))
        params = node.get("parameters", {})
        for path, text in _iter_strings(params):
            matches = _URL_RE.findall(text)
            for hostport in matches:
                if _is_static_host(hostport):
                    findings.append({"node": node_name, "host": normalize_host(hostport),
                                     "raw": text, "verifiable": True})
                else:
                    findings.append({"node": node_name, "host": None,
                                     "raw": text, "verifiable": False})
            leaf_key = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
            if leaf_key in _URL_KEYS and not matches:
                stripped = text.lstrip("=").strip()
                if not stripped:
                    continue
                if "{{" in stripped or "$" in stripped:
                    findings.append({"node": node_name, "host": None,
                                     "raw": text, "verifiable": False})
                else:
                    candidate = normalize_host(stripped.split("/", 1)[0])
                    if _HOSTNAME_RE.match(candidate) and "." in candidate:
                        findings.append({"node": node_name, "host": candidate,
                                         "raw": text, "verifiable": True})
                    else:
                        findings.append({"node": node_name, "host": None,
                                         "raw": text, "verifiable": False})
    return findings


def validate_against_rules(workflow: dict, patterns: list[str]) -> list[dict]:
    """Liefert Verstöße als [{node, host, reason}]. Leer = alles erlaubt.

    `patterns` ist die effektive Allowlist: Abteilungsregeln ∪ Agentenregeln ∪
    implizite Hosts der freigegebenen Konnektoren.
    """
    violations: list[dict] = []
    for f in extract_host_findings(workflow):
        if not f["verifiable"]:
            violations.append({
                "node": f["node"], "host": None,
                "reason": ("Ziel-Host ist nicht statisch prüfbar "
                           f"(dynamische Expression: {f['raw'][:120]!r}). "
                           "Bitte URLs mit festem Host verwenden."),
            })
        elif not any(host_matches(f["host"], p) for p in patterns):
            violations.append({
                "node": f["node"], "host": f["host"],
                "reason": (f"Host '{f['host']}' steht nicht auf der Allowlist "
                           "dieser Abteilung/dieses Agenten."),
            })
    return violations

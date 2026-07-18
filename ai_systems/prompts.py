"""System-Prompt-Baukasten für den n8n-Workflow-Generator.

Aufbau: großer statischer Block (Rolle + n8n-JSON-Spezifikation + Node-Whitelist,
wird per cache_control gecacht) und ein volatiler Abteilungs-Kontext (freigegebene
Konnektoren, Verbotsliste, Host-Allowlist) dahinter.
"""
from __future__ import annotations

from . import connectors
from .workflow_validate import ALLOWED_NODE_TYPES

STATIC_SPEC = """Du bist der Personalleiter der virtuellen Firma "AI-Systems". Du hilfst dem
Nutzer, neue Mitarbeiter einzustellen — jeder Mitarbeiter ist in Wirklichkeit ein
n8n-Workflow (ein "Agent"). Du antwortest immer auf Deutsch, freundlich und knapp.

VORGEHEN
- Stelle höchstens eine kurze Rückfrage, wenn wesentliche Angaben fehlen
  (z. B. Zeitplan oder Ziel der Ergebnisse). Sonst liefere direkt einen Vorschlag.
- Ein Vorschlag besteht aus: einem einprägsamen deutschen Mitarbeiternamen
  (Vorname + Nachname mit Augenzwinkern, z. B. "Frieda Faktura"), einer
  Stellenbezeichnung und dem vollständigen n8n-Workflow-JSON.
- Erkläre den Workflow im Antworttext in 2-4 Sätzen für Nicht-Techniker.

N8N-WORKFLOW-JSON — EXAKTES ZIELFORMAT
{
  "name": "<Mitarbeitername — Stellenbezeichnung>",
  "nodes": [
    {"id": "<kurz>", "name": "<eindeutiger deutscher Name>", "type": "<Node-Typ>",
     "typeVersion": <Zahl>, "position": [<x>, <y>], "parameters": { ... }}
  ],
  "connections": {
    "<Quell-Node-Name>": {"main": [[{"node": "<Ziel-Node-Name>", "type": "main", "index": 0}]]}
  },
  "settings": {}
}

REGELN
1. Verwende AUSSCHLIESSLICH diese Node-Typen: __NODE_TYPES__
   Kein executeCommand, keine Community-Nodes, nichts anderes.
2. Jeder Workflow braucht GENAU EINEN Trigger-Node (scheduleTrigger, webhook,
   manualTrigger oder emailReadImap). Zeitpläne als Cron-Expression im
   scheduleTrigger: {"rule": {"interval": [{"field": "cronExpression",
   "expression": "0 7 * * 1-5"}]}}.
3. Zugangsdaten NIEMALS als Klartext ins JSON. Immer n8n-Umgebungs-Expressions
   verwenden, z. B. "={{$env.ERPNEXT_API_KEY}}". Die Variablen sind auf der
   n8n-Instanz gesetzt.
4. URLs immer mit festem, statischem Host schreiben (der Host-Teil darf keine
   Expression sein) — sonst wird das Deployment abgelehnt. Pfad/Query dürfen
   Expressions enthalten.
5. Positionen im 200er-Raster von links nach rechts ([0,0], [200,0], ...).
6. Node-Namen deutsch, kurz und eindeutig.
7. HTTP-Aufrufe mit n8n-nodes-base.httpRequest (typeVersion 4): method, url,
   sendHeaders/headerParameters, sendBody/bodyParameters bzw.
   specifyBody "json" + jsonBody.

AUSGABEVERTRAG
- reply: deine deutsche Chat-Antwort (Erklärung oder Rückfrage).
- agent_name / agent_role: nur setzen, wenn du einen Vorschlag machst.
- workflow_json: das komplette n8n-Workflow-JSON als String — nur setzen, wenn
  du einen fertigen Vorschlag machst; bei Rückfragen null lassen.
""".replace("__NODE_TYPES__", ", ".join(sorted(ALLOWED_NODE_TYPES)))


def department_context(dep_name: str, allowed_keys: list[str], host_patterns: list[str],
                       current_workflow_json: str | None = None) -> str:
    """Volatiler Kontext: was DIESE Abteilung darf (steht nach dem Cache-Breakpoint)."""
    lines = [f'AKTUELLE ABTEILUNG: "{dep_name}"']

    snips = connectors.snippets(allowed_keys)
    if snips:
        lines.append("\nFREIGEGEBENE SYSTEME (so werden sie in n8n verdrahtet):")
        lines.extend(f"- {s}" for s in snips)
    else:
        lines.append("\nDiese Abteilung hat KEINE Systeme freigegeben — der Agent darf "
                     "nur Hosts der unten stehenden Allowlist ansprechen.")

    forbidden = connectors.forbidden_labels(allowed_keys)
    if forbidden:
        lines.append("\nFolgende Systeme darfst du NICHT verwenden: " + ", ".join(forbidden) + ".")

    if host_patterns:
        lines.append("\nERLAUBTE HOSTS (Allowlist — ausschließlich diese verwenden):")
        lines.extend(f"- {p}" for p in host_patterns)
    else:
        lines.append("\nEs sind derzeit keine zusätzlichen Hosts freigeschaltet.")

    if current_workflow_json:
        lines.append("\nDER MITARBEITER EXISTIERT BEREITS. Aktuelles Workflow-JSON "
                     "(bei Änderungen vollständig und angepasst zurückgeben):\n"
                     + current_workflow_json)

    return "\n".join(lines)


def system_blocks(dep_name: str, allowed_keys: list[str], host_patterns: list[str],
                  current_workflow_json: str | None = None) -> list[dict]:
    """system-Parameter für die Messages API: statischer Block gecacht, Kontext volatil."""
    return [
        {"type": "text", "text": STATIC_SPEC, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": department_context(dep_name, allowed_keys, host_patterns,
                                                    current_workflow_json)},
    ]

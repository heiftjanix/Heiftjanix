"""Übersetzt ein n8n-Workflow-JSON in eine verständliche deutsche Schritt-für-
Schritt-Erklärung ("Was macht dieser Mitarbeiter eigentlich?") für die
Agenten-Detailseite — Laien-Ansicht statt rohem JSON.
"""
from __future__ import annotations

# (Icon, Kurzlabel, allgemeine Erklärung) je Node-Typ — deckt die Whitelist aus
# workflow_validate.ALLOWED_NODE_TYPES ab.
NODE_STEP_INFO: dict[str, tuple[str, str, str]] = {
    "n8n-nodes-base.scheduleTrigger": ("⏰", "Zeitplan-Start", "Startet automatisch nach einem festen Zeitplan."),
    "n8n-nodes-base.cron": ("⏰", "Zeitplan-Start", "Startet automatisch nach einem festen Zeitplan."),
    "n8n-nodes-base.manualTrigger": ("▶️", "Manueller Start", "Wird von Hand gestartet."),
    "n8n-nodes-base.webhook": ("🌐", "Webhook-Start", "Startet, sobald ein externer Dienst eine Anfrage sendet."),
    "n8n-nodes-base.emailReadImap": ("📥", "E-Mails abrufen", "Liest neue E-Mails aus dem Postfach."),
    "n8n-nodes-base.httpRequest": ("🔗", "Schnittstellen-Aufruf", "Ruft eine externe Schnittstelle (API) auf."),
    "n8n-nodes-base.if": ("🔀", "Bedingung", "Prüft eine Bedingung und verzweigt den Ablauf."),
    "n8n-nodes-base.switch": ("🔀", "Verzweigung", "Verzweigt den Ablauf je nach Wert."),
    "n8n-nodes-base.filter": ("🧹", "Filter", "Lässt nur passende Datensätze durch."),
    "n8n-nodes-base.set": ("✏️", "Daten aufbereiten", "Verändert oder ergänzt Daten für die nächsten Schritte."),
    "n8n-nodes-base.code": ("💻", "Eigene Logik", "Führt einen selbst geschriebenen Verarbeitungsschritt aus."),
    "n8n-nodes-base.merge": ("🔗", "Zusammenführen", "Führt mehrere Datenströme zusammen."),
    "n8n-nodes-base.splitInBatches": ("📦", "In Gruppen verarbeiten", "Verarbeitet die Daten in kleineren Gruppen."),
    "n8n-nodes-base.emailSend": ("✉️", "E-Mail versenden", "Verschickt eine E-Mail."),
    "n8n-nodes-base.respondToWebhook": ("↩️", "Antwort senden", "Sendet eine Antwort an den aufrufenden Dienst zurück."),
    "n8n-nodes-base.noOp": ("⏸️", "Kein Vorgang", "Platzhalter ohne Wirkung."),
}
_DEFAULT_INFO = ("⚙️", "Verarbeitungsschritt", "Führt einen weiteren Schritt im Ablauf aus.")


def _detail(ntype: str, params: dict) -> str:
    """Kurze, konkrete Zusatzinfo aus den Node-Parametern (z. B. Zeitplan, URL)."""
    if ntype in ("n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.cron"):
        try:
            expr = params["rule"]["interval"][0]["expression"]
            return f"Zeitplan: {expr}"
        except (KeyError, IndexError, TypeError):
            return ""
    if ntype == "n8n-nodes-base.httpRequest":
        method = params.get("method", "GET")
        url = str(params.get("url", "")).lstrip("=")
        return f"{method} {url}"[:160] if url else str(method)
    if ntype == "n8n-nodes-base.emailSend":
        to = params.get("toEmail", "")
        subject = params.get("subject", "")
        parts = [p for p in (f"An: {to}" if to else "", f"Betreff: {subject}" if subject else "") if p]
        return " — ".join(parts)
    if ntype == "n8n-nodes-base.emailReadImap":
        mailbox = params.get("mailbox") or params.get("postalCode") or ""
        return f"Postfach: {mailbox}" if mailbox else ""
    if ntype == "n8n-nodes-base.webhook":
        path = params.get("path", "")
        return f"Pfad: /{path}" if path else ""
    if ntype in ("n8n-nodes-base.if", "n8n-nodes-base.switch", "n8n-nodes-base.filter"):
        return ""
    return ""


def _describe_node(name: str, node: dict) -> dict:
    ntype = node.get("type", "")
    icon, label, description = NODE_STEP_INFO.get(ntype, _DEFAULT_INFO)
    return {
        "name": name, "type": ntype, "icon": icon, "label": label,
        "description": description, "detail": _detail(ntype, node.get("parameters", {}) or {}),
    }


def describe_workflow(workflow: dict) -> list[dict]:
    """Liefert die Schritte in Ablaufreihenfolge (Trigger zuerst), jeweils mit
    Icon/Label/Erklärung/Detail. Folgt den `connections`, beginnend bei Nodes
    ohne eingehende Verbindung (typischerweise die Trigger)."""
    if not isinstance(workflow, dict):
        return []
    nodes = {n["name"]: n for n in workflow.get("nodes", []) if isinstance(n, dict) and n.get("name")}
    connections = workflow.get("connections", {}) if isinstance(workflow.get("connections"), dict) else {}

    incoming: set[str] = set()
    for outputs in connections.values():
        if not isinstance(outputs, dict):
            continue
        for branches in (outputs.get("main") or []):
            if not isinstance(branches, list):
                continue
            for target in branches:
                if isinstance(target, dict) and target.get("node"):
                    incoming.add(target["node"])

    starts = [name for name in nodes if name not in incoming] or list(nodes.keys())[:1]

    order: list[str] = []
    seen: set[str] = set()

    def visit(name: str) -> None:
        if name in seen or name not in nodes:
            return
        seen.add(name)
        order.append(name)
        for branches in (connections.get(name, {}).get("main") or []):
            if not isinstance(branches, list):
                continue
            for target in branches:
                if isinstance(target, dict) and target.get("node"):
                    visit(target["node"])

    for start in starts:
        visit(start)
    for name in nodes:  # unverbundene Restknoten trotzdem anzeigen
        visit(name)

    return [_describe_node(name, nodes[name]) for name in order]

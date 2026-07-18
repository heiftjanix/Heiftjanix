"""Strukturvalidierung für n8n-Workflow-JSON, bevor irgendetwas deployt wird.

Geprüft werden Pflichtfelder, eindeutige Node-Namen, Verbindungen auf
existierende Nodes, mindestens ein Trigger sowie eine kuratierte Whitelist
erlaubter Node-Typen (verhindert z. B. `executeCommand`). Rückgabe ist eine
Liste deutscher Fehlermeldungen — leer bedeutet: strukturell in Ordnung.
"""
from __future__ import annotations

ALLOWED_NODE_TYPES = {
    "n8n-nodes-base.httpRequest",
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.respondToWebhook",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.if",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.filter",
    "n8n-nodes-base.set",
    "n8n-nodes-base.code",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.emailSend",
    "n8n-nodes-base.emailReadImap",
    "n8n-nodes-base.noOp",
}

TRIGGER_NODE_TYPES = {
    "n8n-nodes-base.webhook",
    "n8n-nodes-base.scheduleTrigger",
    "n8n-nodes-base.cron",
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.emailReadImap",
}


def validate_structure(workflow) -> list[str]:
    errors: list[str] = []
    if not isinstance(workflow, dict):
        return ["Workflow muss ein JSON-Objekt sein."]

    name = workflow.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("Feld 'name' fehlt oder ist leer.")

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("Feld 'nodes' fehlt oder ist leer.")
        return errors

    connections = workflow.get("connections")
    if not isinstance(connections, dict):
        errors.append("Feld 'connections' fehlt oder ist kein Objekt.")
        connections = {}

    seen_names: set[str] = set()
    has_trigger = False
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"Node #{i + 1} ist kein Objekt.")
            continue
        n_name = node.get("name")
        n_type = node.get("type")
        if not isinstance(n_name, str) or not n_name.strip():
            errors.append(f"Node #{i + 1} hat keinen Namen.")
            n_name = ""
        elif n_name in seen_names:
            errors.append(f"Node-Name '{n_name}' ist doppelt vergeben.")
        else:
            seen_names.add(n_name)
        if not isinstance(n_type, str) or not n_type:
            errors.append(f"Node '{n_name or f'#{i + 1}'}' hat keinen Typ.")
        elif n_type not in ALLOWED_NODE_TYPES:
            errors.append(
                f"Node-Typ '{n_type}' (Node '{n_name}') ist nicht erlaubt. "
                f"Erlaubt sind nur: {', '.join(sorted(ALLOWED_NODE_TYPES))}."
            )
        else:
            has_trigger = has_trigger or n_type in TRIGGER_NODE_TYPES
        if not isinstance(node.get("parameters", {}), dict):
            errors.append(f"Node '{n_name}': 'parameters' muss ein Objekt sein.")
        pos = node.get("position")
        if not (isinstance(pos, list) and len(pos) == 2
                and all(isinstance(v, (int, float)) for v in pos)):
            errors.append(f"Node '{n_name}': 'position' muss eine Liste aus zwei Zahlen sein.")

    if not has_trigger:
        errors.append(
            "Workflow hat keinen Trigger-Node (z. B. scheduleTrigger, webhook oder manualTrigger)."
        )

    for source, outputs in connections.items():
        if source not in seen_names:
            errors.append(f"Connections verweisen auf unbekannten Quell-Node '{source}'.")
        if not isinstance(outputs, dict):
            errors.append(f"Connections von '{source}' müssen ein Objekt sein.")
            continue
        for branches in outputs.values():
            if not isinstance(branches, list):
                continue
            for branch in branches:
                if not isinstance(branch, list):
                    continue
                for target in branch:
                    if isinstance(target, dict) and target.get("node") not in seen_names:
                        errors.append(
                            f"Connection von '{source}' zeigt auf unbekannten Node "
                            f"'{target.get('node')}'."
                        )
    return errors

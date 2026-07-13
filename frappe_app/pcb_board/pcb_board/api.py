"""Whitelisted API-Endpunkte der PCB-Board-Seite.

Identität kommt aus frappe.session.user (normales ERPNext-Login) — kein zweiter
Login-Screen. Nur „Postfach verbinden" ist ein separater Microsoft-Consent-Schritt
pro Nutzer (Mail.Read braucht eine eigene Freigabe, unabhängig vom ERPNext-Login).
"""
from __future__ import annotations

import secrets

import frappe

from . import auth
from . import refresh as rf
from . import version as ver


def _azure_conf() -> tuple[str | None, str | None, str | None]:
    return (
        frappe.conf.get("azure_client_id"),
        frappe.conf.get("azure_client_secret"),
        frappe.conf.get("azure_tenant_id"),
    )


def _redirect_uri() -> str:
    return frappe.utils.get_url("/api/method/pcb_board.api.outlook_callback")


@frappe.whitelist()
def get_board_metrics():
    settings = rf._settings()
    metrics = rf.get_metrics()
    if metrics is None:
        return {"metrics": None, "status": rf.get_status()}
    view = rf.view_for_user(metrics, frappe.session.user, settings["extra_mailboxes"])
    token_doc = frappe.db.exists("PCB Board Mail Token", frappe.session.user)
    view["outlook_connected"] = bool(token_doc)
    rf.attach_assignments(view)
    return {"metrics": view, "status": rf.get_status()}


def _assignment_name(internet_message_id: str) -> str | None:
    # Lookup immer über das Feld, nie über den Dokumentnamen: echte
    # internetMessageIds sehen wie "<abc@host>" aus, und Frappe verbietet
    # '<'/'>' in Dokumentnamen (autoname ist deshalb "hash").
    return frappe.db.exists("PCB Board Mail Assignment", {"internet_message_id": internet_message_id})


@frappe.whitelist()
def assign_mail(internet_message_id: str, assigned_to: str, mailbox: str | None = None,
                 sender_name: str | None = None, sender: str | None = None,
                 subject: str | None = None):
    if not (internet_message_id and assigned_to):
        frappe.throw("internet_message_id und assigned_to sind erforderlich.")
    name = _assignment_name(internet_message_id)
    if name:
        doc = frappe.get_doc("PCB Board Mail Assignment", name)
    else:
        doc = frappe.new_doc("PCB Board Mail Assignment")
        doc.internet_message_id = internet_message_id
    doc.mailbox = mailbox
    doc.sender_name = sender_name
    doc.sender = sender
    doc.subject = subject
    doc.assigned_to = assigned_to
    doc.assigned_by = frappe.session.user
    doc.status = "Offen"
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def unassign_mail(internet_message_id: str):
    name = _assignment_name(internet_message_id)
    if name:
        frappe.delete_doc("PCB Board Mail Assignment", name, ignore_permissions=True)
        frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def set_assignment_status(internet_message_id: str, status: str):
    if status not in ("Offen", "Erledigt"):
        frappe.throw("Ungültiger Status.")
    name = _assignment_name(internet_message_id)
    if name:
        doc = frappe.get_doc("PCB Board Mail Assignment", name)
        doc.status = status
        doc.save(ignore_permissions=True)
        frappe.db.commit()
    return {"ok": True}


@frappe.whitelist()
def list_assignments():
    return frappe.get_all(
        "PCB Board Mail Assignment",
        fields=["name", "internet_message_id", "mailbox", "sender_name", "sender", "subject",
                "assigned_to", "assigned_by", "status", "creation"],
        order_by="creation desc",
        limit_page_length=0,
        ignore_permissions=True,
    )


@frappe.whitelist()
def get_refresh_status():
    return rf.get_status()


@frappe.whitelist()
def start_refresh():
    accepted = rf.start_refresh(started_by=frappe.utils.get_fullname(frappe.session.user))
    return {"accepted": accepted, **rf.get_status()}


@frappe.whitelist()
def connect_outlook():
    client_id, client_secret, tenant_id = _azure_conf()
    if not (client_id and client_secret and tenant_id):
        frappe.throw("Azure-App-Registrierung ist auf diesem Server noch nicht konfiguriert "
                      "(azure_client_id/azure_client_secret/azure_tenant_id in site_config.json).")
    state = secrets.token_urlsafe(16)
    frappe.cache().set_value(f"pcb_board_oauth_state:{frappe.session.user}", state, expires_in_sec=600)
    url = auth.get_login_url(client_id, client_secret, tenant_id, _redirect_uri(), state)
    return {"url": url}


@frappe.whitelist(allow_guest=False)
def outlook_callback(code: str | None = None, state: str | None = None, error_description: str | None = None):
    board_url = frappe.utils.get_url("/app/pcb-board")
    if error_description:
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{board_url}?connect_error=1"
        return

    expected_state = frappe.cache().get_value(f"pcb_board_oauth_state:{frappe.session.user}")
    if not code or not state or state != expected_state:
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{board_url}?connect_error=1"
        return

    try:
        client_id, client_secret, tenant_id = _azure_conf()
        email, name, serialized_cache = auth.exchange_code(
            client_id, client_secret, tenant_id, _redirect_uri(), code
        )

        if frappe.db.exists("PCB Board Mail Token", frappe.session.user):
            doc = frappe.get_doc("PCB Board Mail Token", frappe.session.user)
        else:
            doc = frappe.new_doc("PCB Board Mail Token")
            doc.user = frappe.session.user
        doc.connected_mailbox = email
        doc.token_cache = serialized_cache
        doc.save(ignore_permissions=True)
        # Ausdrücklicher Commit: Diese Methode setzt die Antwort manuell auf
        # "redirect" statt eine normale Antwort zurückzugeben — dabei ist nicht
        # garantiert, dass Frappes üblicher End-of-Request-Auto-Commit greift.
        frappe.db.commit()
        frappe.cache().delete_value(f"pcb_board_oauth_state:{frappe.session.user}")
        frappe.log_error(
            title="PCB Board Connect erfolgreich",
            message=f"user={frappe.session.user} mailbox={email} doc={doc.name}",
        )
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="PCB Board Connect fehlgeschlagen", message=frappe.get_traceback())
        frappe.local.response["type"] = "redirect"
        frappe.local.response["location"] = f"{board_url}?connect_error=1"
        return

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"{board_url}?connected=1"


@frappe.whitelist()
def disconnect_outlook():
    if frappe.db.exists("PCB Board Mail Token", frappe.session.user):
        frappe.delete_doc("PCB Board Mail Token", frappe.session.user, ignore_permissions=True)
    return {"ok": True}


@frappe.whitelist()
def get_config_status():
    """Nur Ja/Nein je Secret/Einstellung — niemals die Werte selbst (auch fuer
    Nicht-System-Manager sichtbar, damit z. B. IT-Support beim Debuggen hilft,
    ohne Zugriff auf echte Secrets zu brauchen)."""
    client_id, client_secret, tenant_id = _azure_conf()
    settings = frappe.get_single("PCB Board Settings")
    own_token = frappe.db.exists("PCB Board Mail Token", frappe.session.user)
    return {
        "azure_client_id": bool(client_id),
        "azure_client_secret": bool(client_secret),
        "azure_tenant_id": bool(tenant_id),
        "redirect_uri": _redirect_uri(),
        "anthropic_api_key": bool(frappe.conf.get("anthropic_api_key")),
        "ups_client_id": bool(frappe.conf.get("ups_client_id")),
        "ups_client_secret": bool(frappe.conf.get("ups_client_secret")),
        "revenue_target": bool(settings.revenue_target),
        "extra_mailboxes": bool((settings.extra_mailboxes or "").strip()),
        "own_mailbox_connected": bool(own_token),
        "build_time": ver.BUILD_TIME,
        "build_commit": ver.BUILD_COMMIT,
    }

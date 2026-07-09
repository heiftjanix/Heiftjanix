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
    return {"metrics": view, "status": rf.get_status()}


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
    frappe.cache().delete_value(f"pcb_board_oauth_state:{frappe.session.user}")

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"{board_url}?connected=1"


@frappe.whitelist()
def disconnect_outlook():
    if frappe.db.exists("PCB Board Mail Token", frappe.session.user):
        frappe.delete_doc("PCB Board Mail Token", frappe.session.user, ignore_permissions=True)
    return {"ok": True}

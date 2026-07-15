"""Refresh-Orchestrierung: ERPNext (frappe.get_all) + UPS + Microsoft Graph + Claude-
Triage -> Kennzahlen -> frappe.cache() (Redis), damit ALLE angemeldeten Nutzer denselben
globalen Status/Stand sehen (kein eigener Server-Prozess wie in webapp/service.py nötig).

Harte Regel: nur Vorschläge, nichts wird automatisch versendet oder gebucht. Alle
Geldbeträge werden ausschließlich in metrics.py (Python) berechnet.
"""
from __future__ import annotations

import sys
from datetime import date

import frappe

from . import auth, graph, metrics as m, triage, ups_track

STATUS_KEY = "pcb_board_status"
METRICS_KEY = "pcb_board_metrics"


def _settings() -> dict:
    s = frappe.get_single("PCB Board Settings")
    extra = [ln.strip() for ln in (s.extra_mailboxes or "").splitlines() if ln.strip()]
    company = frappe.defaults.get_global_default("company") or ""
    return {
        "company": company,
        # Board-Titel: explizit in PCB Board Settings gepflegter Name hat Vorrang,
        # sonst Fallback auf ERPNexts globale Standard-Firma, sonst leer (neutraler
        # Titel ohne Firmenname).
        "company_name": (s.company_name or "").strip() or company,
        "slogan": (s.slogan or "").strip(),
        "currency": "EUR",
        "revenue_target": s.revenue_target or 100000,
        "forecast": {
            "baseline_months": s.baseline_months or 3,
            "confidence_days_K": s.confidence_days_k or 5,
            "uncertainty_pct": s.uncertainty_pct or 0.15,
            "amber_threshold": s.amber_threshold or 0.85,
        },
        "holidays": {"region": s.holidays_region or "BY", "extra": []},
        "billing": {
            "ups_transit_days": s.ups_transit_days or 2,
            "stale_delivery_note_days": s.stale_delivery_note_days or 60,
        },
        "extra_mailboxes": extra,
        "mail_lookback_hours": (s.mail_lookback_days or 1) * 24,
        "anthropic_model": s.anthropic_model or triage.DEFAULT_MODEL,
        "personnel_costs_monthly": float(s.personnel_costs_monthly or 0),
        "rent_monthly": float(s.rent_monthly or 0),
    }


def get_status() -> dict:
    status = frappe.cache().get_value(STATUS_KEY)
    return status or {"state": "idle", "started_by": None, "started_at": None, "generated_at": None}


def _set_status(**kwargs) -> None:
    status = get_status()
    status.update(kwargs)
    frappe.cache().set_value(STATUS_KEY, status)


def get_metrics() -> dict | None:
    return frappe.cache().get_value(METRICS_KEY)


def start_refresh(started_by: str) -> bool:
    """True wenn ein neuer Refresh gestartet wurde, False wenn schon einer läuft."""
    if get_status().get("state") == "running":
        return False
    _set_status(state="running", started_by=started_by, started_at=frappe.utils.now())
    frappe.enqueue(
        "pcb_board.refresh.run_refresh",
        queue="short",
        started_by=started_by,
        enqueue_after_commit=True,
    )
    return True


def scheduled_refresh() -> None:
    run_refresh(started_by="Scheduler")


def scheduled_mail_sync() -> None:
    """Alle paar Minuten (siehe hooks.py): NUR Mails neu holen/triagieren und still
    in den gecachten Board-Stand einspeisen — rührt NIE den Running-Status an, damit
    kein Ladehinweis erscheint und alle das Board währenddessen normal weiter nutzen
    können. ERPNext/UPS bleiben dem regulären 30-Min-Vollrefresh vorbehalten.

    Läuft ins Leere, falls noch nie ein Vollrefresh gelaufen ist (dann gibt es noch
    nichts, worin die Mails eingespeist werden könnten) oder gerade ein Vollrefresh
    läuft (der bringt ohnehin frische Mails mit)."""
    if get_status().get("state") == "running":
        return
    computed = get_metrics()
    if not computed:
        return
    try:
        config = _settings()
        anthropic_api_key = frappe.conf.get("anthropic_api_key")
        mail_items = _fetch_mail(config, anthropic_api_key)
        computed["mail"] = m.mail_summary({"window_hours": config["mail_lookback_hours"], "items": mail_items})
        computed["generated_at"] = frappe.utils.now()
        frappe.cache().set_value(METRICS_KEY, computed)
    except Exception:  # noqa: BLE001 — still fehlschlagen, alter Stand bleibt einfach stehen
        frappe.log_error(title="PCB Board Mail-Sync fehlgeschlagen", message=frappe.get_traceback())


def _fetch_erpnext(config: dict) -> dict:
    today = date.today()
    y, mo = today.year, today.month
    for _ in range(int(config["forecast"]["baseline_months"])):
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
    cutoff = date(y, mo, 1).isoformat()

    # ignore_permissions: die Kennzahlen sind für alle Board-Nutzer gleich (aggregiert,
    # nicht dokumentenscharf) — Zugriff auf das Board selbst wird über die Desk-Page-
    # Rollen gesteuert, nicht über einzelne DocType-Rechte.
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=[["posting_date", ">=", cutoff], ["docstatus", "=", 1]],
        fields=["name", "customer", "base_net_total", "posting_date", "status"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    dns = frappe.get_all(
        "Delivery Note",
        filters=[["status", "=", "To Bill"]],
        fields=["name", "customer_name", "base_net_total", "per_billed", "posting_date",
                "custom_tracking_numbers", "custom_ups_shipment_date"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    for r in dns:
        r["tracking_number"] = r.pop("custom_tracking_numbers", None)
        r["shipment_date"] = r.pop("custom_ups_shipment_date", None)

    sos = frappe.get_all(
        "Sales Order",
        filters=[["status", "not in", ["Closed", "Cancelled", "Completed"]], ["docstatus", "=", 1]],
        fields=["name", "customer", "base_net_total", "per_billed"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    open_sales_orders = []
    for r in sos:
        net_open = float(r.get("base_net_total") or 0) * (1.0 - float(r.get("per_billed") or 0) / 100.0)
        open_sales_orders.append({"name": r["name"], "customer": r.get("customer"), "net_open": round(net_open, 2)})

    # Kosten: Wareneingänge (Purchase Receipt) — Netto-Basiswert, gebucht.
    purchase_receipts = frappe.get_all(
        "Purchase Receipt",
        filters=[["posting_date", ">=", cutoff], ["docstatus", "=", 1]],
        fields=["name", "supplier", "base_net_total", "posting_date"],
        limit_page_length=0,
        ignore_permissions=True,
    )

    # Top-Produkte: Rechnungspositionen (Sales Invoice Item) nur für den
    # laufenden Monat — eigene, engere Abfrage statt aus `invoices` (mehrere
    # Monate) herausgefiltert, um kein posting_date-Format raten zu müssen.
    month_start = date(today.year, today.month, 1).isoformat()
    month_invoices = frappe.get_all(
        "Sales Invoice",
        filters=[["posting_date", ">=", month_start], ["docstatus", "=", 1]],
        fields=["name"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    invoice_items = []
    if month_invoices:
        invoice_items = frappe.get_all(
            "Sales Invoice Item",
            filters=[["parent", "in", [inv["name"] for inv in month_invoices]]],
            fields=["item_code", "item_name", "base_net_amount"],
            limit_page_length=0,
            ignore_permissions=True,
        )

    return {
        "as_of": today.isoformat(),
        "invoices": invoices,
        "to_bill_delivery_notes": dns,
        "open_sales_orders": open_sales_orders,
        "purchase_receipts": purchase_receipts,
        "invoice_items": invoice_items,
    }


def _fetch_mail(config: dict, anthropic_api_key: str | None) -> list[dict]:
    azure_client_id = frappe.conf.get("azure_client_id")
    azure_client_secret = frappe.conf.get("azure_client_secret")
    azure_tenant_id = frappe.conf.get("azure_tenant_id")
    if not (azure_client_id and azure_client_secret and azure_tenant_id):
        return []

    tokens = frappe.get_all("PCB Board Mail Token", fields=["name", "user"], ignore_permissions=True)
    all_items: list[dict] = []
    for row in tokens:
        doc = frappe.get_doc("PCB Board Mail Token", row.name)
        cache = doc.get_password("token_cache")
        if not cache:
            continue
        try:
            token, new_cache = auth.get_access_token(azure_client_id, azure_client_secret, azure_tenant_id, cache)
        except Exception as exc:  # noqa: BLE001 — ein kaputter Token-Cache darf den Refresh nicht abschießen
            sys.stderr.write(f"[pcb_board] Token-Cache für {row.user} ungültig ({exc}) — bitte neu verbinden.\n")
            continue
        if new_cache != cache:
            doc.token_cache = new_cache
            doc.save(ignore_permissions=True)
        if not token:
            sys.stderr.write(f"[pcb_board] Kein gültiges Graph-Token mehr für {row.user} — bitte neu verbinden.\n")
            continue
        try:
            items = graph.fetch_all_mailboxes(
                token, doc.user, config["extra_mailboxes"], window_hours=config["mail_lookback_hours"]
            )
            all_items.extend(items)
        except Exception as exc:  # noqa: BLE001 — ein Postfach darf den Refresh nicht abschießen
            sys.stderr.write(f"[pcb_board] Postfach-Abruf für {row.user} fehlgeschlagen: {exc}\n")

    return triage.triage_all(all_items, model=config["anthropic_model"], api_key=anthropic_api_key)


def run_refresh(started_by: str | None = None) -> None:
    try:
        config = _settings()
        raw = _fetch_erpnext(config)

        anthropic_api_key = frappe.conf.get("anthropic_api_key")
        mail_items = _fetch_mail(config, anthropic_api_key)
        raw["mail"] = {"window_hours": config["mail_lookback_hours"], "items": mail_items}

        ups_client_id = frappe.conf.get("ups_client_id")
        ups_client_secret = frappe.conf.get("ups_client_secret")
        raw["to_bill_delivery_notes"] = ups_track.resolve_arrivals(
            raw["to_bill_delivery_notes"], config, ups_client_id, ups_client_secret
        )

        computed = m.build_metrics(raw, config)
        computed["dashboard_title"] = (
            f"{config['company_name']} Team-Board" if config["company_name"] else "Team-Board"
        )
        computed["slogan"] = config["slogan"]
        computed["generated_at"] = frappe.utils.now()
        started_at = get_status().get("started_at")
        if started_at:
            from datetime import datetime
            try:
                t0 = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S.%f")
                t1 = datetime.strptime(computed["generated_at"], "%Y-%m-%d %H:%M:%S.%f")
                computed["refresh_seconds"] = round((t1 - t0).total_seconds(), 1)
            except Exception:
                pass
        frappe.cache().set_value(METRICS_KEY, computed)
        _set_status(state="idle", generated_at=computed["generated_at"])
    except Exception as exc:  # noqa: BLE001 — Refresh darf die App nie in "running" haengen lassen
        frappe.log_error(title="PCB Board Refresh fehlgeschlagen", message=frappe.get_traceback())
        _set_status(state="idle")


def view_for_user(metrics_dict: dict, own_email: str, extra_mailboxes: list[str]) -> dict:
    """Blendet Mail-Items auf die für den Nutzer sichtbaren Postfächer ein."""
    import copy

    allowed = {own_email} | set(extra_mailboxes)
    view = copy.deepcopy(metrics_dict)
    mail = metrics_dict.get("mail", {})
    items = [i for i in mail.get("items", []) if i.get("mailbox") in allowed]
    view["mail"] = m.mail_summary({"window_hours": mail.get("window_hours"), "items": items})
    return view


def normalize_mid(internet_message_id: str | None) -> str:
    """RFC-5322-Message-IDs kommen als "<id@host>" — die spitzen Klammern sind nur
    Rahmen, die Identität ist der Teil dazwischen. Gespeichert/verglichen wird
    IMMER ohne Klammern: Frappes HTML-Sanitizer hält "<...>" beim Speichern eines
    Data-Felds für ein HTML-Tag und entfernt den kompletten Wert (Feld wäre leer,
    Pflichtfeld-Fehler), und in Dokumentnamen sind '<'/'>' ohnehin verboten."""
    return (internet_message_id or "").strip().strip("<>").strip()


def attach_assignments(view: dict) -> None:
    """Blendet Zuweisungen (persistiert im DocType, nicht Teil der Refresh-Daten)
    in die Mail-Items der aktuellen Ansicht ein — nach internet_message_id gematcht,
    damit Zuweisungen einen Refresh überleben, obwohl Mails jedes Mal neu geholt werden."""
    items = ((view.get("mail") or {}).get("items")) or []
    if not items:
        return
    rows = frappe.get_all(
        "PCB Board Mail Assignment",
        fields=["internet_message_id", "assigned_to", "status"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    by_id = {normalize_mid(r["internet_message_id"]): r for r in rows}
    names: dict[str, str] = {}
    for i in items:
        row = by_id.get(normalize_mid(i.get("internet_message_id")))
        if not row:
            i["assigned_to"] = None
            i["assigned_to_name"] = None
            i["assignment_status"] = None
            continue
        assigned_to = row["assigned_to"]
        if assigned_to not in names:
            names[assigned_to] = frappe.utils.get_fullname(assigned_to)
        i["assigned_to"] = assigned_to
        i["assigned_to_name"] = names[assigned_to]
        i["assignment_status"] = row["status"]

"""Refresh-Orchestrierung: ERPNext (frappe.get_all) + UPS + Microsoft Graph + Claude-
Triage -> Kennzahlen -> frappe.cache() (Redis), damit ALLE angemeldeten Nutzer denselben
globalen Status/Stand sehen (kein eigener Server-Prozess wie in webapp/service.py nötig).

Harte Regel: nur Vorschläge, nichts wird automatisch versendet oder gebucht. Alle
Geldbeträge werden ausschließlich in metrics.py (Python) berechnet.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

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
        # Status MUSS mitwandern: das Board vergleicht den Zeitstempel im Status
        # mit dem seines geladenen Stands und lädt bei Abweichung neu. Ohne diese
        # Zeile blieben beide dauerhaft verschieden — das Board hätte sich nach
        # dem ersten Mail-Sync im 4-Sekunden-Takt selbst neu gezeichnet (und dabei
        # laufend den Fokus aus Such- und Eingabefeldern geworfen).
        _set_status(generated_at=computed["generated_at"])
    except Exception:  # noqa: BLE001 — still fehlschlagen, alter Stand bleibt einfach stehen
        frappe.log_error(title="PCB Board Mail-Sync fehlgeschlagen", message=frappe.get_traceback())


def _optional(label: str, fn, default):
    """Zusatzdaten dürfen den Refresh nicht kippen.

    Kernzahlen (Umsatz, Lieferscheine, Aufträge, Wareneingänge) müssen stimmen —
    schlägt dort etwas fehl, ist ein Abbruch richtig. Ergänzende Blöcke wie
    Fertigung, Einkaufstool oder der Jahres-Deckungsbeitrag sollen dagegen nur den
    eigenen Abschnitt kosten und nicht das ganze Board: sie landen im Fehlerlog,
    der Rest läuft weiter.
    """
    try:
        return fn()
    except Exception:  # noqa: BLE001
        frappe.log_error(title=f"PCB Board: {label} übersprungen",
                         message=frappe.get_traceback())
        return default


def _fetch_erpnext(config: dict) -> dict:
    today = date.today()
    y, mo = today.year, today.month
    for _ in range(int(config["forecast"]["baseline_months"])):
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
    # Rechnungen/Wareneingänge müssen sowohl die Baseline-Monate (Prognose) als
    # auch das komplette laufende Jahr abdecken (Gewinn/Verlust-Historie + Vortrag).
    cutoff = min(date(y, mo, 1), date(today.year, 1, 1)).isoformat()

    # ignore_permissions: die Kennzahlen sind für alle Board-Nutzer gleich (aggregiert,
    # nicht dokumentenscharf) — Zugriff auf das Board selbst wird über die Desk-Page-
    # Rollen gesteuert, nicht über einzelne DocType-Rechte.
    invoices = frappe.get_all(
        "Sales Invoice",
        filters=[["posting_date", ">=", cutoff], ["docstatus", "=", 1]],
        fields=["name", "customer", "customer_name", "base_net_total", "posting_date", "status"],
        limit_page_length=0,
        ignore_permissions=True,
    )

    # Vorjahresvergleich: das KOMPLETTE Vorjahr — deckt Monatsvergleich,
    # Jahresumsatz-Vergleich und Gewinn/Verlust 2025 ab.
    py = today.year - 1
    prev_year_invoices = frappe.get_all(
        "Sales Invoice",
        filters=[["posting_date", ">=", date(py, 1, 1).isoformat()],
                 ["posting_date", "<", date(today.year, 1, 1).isoformat()],
                 ["docstatus", "=", 1]],
        # customer/customer_name auch hier: die CRM-Kundenentwicklung braucht das
        # Vorjahr, um Neu-/reaktivierte und schlafende Kunden zu erkennen.
        fields=["name", "customer", "customer_name", "base_net_total", "posting_date"],
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
        fields=["name", "customer", "customer_name", "base_net_total", "per_billed", "delivery_date"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    open_sales_orders = []
    for r in sos:
        net_open = float(r.get("base_net_total") or 0) * (1.0 - float(r.get("per_billed") or 0) / 100.0)
        open_sales_orders.append({
            "name": r["name"],
            "customer": r.get("customer"),
            "customer_name": r.get("customer_name"),
            "delivery_date": str(r["delivery_date"]) if r.get("delivery_date") else None,
            "net_open": round(net_open, 2),
        })

    # Kosten: Wareneingänge (Purchase Receipt) — Netto-Basiswert, gebucht.
    # Ab Jahresanfang VORJAHR, damit auch der Gewinn/Verlust 2025 (Kachel im
    # Umsatz-Tab) berechnet werden kann.
    purchase_receipts = frappe.get_all(
        "Purchase Receipt",
        filters=[["posting_date", ">=", date(py, 1, 1).isoformat()], ["docstatus", "=", 1]],
        fields=["name", "supplier", "supplier_name", "base_net_total", "posting_date"],
        limit_page_length=0,
        ignore_permissions=True,
    )

    # Einkauf: offene Bestellungen (noch nicht vollständig eingegangen) — Basis für
    # den erwarteten Wareneingang und die „nachzuhaken"-Liste.
    pos = frappe.get_all(
        "Purchase Order",
        filters=[["docstatus", "=", 1],
                 ["status", "not in", ["Closed", "Cancelled", "Completed", "Delivered"]],
                 ["per_received", "<", 100]],
        fields=["name", "supplier", "supplier_name", "transaction_date", "schedule_date",
                "base_net_total", "per_received", "status"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    po_items: dict[str, list[dict]] = {}
    if pos:
        for row in frappe.get_all(
            "Purchase Order Item",
            filters=[["parent", "in", [p["name"] for p in pos]]],
            fields=["parent", "item_code", "item_name", "qty", "received_qty"],
            limit_page_length=0,
            ignore_permissions=True,
        ):
            # nur noch ausstehende Positionen — bereits gelieferte erwartet niemand mehr.
            open_qty = float(row.get("qty") or 0) - float(row.get("received_qty") or 0)
            if open_qty <= 0:
                continue
            po_items.setdefault(row["parent"], []).append({
                "item_code": row.get("item_code"),
                "item_name": row.get("item_name") or row.get("item_code"),
                "open_qty": round(open_qty, 2),
            })
    open_purchase_orders = []
    for p in pos:
        items = po_items.get(p["name"], [])
        net_open = float(p.get("base_net_total") or 0) * (1.0 - float(p.get("per_received") or 0) / 100.0)
        open_purchase_orders.append({
            "name": p["name"],
            "supplier": p.get("supplier"),
            "supplier_name": p.get("supplier_name"),
            "status": p.get("status"),
            "transaction_date": str(p["transaction_date"]) if p.get("transaction_date") else None,
            "schedule_date": str(p["schedule_date"]) if p.get("schedule_date") else None,
            "net_total": round(float(p.get("base_net_total") or 0), 2),
            "net_open": round(net_open, 2),
            "per_received": float(p.get("per_received") or 0),
            "positions": len(items),
            # Deckel gegen aufgeblähten Cache-Eintrag; die Anzahl steht in positions.
            "items": items[:20],
        })

    def _fetch_crm() -> dict:
        """Angebote, Leads und Opportunities für den CRM-Reiter — optionaler Block.
        docstatus < 2 lässt Stornos weg: bei geänderten Angeboten (AN-1234 storniert,
        AN-1234-1 aktiv) würde sonst jedes Angebot doppelt zählen."""
        py_start = date(today.year - 1, 1, 1).isoformat()
        quotations = [{
            "name": q["name"],
            "customer": q.get("customer_name") or q.get("party_name") or "",
            "status": q.get("status"),
            "is_draft": int(q.get("docstatus") or 0) == 0,
            "date": str(q["transaction_date"])[:10] if q.get("transaction_date") else None,
            "valid_till": str(q["valid_till"])[:10] if q.get("valid_till") else None,
            "net_total": round(float(q.get("base_net_total") or 0), 2),
        } for q in frappe.get_all(
            "Quotation",
            filters=[["docstatus", "<", 2], ["transaction_date", ">=", py_start]],
            fields=["name", "party_name", "customer_name", "status", "transaction_date",
                    "valid_till", "base_net_total", "docstatus"],
            limit_page_length=0,
            ignore_permissions=True,
        )]
        leads = [{
            "name": r["name"],
            "lead_name": r.get("company_name") or r.get("lead_name") or r["name"],
            "status": r.get("status"),
            "created": str(r.get("creation") or "")[:10],
        } for r in frappe.get_all(
            "Lead",
            fields=["name", "lead_name", "company_name", "status", "creation"],
            limit_page_length=0,
            ignore_permissions=True,
        )]
        opportunities = [{
            "name": o["name"],
            "customer": o.get("customer_name") or o.get("party_name") or "",
            "status": o.get("status"),
            "stage": o.get("sales_stage"),
            "date": str(o["transaction_date"])[:10] if o.get("transaction_date") else None,
            "amount": round(float(o.get("opportunity_amount") or 0), 2),
        } for o in frappe.get_all(
            "Opportunity",
            filters=[["docstatus", "<", 2]],
            fields=["name", "party_name", "customer_name", "status", "sales_stage",
                    "transaction_date", "opportunity_amount"],
            limit_page_length=0,
            ignore_permissions=True,
        )]
        return {"quotations": quotations, "leads": leads, "opportunities": opportunities}

    crm = _optional("CRM-Daten", _fetch_crm,
                    {"quotations": [], "leads": [], "opportunities": []})

    def _fetch_production() -> tuple[list[dict], list[dict]]:
        """Fertigungsaufträge, Materialbedarf und EKT-Nummern — optionaler Block."""
        # Nur Aufträge mit offenem Materialbedarf — dafür ist die bestellte Ware
        # gedacht. available_qty_at_source_warehouse ist ERPNexts eigene Bestandszahl
        # aus dem Auftrag (deckungsgleich mit Bin.actual_qty des Quelllagers), damit im
        # Board dieselbe Menge steht wie im Fertigungsauftrag selbst.
        wos = frappe.get_all(
            "Work Order",
            filters=[["docstatus", "=", 1],
                     ["status", "not in", ["Completed", "Cancelled", "Stopped", "Closed"]]],
            fields=["name", "production_item", "item_name", "qty", "status", "sales_order",
                    "planned_start_date", "expected_delivery_date"],
            limit_page_length=0,
            ignore_permissions=True,
        )
        wo_required: dict[str, list[dict]] = {}
        wo_beistellung: dict[str, int] = {}
        if wos:
            for row in frappe.get_all(
                "Work Order Item",
                filters=[["parent", "in", [w["name"] for w in wos]]],
                fields=["parent", "item_code", "item_name", "required_qty", "transferred_qty",
                        "available_qty_at_source_warehouse", "is_customer_provided_item"],
                limit_page_length=0,
                ignore_permissions=True,
            ):
                # Bereits in die Fertigung umgelagerte Mengen fehlen nicht mehr.
                required = float(row.get("required_qty") or 0)
                transferred = float(row.get("transferred_qty") or 0)
                if required - transferred <= 0:
                    continue
                # Beistellung (Kunde liefert bei, Kennzeichen aus der Stückliste): nicht
                # unsere Beschaffung — taucht deshalb nicht als fehlendes Material auf.
                if int(row.get("is_customer_provided_item") or 0):
                    wo_beistellung[row["parent"]] = wo_beistellung.get(row["parent"], 0) + 1
                    continue
                wo_required.setdefault(row["parent"], []).append({
                    "item_code": row.get("item_code"),
                    "item_name": row.get("item_name") or row.get("item_code"),
                    "required_qty": required,
                    "transferred_qty": transferred,
                    "available_qty": float(row.get("available_qty_at_source_warehouse") or 0),
                })

        # EKT-Nummern aus dem Einkaufstool (kundeneigener DocType): fehlt ein Artikel
        # und ist nichts bestellt, liegt dafür oft schon eine Anfrage im Einkaufstool.
        # Zuordnung über components.item_id (= Item-Code); custom_projekte nennt
        # zusätzlich die Fertigungsaufträge, für die eingekauft wird.
        # Die Existenzprüfung hält das Board auf Instanzen ohne Einkaufstool lauffähig.
        ekt_components = []
        req_codes = sorted({it["item_code"] for rows in wo_required.values()
                            for it in rows if it.get("item_code")})
        if req_codes and frappe.db.exists("DocType", "Einkaufstool Component"):
            rows = frappe.get_all(
                "Einkaufstool Component",
                filters=[["parenttype", "=", "Einkaufstool"], ["item_id", "in", req_codes]],
                fields=["parent", "item_id", "custom_projekte", "required_quantity"],
                limit_page_length=0,
                ignore_permissions=True,
            )
            ekt_created: dict[str, str] = {}
            if rows:
                for e in frappe.get_all(
                    "Einkaufstool",
                    filters=[["name", "in", sorted({r["parent"] for r in rows})]],
                    fields=["name", "creation"],
                    limit_page_length=0,
                    ignore_permissions=True,
                ):
                    ekt_created[e["name"]] = str(e.get("creation") or "")[:10]
            for r in rows:
                ekt_components.append({
                    "ekt": r["parent"],
                    "item_code": r["item_id"],
                    "work_orders_text": r.get("custom_projekte") or "",
                    "required_quantity": float(r.get("required_quantity") or 0),
                    "created": ekt_created.get(r["parent"]),
                })

        # Wunschtermin des Kunden = Liefertermin der zugehörigen AB (auch bereits
        # abgerechnete Aufträge, die stehen nicht in open_sales_orders).
        so_names = sorted({w["sales_order"] for w in wos if w.get("sales_order")})
        so_due: dict[str, str] = {}
        if so_names:
            for row in frappe.get_all(
                "Sales Order",
                filters=[["name", "in", so_names]],
                fields=["name", "delivery_date"],
                limit_page_length=0,
                ignore_permissions=True,
            ):
                if row.get("delivery_date"):
                    so_due[row["name"]] = str(row["delivery_date"])[:10]
        work_orders = []
        for w in wos:
            work_orders.append({
                "name": w["name"],
                "production_item": w.get("production_item"),
                "item_name": w.get("item_name") or w.get("production_item"),
                "qty": float(w.get("qty") or 0),
                "status": w.get("status"),
                "sales_order": w.get("sales_order"),
                "planned_start_date": str(w["planned_start_date"])[:10] if w.get("planned_start_date") else None,
                "expected_delivery_date": (
                    str(w["expected_delivery_date"])[:10] if w.get("expected_delivery_date") else None),
                "customer_due_date": so_due.get(w.get("sales_order")),
                "beistellung_count": wo_beistellung.get(w["name"], 0),
                "required_items": wo_required.get(w["name"], []),
            })
        return work_orders, ekt_components

    work_orders, ekt_components = _optional(
        "Fertigungs-/Einkaufstool-Daten", _fetch_production, ([], []))

    # Lieferzeit-Historie je Lieferant: Wareneingangspositionen mit Bestellbezug
    # ergeben (Bestelldatum -> Wareneingangsdatum). Basis sind die oben schon
    # geladenen Wareneingänge (ab Vorjahresanfang); die Median-Bildung und die
    # „erster Wareneingang je Bestellung"-Regel stecken in metrics.py.
    po_receipt_pairs = []
    if purchase_receipts:
        pr_dates = {r["name"]: str(r.get("posting_date") or "") for r in purchase_receipts}
        links = frappe.get_all(
            "Purchase Receipt Item",
            filters=[["parent", "in", list(pr_dates)], ["purchase_order", "!=", ""]],
            fields=["parent", "purchase_order"],
            limit_page_length=0,
            ignore_permissions=True,
        )
        pairs = sorted({(r["parent"], r["purchase_order"]) for r in links if r.get("purchase_order")})
        po_meta: dict[str, dict] = {}
        ref_names = sorted({po for _, po in pairs})
        if ref_names:
            for row in frappe.get_all(
                "Purchase Order",
                filters=[["name", "in", ref_names]],
                fields=["name", "supplier", "transaction_date"],
                limit_page_length=0,
                ignore_permissions=True,
            ):
                po_meta[row["name"]] = row
        for pr_name, po_name in pairs:
            meta = po_meta.get(po_name)
            if not meta or not meta.get("transaction_date"):
                continue
            po_receipt_pairs.append({
                "purchase_order": po_name,
                "supplier": meta.get("supplier"),
                "order_date": str(meta["transaction_date"]),
                "receipt_date": pr_dates.get(pr_name),
            })

    # Top-Produkte: Rechnungspositionen (Sales Invoice Item) nur für den
    # laufenden Monat — eigene, engere Abfrage statt aus `invoices` (mehrere
    # Monate) herausgefiltert, um kein posting_date-Format raten zu müssen.
    month_start = date(today.year, today.month, 1).isoformat()

    def _fetch_month_items() -> list[dict]:
        month_invoices = frappe.get_all(
            "Sales Invoice",
            filters=[["posting_date", ">=", month_start], ["docstatus", "=", 1]],
            fields=["name"],
            limit_page_length=0,
            ignore_permissions=True,
        )
        if not month_invoices:
            return []
        return frappe.get_all(
            "Sales Invoice Item",
            filters=[["parent", "in", [inv["name"] for inv in month_invoices]]],
            fields=["item_code", "item_name", "base_net_amount", "qty"],
            limit_page_length=0,
            ignore_permissions=True,
        )

    invoice_items = _optional("Monats-Artikelumsätze", _fetch_month_items, [])

    # Deckungsbeitrag im Jahresvergleich: Rechnungspositionen je Artikel summiert.
    # Bewusst OHNE SQL-Aggregat im fields-Parameter — diese Frappe-Version lehnt
    # "sum(x) as y" als Zeichenkette ab ("SQL-Funktionen sind in SELECT nicht als
    # Zeichenketten erlaubt"). Stattdessen dieselbe schlichte Abfrage wie überall
    # sonst, in Blöcken, und die Summe in Python. Gecacht wird nur das Ergebnis je
    # Artikel, nicht die Einzelzeilen.
    def _items_per_item(names: list[str]) -> list[dict]:
        totals: dict[str, dict] = {}
        for start in range(0, len(names), 500):
            for row in frappe.get_all(
                "Sales Invoice Item",
                filters=[["parent", "in", names[start:start + 500]]],
                fields=["item_code", "item_name", "base_net_amount", "qty"],
                limit_page_length=0,
                ignore_permissions=True,
            ):
                code = row.get("item_code")
                if not code:
                    continue
                entry = totals.setdefault(code, {
                    "item_code": code,
                    "item_name": row.get("item_name") or code,
                    "net_total": 0.0,
                    "qty": 0.0,
                })
                entry["net_total"] += float(row.get("base_net_amount") or 0)
                entry["qty"] += float(row.get("qty") or 0)
        for entry in totals.values():
            entry["net_total"] = round(entry["net_total"], 2)
            entry["qty"] = round(entry["qty"], 4)
        return list(totals.values())

    def _fetch_year_items() -> tuple[list[dict], list[dict]]:
        year_start = date(today.year, 1, 1).isoformat()
        return (
            _items_per_item([i["name"] for i in invoices
                             if str(i.get("posting_date") or "") >= year_start]),
            _items_per_item([i["name"] for i in prev_year_invoices]),
        )

    invoice_items_year, invoice_items_prev_year = _optional(
        "Jahres-Artikelumsätze", _fetch_year_items, ([], []))

    # Deckungsbeitrag: letzter Einkaufspreis je verkauftem Artikel (Wareneinsatz-
    # Schätzung); für Eigenfertigung ohne Einkaufspreis dient der Wert der
    # aktiven Standard-Stückliste (BOM-Kosten je Einheit) als Fallback.
    # Neben den Monatsartikeln auch die umsatzstärksten Jahresartikel — gedeckelt,
    # damit die Stammdatenabfrage nicht über Tausende Codes läuft. Der DB eines
    # Artikels kann seinen Umsatz nicht übersteigen, die DB-Rangliste steckt also
    # in der Umsatz-Rangliste.
    def _top_codes(rows: list[dict], n: int = 100) -> list[str]:
        ranked = sorted(rows, key=lambda r: float(r.get("net_total") or 0), reverse=True)
        return [r["item_code"] for r in ranked[:n] if r.get("item_code")]

    item_codes = sorted(
        {r["item_code"] for r in invoice_items if r.get("item_code")}
        | set(_top_codes(invoice_items_year))
        | set(_top_codes(invoice_items_prev_year))
    )
    def _fetch_unit_costs() -> tuple[list[dict], list[dict]]:
        if not item_codes:
            return [], []
        rates = frappe.get_all(
            "Item",
            filters=[["name", "in", item_codes]],
            fields=["name", "item_code", "last_purchase_rate"],
            limit_page_length=0,
            ignore_permissions=True,
        )
        boms = frappe.get_all(
            "BOM",
            filters=[["item", "in", item_codes], ["is_active", "=", 1],
                     ["is_default", "=", 1], ["docstatus", "=", 1]],
            fields=["item", "base_total_cost", "total_cost", "quantity"],
            limit_page_length=0,
            ignore_permissions=True,
        )
        bom_costs = []
        for b in boms:
            qty = float(b.get("quantity") or 1) or 1.0
            cost = float(b.get("base_total_cost") or b.get("total_cost") or 0)
            bom_costs.append({"item_code": b["item"], "cost_per_unit": cost / qty})
        return rates, bom_costs

    item_purchase_rates, item_bom_costs = _optional(
        "Stückkosten-Stammdaten", _fetch_unit_costs, ([], []))

    # Top-Einkäufe: Wareneingangspositionen nur für den laufenden Monat — die
    # Belegnamen stehen schon in purchase_receipts (Cutoff reicht weiter zurück).
    month_receipt_names = [
        r["name"] for r in purchase_receipts
        if str(r.get("posting_date") or "") >= month_start
    ]
    purchase_receipt_items = []
    if month_receipt_names:
        purchase_receipt_items = frappe.get_all(
            "Purchase Receipt Item",
            filters=[["parent", "in", month_receipt_names]],
            fields=["item_code", "item_name", "base_net_amount"],
            limit_page_length=0,
            ignore_permissions=True,
        )

    # Positionsanzahl der 5 zuletzt gebuchten Wareneingänge (für die Kosten-Übersicht).
    recent_names = [
        r["name"] for r in sorted(
            purchase_receipts,
            key=lambda r: (str(r.get("posting_date") or ""), r.get("name") or ""),
            reverse=True,
        )[:5]
    ]
    receipt_positions: dict[str, int] = {}
    if recent_names:
        for row in frappe.get_all(
            "Purchase Receipt Item",
            filters=[["parent", "in", recent_names]],
            fields=["parent"],
            limit_page_length=0,
            ignore_permissions=True,
        ):
            receipt_positions[row["parent"]] = receipt_positions.get(row["parent"], 0) + 1

    return {
        "as_of": today.isoformat(),
        "invoices": invoices,
        "to_bill_delivery_notes": dns,
        "open_sales_orders": open_sales_orders,
        "open_purchase_orders": open_purchase_orders,
        "po_receipt_pairs": po_receipt_pairs,
        "work_orders": work_orders,
        "ekt_components": ekt_components,
        "crm": crm,
        "purchase_receipts": purchase_receipts,
        "invoice_items": invoice_items,
        "invoice_items_year": invoice_items_year,
        "invoice_items_prev_year": invoice_items_prev_year,
        "purchase_receipt_items": purchase_receipt_items,
        "item_purchase_rates": item_purchase_rates,
        "item_bom_costs": item_bom_costs,
        "receipt_positions": receipt_positions,
        "prev_year_invoices": prev_year_invoices,
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

    # VOR der Triage entdoppeln: geteilte Postfächer kommen einmal pro verbundenem
    # Nutzer zurück — sonst zahlt jede Dublette auch noch einen Claude-Aufruf.
    all_items = m.dedupe_mail_items(all_items)
    return triage.triage_all(all_items, model=config["anthropic_model"], api_key=anthropic_api_key)


def _attach_todo_trend(computed: dict) -> None:
    """Hängt an computed["todo"] den Vorwochen-Vergleich der überfälligen
    Auftragssumme an (jüngster KPI-Snapshot, der mindestens 7 Tage alt ist).
    Ohne ausreichend alten Snapshot bleibt der Trend einfach weg."""
    todo = computed.get("todo")
    if not todo:
        return
    try:
        today = date.fromisoformat(computed["as_of"])
        rows = frappe.get_all(
            "PCB Board KPI Snapshot",
            filters=[["snapshot_date", "<=", (today - timedelta(days=7)).isoformat()]],
            fields=["snapshot_date", "overdue_net", "overdue_count", "avg_overdue_days"],
            order_by="snapshot_date desc",
            limit_page_length=1,
            ignore_permissions=True,
        )
        if not rows:
            return
        prev = rows[0]
        prev_net = float(prev.get("overdue_net") or 0)
        prev_avg = float(prev.get("avg_overdue_days") or 0)
        todo["trend"] = {
            "prev_date": str(prev["snapshot_date"]),
            "prev_net": round(prev_net, 2),
            "prev_count": int(prev.get("overdue_count") or 0),
            "prev_avg_overdue_days": round(prev_avg, 1),
            "delta_net": round(float(todo.get("overdue_net") or 0) - prev_net, 2),
            "delta_count": len(todo.get("overdue") or []) - int(prev.get("overdue_count") or 0),
            "delta_avg_days": round(float(todo.get("avg_overdue_days") or 0) - prev_avg, 1),
        }
    except Exception:  # noqa: BLE001 — Trend ist Beiwerk, darf den Refresh nie abschießen
        frappe.log_error(title="PCB Board Trend-Berechnung fehlgeschlagen", message=frappe.get_traceback())


def _store_kpi_snapshot(computed: dict) -> None:
    """Schreibt/aktualisiert den heutigen KPI-Snapshot (ein Datensatz pro Tag)."""
    todo = computed.get("todo")
    if not todo:
        return
    try:
        snapshot_date = computed["as_of"]
        name = frappe.db.exists("PCB Board KPI Snapshot", {"snapshot_date": snapshot_date})
        doc = (frappe.get_doc("PCB Board KPI Snapshot", name) if name
               else frappe.new_doc("PCB Board KPI Snapshot"))
        doc.snapshot_date = snapshot_date
        doc.overdue_net = float(todo.get("overdue_net") or 0)
        doc.overdue_count = len(todo.get("overdue") or [])
        doc.avg_overdue_days = float(todo.get("avg_overdue_days") or 0)
        doc.save(ignore_permissions=True)
    except Exception:  # noqa: BLE001 — Snapshot ist Beiwerk, darf den Refresh nie abschießen
        frappe.log_error(title="PCB Board KPI-Snapshot fehlgeschlagen", message=frappe.get_traceback())


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
        _attach_todo_trend(computed)   # liest KPI-Snapshots (frappe) — daher hier, nicht in metrics.py
        _store_kpi_snapshot(computed)  # heutigen Stand für künftige Vorwochen-Vergleiche sichern
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


def attach_work_order_notes(view: dict) -> None:
    """Hängt die vom Team gepflegten Notizen (korrigierter Liefertermin, Bemerkung)
    an die Produktionsaufträge der aktuellen Ansicht. Wird beim Lesen aufgerufen,
    nicht beim Refresh — eine Eingabe steht damit sofort im Board."""
    wos = ((view.get("purchasing") or {}).get("work_orders")) or []
    if not wos:
        return
    rows = frappe.get_all(
        "PCB Board Work Order Note",
        fields=["work_order", "revised_date", "remark", "updated_by"],
        limit_page_length=0,
        ignore_permissions=True,
    )
    by_wo = {r["work_order"]: r for r in rows}
    for wo in wos:
        row = by_wo.get(wo.get("name"))
        wo["note_date"] = str(row["revised_date"]) if (row and row.get("revised_date")) else None
        wo["note_remark"] = (row or {}).get("remark")
        wo["note_by"] = (row or {}).get("updated_by")

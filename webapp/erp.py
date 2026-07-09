"""ERPNext-Daten per REST-API holen (statt über den interaktiven MCP-Connector).

Nutzt dieselben Feldnamen wie die bisherige Routine (siehe scripts/revenue_aggregate.py),
damit build_metrics() unverändert weiterverwendet werden kann. Nur lesend.

Auth: `Authorization: token {ERPNEXT_API_KEY}:{ERPNEXT_API_SECRET}` gegen ERPNEXT_URL.
"""
from __future__ import annotations

import json
import os
from datetime import date

import requests


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def _get(resource: str, filters: list, fields: list[str], limit: int = 0) -> list[dict]:
    base = os.environ["ERPNEXT_URL"].rstrip("/")
    key = os.environ["ERPNEXT_API_KEY"]
    secret = os.environ["ERPNEXT_API_SECRET"]
    resp = requests.get(
        f"{base}/api/resource/{resource}",
        headers={"Authorization": f"token {key}:{secret}"},
        params={
            "filters": json.dumps(filters),
            "fields": json.dumps(fields),
            "limit_page_length": limit,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def fetch_invoices(today: date, baseline_months: int) -> list[dict]:
    y, m = today.year, today.month
    for _ in range(baseline_months):
        y, m = _prev_month(y, m)
    cutoff = date(y, m, 1).isoformat()
    return _get(
        "Sales Invoice",
        filters=[["posting_date", ">=", cutoff], ["docstatus", "=", 1]],
        fields=["name", "customer", "base_net_total", "posting_date", "status"],
    )


def fetch_to_bill_delivery_notes() -> list[dict]:
    rows = _get(
        "Delivery Note",
        filters=[["status", "=", "To Bill"]],
        fields=["name", "customer_name", "base_net_total", "per_billed",
                "posting_date", "custom_tracking_numbers", "custom_ups_shipment_date"],
    )
    for r in rows:
        r["tracking_number"] = r.pop("custom_tracking_numbers", None)
        r["shipment_date"] = r.pop("custom_ups_shipment_date", None)
    return rows


def fetch_open_sales_orders() -> list[dict]:
    rows = _get(
        "Sales Order",
        filters=[["status", "not in", ["Closed", "Cancelled", "Completed"]],
                 ["docstatus", "=", 1]],
        fields=["name", "customer", "base_net_total", "per_billed"],
    )
    out = []
    for r in rows:
        net_open = float(r.get("base_net_total") or 0) * (1.0 - float(r.get("per_billed") or 0) / 100.0)
        out.append({"name": r["name"], "customer": r.get("customer"), "net_open": round(net_open, 2)})
    return out


def fetch_raw(today: date, baseline_months: int) -> dict:
    return {
        "as_of": today.isoformat(),
        "invoices": fetch_invoices(today, baseline_months),
        "to_bill_delivery_notes": fetch_to_bill_delivery_notes(),
        "open_sales_orders": fetch_open_sales_orders(),
    }

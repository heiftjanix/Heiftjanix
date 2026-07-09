"""RefreshManager: stößt einen echten Datenabruf an (Graph + ERPNext + Triage)
und macht den Fortschritt über einen globalen Status allen Nutzern sichtbar
(nicht nur dem, der den Button gedrückt hat).

Alle Geldbeträge werden weiterhin ausschließlich in revenue_aggregate.build_metrics
(Python) berechnet — hier passiert nur Fetch/Orchestrierung.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import io_utils as io           # noqa: E402
import ups_track                         # noqa: E402
import revenue_aggregate as ra           # noqa: E402

from . import auth, erp, graph, triage  # noqa: E402

_LOCK = threading.Lock()
_STATUS = {"state": "idle", "started_by": None, "started_at": None, "generated_at": None}
_METRICS: dict | None = None
_DEMO_PATH = Path(__file__).resolve().parent / "demo_data.json"


def status() -> dict:
    with _LOCK:
        return dict(_STATUS)


def get_last_metrics() -> dict | None:
    with _LOCK:
        return copy.deepcopy(_METRICS) if _METRICS is not None else None


def _now_berlin() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Berlin"))
    except Exception:  # noqa: BLE001 — tzdata evtl. nicht vorhanden
        return datetime.now()


def _fetch_demo() -> dict:
    demo = json.loads(_DEMO_PATH.read_text(encoding="utf-8"))
    erp_data = demo["erp"]
    mail_items = triage.triage_all(demo["mail_messages"])
    return {
        "as_of": date.today().isoformat(),
        "invoices": erp_data["invoices"],
        "to_bill_delivery_notes": erp_data["to_bill_delivery_notes"],
        "open_sales_orders": erp_data["open_sales_orders"],
        "mail": {"window_hours": 24, "items": mail_items},
    }


def _fetch_live(config: dict, session: "auth.SessionData") -> dict:
    today = date.today()
    baseline_months = int(config["forecast"].get("baseline_months", 3))
    raw = erp.fetch_raw(today, baseline_months)

    token = auth.get_access_token(session)
    mail_items: list[dict] = []
    if token:
        window_hours = int(config["email"].get("lookback_hours", 24))
        if today.weekday() == 0:  # Montag -> übers Wochenende zurückblicken
            window_hours = int(config["email"].get("monday_lookback_hours", window_hours))
        raw_messages = graph.fetch_all_mailboxes(
            token, session.email, config["email"].get("extra_mailboxes", []), window_hours
        )
        mail_items = triage.triage_all(raw_messages)
    else:
        sys.stderr.write("[service] Kein gültiges Graph-Token – Postfächer werden übersprungen.\n")

    raw["mail"] = {"window_hours": window_hours if token else None, "items": mail_items}
    return raw


def _run(started_by: str, session: "auth.SessionData | None") -> None:
    global _METRICS
    try:
        config = io.load_config()
        if auth.is_demo_mode() or session is None:
            raw = _fetch_demo()
        else:
            raw = _fetch_live(config, session)

        raw["to_bill_delivery_notes"] = ups_track.resolve_arrivals(
            raw["to_bill_delivery_notes"], config
        )
        metrics = ra.build_metrics(raw, config)
        metrics["dashboard_title"] = config["dashboard"]["title"]
        metrics["company"] = config["company"]
        now = _now_berlin()
        metrics["generated_at"] = now.replace(microsecond=0).isoformat()

        with _LOCK:
            _METRICS = metrics
            _STATUS["generated_at"] = metrics["generated_at"]
    except Exception as exc:  # noqa: BLE001 — Refresh darf die App nie abschießen
        sys.stderr.write(f"[service] Refresh fehlgeschlagen: {exc}\n")
    finally:
        with _LOCK:
            _STATUS["state"] = "idle"


def start_refresh(started_by: str, session: "auth.SessionData | None") -> bool:
    """Startet einen Refresh im Hintergrund. False, wenn schon einer läuft."""
    with _LOCK:
        if _STATUS["state"] == "running":
            return False
        _STATUS["state"] = "running"
        _STATUS["started_by"] = started_by
        _STATUS["started_at"] = _now_berlin().replace(microsecond=0).isoformat()
    thread = threading.Thread(target=_run, args=(started_by, session), daemon=True)
    thread.start()
    return True


def view_for_mailboxes(metrics: dict, allowed_mailboxes: set[str]) -> dict:
    """Blendet Mail-Items auf die für den Nutzer sichtbaren Postfächer ein."""
    view = copy.deepcopy(metrics)
    mail = metrics.get("mail", {})
    items = [i for i in mail.get("items", []) if i.get("mailbox") in allowed_mailboxes]
    view["mail"] = ra._mail_summary({"window_hours": mail.get("window_hours"), "items": items})
    return view

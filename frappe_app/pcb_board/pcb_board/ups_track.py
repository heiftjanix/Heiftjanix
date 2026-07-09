"""UPS-Sendungsverfolgung: ermittelt, ob ein Paket zugestellt ist.

Port von scripts/ups_track.py (Hauptrepo). Unterschied: Zugangsdaten kommen hier
als Parameter (aus frappe.conf, siehe refresh.py) statt aus Umgebungsvariablen/.env
— ups_track.py selbst bleibt frei von frappe-Importen und damit gut testbar.
"""
from __future__ import annotations

import base64
import sys
from datetime import date, datetime

from . import calendar_utils as cal

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

DEFAULT_OAUTH_URL = "https://onlinetools.ups.com/security/v1/oauth/token"
DEFAULT_TRACK_URL = "https://onlinetools.ups.com/api/track/v1/details/"


def get_access_token(client_id: str, client_secret: str, oauth_url: str) -> str | None:
    if not requests:
        return None
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        oauth_url,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "x-merchant-id": client_id,
        },
        data={"grant_type": "client_credentials"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("access_token")


def _parse_ups_date(raw: str | None):
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:8], "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def track_package(tracking_number: str, token: str, track_url: str) -> dict:
    url = track_url.rstrip("/") + "/" + tracking_number
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "transId": f"pcb-{tracking_number}",
            "transactionSrc": "pcb-board",
        },
        params={"locale": "de_DE", "returnSignature": "false"},
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    shipments = body.get("trackResponse", {}).get("shipment", [])
    for shp in shipments:
        for pkg in shp.get("package", []):
            current = pkg.get("currentStatus", {}) or {}
            code = (current.get("type") or current.get("code") or "").upper()
            desc = (current.get("description") or "").lower()
            delivered = code == "D" or "delivered" in desc or "zugestellt" in desc
            del_date = None
            for dd in pkg.get("deliveryDate", []) or []:
                if dd.get("type") in ("DEL", None):
                    del_date = _parse_ups_date(dd.get("date"))
                    break
            if not del_date:
                acts = pkg.get("activity", []) or []
                if acts:
                    del_date = _parse_ups_date(acts[0].get("date"))
            if delivered:
                return {"status": "delivered", "delivered_date": del_date}
            return {"status": "in_transit", "delivered_date": None}
    return {"status": "unknown", "delivered_date": None}


def _fallback(shipment_date: str | None, posting_date: str | None,
              transit_days: int, region: str, extra) -> dict:
    ref = shipment_date or posting_date
    if not ref:
        return {"arrival_status": "unknown", "delivered_date": None, "arrival_method": "none"}
    try:
        ref_date = date.fromisoformat(str(ref)[:10])
    except ValueError:
        return {"arrival_status": "unknown", "delivered_date": None, "arrival_method": "none"}
    eta = cal.add_business_days(ref_date, transit_days, region, extra)
    if date.today() >= eta:
        return {"arrival_status": "delivered", "delivered_date": eta.isoformat(),
                "arrival_method": "fallback"}
    return {"arrival_status": "in_transit", "delivered_date": eta.isoformat(),
            "arrival_method": "fallback"}


def resolve_arrivals(items: list[dict], config: dict,
                      client_id: str | None = None, client_secret: str | None = None) -> list[dict]:
    billing = config["billing"]
    transit_days = int(billing["ups_transit_days"])
    region = config["holidays"]["region"]
    extra = config["holidays"].get("extra", [])
    ups_cfg = config.get("ups", {})
    oauth_url = ups_cfg.get("oauth_url", DEFAULT_OAUTH_URL)
    track_url = ups_cfg.get("track_url", DEFAULT_TRACK_URL)

    token = None
    ups_available = bool(client_id and client_secret and requests)
    if ups_available:
        try:
            token = get_access_token(client_id, client_secret, oauth_url)
        except Exception as exc:  # noqa: BLE001 — jede Störung -> Fallback
            sys.stderr.write(f"[ups_track] OAuth fehlgeschlagen, nutze Fallback: {exc}\n")
            token = None

    out = []
    for it in items:
        item = dict(it)
        tn = (item.get("tracking_number") or "").strip()
        result = None
        if token and tn:
            try:
                r = track_package(tn, token, track_url)
                result = {
                    "arrival_status": r["status"],
                    "delivered_date": r["delivered_date"],
                    "arrival_method": "ups",
                }
            except Exception as exc:  # noqa: BLE001
                sys.stderr.write(f"[ups_track] {tn}: API-Fehler, Fallback: {exc}\n")
                result = None
        if result is None:
            result = _fallback(item.get("shipment_date"), item.get("posting_date"),
                                transit_days, region, extra)
        item.update(result)
        out.append(item)
    return out

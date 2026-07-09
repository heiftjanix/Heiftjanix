"""UPS-Sendungsverfolgung: ermittelt, ob ein Paket zugestellt ist.

Primär über die offizielle UPS Tracking API (OAuth2 client-credentials).
Fällt bei fehlenden Zugangsdaten oder API-Fehlern automatisch auf eine Faustregel
zurück: Versanddatum + N Werktage gilt als zugestellt (N aus config.billing.ups_transit_days).

Zugangsdaten kommen aus den Umgebungsvariablen UPS_CLIENT_ID / UPS_CLIENT_SECRET
(oder einer lokalen .env-Datei zum Testen). Es wird NICHTS geschrieben — reine Abfrage.

CLI:
    python scripts/ups_track.py --input state/to_bill.json --output state/to_bill_enriched.json
Eingabeliste je Element: {name, tracking_number, shipment_date, posting_date}
Ausgabe: gleiche Objekte + {arrival_status, delivered_date, arrival_method}
  arrival_status: "delivered" | "in_transit" | "unknown"
  arrival_method: "ups" | "fallback" | "none"
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import calendar_utils as cal      # noqa: E402
from lib import io_utils as io             # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


def _load_dotenv() -> None:
    """Minimaler .env-Loader (nur fürs lokale Testen; keine Abhängigkeit)."""
    env_path = io.ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


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
    """Rohe UPS-Antwort auf {status, delivered_date} reduzieren."""
    url = track_url.rstrip("/") + "/" + tracking_number
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "transId": f"pcb-{tracking_number}",
            "transactionSrc": "pcb-arbeitsassistent",
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
            # Zustelldatum bevorzugt aus deliveryDate, sonst aus der Aktivität
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


def resolve_arrivals(items: list[dict], config: dict) -> list[dict]:
    _load_dotenv()
    billing = config["billing"]
    transit_days = int(billing["ups_transit_days"])
    region = config["holidays"]["region"]
    extra = config["holidays"].get("extra", [])
    ups_cfg = config["ups"]
    oauth_url = os.environ.get("UPS_OAUTH_URL", ups_cfg["oauth_url"])
    track_url = os.environ.get("UPS_TRACK_URL", ups_cfg["track_url"])
    client_id = os.environ.get("UPS_CLIENT_ID")
    client_secret = os.environ.get("UPS_CLIENT_SECRET")

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


def main() -> None:
    ap = argparse.ArgumentParser(description="UPS-Ankunftsstatus für Lieferscheine.")
    ap.add_argument("--input", help="JSON-Liste (Default: stdin)")
    ap.add_argument("--output", help="Zieldatei (Default: stdout)")
    args = ap.parse_args()

    config = io.load_config()
    if args.input:
        items = io.read_json(args.input)
    else:
        items = json.load(sys.stdin)
    if isinstance(items, dict):
        items = items.get("to_bill_delivery_notes", items.get("items", []))

    enriched = resolve_arrivals(items, config)

    if args.output:
        io.write_json(args.output, enriched)
        methods = {}
        for e in enriched:
            methods[e["arrival_method"]] = methods.get(e["arrival_method"], 0) + 1
        sys.stderr.write(f"[ups_track] {len(enriched)} LS geprüft, Methoden={methods}\n")
    else:
        json.dump(enriched, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

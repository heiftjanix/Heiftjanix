"""Rechen-Pipeline: state/raw.json -> Ankunftsstatus -> Kennzahlen -> Dashboard.

Die Routine ruft dieses Skript auf, NACHDEM Claude die Rohdaten (Outlook wird
separat verarbeitet) via ERPNext-MCP nach state/raw.json geschrieben hat. Alle
Geldbeträge werden ausschließlich hier in Python berechnet.

    python scripts/run_pipeline.py
Erzeugt: state/metrics.json und state/dashboard.html
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import io_utils as io          # noqa: E402
import ups_track                        # noqa: E402
import revenue_aggregate as ra          # noqa: E402
import render_dashboard as rd           # noqa: E402


def main() -> None:
    config = io.load_config()
    raw = io.read_state("raw.json")

    # 1) UPS-Ankunft (live, sonst Fallback) auf die To-Bill-Lieferscheine anwenden
    dns = raw.get("to_bill_delivery_notes", [])
    raw["to_bill_delivery_notes"] = ups_track.resolve_arrivals(dns, config)
    io.write_state("raw.json", raw)

    # 2) Kennzahlen + Prognose
    metrics = ra.build_metrics(raw, config)
    metrics["dashboard_title"] = config["dashboard"]["title"]
    metrics["company"] = config["company"]
    metrics["auto_refresh_minutes"] = config.get("board", {}).get("auto_refresh_minutes", 0)
    # Zeitstempel „Stand" fürs Board (echtes Python -> datetime verfügbar)
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(config.get("timezone", "Europe/Berlin")))
    except Exception:  # noqa: BLE001 — tzdata evtl. nicht vorhanden
        now = datetime.now()
    metrics["generated_at"] = now.replace(microsecond=0).isoformat()
    io.write_state("metrics.json", metrics)

    # 3) Dashboard rendern
    html = rd.render(metrics)
    out = io.STATE_DIR / "dashboard.html"
    out.write_text(html, encoding="utf-8")

    fc = metrics["forecast"]
    b = metrics["billing"]
    print("=== Pipeline fertig ===")
    print(f"Ist (MTD Netto)      : {fc['mtd']:>12,.2f} €")
    print(f"Prognose Monatsende  : {fc['forecast']:>12,.2f} €  ({fc['attainment_pct']*100:.0f} % vom Ziel, {fc['status']})")
    print(f"Lücke zum Ziel       : {fc['gap']:>12,.2f} €")
    print(f"Nötig je Restwerktag : {fc['required_daily']:>12,.2f} €  ({fc['bd_remaining']} Werktage)")
    print(f"Baseline/Werktag     : {metrics['baseline']['baseline_daily']:>12,.2f} €")
    print(f"Abrechnungsbereit    : {b['ready_count']} LS = {metrics['pipeline']['ready_net']:,.2f} € "
          f"(unterwegs {len(b['in_transit'])}, unklar {len(b['unknown'])}, alt {len(b['stale'])})")
    print(f"Dashboard            : {out}")


if __name__ == "__main__":
    main()

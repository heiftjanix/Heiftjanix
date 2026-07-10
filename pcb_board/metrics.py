"""Monatsend-Prognose + Kennzahlen — reine Funktionen, kein frappe-Import.

1:1-Port der Rechenlogik aus scripts/forecast.py + scripts/revenue_aggregate.py
(Hauptrepo). Nimmt hier bereits von ERPNext gelesene Listen von dicts entgegen
(statt state/raw.json), damit refresh.py nur noch frappe.get_all-Resultate
durchreichen muss. Bei Formeländerungen im Original bitte hier nachziehen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date

from . import calendar_utils as cal


@dataclass
class ForecastResult:
    mtd: float
    forecast: float
    target: float
    gap: float
    attainment_pct: float
    bd_elapsed: int
    bd_remaining: int
    bd_total: int
    runrate_daily: float
    baseline_daily: float
    blended_daily: float
    weight: float
    required_daily: float
    forecast_low: float
    forecast_high: float
    status: str

    def to_dict(self) -> dict:
        return asdict(self)


def forecast_month_end(
    mtd: float,
    bd_elapsed: int,
    bd_total: int,
    baseline_daily: float,
    target: float,
    K: int = 5,
    uncertainty_pct: float = 0.15,
    amber_threshold: float = 0.85,
) -> ForecastResult:
    mtd = float(mtd)
    baseline_daily = max(0.0, float(baseline_daily))
    bd_total = max(1, int(bd_total))
    bd_elapsed = max(0, min(int(bd_elapsed), bd_total))
    bd_remaining = bd_total - bd_elapsed

    if bd_elapsed > 0:
        runrate_daily = mtd / bd_elapsed
        weight = min(1.0, bd_elapsed / float(K)) if K > 0 else 1.0
        blended_daily = weight * runrate_daily + (1.0 - weight) * baseline_daily
    else:
        runrate_daily = 0.0
        weight = 0.0
        blended_daily = baseline_daily

    forecast = mtd + blended_daily * bd_remaining

    gap = target - forecast
    attainment = forecast / target if target else 0.0
    required_daily = (target - mtd) / bd_remaining if bd_remaining > 0 else 0.0
    if required_daily < 0:
        required_daily = 0.0

    projected_part = blended_daily * bd_remaining
    band = projected_part * uncertainty_pct * (1.0 - weight + 0.25)
    forecast_low = forecast - band
    forecast_high = forecast + band

    if attainment >= 1.0:
        status = "green"
    elif attainment >= amber_threshold:
        status = "amber"
    else:
        status = "red"

    return ForecastResult(
        mtd=round(mtd, 2),
        forecast=round(forecast, 2),
        target=round(float(target), 2),
        gap=round(gap, 2),
        attainment_pct=round(attainment, 4),
        bd_elapsed=bd_elapsed,
        bd_remaining=bd_remaining,
        bd_total=bd_total,
        runrate_daily=round(runrate_daily, 2),
        baseline_daily=round(baseline_daily, 2),
        blended_daily=round(blended_daily, 2),
        weight=round(weight, 4),
        required_daily=round(required_daily, 2),
        forecast_low=round(max(forecast_low, mtd), 2),
        forecast_high=round(forecast_high, 2),
        status=status,
    )


def _net(row: dict) -> float:
    for key in ("base_net_total", "net_total", "base_total", "total"):
        v = row.get(key)
        if v not in (None, ""):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _pdate(row: dict):
    raw = row.get("posting_date") or row.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def mail_summary(mail: dict | None) -> dict:
    mail = mail or {}
    items = mail.get("items", []) or []

    def is_rel(i):
        return i.get("category") == "relevant"

    boxes: dict[str, dict] = {}
    for i in items:
        mb = i.get("mailbox") or "Posteingang"
        d = boxes.setdefault(mb, {"name": mb, "total": 0, "relevant": 0,
                                  "info": 0, "high_priority": 0})
        d["total"] += 1
        d["relevant" if is_rel(i) else "info"] += 1
        if i.get("priority") == "high":
            d["high_priority"] += 1

    order = {"high": 0, "normal": 1}
    items_sorted = sorted(
        items,
        key=lambda i: (0 if is_rel(i) else 1, order.get(i.get("priority"), 1)),
    )
    return {
        "window_hours": mail.get("window_hours"),
        "total": len(items),
        "relevant": sum(1 for i in items if is_rel(i)),
        "info": sum(1 for i in items if not is_rel(i)),
        "high_priority": sum(1 for i in items if i.get("priority") == "high"),
        "mailboxes": list(boxes.values()),
        "items": items_sorted,
    }


def cost_summary(data: dict, config: dict, today: date) -> dict:
    """Kosten laufender Monat: Wareneingänge (Purchase Receipt, aus ERPNext) plus
    zwei fixe, in PCB Board Settings gepflegte Kostenpunkte (Personal, Miete)."""
    month_start = date(today.year, today.month, 1)
    goods_receipts = 0.0
    for r in data.get("purchase_receipts", []) or []:
        d = _pdate(r)
        if d and month_start <= d <= today:
            goods_receipts += _net(r)

    personnel = float(config.get("personnel_costs_monthly") or 0)
    rent = float(config.get("rent_monthly") or 0)
    total = goods_receipts + personnel + rent
    return {
        "goods_receipts": round(goods_receipts, 2),
        "personnel_costs": round(personnel, 2),
        "rent": round(rent, 2),
        "total": round(total, 2),
    }


def build_metrics(data: dict, config: dict, today: date | None = None) -> dict:
    """data: {as_of, invoices[], to_bill_delivery_notes[], open_sales_orders[], mail{}}.

    config: {company, currency, revenue_target, forecast{...}, holidays{...},
             billing{...}} — dieselben Schlüssel wie config/config.json im Hauptrepo.
    """
    today = today or date.fromisoformat(data["as_of"])
    region = config["holidays"]["region"]
    extra = config["holidays"].get("extra", [])
    target = float(config["revenue_target"])
    fc_cfg = config["forecast"]

    invoices = data.get("invoices", [])
    month_start = date(today.year, today.month, 1)

    daily = defaultdict(float)
    mtd = 0.0
    for inv in invoices:
        d = _pdate(inv)
        if d and month_start <= d <= today:
            amt = _net(inv)
            mtd += amt
            daily[d.isoformat()] += amt

    daily_series = [{"date": k, "net": round(v, 2)} for k, v in sorted(daily.items())]

    n_months = int(fc_cfg.get("baseline_months", 3))
    months = []
    y, m = today.year, today.month
    for _ in range(n_months):
        y, m = _prev_month(y, m)
        months.append((y, m))
    month_totals = {(yy, mm): 0.0 for yy, mm in months}
    for inv in invoices:
        d = _pdate(inv)
        if d and (d.year, d.month) in month_totals:
            month_totals[(d.year, d.month)] += _net(inv)
    trailing_net = sum(month_totals.values())
    trailing_bd = sum(
        cal.business_days_in_month(yy, mm, region, extra) for yy, mm in months
    ) or 1
    baseline_daily = trailing_net / trailing_bd

    bd_total = cal.business_days_in_month(today.year, today.month, region, extra)
    bd_elapsed = cal.business_days_elapsed(today, region, extra)

    fc = forecast_month_end(
        mtd=mtd,
        bd_elapsed=bd_elapsed,
        bd_total=bd_total,
        baseline_daily=baseline_daily,
        target=target,
        K=int(fc_cfg.get("confidence_days_K", 5)),
        uncertainty_pct=float(fc_cfg.get("uncertainty_pct", 0.15)),
        amber_threshold=float(fc_cfg.get("amber_threshold", 0.85)),
    )

    stale_days = int(config["billing"]["stale_delivery_note_days"])
    ready, in_transit, unknown, stale = [], [], [], []
    pipeline_ready_net = pipeline_transit_net = 0.0
    for dn in data.get("to_bill_delivery_notes", []):
        d = _pdate(dn)
        open_net = _net(dn) * (1.0 - float(dn.get("per_billed", 0) or 0) / 100.0)
        age = (today - d).days if d else None
        item = {
            "name": dn.get("name"),
            "customer": dn.get("customer_name") or dn.get("customer"),
            "net_open": round(open_net, 2),
            "posting_date": d.isoformat() if d else None,
            "age_days": age,
            "tracking_number": dn.get("tracking_number"),
            "arrival_status": dn.get("arrival_status", "unknown"),
            "delivered_date": dn.get("delivered_date"),
            "arrival_method": dn.get("arrival_method"),
        }
        is_stale = age is not None and age > stale_days
        status = item["arrival_status"]
        if is_stale:
            stale.append(item)
        if status == "delivered":
            ready.append(item)
            pipeline_ready_net += open_net
        elif status == "in_transit":
            in_transit.append(item)
            pipeline_transit_net += open_net
        else:
            unknown.append(item)

    ready.sort(key=lambda x: x["net_open"], reverse=True)
    stale.sort(key=lambda x: (x["age_days"] or 0), reverse=True)

    open_so_net = round(
        sum(float(so.get("net_open", 0) or 0) for so in data.get("open_sales_orders", [])),
        2,
    )

    tips = []
    if pipeline_ready_net > 0:
        tips.append({
            "title": "Sofort abrechnen",
            "impact_eur": round(pipeline_ready_net, 2),
            "detail": f"{len(ready)} zugestellte, noch nicht berechnete Lieferschein(e) "
                      f"– direkt in Umsatz umwandelbar.",
        })
    if fc.gap > 0:
        inv_count = len(daily_series) and sum(1 for i in invoices
                                              if (_pdate(i) and month_start <= _pdate(i) <= today))
        avg_inv = (mtd / inv_count) if inv_count else baseline_daily
        n_needed = int(fc.gap / avg_inv) + 1 if avg_inv > 0 else 0
        tips.append({
            "title": "Lücke zum Monatsziel",
            "impact_eur": round(fc.gap, 2),
            "detail": f"Prognose {fc.attainment_pct*100:.0f} % vom Ziel. "
                      f"Rest ≈ {n_needed} Aufträge à Ø {avg_inv:,.0f} € "
                      f"oder {fc.required_daily:,.0f} €/Werktag.".replace(",", "."),
        })
    if pipeline_transit_net > 0:
        tips.append({
            "title": "Bald abrechenbar",
            "impact_eur": round(pipeline_transit_net, 2),
            "detail": f"{len(in_transit)} Lieferschein(e) unterwegs – nach Zustellung abrechnen.",
        })
    if open_so_net > 0:
        tips.append({
            "title": "Offene Aufträge beschleunigen",
            "impact_eur": open_so_net,
            "detail": "Noch nicht ausgelieferte/berechnete Auftragswerte – "
                      "Lieferung → Rechnung vorziehen.",
        })
    if stale:
        tips.append({
            "title": "Alte Lieferscheine aufräumen",
            "impact_eur": round(sum(s["net_open"] for s in stale), 2),
            "detail": f"{len(stale)} offene Lieferschein(e) älter als "
                      f"{stale_days} Tage – liegen gebliebener Umsatz.",
        })
    tips.sort(key=lambda t: t["impact_eur"], reverse=True)

    return {
        "as_of": today.isoformat(),
        "company": config["company"],
        "currency": config["currency"],
        "target": target,
        "mail": mail_summary(data.get("mail")),
        "costs": cost_summary(data, config, today),
        "forecast": fc.to_dict(),
        "daily_series": daily_series,
        "baseline": {
            "trailing_months": [f"{yy}-{mm:02d}" for yy, mm in months],
            "trailing_net": round(trailing_net, 2),
            "baseline_daily": round(baseline_daily, 2),
        },
        "pipeline": {
            "ready_net": round(pipeline_ready_net, 2),
            "in_transit_net": round(pipeline_transit_net, 2),
            "open_so_net": open_so_net,
            "coverage_after_forecast": round(
                fc.forecast + pipeline_ready_net + pipeline_transit_net, 2
            ),
        },
        "billing": {
            "ready": ready,
            "in_transit": in_transit,
            "unknown": unknown,
            "stale": stale,
            "ready_count": len(ready),
            "total_open_count": len(ready) + len(in_transit) + len(unknown),
        },
        "tips": tips,
    }

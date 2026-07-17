"""Monatsend-Prognose + Kennzahlen — reine Funktionen, kein frappe-Import.

1:1-Port der Rechenlogik aus scripts/forecast.py + scripts/revenue_aggregate.py
(Hauptrepo). Nimmt hier bereits von ERPNext gelesene Listen von dicts entgegen
(statt state/raw.json), damit refresh.py nur noch frappe.get_all-Resultate
durchreichen muss. Bei Formeländerungen im Original bitte hier nachziehen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta

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


def top_products(data: dict, limit: int = 5) -> list[dict]:
    """Top-N Produkte nach Netto-Umsatz im laufenden Monat, aus den bereits auf
    den laufenden Monat gefilterten Rechnungspositionen (Sales Invoice Item)."""
    totals: dict[str, dict] = {}
    for row in data.get("invoice_items", []) or []:
        code = row.get("item_code") or row.get("item_name") or "?"
        entry = totals.setdefault(code, {
            "item_code": code,
            "item_name": row.get("item_name") or code,
            "net_total": 0.0,
        })
        entry["net_total"] += float(row.get("base_net_amount") or 0)
    ranked = sorted(totals.values(), key=lambda r: r["net_total"], reverse=True)
    for r in ranked:
        r["net_total"] = round(r["net_total"], 2)
    return ranked[:limit]


def todo_orders(data: dict, today: date) -> dict:
    """Offene Aufträge nach Liefertermin: überfällig (heute oder überschritten)
    und diese Woche fällig (Rest der laufenden Kalenderwoche, Mo–So). Aufträge
    ohne Liefertermin oder ohne offenen Restwert werden übersprungen."""
    week_end = today - timedelta(days=today.weekday()) + timedelta(days=6)
    overdue, due_this_week = [], []
    for so in data.get("open_sales_orders", []) or []:
        raw = so.get("delivery_date")
        if not raw:
            continue
        try:
            d = date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
        net_open = float(so.get("net_open", 0) or 0)
        if net_open <= 0:
            continue
        item = {
            "name": so.get("name"),
            "customer": so.get("customer_name") or so.get("customer"),
            "delivery_date": d.isoformat(),
            "net_open": round(net_open, 2),
            "days_overdue": (today - d).days,
        }
        if d <= today:
            overdue.append(item)
        elif d <= week_end:
            due_this_week.append(item)
    overdue.sort(key=lambda x: x["delivery_date"])
    due_this_week.sort(key=lambda x: x["delivery_date"])
    return {
        "overdue": overdue,
        "due_this_week": due_this_week,
        "overdue_net": round(sum(i["net_open"] for i in overdue), 2),
        "due_this_week_net": round(sum(i["net_open"] for i in due_this_week), 2),
    }


def top_purchases(data: dict, limit: int = 5) -> list[dict]:
    """Top-N Einkaufsartikel nach Netto-Warenwert im laufenden Monat, aus den
    bereits auf den laufenden Monat gefilterten Wareneingangspositionen
    (Purchase Receipt Item) — Gegenstück zu top_products()."""
    totals: dict[str, dict] = {}
    for row in data.get("purchase_receipt_items", []) or []:
        code = row.get("item_code") or row.get("item_name") or "?"
        entry = totals.setdefault(code, {
            "item_code": code,
            "item_name": row.get("item_name") or code,
            "net_total": 0.0,
        })
        entry["net_total"] += float(row.get("base_net_amount") or 0)
    ranked = sorted(totals.values(), key=lambda r: r["net_total"], reverse=True)
    for r in ranked:
        r["net_total"] = round(r["net_total"], 2)
    return ranked[:limit]


def top_customers(data: dict, today: date, limit: int = 5) -> list[dict]:
    """Top-N Kunden nach Netto-Rechnungsumsatz im laufenden Monat, mit Anteil am
    Monatsumsatz (macht Kundenkonzentration/Klumpenrisiko sichtbar)."""
    month_start = date(today.year, today.month, 1)
    totals: dict[str, float] = defaultdict(float)
    mtd_total = 0.0
    for inv in data.get("invoices", []) or []:
        d = _pdate(inv)
        if d and month_start <= d <= today:
            amt = _net(inv)
            totals[inv.get("customer_name") or inv.get("customer") or "?"] += amt
            mtd_total += amt
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{
        "customer": name,
        "net_total": round(amt, 2),
        "share_pct": round(amt / mtd_total, 4) if mtd_total else 0.0,
    } for name, amt in ranked]


def top_suppliers(data: dict, today: date, limit: int = 5) -> list[dict]:
    """Top-N Lieferanten nach Netto-Einkaufswert (Wareneingänge) im laufenden
    Monat, mit Anteil am Monats-Wareneingang (macht Lieferantenabhängigkeit
    sichtbar) — Gegenstück zu top_customers()."""
    month_start = date(today.year, today.month, 1)
    totals: dict[str, float] = defaultdict(float)
    month_total = 0.0
    for pr in data.get("purchase_receipts", []) or []:
        d = _pdate(pr)
        if d and month_start <= d <= today:
            amt = _net(pr)
            totals[pr.get("supplier_name") or pr.get("supplier") or "?"] += amt
            month_total += amt
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{
        "supplier": name,
        "net_total": round(amt, 2),
        "share_pct": round(amt / month_total, 4) if month_total else 0.0,
    } for name, amt in ranked]


def product_margins(data: dict, limit: int = 5) -> list[dict]:
    """Deckungsbeitrag der Top-Umsatzprodukte des laufenden Monats: Umsatz minus
    Wareneinsatz, geschätzt als verkaufte Menge × Stückkosten. Stückkosten-Quelle:
    letzter Einkaufspreis (Item.last_purchase_rate); fehlt der (Eigenfertigung),
    der Wert der aktiven Standard-Stückliste je Einheit (BOM). cost_source sagt,
    welche Quelle griff ("ek" | "bom"); ganz ohne beides bleiben Kosten/Marge
    leer statt 100 % zu suggerieren."""
    rates: dict[str, float] = {}
    for row in data.get("item_purchase_rates", []) or []:
        code = row.get("item_code") or row.get("name")
        if code:
            rates[code] = float(row.get("last_purchase_rate") or 0)
    bom_rates: dict[str, float] = {}
    for row in data.get("item_bom_costs", []) or []:
        code = row.get("item_code")
        if code:
            bom_rates[code] = float(row.get("cost_per_unit") or 0)

    totals: dict[str, dict] = {}
    for row in data.get("invoice_items", []) or []:
        code = row.get("item_code") or row.get("item_name") or "?"
        entry = totals.setdefault(code, {
            "item_code": code,
            "item_name": row.get("item_name") or code,
            "revenue": 0.0,
            "qty": 0.0,
        })
        entry["revenue"] += float(row.get("base_net_amount") or 0)
        entry["qty"] += float(row.get("qty") or 0)

    out = []
    for entry in sorted(totals.values(), key=lambda r: r["revenue"], reverse=True)[:limit]:
        rate = rates.get(entry["item_code"]) or 0.0
        source = "ek"
        if rate <= 0:
            rate = bom_rates.get(entry["item_code"]) or 0.0
            source = "bom"
        entry["revenue"] = round(entry["revenue"], 2)
        entry["qty"] = round(entry["qty"], 2)
        if rate > 0 and entry["qty"] > 0:
            cost = entry["qty"] * rate
            margin = entry["revenue"] - cost
            entry["cost"] = round(cost, 2)
            entry["margin"] = round(margin, 2)
            entry["margin_pct"] = round(margin / entry["revenue"], 4) if entry["revenue"] else 0.0
            entry["cost_source"] = source
        else:
            entry["cost"] = None
            entry["margin"] = None
            entry["margin_pct"] = None
            entry["cost_source"] = None
        out.append(entry)
    return out


def prev_year_month(data: dict, today: date) -> dict:
    """Vorjahresvergleich (aus data["prev_year_invoices"], Jahresanfang Vorjahr
    bis Ende des gleichen Monats): Gesamtsumme des gleichen Monats, Summe bis
    zum gleichen Kalendertag (fairer Monatsvergleich) und Jahressumme bis
    Monatsende (Vergleichsbasis für den laufenden Jahresumsatz)."""
    total = 0.0
    mtd_same_day = 0.0
    ytd_through_month_end = 0.0
    for inv in data.get("prev_year_invoices", []) or []:
        d = _pdate(inv)
        if not d:
            continue
        amt = _net(inv)
        ytd_through_month_end += amt
        if d.month == today.month:
            total += amt
            if d.day <= today.day:
                mtd_same_day += amt
    return {
        "year": today.year - 1,
        "month": today.month,
        "total": round(total, 2),
        "mtd_same_day": round(mtd_same_day, 2),
        "ytd_through_month_end": round(ytd_through_month_end, 2),
    }


def profit_history(data: dict, config: dict, today: date) -> dict:
    """Gewinn/Verlust je Monat des laufenden Jahres: Netto-Rechnungsumsatz minus
    Wareneingänge des jeweiligen Monats minus fixe Kosten (Personal + Miete, als
    konstant angenommen — Annahme laut Anforderung). Vortrag = Summe der
    ABGESCHLOSSENEN Monate; ytd_profit zusätzlich inkl. laufendem Teilmonat.
    Setzt voraus, dass invoices/purchase_receipts bis Jahresanfang zurückreichen."""
    fixed = float(config.get("personnel_costs_monthly") or 0) + float(config.get("rent_monthly") or 0)

    revenue: dict[int, float] = defaultdict(float)
    for inv in data.get("invoices", []) or []:
        d = _pdate(inv)
        if d and d.year == today.year and d <= today:
            revenue[d.month] += _net(inv)
    goods: dict[int, float] = defaultdict(float)
    for pr in data.get("purchase_receipts", []) or []:
        d = _pdate(pr)
        if d and d.year == today.year and d <= today:
            goods[d.month] += _net(pr)

    months = []
    carry = 0.0
    for m in range(1, today.month + 1):
        total_costs = goods[m] + fixed
        profit = revenue[m] - total_costs
        months.append({
            "month": f"{today.year}-{m:02d}",
            "revenue": round(revenue[m], 2),
            "goods_receipts": round(goods[m], 2),
            "fixed_costs": round(fixed, 2),
            "profit": round(profit, 2),
            # Umsatz-zu-Kosten-Verhältnis fürs Monats-Ranking (>1 = profitabel);
            # ohne Kosten kein sinnvolles Verhältnis -> None, landet im Rang hinten.
            "ratio": round(revenue[m] / total_costs, 4) if total_costs > 0 else None,
            "is_current": m == today.month,
        })
        if m < today.month:
            carry += profit
    for rank, mo in enumerate(
        sorted(months, key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0))), start=1
    ):
        mo["rank"] = rank if mo["ratio"] is not None else None
    return {
        "months": months,
        "carry_forward": round(carry, 2),
        "ytd_profit": round(carry + months[-1]["profit"], 2) if months else 0.0,
        "fixed_costs_monthly": round(fixed, 2),
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
        "top_products": top_products(data),
        "top_purchases": top_purchases(data),
        "top_customers": top_customers(data, today),
        "top_suppliers": top_suppliers(data, today),
        "product_margins": product_margins(data),
        "prev_year": prev_year_month(data, today),
        # Umsatz laufendes Jahr (Jahresanfang bis heute) — Gegenstück zu
        # prev_year.ytd_through_month_end.
        "ytd_revenue": round(sum(
            _net(inv) for inv in invoices
            if (d := _pdate(inv)) and d.year == today.year and d <= today
        ), 2),
        "todo": todo_orders(data, today),
        "profit_history": profit_history(data, config, today),
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

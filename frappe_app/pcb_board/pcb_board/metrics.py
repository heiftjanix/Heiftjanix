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


def _to_date(raw):
    """Datum aus einem Feldwert (date oder ISO-String); None wenn leer/unlesbar."""
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _pdate(row: dict):
    return _to_date(row.get("posting_date") or row.get("date"))


def _median(values) -> float:
    """Median einer nicht-leeren Zahlenliste (unsortiert erlaubt)."""
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def dedupe_mail_items(items: list[dict] | None) -> list[dict]:
    """Dieselbe Mail einmal je Postfach — nicht einmal je verbundenem Nutzer.

    Jeder verbundene Nutzer liest sein EIGENES Postfach und zusätzlich ALLE
    geteilten Postfächer (bestellung@, anfrage@, …). Eine Mail in einem geteilten
    Postfach kam damit einmal pro Token zurück: bei drei verbundenen Nutzern stand
    sie dreimal im Board und wurde dreimal triagiert.

    Schlüssel ist Postfach + Message-ID. Die gleiche Mail in ZWEI verschiedenen
    Postfächern bleibt erhalten — sie liegt dort auch wirklich zweimal und muss in
    beiden bearbeitet werden. Einträge ohne jede ID bleiben unangetastet.
    """
    seen = set()
    out = []
    for i in items or []:
        mailbox = str(i.get("mailbox_email") or i.get("mailbox") or "").strip().lower()
        mid = str(i.get("internet_message_id") or i.get("graph_id") or "").strip()
        if not mid:
            out.append(i)
            continue
        key = (mailbox, mid)
        if key in seen:
            continue
        seen.add(key)
        out.append(i)
    return out


def mail_summary(mail: dict | None) -> dict:
    mail = mail or {}
    items = dedupe_mail_items(mail.get("items", []))

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
    # Anteil am Gesamtwert ALLER Positionen des Zeitraums (nicht nur der Top-N) —
    # sonst summierten sich die Anteile in der Tabelle immer auf 100 %.
    grand = sum(r["net_total"] for r in totals.values())
    ranked = sorted(totals.values(), key=lambda r: r["net_total"], reverse=True)
    for r in ranked:
        r["share_pct"] = round(r["net_total"] / grand, 4) if grand else 0.0
        r["net_total"] = round(r["net_total"], 2)
    return ranked[:limit]


def todo_orders(data: dict, today: date, work_orders: list[dict] | None = None) -> dict:
    """Offene Aufträge nach Liefertermin: überfällig (heute oder überschritten)
    und diese Woche fällig (Rest der laufenden Kalenderwoche, Mo–So). Aufträge
    ohne Liefertermin, ohne offenen Restwert oder bereits vollständig ausgeliefert
    (Lieferschein gebucht) werden übersprungen — letztere stehen bei den
    ausgehenden Paketen.

    work_orders (aus work_order_material): hängt je Auftrag die verknüpften
    Produktionsaufträge samt Materialstand an — damit im Board sichtbar ist, ob
    ein Liefertermin überhaupt gehalten werden kann.
    """
    by_so: dict[str, list[dict]] = defaultdict(list)
    for wo in work_orders or []:
        so = wo.get("sales_order")
        if so:
            by_so[so].append({
                "name": wo.get("name"),
                "item_code": wo.get("production_item"),
                "item_name": wo.get("item_name"),
                "qty": wo.get("qty"),
                "status": wo.get("status"),
                "material_ok": bool(wo.get("material_ok")),
                "complete_on": wo.get("complete_on"),
                "missing_count": len(wo.get("missing_items") or []),
                "awaiting": wo.get("awaiting") or [],
            })

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
        # Ist zu einem Auftrag schon ein Lieferschein gebucht, gehört der geliefert
        # Teil nicht mehr hierher — er steckt bei den ausgehenden Paketen. Ein
        # vollständig ausgelieferter Auftrag verschwindet deshalb komplett aus der
        # Liste, auch wenn die Rechnung noch offen ist.
        #
        # TEILLIEFERUNGEN bleiben stehen: der Restwert ist noch nicht beim Kunden
        # und keine andere Liste zeigt ihn. Sie werden als „teilgeliefert x %"
        # markiert; wer sie ruhen lassen will, setzt die Wiedervorlage — dafür ist
        # das Feld da.
        delivered_pct = float(so.get("delivered_pct") or 0)
        if delivered_pct >= 99.995:
            continue
        # Maßstab dieser Liste ist der noch nicht AUSGELIEFERTE Wert. Ältere
        # Cache-Stände kennen das Feld nicht, dort gilt weiter der offene
        # (unberechnete) Wert.
        net_undelivered = so.get("net_undelivered")
        if net_undelivered is None:
            net_undelivered = so.get("net_open", 0)
        net_open = float(net_undelivered or 0)
        if net_open <= 0:
            continue
        # Die Wiedervorlage entscheidet, OB der Auftrag jetzt in der Liste steht:
        # ist eine gesetzt, zählt sie statt des Liefertermins. Ein verzögerter
        # Auftrag mit Wiedervorlage in drei Wochen verschwindet damit bis dahin aus
        # der Liste — genau dafür ist das Feld da. Der Liefertermin bleibt
        # unangetastet und bestimmt weiter Status und Gruppierung, damit die
        # Kacheln „überfällig"/„diese Woche" die Zusage an den Kunden abbilden und
        # nicht die interne Wiedervorlage.
        followup = _to_date(so.get("followup_date"))
        ref = followup or d
        if ref > week_end:
            continue
        wos = by_so.get(so.get("name")) or []
        if d < today:
            due_state = "overdue"
        elif d == today:
            due_state = "today"
        elif d <= week_end:
            due_state = "week"
        else:
            # Nur wegen der Wiedervorlage in der Liste — der Liefertermin liegt
            # noch weiter vorne.
            due_state = "later"
        item = {
            "name": so.get("name"),
            "customer": so.get("customer_name") or so.get("customer"),
            "delivery_date": d.isoformat(),
            # Wiedervorlage aus dem Auftrag (Custom Field), vom Team gepflegt.
            "followup_date": followup.isoformat() if followup else None,
            "listed_by": "followup" if (followup and followup != d) else "delivery",
            "due_state": due_state,
            "net_open": round(net_open, 2),
            "delivered_pct": round(delivered_pct, 2),
            "days_overdue": (today - d).days,
            "work_orders": wos,
            "material_ok": bool(wos) and all(w["material_ok"] for w in wos),
        }
        if d <= today:
            overdue.append(item)
        else:
            due_this_week.append(item)
    overdue.sort(key=lambda x: x["delivery_date"])
    due_this_week.sort(key=lambda x: x["delivery_date"])
    avg_overdue_days = (
        round(sum(i["days_overdue"] for i in overdue) / len(overdue), 1) if overdue else 0.0
    )
    return {
        "overdue": overdue,
        "due_this_week": due_this_week,
        "overdue_net": round(sum(i["net_open"] for i in overdue), 2),
        "due_this_week_net": round(sum(i["net_open"] for i in due_this_week), 2),
        "avg_overdue_days": avg_overdue_days,
    }


def recent_receipts(data: dict, limit: int = 5) -> list[dict]:
    """Die zuletzt gebuchten Wareneingänge (Purchase Receipt) mit Positionsanzahl.
    positions kommt aus data["receipt_positions"] (name -> Anzahl), von refresh.py
    befüllt; fehlt der Eintrag, bleibt die Positionszahl None."""
    positions = data.get("receipt_positions") or {}
    rows = [r for r in (data.get("purchase_receipts") or []) if _pdate(r)]
    rows.sort(key=lambda r: (_pdate(r), r.get("name") or ""), reverse=True)
    out = []
    for r in rows[:limit]:
        out.append({
            "name": r.get("name"),
            "supplier": r.get("supplier_name") or r.get("supplier") or "",
            "positions": positions.get(r.get("name")),
            "net_total": round(_net(r), 2),
            "posting_date": _pdate(r).isoformat(),
        })
    return out


def supplier_lead_times(data: dict) -> dict:
    """Lieferzeit je Lieferant in Tagen (Median) aus abgeschlossenen Vorgängen:
    Bestelldatum -> ERSTER Wareneingang zur Bestellung. Der erste Wareneingang ist
    der Maßstab, weil Teillieferungen dieselbe Bestellung sonst mehrfach und mit
    künstlich langer Laufzeit zählen würden. Median statt Mittelwert, damit ein
    einzelner Ausreißer (Sonderbestellung, Rückstand) die Erwartung nicht kippt.

    data["po_receipt_pairs"]: [{purchase_order, supplier, order_date, receipt_date}]
    """
    first: dict[str, dict] = {}
    for row in data.get("po_receipt_pairs") or []:
        po = row.get("purchase_order")
        od, rd = _to_date(row.get("order_date")), _to_date(row.get("receipt_date"))
        if not po or not od or not rd or rd < od:
            continue
        cur = first.get(po)
        if cur is None or rd < cur["receipt_date"]:
            first[po] = {"supplier": row.get("supplier") or "", "order_date": od, "receipt_date": rd}

    by_supplier: dict[str, list[int]] = defaultdict(list)
    all_days: list[int] = []
    for rec in first.values():
        days = (rec["receipt_date"] - rec["order_date"]).days
        all_days.append(days)
        if rec["supplier"]:
            by_supplier[rec["supplier"]].append(days)
    return {
        "per_supplier": {
            sup: {"median_days": round(_median(v), 1), "samples": len(v)}
            for sup, v in by_supplier.items()
        },
        "overall_median_days": round(_median(all_days), 1) if all_days else None,
        "samples": len(all_days),
    }


def _pick_ekt(rows: list[dict] | None, wo_name: str | None) -> dict | None:
    """Passende Einkaufstool-Anfrage (EKT) zu einem fehlenden Artikel: bevorzugt
    die, in der dieser Fertigungsauftrag ausdrücklich genannt ist, sonst die
    neueste — eine alte Anfrage sagt weniger über den aktuellen Stand."""
    if not rows:
        return None
    named = [r for r in rows if wo_name and wo_name in (r.get("work_orders_text") or "")]
    pool = named or rows
    best = sorted(pool, key=lambda r: (r.get("created") or "", r.get("ekt") or ""))[-1]
    return dict(best, match="work_order" if named else "item")


def work_order_material(data: dict, po_rows: list[dict]) -> dict:
    """Ordnet den erwarteten Wareneingängen die Fertigungsaufträge zu, für die das
    Material gedacht ist, und bestimmt je Auftrag die LETZTE nötige Lieferung — ab
    ihr ist der Auftrag material-komplett und kann bearbeitet werden.

    Bestand und Zulieferung werden dabei nur EINMAL verplant: die Aufträge werden
    nach Bedarfstermin abgearbeitet (frühester zuerst) und verbrauchen aus einem
    gemeinsamen Topf. Ohne diese Reihenfolge würde dieselbe knappe Menge mehreren
    Aufträgen gleichzeitig als Deckung gutgeschrieben, und das Board würde zwei
    Aufträge als „wird frei" melden, obwohl das Material nur für einen reicht.

    Annahme: ein Bestandstopf je Artikel (die Aufträge melden denselben Bestand des
    Quelllagers). Reservierungen anderer Vorgänge sind darin nicht abgebildet.
    """
    # Zulieferung je Artikel, nach erwartetem Termin — ohne Termin ans Ende.
    incoming: dict[str, list[dict]] = defaultdict(list)
    for row in po_rows:
        for it in row.get("items") or []:
            code = it.get("item_code")
            if not code:
                continue
            incoming[code].append({
                "po": row.get("name"),
                "supplier": row.get("supplier"),
                "expected_date": row.get("expected_date"),
                "item_name": it.get("item_name") or code,
                "qty": float(it.get("open_qty") or 0),
            })
    for lst in incoming.values():
        lst.sort(key=lambda r: (r["expected_date"] is None, r["expected_date"] or "", r["po"] or ""))

    # Einkaufstool-Anfragen je Artikel — greifen bei fehlendem, nicht bestelltem
    # Material als Hinweis „liegt schon im Einkauf".
    ekt_by_item: dict[str, list[dict]] = defaultdict(list)
    for row in data.get("ekt_components") or []:
        if row.get("item_code"):
            ekt_by_item[row["item_code"]].append(row)

    # Bestandstopf — LIVE aus Bin (Artikel + Lager). Der im Fertigungsauftrag
    # gespeicherte available_qty_at_source_warehouse ist nur ein Schnappschuss vom
    # letzten Speichern des Auftrags: ein danach gebuchter Wareneingang taucht dort
    # nie auf, und das Board hielt bereits gelieferte Artikel weiter für fehlend.
    # Der Schnappschuss bleibt nur Notnagel, falls die Bin-Abfrage ausfällt.
    bins: dict[tuple[str, str], float] = {}
    bin_total: dict[str, float] = defaultdict(float)
    for b in data.get("stock_bins") or []:
        code = b.get("item_code")
        if not code:
            continue
        qty = float(b.get("actual_qty") or 0)
        key = (code, b.get("warehouse") or "")
        bins[key] = bins.get(key, 0.0) + qty
        bin_total[code] += qty
    use_bins = bool(bins)

    snapshot: dict[str, float] = {}
    if not use_bins:
        for wo in data.get("work_orders") or []:
            for it in wo.get("required_items") or []:
                code = it.get("item_code")
                if code:
                    snapshot[code] = max(snapshot.get(code, 0.0), float(it.get("available_qty") or 0))

    stock: dict[tuple[str, str], float] = {}

    def stock_key(code: str, warehouse) -> tuple[str, str]:
        # Ohne Bin-Daten wird nur je Artikel gerechnet (ein Topf, wie bisher).
        return (code, (warehouse or "") if use_bins else "")

    def stock_left(code: str, warehouse) -> float:
        """Noch nicht verplanter Bestand. Beim ersten Zugriff aus Bin befüllt —
        danach zehren die Aufträge in Bedarfsreihenfolge davon ab."""
        key = stock_key(code, warehouse)
        if key not in stock:
            if not use_bins:
                stock[key] = snapshot.get(code, 0.0)
            elif warehouse:
                stock[key] = bins.get((code, warehouse), 0.0)
            else:
                # Position ohne Quelllager: Bestand über alle Lager
                stock[key] = bin_total.get(code, 0.0)
        return stock[key]

    def need_date(wo: dict) -> str:
        return wo.get("planned_start_date") or wo.get("expected_delivery_date") or "9999-12-31"

    wos = sorted(data.get("work_orders") or [],
                 key=lambda w: (need_date(w), w.get("name") or ""))

    by_po: dict[str, dict] = {}
    out = []
    for wo in wos:
        links = []          # (po, item_code, expected_date) — was dieser Auftrag zieht
        missing = []        # Artikel ohne jede Deckung (Bestand + Bestellungen)
        positions = []      # JEDE Stücklistenposition mit ihrem Zustand
        from_stock_only = True
        for it in wo.get("required_items") or []:
            code = it.get("item_code")
            if not code:
                continue
            required = float(it.get("required_qty") or 0)
            transferred = float(it.get("transferred_qty") or 0)
            need = required - transferred
            # Zustand je Position: done = schon in der Fertigung, stock = liegt am
            # Lager, incoming = kommt mit einer Bestellung, missing = ungedeckt.
            pos = {
                "item_code": code,
                "item_name": it.get("item_name") or code,
                "required_qty": round(required, 2),
                "transferred_qty": round(transferred, 2),
                "open_qty": round(max(need, 0.0), 2),
                "from_stock": 0.0,
                "incoming": [],
                "short_qty": 0.0,
                "ekt": None,
                "state": "done",
            }
            positions.append(pos)
            if need <= 1e-9:
                continue
            wh = it.get("source_warehouse")
            take = min(need, max(stock_left(code, wh), 0.0))
            stock[stock_key(code, wh)] = stock_left(code, wh) - take
            need -= take
            pos["from_stock"] = round(take, 2)
            if need <= 1e-9:
                pos["state"] = "stock"
                continue
            from_stock_only = False
            for inc in incoming.get(code, []):
                if inc["qty"] <= 1e-9:
                    continue
                use = min(need, inc["qty"])
                inc["qty"] -= use
                need -= use
                pos["incoming"].append({
                    "po": inc["po"],
                    "supplier": inc.get("supplier") or "",
                    "expected_date": inc["expected_date"],
                    "qty": round(use, 2),
                    "is_last": False,
                })
                links.append({"po": inc["po"], "item_code": code,
                              "supplier": inc.get("supplier"),
                              "item_name": inc.get("item_name") or code,
                              "expected_date": inc["expected_date"]})
                if need <= 1e-9:
                    break
            pos["state"] = "incoming"
            if need > 1e-9:
                ekt = _pick_ekt(ekt_by_item.get(code), wo.get("name"))
                pos["state"] = "missing"
                pos["short_qty"] = round(need, 2)
                pos["ekt"] = ekt["ekt"] if ekt else None
                missing.append({"item_code": code,
                                "item_name": it.get("item_name") or code,
                                "short_qty": round(need, 2),
                                "ekt": ekt["ekt"] if ekt else None,
                                "ekt_created": ekt.get("created") if ekt else None,
                                "ekt_match": ekt.get("match") if ekt else None})

        # Material-komplett nur, wenn nichts fehlt UND jede genutzte Lieferung
        # einen Termin hat — ohne Termin ist kein „ab wann" nennbar.
        complete = not missing
        dates = [l["expected_date"] for l in links]
        undated = any(d is None for d in dates)
        complete_on = max(dates) if (complete and dates and not undated) else None
        complete_po = None
        if complete_on is not None:
            # die späteste nötige Lieferung schließt den Auftrag ab
            for l in links:
                if l["expected_date"] == complete_on:
                    complete_po = l["po"]

        for pos in positions:
            for inc in pos["incoming"]:
                inc["is_last"] = bool(complete_po) and inc["po"] == complete_po

        # Vollständigkeit = Anteil der Positionen, deren Material greifbar ist
        # (in der Fertigung oder am Lager). Positionen zählen, nicht Mengen: eine
        # Widerstandsposition über 5000 Stück ist fürs Rüsten genauso EINE Lücke
        # wie die eine fehlende Platine. Die mengengewichtete Quote steht
        # zusätzlich daneben.
        ready_states = ("done", "stock")
        total_pos = len(positions)
        ready_pos = len([p for p in positions if p["state"] in ready_states])
        req_sum = sum(p["required_qty"] for p in positions)
        have_sum = sum(min(p["transferred_qty"] + p["from_stock"], p["required_qty"])
                       for p in positions)

        for l in links:
            entry = {
                "name": wo.get("name"),
                "item_name": wo.get("item_name"),
                "qty": wo.get("qty"),
                "status": wo.get("status"),
                "sales_order": wo.get("sales_order"),
                "need_date": wo.get("planned_start_date") or wo.get("expected_delivery_date"),
                "is_last": bool(complete_po) and l["po"] == complete_po,
                "still_missing": len(missing),
            }
            per_item = by_po.setdefault(l["po"], {}).setdefault(l["item_code"], [])
            if not any(e["name"] == entry["name"] for e in per_item):
                per_item.append(entry)

        # Auf welche Lieferanten wartet dieser Auftrag — je Bestellung einmal,
        # mit den Artikeln, die von dort noch kommen.
        awaiting = []
        for l in links:
            hit = next((a for a in awaiting if a["po"] == l["po"]), None)
            if hit is None:
                awaiting.append({
                    "po": l["po"],
                    "supplier": l.get("supplier") or "",
                    "expected_date": l["expected_date"],
                    "items": [{"item_code": l["item_code"], "item_name": l.get("item_name")}],
                    "is_last": bool(complete_po) and l["po"] == complete_po,
                })
            elif not any(i["item_code"] == l["item_code"] for i in hit["items"]):
                hit["items"].append({"item_code": l["item_code"], "item_name": l.get("item_name")})
        awaiting.sort(key=lambda a: (a["expected_date"] is None, a["expected_date"] or "", a["po"] or ""))

        waiting = bool(links) or bool(missing)
        out.append({
            "name": wo.get("name"),
            "item_name": wo.get("item_name"),
            "production_item": wo.get("production_item"),
            "qty": wo.get("qty"),
            "status": wo.get("status"),
            "sales_order": wo.get("sales_order"),
            "need_date": wo.get("planned_start_date") or wo.get("expected_delivery_date"),
            # Wunschtermin des Kunden = Liefertermin der AB; ohne AB kein Termin.
            "customer_due_date": wo.get("customer_due_date"),
            "beistellung_count": int(wo.get("beistellung_count") or 0),
            "waiting": waiting,
            # Material vollständig = nichts mehr zu beschaffen (Bestand reicht bzw.
            # ist bereits in die Fertigung umgelagert).
            "material_ok": not waiting,
            "from_stock_only": from_stock_only,
            "complete_on": complete_on,
            "complete_po": complete_po,
            "awaiting": awaiting,
            "missing_items": missing,
            "positions": positions,
            "positions_total": total_pos,
            "positions_ready": ready_pos,
            "positions_incoming": len([p for p in positions if p["state"] == "incoming"]),
            "positions_missing": len([p for p in positions if p["state"] == "missing"]),
            "ready_pct": round(ready_pos / total_pos, 4) if total_pos else None,
            "qty_ready_pct": round(have_sum / req_sum, 4) if req_sum > 0 else None,
        })

    waiting = [w for w in out if w["waiting"]]
    return {
        "by_po": by_po,
        "work_orders": out,
        "waiting_count": len(waiting),
        # wird durch erwartete Lieferungen komplett …
        "unblockable_count": len([w for w in waiting if not w["missing_items"]]),
        # … versus: dafür muss erst noch bestellt werden
        "need_order_count": len([w for w in waiting if w["missing_items"]]),
    }


def purchase_orders(data: dict, today: date) -> dict:
    """Offene Bestellungen mit erwartetem Wareneingang.

    Erwarteter Termin = Bestelldatum + Median-Lieferzeit des Lieferanten; ohne
    Historie für diesen Lieferanten greift der Median über alle Lieferanten, ohne
    jede Historie der Wunschtermin der Bestellung (schedule_date). Bestellungen,
    deren erwarteter Termin überschritten ist, fallen aus dem Zeitplan und landen
    zusätzlich in follow_up („nachzuhaken"). „On Hold" bleibt sichtbar, wird aber
    nicht angemahnt — die Bestellung ist bewusst pausiert.
    """
    lead = supplier_lead_times(data)
    per_supplier = lead["per_supplier"]
    overall = lead["overall_median_days"]

    rows = []
    for po in data.get("open_purchase_orders") or []:
        order_date = _to_date(po.get("transaction_date"))
        schedule = _to_date(po.get("schedule_date"))
        stat = per_supplier.get(po.get("supplier") or "")
        lead_days = stat["median_days"] if stat else overall
        source = "supplier" if stat else ("overall" if overall is not None else None)

        if order_date is not None and lead_days is not None:
            expected = order_date + timedelta(days=int(round(lead_days)))
        else:
            expected, source = schedule, ("schedule" if schedule else None)

        late = expected is not None and expected < today
        rows.append({
            "name": po.get("name"),
            "supplier": po.get("supplier_name") or po.get("supplier") or "",
            "status": po.get("status"),
            "on_hold": (po.get("status") or "") == "On Hold",
            "order_date": order_date.isoformat() if order_date else None,
            "schedule_date": schedule.isoformat() if schedule else None,
            "expected_date": expected.isoformat() if expected else None,
            "expected_source": source,
            "lead_days": lead_days,
            "lead_samples": stat["samples"] if stat else 0,
            "net_open": round(float(po.get("net_open") or 0), 2),
            "positions": int(po.get("positions") or 0),
            "items": po.get("items") or [],
            "days_late": (today - expected).days if late else 0,
            "days_until": (expected - today).days if expected is not None and not late else None,
        })

    # Ohne erwarteten Termin ans Ende (nichts zu planen), sonst nach Termin.
    rows.sort(key=lambda r: (r["expected_date"] is None, r["expected_date"] or "", r["name"] or ""))

    # Fertigungsbezug: welcher Artikel wird für welchen Auftrag gebraucht und
    # welche Bestellung macht einen Auftrag material-komplett.
    wom = work_order_material(data, rows)
    for r in rows:
        links = wom["by_po"].get(r["name"]) or {}
        unblocks, names = [], set()
        for it in r["items"]:
            entries = links.get(it.get("item_code")) or []
            it["work_orders"] = entries
            for e in entries:
                names.add(e["name"])
                if e["is_last"] and e["name"] not in unblocks:
                    unblocks.append(e["name"])
        r["work_orders_count"] = len(names)
        r["unblocks"] = unblocks

    follow_up = [r for r in rows if r["days_late"] > 0 and not r["on_hold"]]
    follow_up.sort(key=lambda r: -r["days_late"])

    due_today = [r for r in rows if r["expected_date"] == today.isoformat()]
    items_today = []
    for r in due_today:
        for it in r["items"]:
            items_today.append({
                "item_code": it.get("item_code"),
                "item_name": it.get("item_name") or it.get("item_code"),
                "open_qty": it.get("open_qty"),
                "purchase_order": r["name"],
            })
    return {
        "open": rows,
        "follow_up": follow_up,
        "open_count": len(rows),
        "open_net": round(sum(r["net_open"] for r in rows), 2),
        "follow_up_count": len(follow_up),
        "follow_up_net": round(sum(r["net_open"] for r in follow_up), 2),
        "expected_today": {
            "orders": len(due_today),
            "positions": sum(r["positions"] for r in due_today),
            "net": round(sum(r["net_open"] for r in due_today), 2),
            "items": items_today,
        },
        "lead_times": lead,
        "work_orders": wom["work_orders"],
        "wo_waiting_count": wom["waiting_count"],
        "wo_unblockable_count": wom["unblockable_count"],
        "wo_need_order_count": wom["need_order_count"],
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
    grand = sum(r["net_total"] for r in totals.values())
    ranked = sorted(totals.values(), key=lambda r: r["net_total"], reverse=True)
    for r in ranked:
        r["share_pct"] = round(r["net_total"] / grand, 4) if grand else 0.0
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


def top_customers_year(data: dict, today: date, limit: int = 10) -> dict:
    """Top-N Kunden des laufenden Jahres nach Netto-Rechnungsumsatz (Jahresanfang
    bis heute), mit Anteil am Jahresumsatz und dem Vorjahreswert desselben Kunden.

    Der Vorjahresbetrag ist das KOMPLETTE Vorjahr — die Prozentangabe daneben
    vergleicht also einen laufenden Zeitraum mit einem abgeschlossenen Jahr und
    fällt früh im Jahr zwangsläufig negativ aus. Im Board steht das als Hinweis
    unter der Tabelle, damit die Zahl nicht als Kundenverlust gelesen wird.
    """
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    year_total = 0.0
    for inv in data.get("invoices", []) or []:
        d = _pdate(inv)
        if d and d.year == today.year and d <= today:
            amt = _net(inv)
            key = inv.get("customer_name") or inv.get("customer") or "?"
            totals[key] += amt
            counts[key] += 1
            year_total += amt

    prev: dict[str, float] = defaultdict(float)
    for inv in data.get("prev_year_invoices", []) or []:
        d = _pdate(inv)
        if d and d.year == today.year - 1:
            prev[inv.get("customer_name") or inv.get("customer") or "?"] += _net(inv)

    rows = []
    for name, amt in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
        prev_amt = prev.get(name)
        rows.append({
            "customer": name,
            "net_total": round(amt, 2),
            "invoices": counts[name],
            "share_pct": round(amt / year_total, 4) if year_total else 0.0,
            "prev_net_total": round(prev_amt, 2) if prev_amt is not None else None,
            "delta_pct": (round((amt - prev_amt) / prev_amt, 4)
                          if prev_amt and prev_amt > 0 else None),
        })
    return {
        "year": today.year,
        "prev_year": today.year - 1,
        "rows": rows,
        "year_total": round(year_total, 2),
        # Anteil der Top-N am Jahresumsatz = Klumpenrisiko in einer Zahl.
        "top_share_pct": (round(sum(r["net_total"] for r in rows) / year_total, 4)
                          if year_total else 0.0),
        "customer_count": len(totals),
    }


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


def top_suppliers_year(data: dict, today: date, limit: int = 10) -> dict:
    """Top-N Lieferanten des laufenden Jahres nach Netto-Einkaufswert (gebuchte
    Wareneingänge, Jahresanfang bis heute), mit Anteil am Jahres-Einkauf und dem
    Vorjahreswert desselben Lieferanten — Gegenstück zu top_customers_year().

    Wie dort ist der Vorjahresbetrag das KOMPLETTE Vorjahr, der Vergleich stellt
    also einen laufenden Zeitraum einem abgeschlossenen Jahr gegenüber. Beide
    Jahre kommen aus derselben Liste (purchase_receipts reicht bis zum
    Vorjahresanfang zurück), deshalb wird hier nach Jahr gefiltert statt zwei
    Datenquellen zu mischen.
    """
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    prev: dict[str, float] = defaultdict(float)
    year_total = 0.0
    for pr in data.get("purchase_receipts", []) or []:
        d = _pdate(pr)
        if not d:
            continue
        key = pr.get("supplier_name") or pr.get("supplier") or "?"
        if d.year == today.year and d <= today:
            amt = _net(pr)
            totals[key] += amt
            counts[key] += 1
            year_total += amt
        elif d.year == today.year - 1:
            prev[key] += _net(pr)

    rows = []
    for name, amt in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
        prev_amt = prev.get(name)
        rows.append({
            "supplier": name,
            "net_total": round(amt, 2),
            "receipts": counts[name],
            "share_pct": round(amt / year_total, 4) if year_total else 0.0,
            "prev_net_total": round(prev_amt, 2) if prev_amt is not None else None,
            "delta_pct": (round((amt - prev_amt) / prev_amt, 4)
                          if prev_amt and prev_amt > 0 else None),
        })
    return {
        "year": today.year,
        "prev_year": today.year - 1,
        "rows": rows,
        "year_total": round(year_total, 2),
        # Anteil der Top-N am Jahreseinkauf = Lieferantenabhängigkeit in einer Zahl.
        "top_share_pct": (round(sum(r["net_total"] for r in rows) / year_total, 4)
                          if year_total else 0.0),
        "supplier_count": len(totals),
    }


def _unit_costs(data: dict) -> tuple[dict[str, float], dict[str, float]]:
    """Stückkosten je Artikel: (letzter Einkaufspreis, Stücklistenwert je Einheit)."""
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
    return rates, bom_rates


def _aggregate_items(rows) -> dict[str, dict]:
    """Rechnungspositionen je Artikel summieren. Nimmt sowohl Einzelzeilen
    (base_net_amount) als auch in der Datenbank vorsummierte Zeilen (net_total)."""
    totals: dict[str, dict] = {}
    for row in rows or []:
        code = row.get("item_code") or row.get("item_name") or "?"
        entry = totals.setdefault(code, {
            "item_code": code,
            "item_name": row.get("item_name") or code,
            "revenue": 0.0,
            "qty": 0.0,
        })
        amount = row.get("base_net_amount")
        if amount in (None, ""):
            amount = row.get("net_total")
        entry["revenue"] += float(amount or 0)
        entry["qty"] += float(row.get("qty") or 0)
    return totals


def _with_margin(entry: dict, rates: dict, bom_rates: dict) -> dict:
    """Deckungsbeitrag an einen Artikel-Eintrag anhängen: Umsatz minus Wareneinsatz
    (verkaufte Menge × Stückkosten). Stückkosten-Quelle: letzter Einkaufspreis
    (Item.last_purchase_rate); fehlt der (Eigenfertigung), der Wert der aktiven
    Standard-Stückliste je Einheit (BOM). cost_source sagt, welche Quelle griff
    ("ek" | "bom"); ganz ohne beides bleiben Kosten/Marge leer statt 100 % zu
    suggerieren."""
    entry = dict(entry)
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
    return entry


def _with_share(rows: list[dict], grand: float) -> list[dict]:
    """Anteil am Gesamtumsatz des Zeitraums an jede Zeile hängen."""
    for r in rows:
        r["share_pct"] = round(r["revenue"] / grand, 4) if grand else 0.0
    return rows


def product_margins(data: dict, limit: int = 5) -> list[dict]:
    """Deckungsbeitrag der Top-Umsatzprodukte des laufenden Monats."""
    rates, bom_rates = _unit_costs(data)
    totals = _aggregate_items(data.get("invoice_items"))
    grand = sum(e["revenue"] for e in totals.values())
    ranked = sorted(totals.values(), key=lambda r: r["revenue"], reverse=True)[:limit]
    return _with_share([_with_margin(e, rates, bom_rates) for e in ranked], grand)


def product_flops(data: dict, limit: int = 5) -> list[dict]:
    """Die schwächsten Produkte des laufenden Monats nach Deckungsbeitrag —
    größter Verlust zuerst. Bewertet wird der ABSOLUTE DB, nicht die Prozentmarge:
    ein Cent-Verlust an einem Kleinteil ist harmlos, ein vierstelliger Verlust an
    einem Großauftrag nicht. Artikel ohne EK und ohne Stückliste lassen sich nicht
    bewerten und bleiben deshalb außen vor (sie stünden sonst mit „Marge 100 %"
    ganz oben oder ganz unten, je nach Zufall)."""
    rates, bom_rates = _unit_costs(data)
    totals = _aggregate_items(data.get("invoice_items"))
    grand = sum(e["revenue"] for e in totals.values())
    rows = [_with_margin(e, rates, bom_rates) for e in totals.values()]
    scored = [r for r in rows if r["margin"] is not None]
    scored.sort(key=lambda r: (r["margin"], r["margin_pct"] if r["margin_pct"] is not None else 0))
    return _with_share(scored[:limit], grand)


def product_margins_year(data: dict, today: date, limit: int = 5) -> dict:
    """Top-Produkte des laufenden Jahres nach Deckungsbeitrag, mit dem Vorjahr
    daneben (Jahresvergleich auf DB-Basis).

    Wichtige Annahme: die Stückkosten sind der HEUTIGE Stand (letzter EK bzw.
    Stücklistenwert) und werden auf beide Jahre angewandt — ERPNext hält den
    damaligen Einstandspreis nicht am Rechnungsbeleg. Der Vergleich zeigt also die
    Entwicklung von Menge und Verkaufspreis bei heutigen Kosten, nicht die
    damalige Einkaufslage.
    """
    rates, bom_rates = _unit_costs(data)
    cur = {c: _with_margin(e, rates, bom_rates)
           for c, e in _aggregate_items(data.get("invoice_items_year")).items()}
    prev = {c: _with_margin(e, rates, bom_rates)
            for c, e in _aggregate_items(data.get("invoice_items_prev_year")).items()}
    year_grand = sum(r["revenue"] for r in cur.values())
    prev_grand = sum(r["revenue"] for r in prev.values())
    ranked = sorted([r for r in cur.values() if r["margin"] is not None],
                    key=lambda r: r["margin"], reverse=True)[:limit]
    rows = []
    for r in ranked:
        p = prev.get(r["item_code"]) or {}
        pm = p.get("margin")
        rows.append(dict(
            r,
            share_pct=round(r["revenue"] / year_grand, 4) if year_grand else 0.0,
            prev_share_pct=(round(p["revenue"] / prev_grand, 4)
                            if p.get("revenue") is not None and prev_grand else None),
            prev_revenue=p.get("revenue"),
            prev_qty=p.get("qty"),
            prev_margin=pm,
            delta_margin=round(r["margin"] - pm, 2) if pm is not None else None,
            delta_revenue=(round(r["revenue"] - p["revenue"], 2)
                            if p.get("revenue") is not None else None),
        ))
    return {"year": today.year, "prev_year": today.year - 1, "rows": rows}


# Angebotsstatus in ERPNext, gruppiert nach Bedeutung fürs Board.
QUOTE_WON = ("Ordered", "Partially Ordered")
QUOTE_LOST = ("Lost",)
QUOTE_EXPIRED = ("Expired",)
QUOTE_OPEN = ("Open", "Replied")


def crm_summary(data: dict, today: date, expiring_days: int = 14,
                dormant_days: int = 180) -> dict:
    """CRM-Überblick: Angebote (offen, nachzufassen, Trefferquote) und die
    Kundenentwicklung aus den Rechnungsdaten, dazu Leads/Opportunities.

    Storno-Belege (docstatus 2) sind schon im Abruf ausgeschlossen — bei
    geänderten Angeboten (AN-1234 storniert, AN-1234-1 aktiv) würde sonst jedes
    Angebot doppelt zählen.

    Kundenentwicklung: das Datenfenster reicht vom Vorjahresanfang bis heute.
    „Neu" heißt darum genau: Umsatz im laufenden Jahr, keiner im Vorjahr — das
    umfasst auch reaktivierte Altkunden und ist im Board so benannt.
    """
    crm = data.get("crm") or {}
    quotes = crm.get("quotations") or []

    horizon = today + timedelta(days=expiring_days)
    open_rows, draft_rows = [], []
    for q in quotes:
        d = _to_date(q.get("date"))
        vt = _to_date(q.get("valid_till"))
        row = {
            "name": q.get("name"),
            "customer": q.get("customer") or "",
            "status": q.get("status"),
            "date": d.isoformat() if d else None,
            "valid_till": vt.isoformat() if vt else None,
            "net_total": round(float(q.get("net_total") or 0), 2),
            "age_days": (today - d).days if d else None,
            "days_left": (vt - today).days if vt else None,
            # abgelaufen laut Datum, aber im Status noch offen -> nachfassen
            "overdue": bool(vt and vt < today),
            "expiring": bool(vt and vt <= horizon),
        }
        if q.get("is_draft"):
            draft_rows.append(row)
        elif q.get("status") in QUOTE_OPEN:
            open_rows.append(row)
    # ohne Gültigkeitsdatum ans Ende: da ist nichts zu terminieren
    open_rows.sort(key=lambda r: (r["valid_till"] is None, r["valid_till"] or "", r["name"] or ""))
    draft_rows.sort(key=lambda r: (r["date"] is None, r["date"] or ""), reverse=True)
    expiring = [r for r in open_rows if r["expiring"]]

    by_customer: dict[str, dict] = {}
    for r in open_rows:
        e = by_customer.setdefault(r["customer"], {"customer": r["customer"], "count": 0, "net": 0.0})
        e["count"] += 1
        e["net"] += r["net_total"]
    top_customers_q = sorted(by_customer.values(), key=lambda e: e["net"], reverse=True)[:5]
    for e in top_customers_q:
        e["net"] = round(e["net"], 2)

    def conversion(year: int) -> dict:
        won = lost = exp = still_open = 0
        won_net = lost_net = exp_net = open_net = 0.0
        for q in quotes:
            d = _to_date(q.get("date"))
            if not d or d.year != year or q.get("is_draft"):
                continue
            net = float(q.get("net_total") or 0)
            st = q.get("status")
            if st in QUOTE_WON:
                won += 1
                won_net += net
            elif st in QUOTE_LOST:
                lost += 1
                lost_net += net
            elif st in QUOTE_EXPIRED:
                exp += 1
                exp_net += net
            elif st in QUOTE_OPEN:
                still_open += 1
                open_net += net
        decided = won + lost + exp
        decided_net = won_net + lost_net + exp_net
        return {
            "year": year,
            "won": won, "won_net": round(won_net, 2),
            "lost": lost, "lost_net": round(lost_net, 2),
            "expired": exp, "expired_net": round(exp_net, 2),
            "open": still_open, "open_net": round(open_net, 2),
            "decided": decided,
            # Trefferquote nur über ENTSCHIEDENE Angebote — noch offene sind
            # weder gewonnen noch verloren und würden die Quote künstlich drücken.
            "rate": round(won / decided, 4) if decided else None,
            "rate_net": round(won_net / decided_net, 4) if decided_net > 0 else None,
        }

    # --- Kundenentwicklung aus den Rechnungen ------------------------------
    per_customer: dict[str, dict] = {}
    for inv in list(data.get("invoices") or []) + list(data.get("prev_year_invoices") or []):
        d = _pdate(inv)
        if not d or d > today:
            continue
        key = inv.get("customer_name") or inv.get("customer")
        if not key:
            continue
        e = per_customer.setdefault(key, {
            "customer": key, "first_date": d, "last_date": d,
            "revenue_year": 0.0, "revenue_prev_year": 0.0,
        })
        e["first_date"] = min(e["first_date"], d)
        e["last_date"] = max(e["last_date"], d)
        amt = _net(inv)
        if d.year == today.year:
            e["revenue_year"] += amt
        elif d.year == today.year - 1:
            e["revenue_prev_year"] += amt

    new_customers, dormant = [], []
    for e in per_customer.values():
        entry = {
            "customer": e["customer"],
            "first_date": e["first_date"].isoformat(),
            "last_date": e["last_date"].isoformat(),
            "days_since": (today - e["last_date"]).days,
            "revenue_year": round(e["revenue_year"], 2),
            "revenue_prev_year": round(e["revenue_prev_year"], 2),
        }
        if e["revenue_year"] > 0 and e["revenue_prev_year"] <= 0:
            new_customers.append(entry)
        # schlafend: war im Vorjahr echter Kunde, seit Monaten kein Umsatz mehr
        if e["revenue_prev_year"] > 0 and entry["days_since"] > dormant_days:
            dormant.append(entry)
    new_customers.sort(key=lambda e: e["revenue_year"], reverse=True)
    dormant.sort(key=lambda e: e["revenue_prev_year"], reverse=True)

    leads = crm.get("leads") or []
    lead_closed = ("Converted", "Do Not Contact", "Lost Quotation")
    lead_status: dict[str, int] = {}
    for row in leads:
        st = row.get("status") or "?"
        lead_status[st] = lead_status.get(st, 0) + 1
    opps = crm.get("opportunities") or []
    open_opps = [o for o in opps if (o.get("status") or "") == "Open"]

    return {
        "quotations": {
            "open": open_rows,
            "open_count": len(open_rows),
            "open_net": round(sum(r["net_total"] for r in open_rows), 2),
            "expiring": expiring,
            "expiring_count": len(expiring),
            "expiring_net": round(sum(r["net_total"] for r in expiring), 2),
            "overdue_count": len([r for r in open_rows if r["overdue"]]),
            "draft": draft_rows[:10],
            "draft_count": len(draft_rows),
            "draft_net": round(sum(r["net_total"] for r in draft_rows), 2),
            "by_customer": top_customers_q,
            "conversion": conversion(today.year),
            "conversion_prev": conversion(today.year - 1),
            "expiring_days": expiring_days,
        },
        "customers": {
            "new": new_customers[:10],
            "new_count": len(new_customers),
            "dormant": dormant[:10],
            "dormant_count": len(dormant),
            "dormant_days": dormant_days,
            "active_count": len([e for e in per_customer.values() if e["revenue_year"] > 0]),
        },
        "leads": {
            "total": len(leads),
            "open_count": len([r for r in leads if (r.get("status") or "") not in lead_closed]),
            "by_status": sorted(lead_status.items()),
            "recent": sorted(leads, key=lambda r: r.get("created") or "", reverse=True)[:5],
        },
        "opportunities": {
            "total": len(opps),
            "open_count": len(open_opps),
            "open_amount": round(sum(float(o.get("amount") or 0) for o in open_opps), 2),
            "rows": sorted(open_opps, key=lambda o: float(o.get("amount") or 0), reverse=True)[:5],
        },
    }


def prev_year_month(data: dict, config: dict, today: date) -> dict:
    """Vorjahres-Kennzahlen (aus data["prev_year_invoices"], komplettes Vorjahr):
    Gesamtsumme des gleichen Monats, Summe bis zum gleichen Kalendertag (fairer
    Monatsvergleich), Jahressumme bis Ende des gleichen Monats (Vergleichsbasis
    für den laufenden Jahresumsatz), komplette Jahressumme sowie Gewinn/Verlust
    des Vorjahres (Umsatz − Wareneingänge Vorjahr − 12 × Fixkosten, gleiche
    Konstanz-Annahme wie in profit_history)."""
    total = 0.0
    mtd_same_day = 0.0
    ytd_through_month_end = 0.0
    ytd_same_day = 0.0
    full_year_total = 0.0
    for inv in data.get("prev_year_invoices", []) or []:
        d = _pdate(inv)
        if not d:
            continue
        amt = _net(inv)
        full_year_total += amt
        if d.month <= today.month:
            ytd_through_month_end += amt
        # fairer Jahresvergleich: Vorjahr bis zum selben Kalendertag wie heute
        if d.month < today.month or (d.month == today.month and d.day <= today.day):
            ytd_same_day += amt
        if d.month == today.month:
            total += amt
            if d.day <= today.day:
                mtd_same_day += amt

    prev_year = today.year - 1
    goods = 0.0
    for pr in data.get("purchase_receipts", []) or []:
        d = _pdate(pr)
        if d and d.year == prev_year:
            goods += _net(pr)
    fixed = float(config.get("personnel_costs_monthly") or 0) + float(config.get("rent_monthly") or 0)
    full_year_profit = full_year_total - goods - 12 * fixed

    return {
        "year": prev_year,
        "month": today.month,
        "total": round(total, 2),
        "mtd_same_day": round(mtd_same_day, 2),
        "ytd_through_month_end": round(ytd_through_month_end, 2),
        "ytd_same_day": round(ytd_same_day, 2),
        "full_year_total": round(full_year_total, 2),
        "full_year_profit": round(full_year_profit, 2),
    }


def profit_history(data: dict, config: dict, today: date) -> dict:
    """Gewinn/Verlust je Monat, KUMULIERT SEIT DEM VORJAHR: Netto-Rechnungsumsatz
    minus Wareneingänge des jeweiligen Monats minus fixe Kosten (Personal + Miete,
    als konstant angenommen — Annahme laut Anforderung). Die kumulierte Spalte
    läuft durchgehend vom Januar des Vorjahres bis zum laufenden Monat, das
    laufende Jahr baut also auf dem Vorjahresergebnis auf.

    - carry_forward: kumulierter G/V der abgeschlossenen Monate des LAUFENDEN
      Jahres (unverändert, für die „Vortrag <Jahr>"-Kachel).
    - since_prev_total: kumuliert Vorjahr-Anfang bis heute (inkl. laufendem Monat).
    - since_prev_completed: dasselbe bis zum letzten ABGESCHLOSSENEN Monat.
    - trend: G/V des letzten abgeschlossenen Monats (Richtung der Kumulierten).
    Setzt voraus, dass invoices bis Jahresanfang und prev_year_invoices/
    purchase_receipts bis Vorjahresanfang zurückreichen."""
    fixed = float(config.get("personnel_costs_monthly") or 0) + float(config.get("rent_monthly") or 0)
    prev_year = today.year - 1

    revenue: dict[tuple[int, int], float] = defaultdict(float)
    for inv in list(data.get("invoices", []) or []) + list(data.get("prev_year_invoices", []) or []):
        d = _pdate(inv)
        if d and d <= today:
            revenue[(d.year, d.month)] += _net(inv)
    goods: dict[tuple[int, int], float] = defaultdict(float)
    for pr in data.get("purchase_receipts", []) or []:
        d = _pdate(pr)
        if d and d <= today:
            goods[(d.year, d.month)] += _net(pr)

    months = []
    cumulative = 0.0
    carry = 0.0                       # nur laufendes Jahr, abgeschlossene Monate
    since_prev_completed = 0.0        # alle abgeschlossenen Monate seit Vorjahr
    y, mth = prev_year, 1
    while (y, mth) <= (today.year, today.month):
        total_costs = goods[(y, mth)] + fixed
        profit = revenue[(y, mth)] - total_costs
        cumulative += profit
        is_current = (y == today.year and mth == today.month)
        months.append({
            "month": f"{y}-{mth:02d}",
            "year": y,
            "revenue": round(revenue[(y, mth)], 2),
            "goods_receipts": round(goods[(y, mth)], 2),
            "fixed_costs": round(fixed, 2),
            "profit": round(profit, 2),
            "cumulative": round(cumulative, 2),
            # Umsatz-zu-Kosten-Verhältnis fürs Monats-Ranking (>1 = profitabel);
            # ohne Kosten kein sinnvolles Verhältnis -> None, landet im Rang hinten.
            "ratio": round(revenue[(y, mth)] / total_costs, 4) if total_costs > 0 else None,
            "is_current": is_current,
        })
        if not is_current:
            since_prev_completed += profit
            if y == today.year:
                carry += profit
        mth += 1
        if mth == 13:
            y, mth = y + 1, 1

    for rank, mo in enumerate(
        sorted(months, key=lambda r: (r["ratio"] is None, -(r["ratio"] or 0))), start=1
    ):
        mo["rank"] = rank if mo["ratio"] is not None else None

    # Trend der Kumulierten = G/V des letzten abgeschlossenen Monats.
    last_completed = None
    for mo in reversed(months):
        if not mo["is_current"]:
            last_completed = mo
            break
    return {
        "months": months,
        "carry_forward": round(carry, 2),
        "ytd_profit": round(carry + (months[-1]["profit"] if months else 0), 2),
        "since_prev_total": round(cumulative, 2),
        "since_prev_completed": round(since_prev_completed, 2),
        "prev_year": prev_year,
        "trend_last_month": last_completed["month"] if last_completed else None,
        "trend_value": last_completed["profit"] if last_completed else None,
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
            # Versanddatum: das von UPS gemeldete Datum, sonst das Lieferscheindatum
            # (dann ist der Beleg das einzige Zeugnis für den Versandtag).
            "shipment_date": (str(dn.get("shipment_date"))[:10] if dn.get("shipment_date")
                              else (d.isoformat() if d else None)),
            "shipment_date_source": "ups" if dn.get("shipment_date") else ("note" if d else None),
            "age_days": age,
            "tracking_number": dn.get("tracking_number"),
            "arrival_status": dn.get("arrival_status", "unknown"),
            "delivered_date": dn.get("delivered_date"),
            "arrival_method": dn.get("arrival_method"),
        }
        is_stale = age is not None and age > stale_days
        item["needs_review"] = is_stale
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

    # „Jetzt abrechenbar" und „zu klären" getrennt ausweisen — dieselbe Summe darf
    # nicht in beiden Zahlen stehen. Ein zugestellter Lieferschein, der älter als
    # die Klärgrenze ist, gehört zum Klärfall (so markiert ihn auch die Tabelle).
    stale_net = round(sum(r["net_open"] for r in stale), 2)
    ready_clear_net = round(sum(r["net_open"] for r in ready if not r["needs_review"]), 2)

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

    # Durchlaufzeit-Analyse: wie lange liegen die noch offenen „To Bill"-
    # Lieferscheine schon (Lieferschein erstellt → noch nicht abgerechnet)?
    # Das ist die aktionable Kennzahl (Backlog, der abgerechnet werden sollte);
    # ehrlich als „offen/wartend" bezeichnet, nicht als realisierte Ø-Zeit.
    open_ages = sorted(
        it["age_days"] for it in (ready + in_transit + unknown) if it.get("age_days") is not None
    )
    if open_ages:
        n = len(open_ages)
        throughput = {
            "open_count": n,
            "avg_open_age_days": round(sum(open_ages) / n, 1),
            "median_open_age_days": round(_median(open_ages), 1),
            "max_open_age_days": open_ages[-1],
        }
    else:
        throughput = {"open_count": 0, "avg_open_age_days": 0.0,
                      "median_open_age_days": 0.0, "max_open_age_days": 0}

    # Vor todo_orders: liefert den Materialstand der Produktionsaufträge, den die
    # Liefertermin-Liste je Auftrag mit anzeigt.
    purchasing = purchase_orders(data, today)

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
        "top_customers_year": top_customers_year(data, today),
        "top_suppliers": top_suppliers(data, today),
        "top_suppliers_year": top_suppliers_year(data, today),
        "product_margins": product_margins(data),
        "product_flops": product_flops(data),
        "product_margins_year": product_margins_year(data, today),
        "recent_receipts": recent_receipts(data),
        "prev_year": prev_year_month(data, config, today),
        # Umsatz laufendes Jahr (Jahresanfang bis heute) — Gegenstück zu
        # prev_year.ytd_through_month_end.
        "ytd_revenue": round(sum(
            _net(inv) for inv in invoices
            if (d := _pdate(inv)) and d.year == today.year and d <= today
        ), 2),
        "purchasing": purchasing,
        "todo": todo_orders(data, today, purchasing.get("work_orders")),
        "crm": crm_summary(data, today),
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
            "ready_clear_count": len([r for r in ready if not r["needs_review"]]),
            "ready_clear_net": ready_clear_net,
            "stale_count": len(stale),
            "stale_net": stale_net,
            "stale_days": stale_days,
            "total_open_count": len(ready) + len(in_transit) + len(unknown),
            "throughput": throughput,
        },
        "tips": tips,
    }

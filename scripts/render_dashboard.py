"""Rendert metrics.json -> interaktives, eigenständiges Team-Board (Artifact-tauglich).

Keine externen Assets, kein CDN — inline CSS/JS/SVG. Theme-fähig (hell/dunkel).
Interaktiv: Postfach-Auswahl, Suche/Filter, aufklappbare Mail-Karten mit Kopieren-
Button, „Live aktualisieren" mit pulsierendem PCB-Logo. Chart-Serien nach der
validierten dataviz-Palette; Marken-Teal/-Rot nur fürs Logo.

CLI:
    python scripts/render_dashboard.py --input state/metrics.json --output state/dashboard.html
"""
from __future__ import annotations

import argparse
import calendar
import html
import math
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import io_utils as io   # noqa: E402


def eur(v: float, cents: bool = False) -> str:
    """Deutsche Zahlenformatierung: 12.345 € bzw. 12.345,67 €."""
    v = float(v or 0)
    s = f"{v:,.2f}" if cents else f"{round(v):,.0f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def pct(v: float) -> str:
    return f"{v*100:.0f} %"


STATUS = {
    "green": ("var(--good)", "Auf Kurs", "▲"),
    "amber": ("var(--warning)", "Knapp", "▶"),
    "red": ("var(--critical)", "Unter Ziel", "▼"),
}

MONTHS_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember"]


def pcb_logo_svg(size: int = 40, animated: bool = False, cls: str = "") -> str:
    """Musterfirma-Logo als Inline-SVG: 8 Ringsegmente (teal) + 1 rotes + innere Scheibe."""
    cx = cy = 100.0
    r_out, r_in, disc = 94.0, 54.0, 38.0
    pad = 5.0            # weiße Speichen zwischen den Segmenten (Grad)
    red_index = 1        # Segment oben rechts ist rot (wie im Logo)
    segs = []
    for k in range(8):
        a0 = math.radians(k * 45 + pad - 90)
        a1 = math.radians((k + 1) * 45 - pad - 90)
        x0o, y0o = cx + r_out * math.cos(a0), cy + r_out * math.sin(a0)
        x1o, y1o = cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)
        x0i, y0i = cx + r_in * math.cos(a0), cy + r_in * math.sin(a0)
        x1i, y1i = cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)
        d = (f"M{x0o:.2f},{y0o:.2f} A{r_out},{r_out} 0 0 1 {x1o:.2f},{y1o:.2f} "
             f"L{x1i:.2f},{y1i:.2f} A{r_in},{r_in} 0 0 0 {x0i:.2f},{y0i:.2f} Z")
        color = "pcb-red" if k == red_index else "pcb-teal"
        segs.append(f'<path class="pcb-seg {color}" style="--i:{k}" d="{d}"/>')
    disc_el = f'<circle class="pcb-teal pcb-disc" cx="{cx}" cy="{cy}" r="{disc}"/>'
    klass = "pcb-logo" + (" pulsing" if animated else "") + (f" {cls}" if cls else "")
    return (f'<svg class="{klass}" viewBox="0 0 200 200" width="{size}" height="{size}" '
            f'aria-label="Musterfirma" role="img">{"".join(segs)}{disc_el}</svg>')


# ---------------------------------------------------------------- Umsatz-Charts

def _cumulative(daily_series, days_in_month, today_day):
    by_day = {}
    for row in daily_series:
        d = date.fromisoformat(row["date"])
        by_day[d.day] = by_day.get(d.day, 0.0) + float(row["net"])
    cum, running = [], 0.0
    for day in range(1, min(today_day, days_in_month) + 1):
        running += by_day.get(day, 0.0)
        cum.append((day, running))
    return cum


def _line_chart_svg(m: dict) -> str:
    fc = m["forecast"]
    as_of = date.fromisoformat(m["as_of"])
    days_in_month = calendar.monthrange(as_of.year, as_of.month)[1]
    target = m["target"]
    W, H = 720, 300
    ml, mr, mt, mb = 56, 16, 16, 30
    pw, ph = W - ml - mr, H - mt - mb
    cum = _cumulative(m["daily_series"], days_in_month, as_of.day)
    y_max = max(target, fc["forecast_high"], (cum[-1][1] if cum else 0)) * 1.08 or 1

    def X(day):
        return ml + (day - 1) / max(days_in_month - 1, 1) * pw

    def Y(val):
        return mt + ph - (val / y_max) * ph

    def tick_label(v):
        if v < 1:
            return "0"
        return f"{v/1000:.0f}k".replace(".", ",") if v >= 1000 else f"{v:.0f}"

    ticks, val = [], 0.0
    step = target / 4
    while val <= y_max + 1:
        ticks.append(val)
        val += step
    grid = []
    for t in ticks:
        y = Y(t)
        grid.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        grid.append(f'<text x="{ml-8}" y="{y+4:.1f}" class="ytick" text-anchor="end">{tick_label(t)} €</text>')
    xt = []
    for day in range(1, days_in_month + 1, 5):
        xt.append(f'<text x="{X(day):.1f}" y="{H-mb+20:.1f}" class="xtick" text-anchor="middle">{day}.</text>')
    yt = Y(target)
    target_line = (f'<line x1="{ml}" y1="{yt:.1f}" x2="{W-mr}" y2="{yt:.1f}" class="target"/>'
                   f'<text x="{W-mr}" y="{yt-6:.1f}" class="target-label" text-anchor="end">Ziel {eur(target)}</text>')
    actual_pts = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in cum)
    area = line = dots = proj = ""
    if cum:
        area = f'<polygon class="area" points="{ml},{mt+ph} {actual_pts} {X(cum[-1][0]):.1f},{mt+ph}"/>'
        line = f'<polyline class="line" points="{actual_pts}"/>'
        for d, v in cum:
            dots += (f'<circle class="dot" cx="{X(d):.1f}" cy="{Y(v):.1f}" r="3" '
                     f'data-label="{d}. {as_of.month:02d}. — kumuliert {html.escape(eur(v))}"/>')
        lx, lv = cum[-1]
        proj = (f'<line class="proj" x1="{X(lx):.1f}" y1="{Y(lv):.1f}" '
                f'x2="{X(days_in_month):.1f}" y2="{Y(fc["forecast"]):.1f}"/>'
                f'<circle class="dot-proj" cx="{X(days_in_month):.1f}" cy="{Y(fc["forecast"]):.1f}" r="4" '
                f'data-label="Prognose Monatsende — {html.escape(eur(fc["forecast"]))}"/>')
    return f'''<svg viewBox="0 0 {W} {H}" class="chart-svg" role="img"
     aria-label="Kumulierter Netto-Umsatz im Monatsverlauf gegen das Ziel">
  {''.join(grid)}{area}{target_line}
  <polyline class="line-bg" points="{actual_pts}"/>{line}{proj}{dots}
  {''.join(xt)}
</svg>'''


def _coverage_bar(m: dict) -> str:
    fc, pl, target = m["forecast"], m["pipeline"], m["target"]
    scale_max = max(target, pl["coverage_after_forecast"]) * 1.02 or 1
    segs = [
        ("Ist (Monat)", fc["mtd"], "var(--series-1)"),
        ("Prognose-Rest", max(fc["forecast"] - fc["mtd"], 0), "var(--series-1-soft)"),
        ("Abrechnungsbereit", pl["ready_net"], "var(--series-2)"),
        ("Unterwegs", pl["in_transit_net"], "var(--series-3)"),
    ]
    rects = "".join(
        f'<div class="seg" style="width:{v/scale_max*100:.2f}%;background:{c}" title="{html.escape(l)}: {html.escape(eur(v))}"></div>'
        for l, v, c in segs if v > 0)
    legend = "".join(
        f'<span class="lg"><i style="background:{c}"></i>{html.escape(l)} · {eur(v)}</span>'
        for l, v, c in segs if v > 0)
    coverage = pl["coverage_after_forecast"]
    verdict = ("Pipeline deckt das Ziel ✓" if coverage >= target
               else f"Auch mit Pipeline noch {eur(target-coverage)} bis zum Ziel")
    return (f'<div class="cov-track">{rects}'
            f'<div class="cov-target" style="left:{target/scale_max*100:.2f}%" title="Ziel {html.escape(eur(target))}"></div></div>'
            f'<div class="cov-legend">{legend}</div><p class="cov-verdict">{html.escape(verdict)}</p>')


def _tips(m: dict) -> str:
    items = m.get("tips", [])
    if not items:
        return '<p class="muted">Keine Handlungsempfehlungen – alles im grünen Bereich.</p>'
    rows = "".join(
        f'<li><span class="tip-eur">{eur(t["impact_eur"])}</span>'
        f'<span class="tip-body"><b>{html.escape(t["title"])}</b>'
        f'<span class="tip-detail">{html.escape(t["detail"])}</span></span></li>'
        for t in items)
    return f'<ol class="tips">{rows}</ol>'


def _billing_group(title, rows_data, show_total=None):
    method_label = {"ups": "UPS", "fallback": "geschätzt", "none": "—"}
    if not rows_data:
        return f'<figcaption>{title}</figcaption><p class="muted">—</p>'
    rows = ""
    for r in rows_data:
        age = r.get("age_days")
        alt = ' <span class="dot-hi">alt</span>' if (age is not None and age > 60) else ""
        rows += (f'<tr><td>{html.escape(str(r["name"]))}</td>'
                 f'<td>{html.escape(str(r.get("customer") or ""))}</td>'
                 f'<td class="num">{eur(r["net_open"])}</td>'
                 f'<td>{html.escape(str(r.get("delivered_date") or r.get("posting_date") or "—"))}{alt}</td>'
                 f'<td>{method_label.get(r.get("arrival_method"), "—")}</td></tr>')
    tfoot = (f'<tfoot><tr><td colspan="2">Summe</td><td class="num">{eur(show_total)}</td>'
             f'<td colspan="2"></td></tr></tfoot>' if show_total is not None else "")
    return (f'<figcaption>{title}</figcaption><table class="tbl"><thead><tr><th>Lieferschein</th>'
            f'<th>Kunde</th><th class="num">Netto</th><th>zugestellt / Datum</th><th>Quelle</th></tr></thead>'
            f'<tbody>{rows}</tbody>{tfoot}</table>')


# ---------------------------------------------------------------- Posteingang

def _short_box(email: str) -> str:
    return (email or "").split("@")[0] or email


def _mail_tab(m: dict) -> str:
    mail = m.get("mail") or {}
    items = mail.get("items", [])
    boxes = mail.get("mailboxes", [])
    win = mail.get("window_hours")
    winlbl = f"letzte {win} h" if win else "aktuell"

    # Postfach-Chips
    chips = ['<button class="chip active" data-mb="all">Alle</button>']
    for b in boxes:
        chips.append(f'<button class="chip" data-mb="{html.escape(b["name"])}">'
                     f'{html.escape(_short_box(b["name"]))} <span class="chip-n">{b["total"]}</span></button>')
    chips_html = f'<div class="chips" id="mbChips">{"".join(chips)}</div>'

    # Zählkacheln (werden per JS je Postfach aktualisiert)
    tiles = f'''<div class="mini" id="mailCounts">
  <div class="b"><div class="v" data-count="total">{mail.get("total",0)}</div><div class="k">Neu ({winlbl})</div></div>
  <div class="b"><div class="v" data-count="relevant" style="color:var(--series-1)">{mail.get("relevant",0)}</div><div class="k">Zu beantworten</div></div>
  <div class="b"><div class="v" data-count="info">{mail.get("info",0)}</div><div class="k">Nur Info</div></div>
  <div class="b"><div class="v" data-count="high" style="color:var(--critical)">{mail.get("high_priority",0)}</div><div class="k">Dringend</div></div>
</div>'''

    # Filter + Suche
    controls = '''<div class="mailctl">
  <div class="segbtns" id="catFilter">
    <button class="active" data-cat="all">Alle</button>
    <button data-cat="relevant">Zu beantworten</button>
    <button data-cat="high">Dringend</button>
    <button data-cat="info">Info</button>
  </div>
  <input type="search" id="mailSearch" placeholder="Suche: Absender, Betreff …">
</div>'''

    # Karten
    cards = []
    for idx, i in enumerate(items):
        rel = i.get("category") == "relevant"
        prio = "high" if i.get("priority") == "high" else "normal"
        mbn = i.get("mailbox") or ""
        sender = str(i.get("sender_name") or i.get("sender") or "")
        subj = str(i.get("subject") or "")
        reason = str(i.get("reason") or "")
        draft = str(i.get("draft") or "").strip()
        search_txt = html.escape(f"{sender} {subj} {reason}".lower(), quote=True)
        dot = '<span class="mc-dot hi" title="dringend"></span>' if prio == "high" else '<span class="mc-dot"></span>'
        pill = ('<span class="pill rel">Antwort</span>' if rel else '<span class="pill info">Info</span>')
        can = bool(draft)
        chev = '<span class="mc-chev">▾</span>' if can else ""
        head = (f'<div class="mc-head{"" if can else " nodraft"}">'
                f'{dot}{pill}<span class="mc-box">{html.escape(_short_box(mbn))}</span>'
                f'<span class="mc-sender">{html.escape(sender)}</span>'
                f'<span class="mc-subj">{html.escape(subj)}</span>'
                f'<span class="mc-reason">{html.escape(reason)}</span>{chev}</div>')
        draft_block = ""
        if can:
            draft_block = (f'<div class="mc-draft" hidden><div class="mc-draft-lbl">Antwortvorschlag '
                           f'(zum Kopieren – wird nicht automatisch gesendet):</div>'
                           f'<pre class="draft-text">{html.escape(draft)}</pre>'
                           f'<button class="copybtn" type="button">📋 Kopieren</button></div>')
        cards.append(f'<div class="mailcard{" has-draft" if can else ""}" data-mb="{html.escape(mbn)}" '
                     f'data-cat="{"relevant" if rel else "info"}" data-prio="{prio}" '
                     f'data-text="{search_txt}">{head}{draft_block}</div>')
    cards_html = f'<div id="mailList">{"".join(cards)}</div>' if cards else '<p class="muted">Keine Mails im Zeitfenster.</p>'
    empty = '<p class="muted" id="mailEmpty" hidden>Keine Treffer für die aktuelle Auswahl.</p>'

    return (f'<section class="card"><div class="sec-h"><h2>Posteingang</h2>'
            f'<span class="muted">alle Postfächer im Überblick</span></div>'
            f'{chips_html}{tiles}{controls}{cards_html}{empty}</section>')


# ------------------------------------------------------------------- Umsatz-Tab

def _revenue_tab(m: dict) -> str:
    fc = m["forecast"]
    color, label, arrow = STATUS.get(fc["status"], STATUS["amber"])
    as_of = date.fromisoformat(m["as_of"])
    period = f"{MONTHS_DE[as_of.month]} {as_of.year}"
    scale_max = max(m["target"], fc["forecast_high"]) or 1
    mtd_w = fc["mtd"] / scale_max * 100
    proj_w = max(fc["forecast"] - fc["mtd"], 0) / scale_max * 100
    target_pos = m["target"] / scale_max * 100
    tiles = f'''<div class="tiles">
  <div class="tile"><p class="k">Ist-Umsatz (Netto, {period})</p><div class="v">{eur(fc["mtd"])}</div>
    <div class="m">{fc["bd_elapsed"]} von {fc["bd_total"]} Werktagen</div></div>
  <div class="tile"><p class="k">Prognose Monatsende</p><div class="v">{eur(fc["forecast"])}</div>
    <div class="m"><span class="badge" style="background:{color}">{arrow} {label} · {pct(fc["attainment_pct"])}</span></div></div>
  <div class="tile"><p class="k">{"Lücke zum Ziel" if fc["gap"]>0 else "Über Ziel"}</p><div class="v">{eur(abs(fc["gap"]))}</div>
    <div class="m">Ziel {eur(m["target"])}</div></div>
  <div class="tile"><p class="k">Nötig je Restwerktag</p><div class="v">{eur(fc["required_daily"])}</div>
    <div class="m">an {fc["bd_remaining"]} Werktagen</div></div>
</div>'''
    meter = f'''<section class="card"><figcaption>Zielerreichung {period}</figcaption>
  <div class="meter-wrap"><div class="meter"><div class="meter-row">
      <div class="fill" style="width:{mtd_w:.2f}%;background:var(--series-1)"></div>
      <div class="proj" style="width:{proj_w:.2f}%;background:{color}"></div></div>
    <div class="mk" style="left:{target_pos:.2f}%"></div></div>
  <div class="meter-labels"><span>Ist {eur(fc["mtd"])}</span><span>Prognose {eur(fc["forecast"])}</span>
    <span>Ziel {eur(m["target"])}</span></div></div></section>'''
    charts = f'''<div class="grid2">
  <figure class="card"><figcaption>Umsatzverlauf & Prognose</figcaption>
    <div class="chart-wrap">{_line_chart_svg(m)}</div>
    <div class="legend"><span><i style="background:var(--series-1)"></i>Ist kumuliert</span>
      <span><span class="dash"></span>Prognose</span>
      <span><i style="background:var(--baseline)"></i>Ziel {eur(m["target"])}</span></div></figure>
  <figure class="card"><figcaption>Zieldeckung inkl. Pipeline</figcaption>{_coverage_bar(m)}</figure>
</div>'''
    tips = f'<section class="card"><figcaption>🚀 Wo wir pushen können</figcaption>{_tips(m)}</section>'
    return f'{tiles}{meter}{charts}{tips}'


def _billing_tab(m: dict) -> str:
    b = m["billing"]
    ready = f'<section class="card">{_billing_group("🧾 Jetzt abrechnen (Paket zugestellt) · " + str(b["ready_count"]), b["ready"], m["pipeline"]["ready_net"])}</section>'
    transit = f'<section class="card">{_billing_group("⏳ Unterwegs – nach Zustellung abrechnen · " + str(len(b["in_transit"])), b["in_transit"])}</section>'
    extra = ""
    if b.get("stale"):
        extra = f'<section class="card">{_billing_group("⚠️ Alte offene Lieferscheine (>60 Tage) · " + str(len(b["stale"])), b["stale"])}</section>'
    return f'{ready}{transit}{extra}'


# --------------------------------------------------------------------- CSS / JS

CSS = r"""
.viz-root{--surface-1:#fcfcfb;--plane:#f4f5f3;--text-primary:#0b0b0b;--text-secondary:#52514e;
--muted:#898781;--grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
--series-1:#2a78d6;--series-1-soft:#9ec5f4;--series-2:#1baf7a;--series-3:#eda100;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--brand-teal:#0c8a8c;--brand-red:#c30f3b;
font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text-primary);
background:var(--plane);padding:16px;max-width:1080px;margin:0 auto;line-height:1.45}
@media (prefers-color-scheme:dark){.viz-root{--surface-1:#1a1a19;--plane:#0d0d0d;
--text-primary:#fff;--text-secondary:#c3c2b7;--muted:#8a8880;--grid:#2c2c2a;--baseline:#383835;
--border:rgba(255,255,255,.12);--series-1:#3987e5;--series-1-soft:#1c5cab;--series-2:#199e70;
--series-3:#c98500;--brand-teal:#14a1a4;--brand-red:#e14b6f}}
.viz-root[data-theme=dark]{--surface-1:#1a1a19;--plane:#0d0d0d;--text-primary:#fff;
--text-secondary:#c3c2b7;--muted:#8a8880;--grid:#2c2c2a;--baseline:#383835;--border:rgba(255,255,255,.12);
--series-1:#3987e5;--series-1-soft:#1c5cab;--series-2:#199e70;--series-3:#c98500;--brand-teal:#14a1a4;--brand-red:#e14b6f}
.viz-root[data-theme=light]{--surface-1:#fcfcfb;--plane:#f4f5f3;--text-primary:#0b0b0b;
--text-secondary:#52514e;--muted:#898781;--grid:#e1e0d9;--baseline:#c3c2b7;--border:rgba(11,11,11,.10);
--series-1:#2a78d6;--series-1-soft:#9ec5f4;--series-2:#1baf7a;--series-3:#eda100;--brand-teal:#0c8a8c;--brand-red:#c30f3b}
.viz-root *{box-sizing:border-box}
.viz-root h1,.viz-root h2{margin:0;font-weight:660}
/* Logo */
.pcb-logo .pcb-teal{fill:var(--brand-teal)} .pcb-logo .pcb-red{fill:var(--brand-red)}
.pcb-logo .pcb-seg{transform-origin:100px 100px}
.pcb-logo.pulsing{animation:pcbspin 6s linear infinite}
.pcb-logo.pulsing .pcb-seg{animation:pcbpulse 1.2s ease-in-out infinite;animation-delay:calc(var(--i)*0.12s)}
.pcb-logo.pulsing .pcb-disc{animation:pcbdisc 1.2s ease-in-out infinite}
@keyframes pcbpulse{0%,100%{opacity:.28}30%{opacity:1}}
@keyframes pcbdisc{0%,100%{opacity:.8;transform:scale(.94)}50%{opacity:1;transform:scale(1)}}
@keyframes pcbspin{to{transform:rotate(360deg)}}
/* Header */
.hd{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.hd .brand{display:flex;align-items:center;gap:12px;flex:1;min-width:220px}
.hd h1{font-size:1.3rem;line-height:1.1}.hd .tag{color:var(--brand-teal);font-weight:600;font-size:.82rem}
.hd .sub{color:var(--text-secondary);font-size:.82rem;margin-top:2px}
.hd .actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{border:1px solid var(--border);background:var(--surface-1);color:var(--text-primary);
border-radius:9px;padding:8px 12px;font-size:.85rem;cursor:pointer;font-weight:600;display:inline-flex;align-items:center;gap:7px}
.btn.primary{background:var(--brand-teal);color:#fff;border-color:transparent}
.btn.ghost{color:var(--text-secondary);font-weight:500}
.btn:hover{filter:brightness(1.06)}
.stand{font-size:.78rem;color:var(--muted)}
/* Tabs */
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin:4px 0 2px}
.tabs button{background:none;border:0;border-bottom:2px solid transparent;color:var(--text-secondary);
padding:9px 14px;font-size:.92rem;font-weight:600;cursor:pointer;margin-bottom:-1px}
.tabs button.active{color:var(--brand-teal);border-bottom-color:var(--brand-teal)}
.tab-panel{display:none}.tab-panel.active{display:block}
.card{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px;margin-top:16px}
.sec-h{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}.sec-h h2{font-size:1.05rem}
/* Chips */
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.chip{border:1px solid var(--border);background:var(--plane);color:var(--text-secondary);
border-radius:999px;padding:6px 13px;font-size:.84rem;font-weight:600;cursor:pointer}
.chip.active{background:var(--brand-teal);color:#fff;border-color:transparent}
.chip-n{opacity:.75;font-weight:700;margin-left:3px}
/* Count tiles */
.mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:14px}
.mini .b{background:var(--plane);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.mini .b .v{font-size:1.45rem;font-weight:680}.mini .b .k{font-size:.78rem;color:var(--text-secondary)}
/* Mail controls */
.mailctl{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.segbtns{display:inline-flex;border:1px solid var(--border);border-radius:9px;overflow:hidden}
.segbtns button{background:var(--surface-1);border:0;border-right:1px solid var(--border);color:var(--text-secondary);
padding:7px 12px;font-size:.82rem;font-weight:600;cursor:pointer}
.segbtns button:last-child{border-right:0}.segbtns button.active{background:var(--brand-teal);color:#fff}
#mailSearch{flex:1;min-width:180px;border:1px solid var(--border);background:var(--plane);color:var(--text-primary);
border-radius:9px;padding:8px 12px;font-size:.85rem}
/* Mail cards */
.mailcard{border:1px solid var(--border);border-radius:10px;margin-bottom:8px;background:var(--plane);overflow:hidden}
.mc-head{display:grid;grid-template-columns:auto auto auto 1fr;gap:8px;align-items:center;padding:10px 12px;cursor:default}
.mailcard.has-draft .mc-head{cursor:pointer}
.mc-head.nodraft{opacity:.9}
.mc-dot{width:9px;height:9px;border-radius:50%;background:var(--baseline);display:inline-block}
.mc-dot.hi{background:var(--critical);box-shadow:0 0 0 3px color-mix(in srgb,var(--critical) 25%,transparent)}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:.72rem;font-weight:700;white-space:nowrap}
.pill.rel{background:var(--series-1);color:#fff}.pill.info{background:var(--grid);color:var(--text-secondary)}
.mc-box{font-size:.72rem;font-weight:700;color:var(--brand-teal);background:color-mix(in srgb,var(--brand-teal) 12%,transparent);
padding:2px 8px;border-radius:6px;white-space:nowrap}
.mc-sender{font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:190px}
.mc-subj{color:var(--text-secondary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;grid-column:1/-1}
.mc-reason{grid-column:1/-1;font-size:.86rem;color:var(--text-secondary)}
.mc-chev{position:absolute;right:12px;color:var(--muted);transition:transform .15s}
.mailcard{position:relative}.mailcard.open .mc-chev{transform:rotate(180deg)}
.mc-draft{padding:0 12px 12px}.mc-draft-lbl{font-size:.78rem;color:var(--muted);margin:2px 0 6px}
.draft-text{white-space:pre-wrap;background:var(--surface-1);border:1px solid var(--border);border-radius:8px;
padding:12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.83rem;margin:0 0 8px;overflow-x:auto}
.copybtn{border:1px solid var(--brand-teal);background:transparent;color:var(--brand-teal);border-radius:8px;
padding:6px 12px;font-size:.82rem;font-weight:700;cursor:pointer}.copybtn:hover{background:var(--brand-teal);color:#fff}
.dot-hi{color:var(--critical);font-weight:700}
@media (min-width:680px){.mc-head{grid-template-columns:auto auto auto minmax(150px,220px) 2fr;padding-right:30px}
.mc-subj{grid-column:auto}.mc-reason{grid-column:1/-1}}
/* Umsatz reuse */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.tile{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:16px}
.tile .k{color:var(--text-secondary);font-size:.82rem;margin:0 0 6px}.tile .v{font-size:1.7rem;font-weight:680}
.tile .m{font-size:.82rem;color:var(--muted);margin-top:4px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:.82rem;font-weight:600;color:#fff}
figure{margin:0}figcaption{font-weight:600;margin-bottom:8px;font-size:.98rem}
.meter-wrap{margin-top:10px}.meter{position:relative;height:26px;border-radius:8px;background:var(--grid);overflow:hidden}
.meter .fill{height:100%;border-radius:8px 0 0 8px}.meter .proj{height:100%;opacity:.45}.meter-row{display:flex;height:100%}
.meter .mk{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--text-primary)}
.meter-labels{display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-secondary);margin-top:6px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media (max-width:720px){.grid2{grid-template-columns:1fr}}
.chart-wrap{overflow-x:auto}.chart-svg{width:100%;height:auto;min-width:420px}
.grid{stroke:var(--grid);stroke-width:1}.ytick,.xtick{fill:var(--muted);font-size:11px}.ytick{font-variant-numeric:tabular-nums}
.target{stroke:var(--baseline);stroke-width:1.5;stroke-dasharray:2 3}.target-label{fill:var(--text-secondary);font-size:11px}
.area{fill:var(--series-1);opacity:.12}.line{fill:none;stroke:var(--series-1);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}
.line-bg{fill:none;stroke:var(--surface-1);stroke-width:5;stroke-linejoin:round;stroke-linecap:round}
.proj{stroke:var(--series-1);stroke-width:2;stroke-dasharray:5 4;opacity:.8}
.dot{fill:var(--series-1);stroke:var(--surface-1);stroke-width:1.5}.dot-proj{fill:var(--surface-1);stroke:var(--series-1);stroke-width:2}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.82rem;color:var(--text-secondary);margin-top:8px}
.legend i,.cov-legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.legend .dash{width:16px;height:0;border-top:2px dashed var(--series-1)}
.cov-track{position:relative;display:flex;height:30px;border-radius:8px;overflow:hidden;background:var(--grid);gap:2px}
.cov-track .seg{height:100%}.cov-target{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--text-primary)}
.cov-legend{display:flex;gap:14px;flex-wrap:wrap;font-size:.82rem;color:var(--text-secondary);margin-top:10px}
.cov-verdict{font-size:.9rem;margin:8px 0 0;color:var(--text-secondary)}
.tips{margin:0;padding:0;list-style:none}.tips li{display:flex;gap:14px;align-items:baseline;padding:10px 0;border-top:1px solid var(--border)}
.tips li:first-child{border-top:0}.tip-eur{font-weight:680;color:var(--series-2);min-width:96px;text-align:right;font-variant-numeric:tabular-nums}
.tip-body{display:flex;flex-direction:column}.tip-detail{color:var(--text-secondary);font-size:.88rem}
.tbl{width:100%;border-collapse:collapse;font-size:.9rem}.tbl th,.tbl td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}
.tbl th{color:var(--text-secondary);font-weight:600}.tbl .num{text-align:right;font-variant-numeric:tabular-nums}
.tbl tfoot td{font-weight:650;border-top:2px solid var(--baseline)}
.muted{color:var(--muted)}.foot{color:var(--muted);font-size:.78rem;margin-top:18px}
.vz-tooltip{position:fixed;pointer-events:none;background:var(--text-primary);color:var(--surface-1);
padding:5px 9px;border-radius:6px;font-size:.8rem;opacity:0;transition:opacity .1s;z-index:60;white-space:nowrap}
/* Overlay + toast */
.overlay{position:fixed;inset:0;background:color-mix(in srgb,var(--plane) 82%,transparent);
backdrop-filter:blur(3px);display:none;flex-direction:column;align-items:center;justify-content:center;gap:18px;z-index:50}
.overlay.show{display:flex}.overlay .ov-txt{font-weight:700;color:var(--brand-teal);font-size:1.05rem}
.overlay .ov-sub{color:var(--text-secondary);font-size:.85rem;margin-top:-8px}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(20px);background:var(--text-primary);
color:var(--surface-1);padding:10px 18px;border-radius:10px;font-size:.86rem;font-weight:600;opacity:0;
transition:all .2s;z-index:70;pointer-events:none}.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
/* Webapp: angemeldeter Nutzer */
.userchip{display:inline-flex;align-items:center;gap:6px;font-size:.82rem;font-weight:600;color:var(--text-secondary);
background:var(--surface-1);border:1px solid var(--border);border-radius:999px;padding:6px 12px}
a.btn{text-decoration:none}
@media (prefers-reduced-motion:reduce){.pcb-logo.pulsing,.pcb-logo.pulsing .pcb-seg,.pcb-logo.pulsing .pcb-disc{animation:none}}
"""

JS = r"""
(function(){
 var root=document.currentScript.closest('.viz-root')||document.querySelector('.viz-root');
 function $(s,c){return (c||root).querySelector(s);} function $$(s,c){return Array.prototype.slice.call((c||root).querySelectorAll(s));}
 // Theme
 var tb=$('#themeBtn'); if(tb){tb.addEventListener('click',function(){
   var cur=root.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
   root.setAttribute('data-theme',cur==='dark'?'light':'dark');});}
 // Tabs
 $$('.tabs button').forEach(function(b){b.addEventListener('click',function(){
   $$('.tabs button').forEach(function(x){x.classList.remove('active');}); b.classList.add('active');
   $$('.tab-panel').forEach(function(p){p.classList.toggle('active',p.id==='tab-'+b.dataset.tab);});});});
 // Mail filtering
 var selMb='all', selCat='all', q='';
 function apply(){
   var cards=$$('.mailcard'), empty=$('#mailEmpty'), shown=0;
   var c={total:0,relevant:0,info:0,high:0};
   cards.forEach(function(card){
     var mbOk=(selMb==='all'||card.dataset.mb===selMb);
     if(mbOk){c.total++; if(card.dataset.cat==='relevant')c.relevant++; else c.info++; if(card.dataset.prio==='high')c.high++;}
     var catOk=(selCat==='all')||(selCat==='info'&&card.dataset.cat==='info')||(selCat==='relevant'&&card.dataset.cat==='relevant')||(selCat==='high'&&card.dataset.prio==='high');
     var qOk=(!q)||card.dataset.text.indexOf(q)>=0;
     var vis=mbOk&&catOk&&qOk; card.style.display=vis?'':'none'; if(vis)shown++;
   });
   if(empty)empty.hidden=shown>0;
   $$('#mailCounts [data-count]').forEach(function(el){el.textContent=c[el.dataset.count];});
 }
 $$('#mbChips .chip').forEach(function(ch){ch.addEventListener('click',function(){
   $$('#mbChips .chip').forEach(function(x){x.classList.remove('active');}); ch.classList.add('active'); selMb=ch.dataset.mb; apply();});});
 $$('#catFilter button').forEach(function(bt){bt.addEventListener('click',function(){
   $$('#catFilter button').forEach(function(x){x.classList.remove('active');}); bt.classList.add('active'); selCat=bt.dataset.cat; apply();});});
 var srch=$('#mailSearch'); if(srch)srch.addEventListener('input',function(){q=srch.value.toLowerCase().trim(); apply();});
 // Mail card expand
 $$('.mailcard.has-draft .mc-head').forEach(function(h){h.addEventListener('click',function(){
   var card=h.parentNode, d=$('.mc-draft',card); card.classList.toggle('open'); if(d)d.hidden=!card.classList.contains('open');});});
 // Copy draft
 function toast(msg){var t=$('#toast'); if(!t)return; t.textContent=msg; t.classList.add('show'); setTimeout(function(){t.classList.remove('show');},1600);}
 $$('.copybtn').forEach(function(btn){btn.addEventListener('click',function(e){
   e.stopPropagation(); var pre=$('.draft-text',btn.parentNode); var txt=pre?pre.textContent:'';
   if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(function(){toast('Antwort kopiert ✓');},function(){toast('Kopieren nicht möglich');});}
   else{try{var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);toast('Antwort kopiert ✓');}catch(err){toast('Kopieren nicht möglich');}}});});
 // Refresh: Webapp = echter Server-Refresh + Status-Polling; Artifact = Reload des letzten Stands
 var rb=$('#refreshBtn'), ov=$('#overlay'), mode=root.dataset.mode||'artifact';
 if(mode==='webapp'){
   var gen=root.dataset.generated||'', ovsub=$('#ovSub');
   function poll(){
     fetch('/api/status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(s){
       if(s.state==='running'){
         if(ov)ov.classList.add('show');
         if(ovsub)ovsub.textContent=(s.started_by?('Gestartet von '+s.started_by+' — '):'')+'Outlook & ERPNext werden neu ausgewertet';
       }else{
         if(ov)ov.classList.remove('show');
         if(s.generated_at&&s.generated_at!==gen){location.reload();}
       }
     }).catch(function(){});
   }
   setInterval(poll,4000);
   if(rb)rb.addEventListener('click',function(){
     if(ov)ov.classList.add('show');
     fetch('/api/refresh',{method:'POST'}).then(poll).catch(function(){if(ov)ov.classList.remove('show');toast('Aktualisierung nicht erreichbar');});
   });
 }else{
   if(rb)rb.addEventListener('click',function(){ if(ov)ov.classList.add('show'); setTimeout(function(){location.reload();},1400);});
   // Auto refresh (Wandmonitor)
   var mins=parseInt(root.dataset.refresh||'0',10);
   if(mins>0){setTimeout(function(){location.reload();},mins*60000);}
 }
 // Chart tooltips
 var tip=document.createElement('div');tip.className='vz-tooltip';document.body.appendChild(tip);
 $$('[data-label]').forEach(function(el){
   el.addEventListener('mousemove',function(e){tip.textContent=el.getAttribute('data-label');tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY-10)+'px';tip.style.opacity=1;});
   el.addEventListener('mouseleave',function(){tip.style.opacity=0;});});
 apply();
})();
"""


def render(m: dict, mode: str = "artifact", user: str | None = None) -> str:
    as_of = date.fromisoformat(m["as_of"])
    gen = m.get("generated_at")
    if gen:
        try:
            stand = datetime.fromisoformat(gen).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            stand = as_of.strftime("%d.%m.%Y")
    else:
        stand = as_of.strftime("%d.%m.%Y")
    refresh_min = int(m.get("auto_refresh_minutes", 0) or 0)
    title = html.escape(m.get("dashboard_title", "Musterfirma Board"))
    company = html.escape(m.get("company", ""))

    sub_extra = (" · Auto-Aktualisierung ~" + str(refresh_min) + " Min"
                 if refresh_min and mode == "artifact" else "")
    userchip = (f'<span class="userchip">👤 {html.escape(user)}</span>'
                if (mode == "webapp" and user) else "")
    logout = ('<a class="btn ghost" href="/logout">Abmelden</a>'
              if (mode == "webapp" and user) else "")
    header = f'''<div class="hd">
  <div class="brand">{pcb_logo_svg(46)}
    <div><h1>{title}</h1>
      <div class="tag">Musterfirma-Sekretärin</div>
      <div class="sub">{company} · Stand {stand}{sub_extra}</div>
    </div></div>
  <div class="actions">
    {userchip}
    <button class="btn primary" id="refreshBtn" type="button">⟳ Live aktualisieren</button>
    <button class="btn ghost" id="themeBtn" type="button">◐ Theme</button>
    {logout}
  </div>
</div>'''

    tabs = '''<div class="tabs">
  <button class="active" data-tab="mail">📥 Posteingang</button>
  <button data-tab="revenue">📊 Umsatz</button>
  <button data-tab="billing">🧾 Abrechnung</button>
</div>'''

    panels = (f'<div class="tab-panel active" id="tab-mail">{_mail_tab(m)}</div>'
              f'<div class="tab-panel" id="tab-revenue">{_revenue_tab(m)}</div>'
              f'<div class="tab-panel" id="tab-billing">{_billing_tab(m)}</div>')

    if mode == "webapp":
        foot = ('Postfach-Übersicht + Antwortvorschläge (zum Kopieren, werden nicht automatisch gesendet). '
                'UPS-Ankunft live abgefragt, sonst über Versanddatum geschätzt. Alle Beträge netto. '
                'Der „Live aktualisieren"-Button startet eine echte Neuauswertung von Outlook & ERPNext — '
                'sichtbar für alle angemeldeten Nutzer.')
    else:
        foot = ('Postfach-Übersicht + Antwortvorschläge (zum Kopieren, werden nicht automatisch gesendet). '
                'UPS-Ankunft live abgefragt, sonst über Versanddatum geschätzt. Alle Beträge netto. '
                'Der „Live aktualisieren"-Button lädt den zuletzt von der Routine erzeugten Stand.')

    overlay = (f'<div class="overlay" id="overlay">{pcb_logo_svg(96, animated=True)}'
               f'<div class="ov-txt">Aktualisiere Daten …</div>'
               f'<div class="ov-sub" id="ovSub">Outlook &amp; ERPNext werden neu ausgewertet</div></div>')

    return f'''<div class="viz-root" data-refresh="{refresh_min}" data-mode="{html.escape(mode)}" data-generated="{html.escape(gen or "")}">
<style>{CSS}</style>
{header}{tabs}{panels}
<p class="foot">{foot}</p>
{overlay}
<div class="toast" id="toast"></div>
<script>{JS}</script>
</div>'''


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(io.STATE_DIR / "metrics.json"))
    ap.add_argument("--output", default=str(io.STATE_DIR / "dashboard.html"))
    args = ap.parse_args()
    m = io.read_json(args.input)
    config = io.load_config()
    m.setdefault("dashboard_title", config["dashboard"]["title"])
    m.setdefault("company", config["company"])
    m.setdefault("auto_refresh_minutes", config.get("board", {}).get("auto_refresh_minutes", 0))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(m), encoding="utf-8")
    print(f"[render_dashboard] -> {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

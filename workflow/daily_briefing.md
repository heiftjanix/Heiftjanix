# Ablauf: Tägliches Briefing (Schritt-für-Schritt)

Dies ist die verbindliche Checkliste, die die Routine jeden Werktagmorgen abarbeitet.
Der eigentliche Auslöse-Prompt steht in `routine_prompt.md`. Geldbeträge werden
**ausschließlich in Python** berechnet (Skripte in `scripts/`), nie im Modell geschätzt.

## Schritt 0 — Connector-Check
- `mcp__Microsoft_365__get_me` aufrufen.
- 1 Datensatz aus ERPNext lesen (`list_documents` Sales Invoice, limit 1).
- Schlägt einer fehl → **degradierte Push** ("Bitte Outlook/ERPNext neu verbinden")
  und mit den verfügbaren Teilen fortfahren, nicht abbrechen.

## Schritt 1 — Daten holen (MCP → `state/raw.json`)
1. **Outlook:** `outlook_email_search` (folderName "Inbox", order newest), Zeitfenster
   = `config.email.lookback_hours` (montags `monday_lookback_hours`, Standard 72 h).
   **Nur UNGELESENE Mails berücksichtigen** (`isRead: false` im Suchergebnis) —
   gelesene Mails gelten als erledigt und gehören weder in die Triage noch ins
   Briefing/Board. Zusätzlich jedes Postfach in `config.email.extra_mailboxes` über
   `mailboxOwnerEmail` scannen (z. B. `bestellung@example.com`). Bei Bedarf
   `read_resource` für Volltext.
2. **Ausgangsrechnungen:** `list_documents` Sales Invoice, `docstatus=1`,
   `posting_date >= <erster Tag des Vor-Vor-Vormonats>`; Felder name, customer,
   base_net_total, posting_date, status. (Laufender Monat = Ist, Vormonate = Baseline.)
3. **Lieferscheine "To Bill":** `list_documents` Delivery Note, `status="To Bill"`;
   Felder name, customer_name, base_net_total, per_billed, posting_date,
   custom_tracking_numbers, custom_ups_shipment_date.
4. **Offene Aufträge:** `list_documents` Sales Order, status in
   ("To Deliver and Bill","To Bill"); net_open = base_net_total·(1−per_billed/100).
5. `raw.json` schreiben mit Schema:
   `{as_of, invoices[], to_bill_delivery_notes[<mit tracking_number, shipment_date>], open_sales_orders[<net_open>]}`.

## Schritt 2 — Mail-Triage (Claude, geführt von `config/relevance_guidance.md`)
Für jede geholte Mail inhaltlich entscheiden und in `state/raw.json` unter `mail`
ablegen (steuert die Posteingang-Übersicht im Board):
- **relevant** (`category:"relevant"`) → zusätzlich einen deutschen **Antwortvorschlag** direkt
  ins Feld **`draft`** des Eintrags schreiben (Sie-Form, Signatur, Platzhalter `[…]` wo Daten
  fehlen; Bezug auf ERPNext-Vorgang, falls Auftrags-/LS-/Rechnungsnr. erkennbar). Das Board
  zeigt den Entwurf in der aufklappbaren Mail-Karte mit **Kopieren-Button**. Für Angebotsanfragen
  (Postfach `anfrage@`) den Standardtext aus `relevance_guidance.md` verwenden.
- **unwichtig** (`category:"info"`) → **ein Satz** als `reason`, kein `draft`.
- Dringlichkeit über `priority:"high"|"normal"` (Betreff/Importance/Inhalt).
- Schema je Eintrag: `{mailbox, sender_name, sender, subject, category, priority, reason, received, draft?}`.
`raw.mail = {window_hours, items:[…]}`. Nichts versenden.

## Schritt 3 — Rechnen & Dashboard (Python)
- `python scripts/run_pipeline.py`
  - ruft UPS-Ankunft ab (`ups_track.py`, live sonst Faustregel),
  - berechnet Ist/Baseline/Prognose/Pipeline und die Posteingang-Übersicht
    (`revenue_aggregate.py` + `forecast.py`),
  - rendert `state/dashboard.html` inkl. **Posteingang-Panel** (`render_dashboard.py`).
- Ergebnis liegt in `state/metrics.json`.

## Schritt 4 — Briefing zusammenstellen (`state/briefing_<datum>.md`)
Reihenfolge: Kernzahlen → relevante Mails mit Vorschlägen → unwichtige Mails →
Abrechnungsliste (zustellt vs. unterwegs, alte >60 Tage markiert) → Push-Tipps →
Link zum Dashboard-Artifact.

## Schritt 5 — Dashboard veröffentlichen
- `Artifact`-Tool auf `state/dashboard.html`, **gleicher Titel/Favicon** (📊) → stabile URL.
- URL oben ins Briefing setzen.

## Schritt 6 — Ausliefern
- **`SendUserFile`** mit `state/briefing_<datum>.md` (display: attach) — enthält die
  sensiblen Inhalte (Entwürfe, Kundennamen).
- **`PushNotification`**: Kernzahlen + Dashboard-URL, z. B.
  „Umsatz Juli 8.710 € · Prognose 72.946 € (73 %) · 10 Rechnungen bereit (8.792 €) · 4 Mails".

## Nicht verhandelbar
- Keine Rechnung automatisch erstellen/buchen, keine Mail automatisch senden.
- Alle Beträge **netto**. Prognose-Ziel = `config.revenue_target`.
- Alles aus den Connectoren neu holen (die Session ist zustandslos gegenüber Vorläufen).

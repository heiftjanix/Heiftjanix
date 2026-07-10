# Musterfirma Team-Board („Sekretärin")

Ein automatisiertes, **interaktives Team-Board** für Musterfirma, das werktags laufend
Outlook (mehrere Postfächer) und ERPNext auswertet:

- 📥 **Posteingang-Board** – alle Postfächer im Überblick mit **Postfach-Auswahl**
  (Alle · m.mustermann@ · bestellung@ · anfrage@ · webshop@), Suche/Filter und
  **aufklappbaren Mail-Karten** mit fertigem **Antwortvorschlag + Kopieren-Button**;
  unwichtige Mails werden nur gezählt/zusammengefasst.
- 🧾 **Abrechnung** – prüft die „To Bill"-Lieferscheine, ob das **Paket angekommen**
  ist (Live-UPS-Abfrage, sonst Faustregel), getrennt nach zustellt / unterwegs / alt.
- 📊 **Umsatz** – Ist-Umsatz, **Monatsend-Prognose** gegen das **100.000 €-Ziel** (netto),
  Pipeline-Deckung und **Tipps, wo sich pushen lohnt**.
- ⟳ **„Live aktualisieren"** mit **pulsierendem PCB-Logo** als Arbeitsanzeige; optionaler
  Auto-Reload für einen Wandmonitor. Theme-Umschalter (hell/dunkel).

Ausgeliefert wird als **interaktives Board** (teilbarer Artifact-Link), zusätzlich ein
**privates Markdown-Briefing** und eine **Push-Benachrichtigung** mit den Kernzahlen.

> **Grundregel:** Das Board **schlägt nur vor**. Es versendet keine Mails und
> erstellt/bucht keine Rechnungen automatisch.

## Wie es läuft

Eine geplante **Claude-Routine** (Cron-Trigger, feuert in diese Session, damit die
Outlook-/ERPNext-Anmeldung erhalten bleibt) arbeitet die Checkliste in
[`workflow/daily_briefing.md`](workflow/daily_briefing.md) ab und veröffentlicht das Board
neu. Takt: **alle 30 Min werktags** über zwei versetzte Stunden-Trigger (`:00` und `:30`,
ca. 06–18 Uhr CEST) – der Scheduler erlaubt minimal einen Stundentakt, daher zwei Trigger.
Der „Live aktualisieren"-Button lädt jeweils den zuletzt veröffentlichten Stand (ein
Artifact darf aus Sicherheitsgründen selbst keine Live-Daten holen). Alle Geldbeträge
werden ausschließlich in Python berechnet.

## Native ERPNext-App (empfohlen)

Unter [`frappe_app/pcb_board/`](frappe_app/pcb_board/README.md) liegt eine
**installierbare Custom-Frappe-App**: Posteingang, Umsatz und Abrechnung als eigene
Seite **direkt in eurem ERPNext** (`/app/pcb-board`). Login = euer normales
ERPNext-Login (kein zweiter Account); „Postfach verbinden" ist ein einmaliger
Microsoft-Consent-Schritt pro Nutzer. Kein separater Server nötig — läuft im
bestehenden Bench, inkl. eigenem 30-Min-Scheduler-Takt (ersetzt die Claude-Cron-
Trigger für diesen Weg). Installation per `bench get-app` + `bench install-app`,
Details und Checkliste in [`frappe_app/pcb_board/README.md`](frappe_app/pcb_board/README.md).
Die reine Rechenlogik ist 1:1 aus `scripts/forecast.py`/`scripts/revenue_aggregate.py`
nach `frappe_app/pcb_board/pcb_board/metrics.py` portiert (kein frappe-Import, eigene
Tests unter `frappe_app/pcb_board/pcb_board/tests/`).

## Team-Webapp (Alternative ohne Bench-Zugriff)

Alternativ zur nativen ERPNext-App gibt es unter `webapp/` eine **gehostete FastAPI-App**
mit echtem **Microsoft-Login**: Jedes Teammitglied meldet sich mit seinem PCB-Microsoft-
Konto an und sieht **sein eigenes Postfach + die geteilten** (bestellung@, anfrage@,
webshop@). Der „Live aktualisieren"-Button stößt hier einen **echten Refresh** an
(Microsoft Graph + ERPNext + Claude-Triage) — währenddessen sehen **alle** angemeldeten
Nutzer das pulsierende PCB-Logo (globaler Status, nicht nur beim Klickenden).

```
webapp/app.py            FastAPI-Routen: /, /login, /auth/callback, /logout,
                          POST /api/refresh, GET /api/status, /healthz
webapp/auth.py            Microsoft-Login (MSAL Auth-Code-Flow) + DEMO_MODE
webapp/graph.py           Microsoft Graph: eigenes + geteilte Postfächer
webapp/erp.py             ERPNext REST-API (Rechnungen, To-Bill-LS, offene Aufträge)
webapp/triage.py          Mail-Triage per Anthropic-API (+ Keyword-Fallback ohne Key)
webapp/service.py         RefreshManager: Hintergrund-Refresh, globaler Status
webapp/demo_data.json     Beispieldaten für DEMO_MODE (keine echten Kundendaten)
```

**Demo starten (ohne jegliche Zugangsdaten):**
```bash
DEMO_MODE=1 SESSION_SECRET=dev uvicorn webapp.app:app --reload
```
Dann `http://localhost:8000/login` öffnen → Demo-Login als Max Mustermann, Demo-Daten,
Keyword-Fallback statt Claude-Triage.

**Echter Betrieb** braucht (siehe `.env.example`):
- **Azure-App-Registrierung** (Azure Portal → App registrations) mit Redirect-URI
  `{BASE_URL}/auth/callback` und den delegierten Graph-Berechtigungen `User.Read`,
  `Mail.Read`, `Mail.Read.Shared`, `offline_access` → `AZURE_CLIENT_ID/SECRET/TENANT_ID`.
- **ERPNext-API-Key/Secret** (ERPNext → Nutzer → API Access) → `ERPNEXT_URL`,
  `ERPNEXT_API_KEY/SECRET`.
- **`ANTHROPIC_API_KEY`** für die Claude-Triage (ohne Key: Keyword-Fallback).
- **`SESSION_SECRET`** (langer Zufalls-String) zum Signieren der Session-Cookies.
- Hosting, z. B. via `webapp/Dockerfile` (`docker build -t pcb-board -f webapp/Dockerfile .`).

Wiederverwendet wird die komplette bestehende Logik (`scripts/lib`, `forecast.py`,
`revenue_aggregate.py`, `ups_track.py`, `render_dashboard.py` mit `mode="webapp"`) —
Geldbeträge werden weiterhin ausschließlich in Python berechnet, nichts wird
automatisch versendet oder verbucht.

**Grenzen:** Token-Cache liegt in-memory (Neustart = neu anmelden); ohne Azure-
Registrierung läuft nur DEMO_MODE; Graph-Zugriff ist lesend, Entwürfe bleiben
Kopieren-Buttons.

## Projektaufbau

```
config/config.example.json    Vorlage (Platzhalter) — nach config/config.json kopieren
                              und mit echten Werten (Firma, Ziel, Postfächer) befüllen
config/config.json            Lokal, NICHT im Repo (gitignored): Ziel, Firma, Zeitzone,
                              UPS-Transittage, Feiertage, Prognose-Parameter, Zeitfenster,
                              email.extra_mailboxes (weitere/geteilte Postfächer)
config/relevance_guidance.example.md  Vorlage — nach relevance_guidance.md kopieren
config/relevance_guidance.md  Lokal, NICHT im Repo: Relevanz-Rubrik + echte Antwortstil-
                              Signatur (Name/Firma)
workflow/routine_prompt.md    Auslöse-Prompt der Routine
workflow/daily_briefing.md    Detaillierter Ablauf
scripts/run_pipeline.py       Orchestriert: UPS → Kennzahlen → Dashboard
scripts/ups_track.py          UPS Tracking API (OAuth2) + Versanddatum-Fallback
scripts/revenue_aggregate.py  Ist/Baseline/Pipeline/Tipps aus raw.json
scripts/forecast.py           Monatsend-Prognose (Werktags-Blend), getestet
scripts/render_dashboard.py   metrics.json → self-contained dashboard.html
scripts/lib/                  Werktags-/Feiertagslogik, JSON-IO
webapp/                       Team-Webapp mit Microsoft-Login (Alternative, siehe oben)
frappe_app/pcb_board/         Native ERPNext-Custom-App (empfohlen, siehe oben)
tests/                        Unit-Tests (python3 -m unittest discover -s tests)
state/                        Scratch (raw.json, metrics.json, dashboard.html) – gitignored
```

## Prognose (kurz)

`Prognose = Ist + gewichteter Tageswert × Rest-Werktage`, wobei sich der Tageswert
früh im Monat auf die stabile 3-Monats-Baseline stützt und mit fortschreitendem
Monat auf die tatsächliche Lauf-Rate umschwenkt (Gewicht `w = min(1, Werktage/K)`).
Werktage = Mo–Fr abzüglich bayerischer Feiertage. Details in `scripts/forecast.py`.
Pipeline (zugestellte/unterwegs Lieferscheine, offene Aufträge) wird **separat** als
Zieldeckung ausgewiesen, nicht auf die Prognose addiert.

## Einrichtung

### Voraussetzungen
- Python 3.11+, Standardbibliothek genügt (optional `requests` für die UPS-API).
- Aktive MCP-Connectoren „Microsoft 365" und „ERPNext" in der Session.

### Echte Konfiguration anlegen (nicht im Repo)
`config/config.json` und `config/relevance_guidance.md` enthalten eure echten
Firmen-/Kontaktdaten und sind deshalb **gitignored** (wie `.env`) — nie committen.
Einmalig aus den Vorlagen erzeugen und mit echten Werten befüllen:
```bash
cp config/config.example.json config/config.json
cp config/relevance_guidance.example.md config/relevance_guidance.md
```

### UPS Live-Abfrage (optional, empfohlen)
Ohne UPS-Zugang wird die Ankunft aus **Versanddatum + Transittagen** geschätzt.
Für die Live-Abfrage:
1. Unter <https://developer.ups.com/> eine App anlegen und **Tracking** aktivieren.
2. `UPS_CLIENT_ID` / `UPS_CLIENT_SECRET` als **Umgebungs-Secrets** hinterlegen
   (siehe `.env.example`; niemals committen).

### Zeitplan / Zeitzone
Zwei Trigger (UTC) für 30-Min-Takt werktags: `0 4-16 * * 1-5` und `30 4-16 * * 1-5`
(≈ 06:00–18:30 CEST im Sommer, im Winter eine Stunde früher). `board.auto_refresh_minutes`
in `config/config.json` steuert den Auto-Reload des Boards. Bei Bedarf Fenster/Takt anpassen.

### Manuell testen
```bash
python3 -m unittest discover -s tests        # Logik-Tests
python3 scripts/run_pipeline.py              # benötigt state/raw.json
```
(In der Routine schreibt Claude `state/raw.json` zuvor aus den ERPNext-Daten.)

## Grenzen & Hinweise
- **Outlook ist nur lesend** → Entwürfe werden als Text geliefert, nicht in Outlook gespeichert.
- Das Dashboard ist standardmäßig **privat**; beim Teilen des Links werden Kundennamen sichtbar.
- Läuft die Session-Anmeldung ab, meldet der Connector-Check dies und liefert ein Teil-Briefing.

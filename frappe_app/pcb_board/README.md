# PCB Board — native ERPNext-Custom-App

Posteingang (mit Antwortvorschlägen), Umsatz-Prognose und Abrechnung als eigene
ERPNext-Seite (`/app/pcb-board`). Login = euer normales ERPNext-Login; „Postfach
verbinden" ist ein einmaliger Microsoft-Consent-Schritt pro Nutzer (unabhängig vom
ERPNext-Login, da Outlook-Zugriff eine eigene Freigabe braucht).

> **Grundregel:** Die Seite **schlägt nur vor**. Sie versendet keine Mails und
> erstellt/bucht keine Rechnungen automatisch.

## Installation

Voraussetzung: Ein bestehendes Frappe/ERPNext-Bench mit Zugriff auf die Konsole
(SSH), z. B. `bench --site erp.example.com ...`.

> **Frappe Cloud:** Auf Frappe Cloud gibt es keine direkte SSH/Bench-Konsole für
> Custom Apps — die Installation läuft dort über "Bench" → "Apps" → "Install App
> from GitHub". **Wichtig:** Der Installer erwartet `pyproject.toml` **im Root des
> gewählten Branches** — er kann nicht mit einem Unterordner in einem Monorepo
> umgehen ("Not a valid Frappe App! pyproject.toml does not exist in app
> directory."). Deshalb gibt es dafür den separaten Branch **`frappe-app-pcb-board`**
> (per `git subtree split --prefix=frappe_app/pcb_board` erzeugt): Er enthält
> **nur** den Inhalt dieses Ordners, mit `pyproject.toml` direkt im Root. Im Dialog
> also die GitHub-URL wie gewohnt, aber im Branch-Dropdown **`frappe-app-pcb-board`**
> statt `claude/work-automation-dashboard-d5pz9j` auswählen. Noch nicht
> end-to-end durchgetestet (kein Frappe-Cloud-Zugriff) — bitte vorab in einer
> Test-/Staging-Site ausprobieren, bevor produktiv installiert wird. Bei
> künftigen Änderungen an `frappe_app/pcb_board/` muss der Split-Branch neu
> erzeugt und gepusht werden (`git subtree split --prefix=frappe_app/pcb_board
> -b frappe-app-pcb-board-new` + `git push -f origin
> frappe-app-pcb-board-new:frappe-app-pcb-board`).

```bash
# 1) App ins Bench holen (lokaler Pfad oder Git-URL zu diesem Repo)
bench get-app /pfad/zu/diesem/repo/frappe_app/pcb_board
# oder per Git (root-App-Branch, siehe Hinweis oben):
# bench get-app https://github.com/<org>/Heiftjanix.git --branch frappe-app-pcb-board

# 2) Auf der Site installieren
bench --site erp.example.com install-app pcb_board
bench --site erp.example.com migrate
bench build
bench restart   # bzw. Supervisor/systemd neu laden, je nach Setup
```

## Secrets hinterlegen (site_config.json, NICHT im Repo)

```bash
bench --site erp.example.com set-config anthropic_api_key "sk-ant-..."
bench --site erp.example.com set-config azure_client_id "..."
bench --site erp.example.com set-config azure_client_secret "..."
bench --site erp.example.com set-config azure_tenant_id "..."
# optional, für Live-UPS-Tracking (sonst Fallback über Versanddatum + Transittage):
bench --site erp.example.com set-config ups_client_id "..."
bench --site erp.example.com set-config ups_client_secret "..."
```

### Azure-App-Registrierung (für „Postfach verbinden")

1. Azure Portal → App registrations → New registration.
2. Redirect-URI (Web): `https://erp.example.com/api/method/pcb_board.api.outlook_callback`
   (Domain durch eure echte ERPNext-URL ersetzen).
3. API-Berechtigungen (Microsoft Graph, **delegiert**): `User.Read`, `Mail.Read`,
   `Mail.Read.Shared`, `offline_access`.
4. Client-Secret erzeugen → als `azure_client_secret` hinterlegen (siehe oben).

Ohne diese drei `azure_*`-Werte funktioniert die Seite weiterhin für Umsatz/Abrechnung
(rein ERPNext-intern) — nur „Postfach verbinden" zeigt dann einen Hinweis, dass die
Azure-Registrierung noch fehlt.

## Einstellungen

Unter **PCB Board Settings** (normale ERPNext-Formularmaske, Suche im Awesomplete)
lassen sich Umsatzziel, geteilte Postfächer, Mail-Rückblick (Tage, Standard 1 —
klein halten, jede Mail kostet einen Claude-API-Call), Prognose-Parameter und
das Claude-Modell für die Mail-Triage anpassen — kein Datei-Edit nötig.

## Ablauf nach der Installation (Checkliste)

- [ ] `/app/pcb-board` öffnen — Seite lädt (zunächst „Noch kein Datenstand").
- [ ] **PCB Board Settings** ausfüllen (mind. Umsatzziel + geteilte Postfächer).
- [ ] „Live aktualisieren" klicken → PCB-Logo pulsiert; nach Abschluss erscheinen
      Umsatz/Abrechnung (auch ohne verbundenes Postfach, da rein ERPNext-Daten).
- [ ] „Postfach verbinden" klicken (falls Azure hinterlegt) → Microsoft-Login →
      zurück zur Seite → Posteingang zeigt Mails aus eigenem + geteilten Postfächern.
- [ ] Scheduler-Log prüfen (`bench --site <site> doctor` bzw. Error Log in ERPNext),
      dass `pcb_board.refresh.scheduled_refresh` alle 30 Min werktags läuft (und
      `scheduled_mail_sync` alle 5 Min, siehe unten).

## Wie es funktioniert (kurz)

- **Daten:** `refresh.py` liest ERPNext direkt über `frappe.get_all` (kein REST/MCP
  nötig), holt bei verbundenen Postfächern Microsoft-Graph-Mails, klassifiziert sie
  gebatcht per Anthropic-API (mehrere Mails pro Call, wichtig bei knappen Requests-
  pro-Minute-Limits; Fallback: Keyword-Heuristik ohne Key oder bei Batch-Fehlern) und
  berechnet Prognose/Pipeline/Tipps in `metrics.py` (reine Python-Funktionen, 1:1-Port
  aus `scripts/forecast.py` + `scripts/revenue_aggregate.py` im Hauptrepo).
- **Status/Refresh:** Ergebnis + Status liegen in `frappe.cache()` (Redis) — daher
  sehen **alle** angemeldeten Nutzer denselben Stand. Der „Aktualisiere..."-Hinweis
  ist bewusst **kein** vollflächiges, blockierendes Overlay mehr, sondern ein kleiner
  Hinweis oben rechts — das Board bleibt für alle bedienbar (Tabs, Filter, Mail-
  Karten), während im Hintergrund aktualisiert wird.
- **Takt:** `hooks.py` registriert zwei Frappe-Scheduler-Cronjobs (kein externer
  Trigger nötig): alle 30 Min werktags ein **voller** Refresh (ERPNext + Mail + UPS,
  `scheduled_refresh`), dazwischen alle 5 Min ein **stiller Mail-only-Sync**
  (`scheduled_mail_sync`, rührt ERPNext/UPS nicht an und setzt nie den „läuft
  gerade"-Status — kein Ladehinweis dafür). Ein Rate-Limit (429) beim Mail-Triage
  löst einen einmaligen ~1-Minuten-Backoff-Retry aus, bevor der betroffene Batch auf
  die Keyword-Heuristik zurückfällt.
- **Postfach-Zugriff:** `PCB Board Mail Token` speichert den MSAL-Token-Cache pro
  Nutzer (Frappe-Password-Feld, verschlüsselt); jeder Nutzer sieht nur sein eigenes
  + die in den Settings konfigurierten geteilten Postfächer.
- **Gelesen-Status & Zuweisung:** Mail-Karten zeigen „● ungelesen" (aus Outlook via
  Graph `isRead`). Über „+ Zuweisen" wird eine Mail einem Kollegen zugewiesen
  (`PCB Board Mail Assignment`, ein Datensatz pro `internet_message_id` — überlebt
  Refreshs, da Mails selbst nicht gespeichert werden, nur die Zuordnung). Tab
  „Zuweisungen" zeigt allen Nutzern alle offenen/erledigten Zuweisungen team-weit
  (kein Owner-Filter — bewusst für alle sichtbar/bearbeitbar).
- **Kosten:** Tab „Kosten" summiert Wareneingänge (`Purchase Receipt`, ERPNext,
  laufender Monat) plus zwei fixe, in PCB Board Settings gepflegte Kostenpunkte
  (Personalkosten/Monat, Miete/Monat) zu einer Gesamtkostenzahl. Diese
  Gesamtkosten erscheinen zusätzlich im Tab „Umsatz" als roter Marker auf dem
  Zielerreichungs-Balken (neben dem Umsatzziel) plus Klartext-Hinweis, ob der
  laufende Monat die Kosten schon deckt — und eine Prognose-Kachel
  „Gewinn/Verlust" zeigt den erwarteten Monatsabschluss nach Kostenabzug.
- **Top-Produkte:** Tab „Umsatz" zeigt zusätzlich die 5 umsatzstärksten Produkte
  des laufenden Monats (aus `Sales Invoice Item`, nach `base_net_amount` summiert
  und absteigend sortiert — nur gebuchte Rechnungen).

## Grenzen

- Ohne Azure-Registrierung: kein Posteingang, Umsatz/Abrechnung funktionieren trotzdem.
- Ohne UPS-Zugangsdaten: Zustellstatus wird geschätzt (Versanddatum + Transittage).
- Token-Cache ist an den einzelnen Nutzer gebunden — läuft die Microsoft-Freigabe ab,
  zeigt die Seite einen Hinweis, erneut „Postfach verbinden" zu klicken.

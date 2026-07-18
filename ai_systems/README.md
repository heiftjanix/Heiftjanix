# AI-Systems — Virtuelle Firma für n8n-Agenten

**AI-Systems** ist eine installierbare Plattform, mit der ihr — mit Claudes Hilfe —
**n8n-Agenten baut, verwaltet und benennt**. Das Erscheinungsbild ist eine
**virtuelle Firma**: Ihr legt **Abteilungen** an (Sekretariat, Buchhaltung,
Versand, …), und jede Abteilung beschäftigt **Mitarbeiter** — jeder Mitarbeiter
ist in Wirklichkeit ein n8n-Workflow auf eurer bestehenden n8n-Instanz.

- 💬 **Mitarbeiter einstellen per Chat:** Beschreibt auf Deutsch, was der Agent
  tun soll („Fasse mir jeden Morgen die ungelesenen Mails zusammen") — Claude
  schlägt Name, Stellenbezeichnung und den fertigen n8n-Workflow vor; ihr prüft
  und klickt „Übernehmen & deployen". Bestehende Mitarbeiter lassen sich
  genauso per Chat bearbeiten.
- 🗂️ **Verwalten wie eine Firma:** Abteilungs-Kacheln, Mitarbeiter-Karten mit
  Aktiv-Schalter und Lauf-Status (grün/gelb/rot), Ausführungsverlauf aus n8n,
  Umbenennen, „Mitarbeiter entlassen".
- 🔌 **Fester Konnektoren-Katalog** eurer Systeme: ERPNext, Microsoft 365 /
  Outlook, GitHub, UPS und die Anthropic-API. Pro Abteilung gebt ihr frei,
  welche Systeme deren Agenten nutzen dürfen — Claude verdrahtet nur Erlaubtes.
- 🛡️ **Netzwerk-Zugriffsregeln:** Pro Abteilung (und optional pro Agent) eine
  Host-Allowlist (`erp.example.com`, `*.example.com`). Beim Deployment wird das
  Workflow-JSON geprüft; nicht erlaubte oder nicht statisch prüfbare Ziele
  werden **abgelehnt**.
- 🎭 **Demo-Modus ohne Zugangsdaten:** Ohne `N8N_URL` (oder mit `DEMO_MODE=1`)
  startet eine Demo-Firma mit Beispiel-Mitarbeitern und gecannten
  Claude-Antworten — ideal zum Ausprobieren.

> **Grundregel wie beim Team-Board:** Secrets bleiben in Umgebungsvariablen.
> Sie landen weder in der Datenbank noch im Workflow-JSON — Claude verdrahtet
> Zugangsdaten ausschließlich als n8n-Expressions (`{{$env.NAME}}`), die
> Variablen müssen **auf der n8n-Instanz** gesetzt sein.

## Schnellstart (Demo, ohne jegliche Zugangsdaten)

```bash
pip install -r ai_systems/requirements.txt
DEMO_MODE=1 uvicorn ai_systems.app:app --port 8010
```

Dann <http://localhost:8010> öffnen → Demo-Firma mit Sekretariat, Buchhaltung
und Versand. „＋ Mitarbeiter einstellen" startet den Chat (gecannte Antworten).

## Echter Betrieb

1. **`.env` befüllen** (siehe `.env.example`, Abschnitt „AI-Systems"):
   - `N8N_URL` + `N8N_API_KEY` — bestehende n8n-Instanz
     (n8n → Settings → n8n API → Create API Key).
   - `ANTHROPIC_API_KEY` — für den Agenten-Generator
     (Modell per `AI_SYSTEMS_MODEL` änderbar, Default `claude-fable-5`).
   - Konnektor-Zugangsdaten nach Bedarf: `ERPNEXT_*`, `AZURE_*`, `GITHUB_TOKEN`,
     `UPS_*`. **Wichtig:** Dieselben Variablen zusätzlich auf der n8n-Instanz
     setzen, damit die deployten Workflows sie zur Laufzeit auflösen können.
2. **Starten** — entweder direkt:
   ```bash
   uvicorn ai_systems.app:app --host 0.0.0.0 --port 8010
   ```
   oder per Docker Compose (empfohlen):
   ```bash
   cd ai_systems && docker compose up -d --build
   ```
   Die SQLite-Datenbank (Abteilungen, Agenten, Regeln, Chats) liegt im Volume
   `ai_systems_state` bzw. lokal unter `state/ai_systems.db` (gitignored).

## Desktop-App (Electron, Windows-Installer)

Unter `ai_systems/electron/` liegt ein bewusst dünner Desktop-Wrapper: Er lädt
die Web-App von eurem Server (Standard `http://localhost:8010`; änderbar unter
„Datei → Einstellungen…") und liefert eine Fehlerseite, wenn der Server nicht
erreichbar ist.

```bash
cd ai_systems/electron
npm install
npm start        # direkt starten (Entwicklung)
npm run dist     # Windows-Installer (NSIS) nach electron/dist/ bauen
```

## Wie die Zugriffsverwaltung funktioniert (und ihre Grenzen)

Jede Abteilung hat eine **Host-Allowlist** aus drei Quellen:

1. manuell gepflegte Regeln der Abteilung (`erp.example.com`, `*.example.com` —
   Wildcard matcht Subdomains, nicht die Apex-Domain),
2. optionale agentenspezifische Zusatzregeln,
3. implizite Hosts der freigegebenen Konnektoren (z. B. schaltet die
   Microsoft-Freigabe `graph.microsoft.com` und `login.microsoftonline.com` frei).

Beim **Deployment** wird das Workflow-JSON vollständig durchsucht (alle
Parameter, auch URLs innerhalb von n8n-Expressions). Verstöße und dynamische,
nicht statisch prüfbare Hosts (`={{ $json.url }}`) führen zur Ablehnung mit
verständlicher Fehlermeldung; Claude bekommt die Fehler automatisch einmal zur
Korrektur zurückgereicht. Zusätzlich sind nur unkritische Node-Typen erlaubt
(kein `executeCommand` o. ä.).

**Grenze:** Die Prüfung erfolgt zum Deploy-Zeitpunkt. Eine Durchsetzung zur
*Laufzeit* würde einen Egress-Proxy vor der n8n-Instanz erfordern (z. B.
Squid/Envoy mit Host-Allowlist) — bewusst außerhalb des Umfangs; wer Workflows
direkt in n8n editiert, umgeht die Prüfung. Der n8n-API-Key gehört deshalb nur
in die Hände der Plattform.

## Projektaufbau

```
ai_systems/
├── app.py               FastAPI: HTML-SPA (/) + JSON-API (/api/...)
├── render_ui.py         Deutsche Single-Page-Oberfläche (Inline-CSS/JS, hell/dunkel)
├── service.py           Chat → Claude-Vorschlag → Validierung → Deploy nach n8n
├── claude_gen.py        Anthropic Messages API (strukturierte Ausgabe) + Demo-Fallback
├── prompts.py           System-Prompt: n8n-Spezifikation, Konnektor-Snippets, Allowlist
├── netrules.py          Host-Allowlist-Matching + URL-Extraktion aus Workflow-JSON
├── workflow_validate.py Strukturprüfung + Node-Typ-Whitelist
├── n8n_client.py        n8n-REST-Client (X-N8N-API-KEY) + In-Memory-DemoN8n
├── connectors.py        Fester Katalog: ERPNext, M365, GitHub, UPS, Anthropic
├── db.py                SQLite: Abteilungen, Agenten, Regeln, Chats (state/ai_systems.db)
├── config.py            ENV-Konfiguration, Demo-Modus-Erkennung
├── demo_data.json       Demo-Firma + gecanntes Chat-Szenario
├── Dockerfile           Web-App-Image (Port 8010)
├── docker-compose.yml   Compose-Setup (nur AI-Systems, n8n extern)
└── electron/            Desktop-Wrapper (npm run dist → Windows-Installer)
```

## Tests

```bash
python3 -m unittest tests.test_ai_db tests.test_ai_netrules \
  tests.test_ai_workflow_validate tests.test_ai_n8n_client \
  tests.test_ai_claude_gen tests.test_ai_app
```

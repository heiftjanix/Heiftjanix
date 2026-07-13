Führe das tägliche Arbeitsalltag-Briefing für Musterfirma GmbH aus. Arbeite die
Checkliste in workflow/daily_briefing.md Schritt für Schritt ab. Verlasse dich NICHT
auf frühere Konversation – lies die Konfiguration aus dem Repo (config/config.json,
config/relevance_guidance.md) und hole alle Daten frisch über die MCP-Connectoren.

Kurzfassung der Schritte:
0. Connector-Check (get_me + 1 ERPNext-Datensatz). Bei Fehler: degradierte Push + weiter.
1. Outlook-Mails (Zeitfenster aus config; Mo = 72 h; auch config.email.extra_mailboxes
   via mailboxOwnerEmail; NUR UNGELESENE Mails berücksichtigen — gelesene gelten als
   erledigt) und ERPNext-Daten holen (Sales Invoice laufender + 3 Vormonate,
   Delivery Note status="To Bill", offene Sales Orders) und nach state/raw.json schreiben.
2. Mails inhaltlich einordnen und als state/raw.json["mail"] ablegen (je Eintrag
   mailbox, sender_name, subject, category "relevant"/"info", priority "high"/"normal",
   reason); für relevante den deutschen Antwortvorschlag direkt ins Feld `draft` des
   Eintrags schreiben (Board zeigt ihn mit Kopieren-Button; Angebotsanfragen → Standardtext
   aus relevance_guidance.md). Geführt von config/relevance_guidance.md.
3. `python3 scripts/run_pipeline.py` ausführen (UPS-Ankunft, Kennzahlen, Prognose,
   Dashboard inkl. Posteingang-Übersicht).
4. state/briefing_<datum>.md zusammenstellen (Kernzahlen, Mail-Vorschläge, unwichtige
   Mails, Abrechnungsliste zustellt/unterwegs/alt, Push-Tipps, Dashboard-Link).
5. state/dashboard.html mit dem Artifact-Tool veröffentlichen (Favicon 📊, gleicher Titel).
6. Ausliefern: SendUserFile(briefing) + PushNotification(Kernzahlen + Dashboard-URL).

Regeln: Beträge nur in Python rechnen. NICHTS automatisch senden oder verbuchen –
ausschließlich Vorschläge. Ziel = 100.000 € Netto-Rechnungsumsatz/Monat.

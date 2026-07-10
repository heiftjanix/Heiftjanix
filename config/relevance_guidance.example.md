# Mail-Relevanz & Antwortstil

Diese Datei steuert, wie die Routine eingehende Outlook-Mails einordnet und
Antwortvorschläge formuliert. Anpassen nach Bedarf.

## Wann ist eine Mail RELEVANT (→ Antwortvorschlag)?

Claude beurteilt inhaltlich. Als relevant gilt in der Regel eine Mail, die eine
Handlung oder Antwort von Max Mustermann bzw. Musterfirma erfordert, z. B.:

- **Kunden-/Auftragsbezug:** Bestellungen, Auftragsbestätigungen, Angebotsanfragen,
  Preis-/Lieferzeitfragen, Änderungswünsche.
- **Liefer-/Versandthemen:** Nachfragen zu Lieferscheinen, Sendungsstatus, Reklamationen,
  Retouren, Transportschäden.
- **Rechnung/Zahlung:** Rückfragen zu Rechnungen, Mahnungen, Zahlungsavis, Gutschriften.
- **Technische Rückfragen** zu PCB-Produkten (z. B. CAN-/IO-Baugruppen).
- **Termine/Meetings**, die eine Zu-/Absage brauchen.
- Persönlich adressierte Mails eines bekannten Geschäftskontakts mit konkreter Frage.

## Wann ist eine Mail UNWICHTIG (→ nur 1-Satz-Zusammenfassung)?

- Newsletter, Werbung, automatische Systemmeldungen ohne Handlungsbedarf.
- Reine FYI-/CC-Mails ohne Frage an Max Mustermann.
- Interne Verteiler ohne konkrete Aufgabe.
- Offensichtlicher Spam.

Im Zweifel: eher als relevant einstufen (lieber ein Vorschlag zu viel als eine
wichtige Mail übersehen).

## Antwortstil für Vorschläge

- Sprache: **Deutsch**, höflich-sachlicher Geschäftston (Sie-Form).
- Kurz und konkret; auf die eigentliche Frage eingehen.
- Keine erfundenen Fakten/Zusagen (Preise, Termine, Bestände) — wenn Daten fehlen,
  Platzhalter in `[eckigen Klammern]` setzen, die Max Mustermann ausfüllt.
- Wenn passend: Bezug auf konkrete ERPNext-Daten herstellen (Auftrags-/Lieferschein-/
  Rechnungsnummer), sofern in der Mail erkennbar.
- Grußformel:

  ```
  Mit freundlichen Grüßen
  Max Mustermann
  Musterfirma GmbH
  ```

- Der Vorschlag ist ein **Entwurf zum Kopieren** — er wird NICHT automatisch versendet.

## Standard-Antworttexte

### Angebotsanfragen (Postfach `anfrage@example.com` bzw. Website-Formular)
Für neue Angebotsanfragen diesen Standardtext als Entwurf vorschlagen. **Kein**
konkretes Angebot und **kein** Liefer-/Angebotstermin zusagen – nur eine
Rückmeldung innerhalb eines Tages ankündigen. Ist im Formular ein Ansprechpartner
erkennbar, mit „Sehr geehrte/r Herr/Frau [Name]" personalisieren, sonst neutral.

```
Sehr geehrte Damen und Herren,

vielen Dank für Ihre Anfrage. Wir haben Ihre Angebotsanfrage erhalten und melden
uns innerhalb eines Tages bei Ihnen.

Mit freundlichen Grüßen
Max Mustermann
Musterfirma GmbH
```

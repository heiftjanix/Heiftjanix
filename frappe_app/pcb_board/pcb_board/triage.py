"""Mail-Triage: klassifiziert eine Mail (relevant/info, Priorität) und formuliert
bei Bedarf einen deutschen Antwortvorschlag — per Anthropic-API.

Port von webapp/triage.py (Hauptrepo). Unterschiede: Modell + API-Key werden als
Parameter übergeben (aus PCB Board Settings / frappe.conf, siehe refresh.py) statt
aus Umgebungsvariablen; die Relevanz-Rubrik (config/relevance_guidance.md im
Hauptrepo) ist hier als Konstante eingebettet, da die Bench-Umgebung keinen
Zugriff auf das Repo hat. Ohne API-Key greift ein deterministischer Keyword-Fallback.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL = "claude-opus-4-8"
_CACHE: dict[str, dict] = {}

STANDARD_ANGEBOT_DRAFT = """Sehr geehrte Damen und Herren,

vielen Dank für Ihre Anfrage. Wir haben Ihre Angebotsanfrage erhalten und melden
uns innerhalb eines Tages bei Ihnen.

Mit freundlichen Grüßen
Max Mustermann
Musterfirma GmbH"""

RELEVANCE_GUIDANCE = """# Mail-Relevanz & Antwortstil

## Wann ist eine Mail RELEVANT (-> Antwortvorschlag)?

Als relevant gilt eine Mail, die eine Handlung oder Antwort erfordert, z. B.
Kunden-/Auftragsbezug (Bestellungen, Auftragsbestätigungen, Angebotsanfragen,
Preis-/Lieferzeitfragen), Liefer-/Versandthemen (Sendungsstatus, Reklamationen,
Retouren), Rechnung/Zahlung (Rückfragen, Mahnungen), technische Rückfragen zu
PCB-Produkten, Termine, die eine Zu-/Absage brauchen.

## Wann ist eine Mail UNWICHTIG (-> nur Info)?

Newsletter, Werbung, automatische Systemmeldungen ohne Handlungsbedarf,
reine FYI-/CC-Mails, interne Verteiler ohne konkrete Aufgabe, Spam.

Im Zweifel: eher als relevant einstufen.

## Antwortstil

Deutsch, höflich-sachlicher Geschäftston (Sie-Form), kurz und konkret. Keine
erfundenen Fakten/Zusagen (Preise, Termine, Bestände) — Platzhalter in
[eckigen Klammern] setzen, wenn Daten fehlen. Grußformel:

Mit freundlichen Grüßen
Max Mustermann
Musterfirma GmbH

Der Vorschlag ist ein Entwurf zum Kopieren — er wird NICHT automatisch versendet.

## Angebotsanfragen

Für neue Angebotsanfragen den Standardtext vorschlagen. Kein konkretes Angebot
und kein Liefer-/Angebotstermin zusagen — nur eine Rückmeldung innerhalb eines
Tages ankündigen.
"""

_ANGEBOT_KEYWORDS = ("angebot", "anfrage", "quote", "rfq")
_URGENT_KEYWORDS = ("dringend", "urgent", "deadline", "asap", "eilt")
_RELEVANT_KEYWORDS = (
    "bestellung", "auftrag", "lieferschein", "rechnung", "mahnung", "sendung",
    "reklamation", "retoure", "termin", "order", "invoice", "shipment", "pending",
)
_INFO_KEYWORDS = ("newsletter", "werbung", "unsubscribe", "angebot der woche")


class MailTriage(BaseModel):
    category: Literal["relevant", "info"]
    priority: Literal["high", "normal"]
    reason: str
    draft: str | None = None


def _keyword_fallback(subject: str, body_preview: str) -> MailTriage:
    text = f"{subject} {body_preview}".lower()
    if any(k in text for k in _INFO_KEYWORDS):
        return MailTriage(category="info", priority="normal", reason="Newsletter/Werbung.")
    if any(k in text for k in _ANGEBOT_KEYWORDS):
        return MailTriage(category="relevant", priority="normal",
                           reason="Angebotsanfrage erkannt (Standardtext).",
                           draft=STANDARD_ANGEBOT_DRAFT)
    if any(k in text for k in _RELEVANT_KEYWORDS):
        prio = "high" if any(k in text for k in _URGENT_KEYWORDS) else "normal"
        return MailTriage(category="relevant", priority=prio,
                           reason="Enthält geschäftsrelevante Begriffe – bitte prüfen.",
                           draft=None)
    return MailTriage(category="info", priority="normal", reason="Keine erkennbare Handlungsnotwendigkeit.")


def triage_message(msg: dict, model: str = DEFAULT_MODEL, api_key: str | None = None) -> dict:
    """msg: {mailbox, sender_name, sender, subject, body_preview, internet_message_id}."""
    key = msg.get("internet_message_id") or f"{msg.get('mailbox')}|{msg.get('subject')}"
    if key in _CACHE:
        result = _CACHE[key]
    else:
        if api_key:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                resp = client.messages.parse(
                    model=model,
                    max_tokens=1024,
                    system=[{
                        "type": "text",
                        "text": RELEVANCE_GUIDANCE,
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{
                        "role": "user",
                        "content": (
                            f"Postfach: {msg.get('mailbox')}\n"
                            f"Absender: {msg.get('sender_name')} <{msg.get('sender')}>\n"
                            f"Betreff: {msg.get('subject')}\n"
                            f"Textvorschau: {msg.get('body_preview')}\n\n"
                            "Klassifiziere diese Mail gemäß der Relevanz-Rubrik und "
                            "formuliere bei Relevanz einen Antwortvorschlag (sonst draft=null)."
                        ),
                    }],
                    output_format=MailTriage,
                )
                result = resp.parsed_output.model_dump()
            except Exception as exc:  # noqa: BLE001 — jede API-Störung -> Fallback
                sys.stderr.write(f"[triage] Anthropic-API fehlgeschlagen, nutze Fallback: {exc}\n")
                result = _keyword_fallback(msg.get("subject", ""), msg.get("body_preview", "")).model_dump()
        else:
            result = _keyword_fallback(msg.get("subject", ""), msg.get("body_preview", "")).model_dump()
        _CACHE[key] = result

    return {
        "mailbox": msg.get("mailbox"),
        "sender_name": msg.get("sender_name"),
        "sender": msg.get("sender"),
        "subject": msg.get("subject"),
        **result,
    }


def triage_all(messages: list[dict], model: str = DEFAULT_MODEL, api_key: str | None = None,
                max_workers: int = 8) -> list[dict]:
    """Triagiert alle Mails parallel (I/O-gebunden: je ein Anthropic-API-Call) —
    bei einem größeren Mail-Rückblick (siehe PCB Board Settings) wären sequenzielle
    Aufrufe sonst spürbar langsam (ein Refresh kann sonst mehrere Minuten hängen)."""
    if not messages:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(messages))) as pool:
        return list(pool.map(lambda m: triage_message(m, model, api_key), messages))

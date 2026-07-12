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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
RATE_LIMIT_BACKOFF_SECONDS = 60
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


class MailTriageBatch(BaseModel):
    results: list[MailTriage]


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


def _cache_key(msg: dict) -> str:
    return msg.get("internet_message_id") or f"{msg.get('mailbox')}|{msg.get('subject')}"


def _build_result(msg: dict, result: dict) -> dict:
    return {
        "internet_message_id": msg.get("internet_message_id"),
        "graph_id": msg.get("graph_id"),
        "mailbox": msg.get("mailbox"),
        "mailbox_email": msg.get("mailbox_email"),
        "sender_name": msg.get("sender_name"),
        "sender": msg.get("sender"),
        "subject": msg.get("subject"),
        "is_read": msg.get("is_read"),
        **result,
    }


def triage_message(msg: dict, model: str = DEFAULT_MODEL, api_key: str | None = None) -> dict:
    """Triagiert eine einzelne Mail per eigenem API-Call. Wird nur noch für den
    Keyword-Fallback (kein API-Key) und in Tests benutzt — der normale Pfad läuft
    über triage_all()/_triage_batch(), da einzelne Calls pro Mail bei knappen
    Anthropic-Rate-Limits (Requests/Minute, nicht nur Rechenzeit) schnell in 429s
    laufen. msg: {mailbox, sender_name, sender, subject, body_preview, internet_message_id}."""
    key = _cache_key(msg)
    if key in _CACHE:
        return _build_result(msg, _CACHE[key])

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
    return _build_result(msg, result)


def _triage_batch(msgs: list[dict], model: str, api_key: str) -> list[dict]:
    """Ein einziger API-Call für mehrere Mails auf einmal — entscheidend, wenn das
    Anthropic-Konto ein knappes Requests-pro-Minute-Limit hat (nicht nur ein
    Zeit-/Compute-Limit): weniger, dafür größere Calls kommen viel weiter, bevor
    das Limit greift. Wirft bei jeder Störung (429, Antwort passt nicht zur Anzahl
    Mails, ...) — der Aufrufer fängt das ab und nutzt den Keyword-Fallback."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    body = "\n\n".join(
        f"[Mail {i + 1}]\n"
        f"Postfach: {m.get('mailbox')}\n"
        f"Absender: {m.get('sender_name')} <{m.get('sender')}>\n"
        f"Betreff: {m.get('subject')}\n"
        f"Textvorschau: {m.get('body_preview')}"
        for i, m in enumerate(msgs)
    )
    resp = client.messages.parse(
        model=model,
        max_tokens=1024 * len(msgs),
        system=[{
            "type": "text",
            "text": RELEVANCE_GUIDANCE,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": (
                f"Klassifiziere ALLE {len(msgs)} folgenden Mails gemäß der Relevanz-Rubrik "
                f"und formuliere bei Relevanz je einen Antwortvorschlag (sonst draft=null).\n"
                f"Gib in `results` GENAU {len(msgs)} Einträge zurück, in exakt derselben "
                f"Reihenfolge wie die Mails unten (Ergebnis 1 = Mail 1, usw.).\n\n{body}"
            ),
        }],
        output_format=MailTriageBatch,
    )
    results = resp.parsed_output.results
    if len(results) != len(msgs):
        raise ValueError(f"Batch-Antwort hatte {len(results)} Ergebnisse für {len(msgs)} Mails")
    return [r.model_dump() for r in results]


def _triage_batch_with_retry(msgs: list[dict], model: str, api_key: str) -> list[dict]:
    """Wie _triage_batch(), aber bei einem Rate-Limit (429) einmal ~1 Min. warten und
    erneut versuchen, statt sofort auf den Keyword-Fallback auszuweichen — bei einem
    knappen Requests-pro-Minute-Limit reicht das oft schon, um durchzukommen."""
    try:
        return _triage_batch(msgs, model, api_key)
    except Exception as exc:
        if getattr(exc, "status_code", None) != 429:
            raise
        sys.stderr.write(
            f"[triage] Rate-Limit erreicht ({len(msgs)} Mails) — warte "
            f"{RATE_LIMIT_BACKOFF_SECONDS}s und versuche einmal erneut...\n"
        )
        time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
        return _triage_batch(msgs, model, api_key)


def triage_all(messages: list[dict], model: str = DEFAULT_MODEL, api_key: str | None = None,
                batch_size: int = 20, max_workers: int = 2) -> list[dict]:
    """Triagiert alle Mails — gebatcht (mehrere Mails pro API-Call), da ein knappes
    Requests-pro-Minute-Limit (statt nur Zeit-/Compute-Limit) durch mehr parallele
    Einzel-Calls nicht schneller wird, sondern nur mehr 429-Fehler produziert."""
    if not messages:
        return []
    if not api_key:
        return [triage_message(m, model, api_key) for m in messages]

    to_process = [m for m in messages if _cache_key(m) not in _CACHE]
    chunks = [to_process[i:i + batch_size] for i in range(0, len(to_process), batch_size)]

    def _process_chunk(chunk: list[dict]) -> None:
        try:
            results = _triage_batch_with_retry(chunk, model, api_key)
        except Exception as exc:  # noqa: BLE001 — ganzer Batch fällt zurück auf Keyword-Fallback
            sys.stderr.write(f"[triage] Batch-Call fehlgeschlagen ({len(chunk)} Mails), nutze Fallback: {exc}\n")
            for m in chunk:
                _CACHE[_cache_key(m)] = _keyword_fallback(
                    m.get("subject", ""), m.get("body_preview", "")
                ).model_dump()
            return
        for m, result in zip(chunk, results):
            _CACHE[_cache_key(m)] = result

    if chunks:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(chunks))) as pool:
            list(pool.map(_process_chunk, chunks))

    return [_build_result(m, _CACHE[_cache_key(m)]) for m in messages]

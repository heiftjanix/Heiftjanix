"""Mail-Triage: klassifiziert eine Mail (relevant/info, Priorität) und formuliert
bei Bedarf einen deutschen Antwortvorschlag — per Anthropic-API, geführt von
config/relevance_guidance.md.

Ohne ANTHROPIC_API_KEY (oder im DEMO_MODE) greift ein deterministischer
Keyword-Fallback, damit die App auch ohne API-Key lauffähig bleibt.

Ergebnisse werden je `internet_message_id` zwischengespeichert, damit unverändert
gebliebene Mails bei jedem Refresh nicht erneut (kostenpflichtig) klassifiziert werden.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import io_utils as io  # noqa: E402

MODEL = "claude-opus-4-8"
_CACHE: dict[str, dict] = {}

STANDARD_ANGEBOT_DRAFT = """Sehr geehrte Damen und Herren,

vielen Dank für Ihre Anfrage. Wir haben Ihre Angebotsanfrage erhalten und melden
uns innerhalb eines Tages bei Ihnen.

Mit freundlichen Grüßen
Max Mustermann
Musterfirma GmbH"""

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


def _relevance_guidance() -> str:
    return (io.ROOT / "config" / "relevance_guidance.md").read_text(encoding="utf-8")


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


def _anthropic_client():
    import anthropic
    return anthropic.Anthropic()


def triage_message(msg: dict) -> dict:
    """msg: {mailbox, sender_name, sender, subject, body_preview, internet_message_id}."""
    key = msg.get("internet_message_id") or f"{msg.get('mailbox')}|{msg.get('subject')}"
    if key in _CACHE:
        result = _CACHE[key]
    else:
        use_llm = bool(os.environ.get("ANTHROPIC_API_KEY")) and not os.environ.get("DEMO_MODE")
        if use_llm:
            try:
                client = _anthropic_client()
                resp = client.messages.parse(
                    model=MODEL,
                    max_tokens=1024,
                    system=[{
                        "type": "text",
                        "text": _relevance_guidance(),
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


def triage_all(messages: list[dict]) -> list[dict]:
    return [triage_message(m) for m in messages]

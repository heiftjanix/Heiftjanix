"""Microsoft Graph: Mails aus dem eigenen + den geteilten Postfächern holen.

Port von webapp/graph.py (Hauptrepo) — identische Logik. Nur lesend
(Mail.Read, Mail.Read.Shared); es wird nichts gesendet oder verändert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
SELECT = "id,subject,from,receivedDateTime,bodyPreview,internetMessageId"


def _messages_url(mailbox: str | None) -> str:
    if mailbox:
        return f"{GRAPH}/users/{mailbox}/messages"
    return f"{GRAPH}/me/messages"


def fetch_mailbox(token: str, mailbox: str | None, display_name: str,
                   window_hours: int, top: int = 50) -> list[dict]:
    """Holt neue Mails eines Postfachs; `mailbox=None` = eigenes Postfach (/me)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params = {
        "$select": SELECT,
        "$orderby": "receivedDateTime desc",
        "$top": str(top),
        "$filter": f"receivedDateTime ge {since}",
    }
    resp = requests.get(
        _messages_url(mailbox),
        headers={"Authorization": f"Bearer {token}", "Prefer": 'outlook.body-content-type="text"'},
        params=params,
        timeout=20,
    )
    resp.raise_for_status()
    out = []
    for msg in resp.json().get("value", []):
        sender = (msg.get("from") or {}).get("emailAddress", {})
        out.append({
            "mailbox": display_name,
            "sender_name": sender.get("name") or sender.get("address") or "",
            "sender": sender.get("address") or "",
            "subject": msg.get("subject") or "",
            "body_preview": msg.get("bodyPreview") or "",
            "internet_message_id": msg.get("internetMessageId") or msg.get("id"),
        })
    return out


def fetch_all_mailboxes(token: str, own_email: str, extra_mailboxes: list[str],
                         window_hours: int) -> list[dict]:
    """Eigenes Postfach + alle konfigurierten geteilten Postfächer."""
    items = fetch_mailbox(token, None, own_email, window_hours)
    for mb in extra_mailboxes:
        try:
            items.extend(fetch_mailbox(token, mb, mb, window_hours))
        except requests.HTTPError as exc:
            import sys
            sys.stderr.write(f"[graph] Postfach {mb} nicht lesbar: {exc}\n")
    return items

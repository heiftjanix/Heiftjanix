"""Microsoft Graph: Mails aus dem eigenen + den geteilten Postfächern holen.

Port von webapp/graph.py (Hauptrepo) — identische Logik. Nur lesend
(Mail.Read, Mail.Read.Shared); es wird nichts gesendet oder verändert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
SELECT = "id,subject,from,receivedDateTime,bodyPreview,internetMessageId,isRead"
# PidTagLastVerbExecuted (0x1081): 102=Reply, 103=ReplyAll, 104=Forward
REPLY_PROP = "Integer 0x1081"


def _messages_url(mailbox: str | None) -> str:
    # /messages ohne Ordner-Filter liefert laut Graph-API-Doku Mails aus dem
    # GESAMTEN Postfach (u. a. auch Gesendete Elemente) — daher explizit auf
    # den Posteingang beschränken.
    if mailbox:
        return f"{GRAPH}/users/{mailbox}/mailFolders/inbox/messages"
    return f"{GRAPH}/me/mailFolders/inbox/messages"


def _is_replied(msg: dict) -> bool:
    """Prüft anhand der Extended Property ob die Mail beantwortet/weitergeleitet wurde."""
    for prop in msg.get("singleValueExtendedProperties") or []:
        if prop.get("id") == REPLY_PROP:
            try:
                verb = int(prop["value"])
                return verb in (102, 103)  # Reply / ReplyAll
            except (ValueError, KeyError):
                pass
    return False


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
        # Nur UNGELESENE Mails — gelesene gelten als erledigt und sollen weder
        # triagiert noch angezeigt werden. receivedDateTime muss laut Graph-API
        # als $orderby-Property an erster Stelle im $filter stehen.
        "$filter": f"receivedDateTime ge {since} and isRead eq false",
        "$expand": f"singleValueExtendedProperties($filter=id eq '{REPLY_PROP}')",
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
            "mailbox_email": mailbox,
            "sender_name": sender.get("name") or sender.get("address") or "",
            "sender": sender.get("address") or "",
            "subject": msg.get("subject") or "",
            "body_preview": msg.get("bodyPreview") or "",
            "internet_message_id": msg.get("internetMessageId") or msg.get("id"),
            "graph_id": msg.get("id"),
            "received_at": msg.get("receivedDateTime") or "",
            "is_read": bool(msg.get("isRead")),
            "is_replied": _is_replied(msg),
        })
    return out


def fetch_all_mailboxes(token: str, own_email: str, extra_mailboxes: list[str],
                         window_hours: int) -> list[dict]:
    """Eigenes Postfach + alle konfigurierten geteilten Postfächer."""
    items = fetch_mailbox(token, None, own_email, window_hours)
    own = (own_email or "").strip().lower()
    for mb in extra_mailboxes:
        # Steht das eigene Postfach auch in der Liste der geteilten, käme jede Mail
        # daraus zweimal: einmal über /me, einmal über /users/<adresse>.
        if (mb or "").strip().lower() == own:
            continue
        try:
            items.extend(fetch_mailbox(token, mb, mb, window_hours))
        except requests.HTTPError as exc:
            import sys
            sys.stderr.write(f"[graph] Postfach {mb} nicht lesbar: {exc}\n")
    return items

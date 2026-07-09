"""Microsoft-Login (MSAL Auth-Code-Flow) für die Team-Webapp.

Ohne Azure-App-Registrierung läuft die App im DEMO_MODE (Umgebungsvariable
DEMO_MODE=1): Login setzt direkt eine Demo-Session ohne Redirect zu Microsoft.

Token-Caches werden NIE im Cookie gespeichert (Cookie ist nur signiert, nicht
verschlüsselt) — nur eine zufällige Session-ID liegt im Cookie, der eigentliche
MSAL-Token-Cache liegt serverseitig in einem In-Memory-Dict (siehe SESSIONS).
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

import msal

SCOPES = ["User.Read", "Mail.Read", "Mail.Read.Shared"]
DEMO_USER_EMAIL = "m.mustermann@example.com"
DEMO_USER_NAME = "Max Mustermann (Demo)"


def is_demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").strip() in ("1", "true", "True")


def _base_url() -> str:
    return os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")


def _redirect_uri() -> str:
    return f"{_base_url()}/auth/callback"


@dataclass
class SessionData:
    """Serverseitiger Session-Zustand, per Zufalls-ID an das Cookie gekoppelt."""

    email: str
    display_name: str
    cache: msal.SerializableTokenCache = field(default_factory=msal.SerializableTokenCache)
    oauth_state: str | None = None


SESSIONS: dict[str, SessionData] = {}


def _msal_app(cache: msal.SerializableTokenCache | None = None) -> msal.ConfidentialClientApplication:
    tenant = os.environ["AZURE_TENANT_ID"]
    return msal.ConfidentialClientApplication(
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_credential=os.environ["AZURE_CLIENT_SECRET"],
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache,
    )


def new_session(email: str, display_name: str) -> str:
    sid = secrets.token_urlsafe(24)
    SESSIONS[sid] = SessionData(email=email, display_name=display_name)
    return sid


def get_session(sid: str | None) -> SessionData | None:
    if not sid:
        return None
    return SESSIONS.get(sid)


def end_session(sid: str | None) -> None:
    if sid:
        SESSIONS.pop(sid, None)


def start_login() -> tuple[str, str]:
    """Erzeugt Login-Redirect-URL + oauth_state (im Session-Cookie zwischenspeichern)."""
    oauth_state = secrets.token_urlsafe(16)
    app = _msal_app()
    url = app.get_authorization_request_url(
        SCOPES, state=oauth_state, redirect_uri=_redirect_uri()
    )
    return url, oauth_state


def complete_login(code: str) -> tuple[str, str, msal.SerializableTokenCache]:
    """Tauscht den Auth-Code gegen Tokens, holt das Profil, gibt (email, name, cache) zurück."""
    import requests

    cache = msal.SerializableTokenCache()
    app = _msal_app(cache)
    result = app.acquire_token_by_authorization_code(
        code, scopes=SCOPES, redirect_uri=_redirect_uri()
    )
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Microsoft-Login fehlgeschlagen"))
    resp = requests.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {result['access_token']}"},
        timeout=15,
    )
    resp.raise_for_status()
    profile = resp.json()
    email = (profile.get("mail") or profile.get("userPrincipalName") or "").lower()
    name = profile.get("displayName") or email
    return email, name, cache


def get_access_token(session: SessionData) -> str | None:
    """Silent Token-Refresh über den gespeicherten Cache (kein erneuter Login nötig)."""
    app = _msal_app(session.cache)
    accounts = app.get_accounts()
    if not accounts:
        return None
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if result and "access_token" in result:
        return result["access_token"]
    return None

"""Microsoft-Login-Baustein (MSAL Auth-Code-Flow) für „Postfach verbinden".

Anders als webapp/auth.py (Hauptrepo) gibt es hier keine eigene Session-Verwaltung:
Die Identität kommt aus der ERPNext-Anmeldung (frappe.session.user); dieses Modul
kapselt nur die MSAL-Mechanik, api.py verdrahtet es mit frappe.cache()/DocType.
"""
from __future__ import annotations

import msal
import requests

SCOPES = ["User.Read", "Mail.Read", "Mail.Read.Shared"]


def _msal_app(client_id: str, client_secret: str, tenant_id: str,
               cache: "msal.SerializableTokenCache | None" = None) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        token_cache=cache,
    )


def get_login_url(client_id: str, client_secret: str, tenant_id: str,
                   redirect_uri: str, state: str) -> str:
    app = _msal_app(client_id, client_secret, tenant_id)
    return app.get_authorization_request_url(SCOPES, state=state, redirect_uri=redirect_uri)


def exchange_code(client_id: str, client_secret: str, tenant_id: str,
                   redirect_uri: str, code: str) -> tuple[str, str, str]:
    """Tauscht den Auth-Code gegen Tokens; gibt (email, display_name, serialized_cache) zurück."""
    cache = msal.SerializableTokenCache()
    app = _msal_app(client_id, client_secret, tenant_id, cache)
    result = app.acquire_token_by_authorization_code(
        code, scopes=SCOPES, redirect_uri=redirect_uri
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
    return email, name, cache.serialize()


def get_access_token(client_id: str, client_secret: str, tenant_id: str,
                      serialized_cache: str) -> tuple[str | None, str]:
    """Silent Token-Refresh über den gespeicherten Cache (kein erneuter Login nötig).

    Gibt immer (access_token_or_None, serialized_cache) zurück — der Cache kann sich
    durch den Refresh geändert haben und muss vom Aufrufer zurückgeschrieben werden.
    """
    cache = msal.SerializableTokenCache()
    cache.deserialize(serialized_cache)
    app = _msal_app(client_id, client_secret, tenant_id, cache)
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"], cache.serialize()
    return None, cache.serialize()

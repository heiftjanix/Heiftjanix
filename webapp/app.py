"""FastAPI-Team-Webapp: Team-Board (der/die/das Sekretär/-in) mit echtem Microsoft-Login.

Jeder angemeldete Nutzer sieht sein eigenes Postfach + die geteilten Postfächer
aus config/config.json. Der „Live aktualisieren"-Button stößt einen echten
Refresh an (Graph + ERPNext + Claude-Triage); während er läuft, pulsiert das
PCB-Logo bei ALLEN angemeldeten Nutzern (globaler Status, kein Polling pro Nutzer
nötig, aber hier per einfachem Intervall umgesetzt).

Harte Regel bleibt: nur Vorschläge, kein automatischer Mail-Versand/Rechnungslauf.

Start (Demo, ohne Zugangsdaten):
    DEMO_MODE=1 uvicorn webapp.app:app --reload
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib import io_utils as io  # noqa: E402
import render_dashboard as rd   # noqa: E402

from . import auth, service  # noqa: E402

app = FastAPI(title="Team-Board")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SESSION_SECRET", "dev-insecure-secret-change-me"),
    same_site="lax",
)


def _current_session(request: Request) -> auth.SessionData | None:
    sid = request.session.get("sid")
    return auth.get_session(sid)


def _allowed_mailboxes(email: str, config: dict) -> set[str]:
    return {email} | set(config.get("email", {}).get("extra_mailboxes", []))


@app.get("/healthz")
def healthz():
    return {"ok": True, "demo_mode": auth.is_demo_mode()}


@app.get("/login")
def login(request: Request):
    if auth.is_demo_mode():
        sid = auth.new_session(auth.DEMO_USER_EMAIL, auth.DEMO_USER_NAME)
        request.session["sid"] = sid
        return RedirectResponse("/")
    url, oauth_state = auth.start_login()
    request.session["oauth_state"] = oauth_state
    return RedirectResponse(url)


@app.get("/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None,
                   error_description: str | None = None):
    if error_description:
        return HTMLResponse(f"<p>Anmeldung fehlgeschlagen: {error_description}</p>", status_code=400)
    if not code or state != request.session.get("oauth_state"):
        return HTMLResponse("<p>Ungültige Anmeldeanfrage (state mismatch). Bitte erneut versuchen: "
                             "<a href='/login'>Login</a></p>", status_code=400)
    try:
        email, name, cache = auth.complete_login(code)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(f"<p>Anmeldung fehlgeschlagen: {exc}</p>", status_code=400)
    sid = auth.new_session(email, name)
    auth.SESSIONS[sid].cache = cache
    request.session["sid"] = sid
    request.session.pop("oauth_state", None)
    return RedirectResponse("/")


@app.get("/logout")
def logout(request: Request):
    auth.end_session(request.session.get("sid"))
    request.session.clear()
    return RedirectResponse("/login")


@app.get("/", response_class=HTMLResponse)
def board(request: Request):
    session = _current_session(request)
    if session is None:
        return RedirectResponse("/login")

    config = io.load_config()
    metrics = service.get_last_metrics()
    if metrics is None:
        service.start_refresh(started_by=session.display_name, session=session)
        return HTMLResponse(_loading_page())

    allowed = _allowed_mailboxes(session.email, config)
    view = service.view_for_mailboxes(metrics, allowed)
    view["auto_refresh_minutes"] = 0  # Webapp nutzt Status-Polling, kein Reload-Timer

    html = rd.render(view, mode="webapp", user=session.display_name)
    return HTMLResponse(html)


@app.post("/api/refresh")
def api_refresh(request: Request):
    session = _current_session(request)
    if session is None:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    accepted = service.start_refresh(started_by=session.display_name, session=session)
    return {"accepted": accepted, **service.status()}


@app.get("/api/status")
def api_status(request: Request):
    if _current_session(request) is None:
        return JSONResponse({"error": "not authenticated"}, status_code=401)
    return service.status()


def _loading_page() -> str:
    return """<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<body style="font-family:system-ui;text-align:center;padding:80px">
<h2>Erster Datenabruf läuft …</h2>
<p>Outlook &amp; ERPNext werden ausgewertet — die Seite lädt sich automatisch neu.</p>
</body>"""

"""
Google Calendar integration service.

Requires env vars:
  GOOGLE_CLIENT_ID
  GOOGLE_CLIENT_SECRET
  GOOGLE_REDIRECT_URI   (default: http://localhost:8000/google-cal/callback)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
import httplib2
from google_auth_httplib2 import AuthorizedHttp
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import get_settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_CALENDAR_ID = "primary"

# Allow http://localhost callbacks in dev. In production the redirect URI is
# already https so this env var is effectively ignored.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")


def _settings():
    return get_settings()


# ── Auth flow ──────────────────────────────────────────────────────────────────

def get_auth_url(username: str) -> str:
    s = _settings()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_redirect_uri],
            }
        },
        scopes=SCOPES,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = s.google_redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=username,
    )
    return url


def exchange_code(code: str) -> tuple[str, str, str]:
    """Exchange auth code for tokens. Returns (access_token, refresh_token, expiry_iso)."""
    s = _settings()
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [s.google_redirect_uri],
            }
        },
        scopes=SCOPES,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = s.google_redirect_uri
    flow.fetch_token(code=code, timeout=15)
    creds = flow.credentials
    expiry_iso = creds.expiry.isoformat() if creds.expiry else ""
    return creds.token, creds.refresh_token or "", expiry_iso


# ── Credentials helper ─────────────────────────────────────────────────────────

def _build_creds(row: Any) -> Credentials:
    s = _settings()
    creds = Credentials(
        token=row["access_token"],
        refresh_token=row["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=SCOPES,
    )
    if row["expiry_at"]:
        try:
            expiry = datetime.fromisoformat(str(row["expiry_at"]))
            if expiry.tzinfo is not None:
                expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
            creds.expiry = expiry
        except Exception:
            pass
    return creds


class CalendarSyncError(Exception):
    """Safe, actionable message; never expose provider tokens or response bodies."""


def safe_error(exc):
    if isinstance(exc, CalendarSyncError):
        return str(exc)
    if isinstance(exc, RefreshError) or (isinstance(exc, HttpError) and exc.resp.status == 401):
        return 'Google rechazó la autorización. Vuelve a conectar Google Calendar en Configuración.'
    if isinstance(exc, HttpError) and exc.resp.status == 403:
        return 'Google denegó el acceso al calendario. Revisa los permisos y la API de Calendar.'
    return 'No se pudo contactar con Google Calendar. El cambio queda pendiente de reintento.'


def _refresh_if_needed(creds: Credentials) -> Credentials:
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    return creds


def _service(creds: Credentials):
    return build('calendar', 'v3', http=AuthorizedHttp(creds, http=httplib2.Http(timeout=15)), cache_discovery=False)


def _connected_service(row, repo=None):
    try:
        creds = _refresh_if_needed(_build_creds(row))
        if repo:
            repo.save_google_tokens(row['username'], creds.token, creds.refresh_token or '',
                                    creds.expiry.isoformat() if creds.expiry else '')
        return _service(creds)
    except Exception as exc:
        raise CalendarSyncError(safe_error(exc)) from None


def _session_to_event(session_row: Any) -> dict:
    session_row = dict(session_row)
    date_str = str(session_row["session_date"])
    last_date = session_row.get("end_date") or date_str
    start_time = (session_row["start_time"] or "").strip() if "start_time" in session_row.keys() else ""
    end_time = (session_row["end_time"] or "").strip() if "end_time" in session_row.keys() else ""
    try:
        end_date = (datetime.fromisoformat(last_date).date() + timedelta(days=1)).isoformat()
    except ValueError:
        end_date = date_str
    client = session_row["client_name"] or "Cliente"
    consult = session_row["consult_type"] or "Sesión"
    status = session_row["status"] or ""
    notes = session_row["notes"] or ""

    summary = f"{consult} — {client}"
    description = notes

    s = get_settings()
    event = {
        "summary": summary,
        "description": description,
        "extendedProperties": {"private": {"aglegalConsult": consult, "aglegalSummary": summary, "aglegalStatus": status}},
        "source": {
            "title": "AGLegal",
            "url": f"{s.frontend_url}/sessions",
        },
    }
    if start_time and end_time:
        event["start"] = {"dateTime": f"{date_str}T{start_time[:5]}:00", "timeZone": s.timezone}
        event["end"] = {"dateTime": f"{last_date}T{end_time[:5]}:00", "timeZone": s.timezone}
    else:
        event["start"] = {"date": date_str}
        event["end"] = {"date": end_date}
    return event


def create_event(token_row, session_row, *, repo=None, event_id=None):
    svc = _connected_service(token_row, repo)
    body = _session_to_event(session_row)
    if event_id:
        body['id'] = event_id
    try:
        event = svc.events().insert(calendarId=_CALENDAR_ID, body=body, sendUpdates='none').execute()
        return event['id']
    except HttpError as exc:
        if exc.resp.status == 409 and event_id:
            # The previous request may have succeeded before a connection failed.
            svc.events().patch(calendarId=_CALENDAR_ID,eventId=event_id,
                               body=_session_to_event(session_row),sendUpdates='none').execute()
            return event_id
        raise


def update_event(token_row, event_id, session_row, *, repo=None):
    _connected_service(token_row, repo).events().patch(
        calendarId=_CALENDAR_ID,eventId=event_id,body=_session_to_event(session_row),sendUpdates='none').execute()


def delete_event(token_row, event_id, *, repo=None):
    try:
        _connected_service(token_row, repo).events().delete(
            calendarId=_CALENDAR_ID,eventId=event_id,sendUpdates='none').execute()
    except HttpError as exc:
        if exc.resp.status not in (404,410):
            raise


def list_events(token_row, time_min, time_max, *, repo=None):
    svc = _connected_service(token_row, repo)
    events, page = [], None
    while True:
        response = svc.events().list(calendarId=_CALENDAR_ID,
            timeMin=time_min.astimezone(timezone.utc).isoformat(),
            timeMax=time_max.astimezone(timezone.utc).isoformat(),singleEvents=True,
            showDeleted=True,maxResults=2500,pageToken=page).execute()
        events.extend(response.get('items', []))
        page = response.get('nextPageToken')
        if not page:
            return events

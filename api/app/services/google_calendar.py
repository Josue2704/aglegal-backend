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
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..config import get_settings

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_CALENDAR_ID = "primary"
_TIMEZONE = "America/El_Salvador"

# Local development uses http://localhost callbacks. OAuthlib can reject that
# during the token exchange unless this flag is enabled.
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
    flow.fetch_token(code=code)
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


def _refresh_if_needed(creds: Credentials) -> Credentials:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


# ── Calendar CRUD ──────────────────────────────────────────────────────────────

def _service(creds: Credentials):
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _session_to_event(session_row: Any) -> dict:
    date_str = str(session_row["session_date"])
    start_time = (session_row["start_time"] or "").strip() if "start_time" in session_row.keys() else ""
    end_time = (session_row["end_time"] or "").strip() if "end_time" in session_row.keys() else ""
    try:
        end_date = (datetime.fromisoformat(date_str).date() + timedelta(days=1)).isoformat()
    except ValueError:
        end_date = date_str
    client = session_row["client_name"] or "Cliente"
    consult = session_row["consult_type"] or "Sesión"
    status = session_row["status"] or ""
    notes = session_row["notes"] or ""

    summary = f"{consult} — {client}"
    description = f"Estado: {status}"
    if notes:
        description += f"\n{notes}"

    event = {
        "summary": summary,
        "description": description,
        "source": {
            "title": "AGLegal",
            "url": "http://localhost:5173/sessions",
        },
    }
    if start_time and end_time:
        event["start"] = {"dateTime": f"{date_str}T{start_time}:00", "timeZone": _TIMEZONE}
        event["end"] = {"dateTime": f"{date_str}T{end_time}:00", "timeZone": _TIMEZONE}
    else:
        event["start"] = {"date": date_str}
        event["end"] = {"date": end_date}
    return event


def create_event(token_row: Any, session_row: Any) -> str | None:
    """Create a GCal event. Returns event_id or None on failure."""
    try:
        creds = _refresh_if_needed(_build_creds(token_row))
        svc = _service(creds)
        event = svc.events().insert(
            calendarId=_CALENDAR_ID,
            body=_session_to_event(session_row),
        ).execute()
        return event.get("id")
    except HttpError as e:
        log.warning("GCal create_event failed: %s", e)
        return None
    except Exception as e:
        log.warning("GCal create_event unexpected error: %s", e)
        return None


def update_event(token_row: Any, event_id: str, session_row: Any) -> None:
    try:
        creds = _refresh_if_needed(_build_creds(token_row))
        svc = _service(creds)
        svc.events().update(
            calendarId=_CALENDAR_ID,
            eventId=event_id,
            body=_session_to_event(session_row),
        ).execute()
    except HttpError as e:
        log.warning("GCal update_event failed: %s", e)
    except Exception as e:
        log.warning("GCal update_event unexpected error: %s", e)


def delete_event(token_row: Any, event_id: str) -> None:
    try:
        creds = _refresh_if_needed(_build_creds(token_row))
        svc = _service(creds)
        svc.events().delete(calendarId=_CALENDAR_ID, eventId=event_id).execute()
    except HttpError as e:
        log.warning("GCal delete_event failed: %s", e)
    except Exception as e:
        log.warning("GCal delete_event unexpected error: %s", e)


def list_events(token_row: Any, time_min: datetime, time_max: datetime) -> list[dict]:
    try:
        creds = _refresh_if_needed(_build_creds(token_row))
        svc = _service(creds)
        response = svc.events().list(
            calendarId=_CALENDAR_ID,
            timeMin=time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            timeMax=time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        return list(response.get("items", []))
    except HttpError as e:
        log.warning("GCal list_events failed: %s", e)
        return []
    except Exception as e:
        log.warning("GCal list_events unexpected error: %s", e)
        return []

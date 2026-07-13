"""
Microsoft Outlook Calendar integration via Microsoft Graph API.

Requires env vars:
  OUTLOOK_CLIENT_ID
  OUTLOOK_CLIENT_SECRET
  OUTLOOK_REDIRECT_URI
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import requests

from ..config import get_settings

log = logging.getLogger(__name__)

_AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
_GRAPH = "https://graph.microsoft.com/v1.0"
_SCOPES = "Calendars.ReadWrite offline_access"


# ── Auth flow ──────────────────────────────────────────────────────────────────

def get_auth_url(username: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.outlook_client_id,
        "response_type": "code",
        "redirect_uri": s.outlook_redirect_uri,
        "scope": _SCOPES,
        "response_mode": "query",
        "state": username,
        "prompt": "select_account",
    }
    return f"{_AUTHORITY}/authorize?{urlencode(params)}"


def exchange_code(code: str) -> tuple[str, str, str]:
    """Exchange auth code → (access_token, refresh_token, expiry_iso)."""
    s = get_settings()
    resp = requests.post(
        f"{_AUTHORITY}/token",
        data={
            "client_id": s.outlook_client_id,
            "client_secret": s.outlook_client_secret,
            "code": code,
            "redirect_uri": s.outlook_redirect_uri,
            "grant_type": "authorization_code",
            "scope": _SCOPES,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data["access_token"]
    refresh_token = data.get("refresh_token", "")
    expires_in = int(data.get("expires_in", 3600))
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
    return access_token, refresh_token, expiry


def _refresh_token(token_row: Any) -> str:
    """Return a valid access token, refreshing if expired."""
    s = get_settings()
    expiry_str = str(token_row["expiry_at"] or "")
    if expiry_str:
        try:
            expiry = datetime.fromisoformat(expiry_str)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < expiry - timedelta(minutes=5):
                return str(token_row["access_token"])
        except Exception:
            pass

    resp = requests.post(
        f"{_AUTHORITY}/token",
        data={
            "client_id": s.outlook_client_id,
            "client_secret": s.outlook_client_secret,
            "refresh_token": token_row["refresh_token"],
            "grant_type": "refresh_token",
            "scope": _SCOPES,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data["access_token"])


def _headers(token_row: Any) -> dict:
    return {"Authorization": f"Bearer {_refresh_token(token_row)}", "Content-Type": "application/json"}


# ── Event helpers ──────────────────────────────────────────────────────────────

def _session_to_event(session_row: Any) -> dict:
    s = get_settings()
    date_str = str(session_row["session_date"])
    start_time = (session_row.get("start_time") or "").strip()
    end_time = (session_row.get("end_time") or "").strip()
    client = session_row.get("client_name") or "Cliente"
    consult = session_row.get("consult_type") or "Sesión"
    status = session_row.get("status") or ""
    notes = session_row.get("notes") or ""

    summary = f"{consult} — {client}"
    body_text = f"Estado: {status}"
    if notes:
        body_text += f"\n{notes}"

    event: dict = {
        "subject": summary,
        "body": {"contentType": "text", "content": body_text},
        "isReminderOn": True,
    }

    if start_time and end_time:
        event["start"] = {"dateTime": f"{date_str}T{start_time}:00", "timeZone": s.timezone}
        event["end"] = {"dateTime": f"{date_str}T{end_time}:00", "timeZone": s.timezone}
    else:
        event["isAllDay"] = True
        event["start"] = {"dateTime": f"{date_str}T00:00:00", "timeZone": s.timezone}
        event["end"] = {"dateTime": f"{date_str}T00:00:00", "timeZone": s.timezone}

    return event


# ── Calendar CRUD ──────────────────────────────────────────────────────────────

def create_event(token_row: Any, session_row: Any) -> str | None:
    try:
        resp = requests.post(
            f"{_GRAPH}/me/events",
            headers=_headers(token_row),
            json=_session_to_event(session_row),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception as e:
        log.warning("Outlook create_event failed: %s", e)
        return None


def update_event(token_row: Any, event_id: str, session_row: Any) -> None:
    try:
        resp = requests.patch(
            f"{_GRAPH}/me/events/{event_id}",
            headers=_headers(token_row),
            json=_session_to_event(session_row),
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("Outlook update_event failed: %s", e)


def delete_event(token_row: Any, event_id: str) -> None:
    try:
        resp = requests.delete(
            f"{_GRAPH}/me/events/{event_id}",
            headers=_headers(token_row),
            timeout=15,
        )
        if resp.status_code not in (204, 404):
            resp.raise_for_status()
    except Exception as e:
        log.warning("Outlook delete_event failed: %s", e)

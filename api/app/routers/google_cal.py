from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from aglegal.db import now_iso

from ..config import get_settings
from ..deps import CurrentUser, RepoDep
from ..services import google_calendar as gcal

router = APIRouter(prefix="/google-cal", tags=["google-calendar"])


class StatusOut(BaseModel):
    connected: bool


class AuthUrlOut(BaseModel):
    url: str


class ImportOut(BaseModel):
    imported: int
    updated: int


@router.get("/status", response_model=StatusOut)
def gcal_status(current_user: CurrentUser, repo: RepoDep) -> StatusOut:
    row = repo.get_google_tokens(current_user["username"])
    return StatusOut(connected=row is not None)


@router.get("/authorize", response_model=AuthUrlOut)
def gcal_authorize(current_user: CurrentUser) -> AuthUrlOut:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise HTTPException(503, "Google Calendar no está configurado en el servidor. Añade GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET al .env")
    url = gcal.get_auth_url(current_user["username"])
    return AuthUrlOut(url=url)


@router.get("/callback")
def gcal_callback(code: str, state: str, repo: RepoDep):
    """
    OAuth2 callback from Google. `state` = username.
    Stores tokens, redirects to frontend settings page.
    """
    s = get_settings()
    try:
        access_token, refresh_token, expiry_at = gcal.exchange_code(code)
        repo.save_google_tokens(state, access_token, refresh_token, expiry_at)
        return RedirectResponse(f"{s.frontend_url}/settings?gcal=connected")
    except Exception as e:
        return RedirectResponse(f"{s.frontend_url}/settings?gcal=error&msg={str(e)[:100]}")


@router.delete("/disconnect", status_code=204)
def gcal_disconnect(current_user: CurrentUser, repo: RepoDep):
    repo.delete_google_tokens(current_user["username"])


def _parse_google_event(event: dict) -> dict | None:
    if event.get("status") == "cancelled":
        return None
    start = event.get("start", {})
    end = event.get("end", {})
    start_value = start.get("dateTime") or start.get("date")
    end_value = end.get("dateTime") or end.get("date")
    if not start_value:
        return None

    start_text = str(start_value)
    end_text = str(end_value or "")
    session_date = start_text[:10]
    start_time = start_text[11:16] if "dateTime" in start else None
    end_time = end_text[11:16] if "dateTime" in end and end_text else None
    title = (event.get("summary") or "Evento de Google").strip()
    description = (event.get("description") or "").strip()
    return {
        "event_id": str(event.get("id") or ""),
        "session_date": session_date,
        "start_time": start_time,
        "end_time": end_time,
        "consult_type": title,
        "notes": description,
    }


@router.post("/import", response_model=ImportOut)
def gcal_import(current_user: CurrentUser, repo: RepoDep) -> ImportOut:
    token_row = repo.get_google_tokens(current_user["username"])
    if not token_row:
        raise HTTPException(409, "Google Calendar no está conectado.")

    today = date.today()
    time_min = datetime.combine(today - timedelta(days=90), datetime.min.time(), tzinfo=timezone.utc)
    time_max = datetime.combine(today + timedelta(days=180), datetime.max.time(), tzinfo=timezone.utc)
    events = gcal.list_events(token_row, time_min, time_max)
    imported = 0
    updated = 0

    for event in events:
        parsed = _parse_google_event(event)
        if not parsed or not parsed["event_id"]:
            continue
        existing = repo.conn.execute(
            "SELECT id, status FROM sessions WHERE gcal_event_id=%s",
            (parsed["event_id"],),
        ).fetchone()
        if existing:
            repo.update_session(
                int(existing["id"]),
                case_id=None,
                session_date=parsed["session_date"],
                start_time=parsed["start_time"],
                end_time=parsed["end_time"],
                consult_type=parsed["consult_type"],
                notes=parsed["notes"],
                status=existing["status"] or "Pendiente",
            )
            updated += 1
        else:
            session_id = repo.create_session(
                client_id=None,
                case_id=None,
                session_date=parsed["session_date"],
                start_time=parsed["start_time"],
                end_time=parsed["end_time"],
                consult_type=parsed["consult_type"],
                notes=parsed["notes"],
                status="Pendiente",
                created_at=now_iso(),
            )
            repo.set_session_gcal_event_id(session_id, parsed["event_id"])
            imported += 1

    return ImportOut(imported=imported, updated=updated)

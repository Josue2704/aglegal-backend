from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..config import get_settings
from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.session import SessionIn, SessionOut
from ..services import google_calendar as gcal
from ..services import outlook_calendar as ocal
from ..services.email import send_session_email, send_session_cancel_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])
_executor = ThreadPoolExecutor(max_workers=2)


def _email_notify(session_row, repo: RepoDep, is_update: bool = False) -> None:
    """Send email confirmation to client if they have an email address."""
    try:
        s = get_settings()
        if not s.resend_api_key:
            return
        client_id = session_row.get("client_id")
        if not client_id:
            return
        client = repo.conn.execute(
            "SELECT name, email FROM clients WHERE id=%s", (int(client_id),)
        ).fetchone()
        if not client or not client["email"]:
            return
        send_session_email(
            session_row=session_row,
            client_email=str(client["email"]),
            client_name=str(client["name"]),
            firm_name=s.firm_name,
            resend_api_key=s.resend_api_key,
            resend_from=s.resend_from_email,
            is_update=is_update,
        )
    except Exception as e:
        log.warning("Email notify failed: %s", e)


def _sync_create(current_user: str, session_id: int, repo: RepoDep) -> None:
    """Push new session to Google Calendar and Outlook Calendar if connected."""
    try:
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        gcal_row = repo.get_google_tokens(current_user)
        if gcal_row:
            event_id = gcal.create_event(gcal_row, session_row)
            if event_id:
                repo.set_session_gcal_event_id(session_id, event_id)
        outlook_row = repo.get_outlook_tokens(current_user)
        if outlook_row:
            event_id = ocal.create_event(outlook_row, session_row)
            if event_id:
                repo.set_session_outlook_event_id(session_id, event_id)
    except Exception as e:
        log.warning("Calendar sync_create failed for session %s: %s", session_id, e)


def _sync_update(current_user: str, session_id: int, repo: RepoDep) -> None:
    try:
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        gcal_row = repo.get_google_tokens(current_user)
        if gcal_row and session_row["gcal_event_id"]:
            gcal.update_event(gcal_row, session_row["gcal_event_id"], session_row)
        outlook_row = repo.get_outlook_tokens(current_user)
        if outlook_row and session_row["outlook_event_id"]:
            ocal.update_event(outlook_row, session_row["outlook_event_id"], session_row)
    except Exception as e:
        log.warning("Calendar sync_update failed for session %s: %s", session_id, e)


def _sync_delete(current_user: str, session_id: int, repo: RepoDep) -> None:
    try:
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        gcal_row = repo.get_google_tokens(current_user)
        if gcal_row and session_row["gcal_event_id"]:
            gcal.delete_event(gcal_row, session_row["gcal_event_id"])
        outlook_row = repo.get_outlook_tokens(current_user)
        if outlook_row and session_row["outlook_event_id"]:
            ocal.delete_event(outlook_row, session_row["outlook_event_id"])
    except Exception as e:
        log.warning("Calendar sync_delete failed for session %s: %s", session_id, e)


@router.get("", response_model=list[SessionOut])
def list_sessions(
    current_user: CurrentUser,
    repo: RepoDep,
    client_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
) -> list[SessionOut]:
    return [SessionOut.from_row(row) for row in repo.list_sessions(
        client_id=client_id, start_date=start_date, end_date=end_date, status=status
    )]


@router.post("", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "crear")) -> SessionOut:
    session_id = repo.create_session(
        client_id=body.client_id,
        case_id=body.case_id,
        session_date=body.session_date,
        start_time=body.start_time,
        end_time=body.end_time,
        consult_type=body.consult_type,
        notes=body.notes,
        status=body.status,
        created_at=now_iso(),
    )
    _sync_create(current_user["username"], session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(500, "Error al recuperar la sesión creada")
    _executor.submit(_email_notify, dict(row), repo, False)
    return SessionOut.from_row(row)


@router.put("/{session_id}", response_model=SessionOut)
def update_session(session_id: int, body: SessionIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "editar")) -> SessionOut:
    repo.update_session(
        session_id,
        case_id=body.case_id,
        session_date=body.session_date,
        start_time=body.start_time,
        end_time=body.end_time,
        consult_type=body.consult_type,
        notes=body.notes,
        status=body.status,
    )
    _sync_update(current_user["username"], session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(404, "Sesión no encontrada")
    _executor.submit(_email_notify, dict(row), repo, True)
    return SessionOut.from_row(row)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "eliminar")):
    # Fetch session + client email BEFORE deleting so we can send cancel notification
    row = repo.get_session(session_id)
    if row:
        s = get_settings()
        if s.resend_api_key:
            client_id = row.get("client_id")
            if client_id:
                client = repo.conn.execute(
                    "SELECT name, email FROM clients WHERE id=%s", (int(client_id),)
                ).fetchone()
                if client and client["email"]:
                    _executor.submit(
                        send_session_cancel_email,
                        session_row=dict(row),
                        client_email=str(client["email"]),
                        client_name=str(client["name"]),
                        firm_name=s.firm_name,
                        resend_api_key=s.resend_api_key,
                        resend_from=s.resend_from_email,
                    )
    _sync_delete(current_user["username"], session_id, repo)
    repo.delete_session(session_id)

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep
from ..schemas.session import SessionIn, SessionOut
from ..services import google_calendar as gcal

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


def _sync_create(current_user: str, session_id: int, repo: RepoDep) -> None:
    """After creating a session, push it to Google Calendar if connected."""
    try:
        token_row = repo.get_google_tokens(current_user)
        if not token_row:
            return
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        event_id = gcal.create_event(token_row, session_row)
        if event_id:
            repo.set_session_gcal_event_id(session_id, event_id)
    except Exception as e:
        log.warning("GCal sync_create failed for session %s: %s", session_id, e)


def _sync_update(current_user: str, session_id: int, repo: RepoDep) -> None:
    try:
        token_row = repo.get_google_tokens(current_user)
        if not token_row:
            return
        session_row = repo.get_session(session_id)
        if not session_row or not session_row["gcal_event_id"]:
            return
        gcal.update_event(token_row, session_row["gcal_event_id"], session_row)
    except Exception as e:
        log.warning("GCal sync_update failed for session %s: %s", session_id, e)


def _sync_delete(current_user: str, session_id: int, repo: RepoDep) -> None:
    try:
        token_row = repo.get_google_tokens(current_user)
        if not token_row:
            return
        session_row = repo.get_session(session_id)
        if not session_row or not session_row["gcal_event_id"]:
            return
        gcal.delete_event(token_row, session_row["gcal_event_id"])
    except Exception as e:
        log.warning("GCal sync_delete failed for session %s: %s", session_id, e)


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
def create_session(body: SessionIn, current_user: CurrentUser, repo: RepoDep) -> SessionOut:
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
    _sync_create(current_user, session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(500, "Error al recuperar la sesión creada")
    return SessionOut.from_row(row)


@router.put("/{session_id}", response_model=SessionOut)
def update_session(session_id: int, body: SessionIn, current_user: CurrentUser, repo: RepoDep) -> SessionOut:
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
    _sync_update(current_user, session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(404, "Sesión no encontrada")
    return SessionOut.from_row(row)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: int, current_user: CurrentUser, repo: RepoDep):
    _sync_delete(current_user, session_id, repo)
    repo.delete_session(session_id)

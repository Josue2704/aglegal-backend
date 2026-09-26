from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..config import get_settings
from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.session import SessionIn, SessionOut
from ..services import google_calendar as gcal
from ..services import calendar_sync
from ..services import outlook_calendar as ocal
from ..services.email import send_session_email, send_session_cancel_email

log = logging.getLogger(__name__)
from ..access import require_any, check

router = APIRouter(prefix="/sessions", tags=["sessions"])
_executor = ThreadPoolExecutor(max_workers=2)


def _email_notify(session_row, repo: RepoDep, is_update: bool = False) -> None:
    """Send email confirmation to client if they have an email address.

    La consulta del cliente se hace aquí, en el hilo de la petición: la conexión de `repo`
    se cierra al terminar la respuesta, así que el hilo de fondo solo recibe valores planos
    (antes consultaba la base desde el hilo y fallaba con "connection already closed")."""
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
        _executor.submit(
            _send_session_email_safe,
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


def _send_session_email_safe(**kwargs) -> None:
    try:
        send_session_email(**kwargs)
    except Exception as e:
        log.warning("Email notify failed: %s", e)


def _sync_create(current_user: str, session_id: int, repo: RepoDep) -> None:
    """Push new session to Google Calendar and Outlook Calendar if connected."""
    try:
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        outlook_row = repo.get_outlook_tokens(current_user)
        if outlook_row:
            event_id = ocal.create_event(outlook_row, session_row)
            if event_id:
                repo.set_session_outlook_event_id(session_id, event_id)
                repo.conn.execute("UPDATE sessions SET outlook_owner=%s WHERE id=%s",(current_user,session_id))
                repo.conn.commit()
    except Exception as e:
        log.warning("Calendar sync_create failed for session %s: %s", session_id, e)


def _sync_update(current_user: str, session_id: int, repo: RepoDep) -> None:
    try:
        session_row = repo.get_session(session_id)
        if not session_row:
            return
        outlook_row = repo.get_outlook_tokens(session_row.get("outlook_owner") or "")
        if outlook_row and session_row["outlook_event_id"]:
            ocal.update_event(outlook_row, session_row["outlook_event_id"], session_row)
    except Exception as e:
        log.warning("Calendar sync_update failed for session %s: %s", session_id, e)


@router.get("", response_model=list[SessionOut], dependencies=[require_permission('agenda', 'ver')])
def list_sessions(
    current_user: CurrentUser,
    repo: RepoDep,
    client_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
) -> list[SessionOut]:
    results = []
    for row in repo.list_sessions(client_id=client_id,start_date=start_date,end_date=end_date,status=status):
        result = SessionOut.from_row(row)
        result.calendar_error = calendar_sync.session_error(repo,row['id'])
        results.append(result)
    return results


@router.post("", response_model=SessionOut, status_code=201, dependencies=[require_permission('agenda', 'crear')])
def create_session(body: SessionIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "crear")) -> SessionOut:
    with repo.conn.transaction():
        session_id = repo.create_session(
            client_id=body.client_id,
            case_id=body.case_id,
            session_date=body.session_date, end_date=body.end_date,
            start_time=body.start_time,
            end_time=body.end_time,
            consult_type=body.consult_type,
            notes=body.notes,
            status=body.status,
            monto_adicional_text=str(body.monto_adicional) if body.monto_adicional is not None else "0",
            username=current_user["username"],
            permitir_solape=body.permitir_solape,
            created_at=now_iso(),
        )
        calendar_sync.queue(repo,repo.get_session(session_id),"create",current_user["username"])
    calendar_sync.process(repo,session_id=session_id)
    _sync_create(current_user["username"], session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(500, "Error al recuperar la sesión creada")
    _email_notify(dict(row), repo, False)
    result = SessionOut.from_row(row)
    result.calendar_error = calendar_sync.session_error(repo,session_id)
    return result


@router.put("/{session_id}", response_model=SessionOut, dependencies=[require_permission('agenda', 'editar')])
def update_session(session_id: int, body: SessionIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "editar")) -> SessionOut:
    with repo.conn.transaction():
        repo.update_session(
            session_id,
            client_id=body.client_id, update_client=True, permitir_solape=body.permitir_solape, username=current_user["username"],
            case_id=body.case_id,
            session_date=body.session_date, end_date=body.end_date,
            start_time=body.start_time,
            end_time=body.end_time,
            consult_type=body.consult_type,
            notes=body.notes,
            status=body.status,
        )
        calendar_sync.queue(repo,repo.get_session(session_id),"update",current_user["username"])
    calendar_sync.process(repo,session_id=session_id)
    _sync_update(current_user["username"], session_id, repo)
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(404, "Sesión no encontrada")
    _email_notify(dict(row), repo, True)
    result = SessionOut.from_row(row)
    result.calendar_error = calendar_sync.session_error(repo,session_id)
    return result


@router.delete("/{session_id}", status_code=204, dependencies=[require_permission('agenda', 'eliminar')])
def delete_session(session_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("agenda", "eliminar")):
    # Fetch session + client email BEFORE deleting so we can send cancel notification
    row = repo.get_session(session_id)
    if not row:
        raise HTTPException(404, 'Sesión no encontrada')
    with repo.conn.transaction():
        repo.delete_session(session_id, username=current_user['username'])
        calendar_sync.queue(repo,row,'delete',current_user['username'])
    calendar_sync.process(repo,session_id=session_id)
    owner = row.get('outlook_owner')
    if owner and row.get('outlook_event_id'):
        token = repo.get_outlook_tokens(owner)
        if token:
            ocal.delete_event(token,row['outlook_event_id'])
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

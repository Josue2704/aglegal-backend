from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from aglegal.db import now_iso
from ..config import get_settings
from ..deps import CurrentUser, RepoDep, require_permission
from ..services import google_calendar as gcal, calendar_oauth, calendar_sync

router = APIRouter(prefix='/google-cal', tags=['google-calendar'])

class StatusOut(BaseModel):
    connected: bool
    error: str = ''
    pending: int = 0

class AuthUrlOut(BaseModel):
    url: str

class ImportOut(BaseModel):
    imported: int = 0
    updated: int = 0
    cancelled: int = 0
    skipped: int = 0
    warnings: list[str] = []

@router.get('/status', response_model=StatusOut)
def gcal_status(current_user: CurrentUser, repo: RepoDep):
    return calendar_sync.summary(repo,current_user['username'])

@router.get('/authorize', response_model=AuthUrlOut, dependencies=[require_permission('agenda','ver')])
def gcal_authorize(current_user: CurrentUser, repo: RepoDep, response: Response):
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        raise HTTPException(503,'Google Calendar no está configurado en el servidor.')
    state = calendar_oauth.begin(repo,current_user['username'],'google',response)
    return AuthUrlOut(url=gcal.get_auth_url(state))

@router.get('/callback')
def gcal_callback(request: Request, repo: RepoDep, code: str = '', state: str = '', error: str = ''):
    username = calendar_oauth.consume(repo,'google',state,request.cookies.get('google_oauth'))
    query = {'gcal':'connected'}
    try:
        if error or not code:
            raise ValueError()
        access, refresh, expiry = gcal.exchange_code(code)
        repo.save_google_tokens(username,access,refresh,expiry)
    except Exception:
        query = {'gcal':'error','msg':'No se completó la autorización. Vuelve a conectar Google Calendar.'}
    response = RedirectResponse(get_settings().frontend_url+'/settings?'+urlencode(query))
    response.delete_cookie('google_oauth',path='/')
    return response

@router.delete('/disconnect', status_code=204)
def gcal_disconnect(current_user: CurrentUser, repo: RepoDep):
    repo.delete_google_tokens(current_user['username'])

@router.post('/verify', response_model=StatusOut, dependencies=[require_permission('agenda','ver')])
def gcal_verify(current_user: CurrentUser, repo: RepoDep):
    username = current_user['username']
    row = repo.get_google_tokens(username)
    if not row:
        raise HTTPException(409,'Google Calendar no está conectado.')
    try:
        gcal._connected_service(row,repo).events().list(calendarId='primary',maxResults=1).execute()
        error = ''
    except Exception as exc:
        error = gcal.safe_error(exc)
    repo.conn.execute('UPDATE google_tokens SET last_error=%s WHERE username=%s',(error,username))
    repo.conn.commit()
    return calendar_sync.summary(repo,username)

@router.post('/retry', dependencies=[require_permission('agenda','editar')])
def gcal_retry(current_user: CurrentUser, repo: RepoDep):
    return calendar_sync.process(repo,owner=current_user['username'])


def _parse_google_event(event):
    if event.get('status') == 'cancelled':
        return None
    start, end = event.get('start',{}), event.get('end',{})
    if not start:
        return None
    tz = ZoneInfo(get_settings().timezone)
    if start.get('dateTime'):
        first = datetime.fromisoformat(start['dateTime'].replace('Z','+00:00'))
        last = datetime.fromisoformat(end['dateTime'].replace('Z','+00:00'))
        first = first.replace(tzinfo=ZoneInfo(start.get('timeZone') or get_settings().timezone)) if first.tzinfo is None else first
        last = last.replace(tzinfo=ZoneInfo(end.get('timeZone') or get_settings().timezone)) if last.tzinfo is None else last
        first, last = first.astimezone(tz), last.astimezone(tz)
        session_date, end_date = first.date().isoformat(), last.date().isoformat()
        start_time, end_time = first.strftime('%H:%M'), last.strftime('%H:%M')
    else:
        session_date = date.fromisoformat(start['date']).isoformat()
        end_date = (date.fromisoformat(end['date'])-timedelta(days=1)).isoformat()
        start_time = end_time = None
    title = (event.get('summary') or 'Evento de Google').strip()
    meta = event.get('extendedProperties',{}).get('private',{})
    if meta.get('aglegalSummary') == title and meta.get('aglegalConsult'):
        title = meta['aglegalConsult']
    return dict(event_id=str(event.get('id') or ''),session_date=session_date,end_date=end_date,
        start_time=start_time,end_time=end_time,consult_type=title,
        notes=(event.get('description') or '').strip())

@router.post('/import', response_model=ImportOut, dependencies=[require_permission('agenda','crear'),require_permission('agenda','editar')])
def gcal_import(current_user: CurrentUser, repo: RepoDep):
    username = current_user['username']
    token = repo.get_google_tokens(username)
    if not token:
        raise HTTPException(409,'Google Calendar no está conectado.')
    today = datetime.now(ZoneInfo(get_settings().timezone)).date()
    try:
        events = gcal.list_events(token,
            datetime.combine(today-timedelta(days=90),datetime.min.time(),tzinfo=timezone.utc),
            datetime.combine(today+timedelta(days=180),datetime.max.time(),tzinfo=timezone.utc),repo=repo)
    except Exception as exc:
        error = gcal.safe_error(exc)
        repo.conn.execute('UPDATE google_tokens SET last_error=%s WHERE username=%s',(error,username))
        repo.conn.commit()
        raise HTTPException(502,error) from None
    result = ImportOut()
    for event in events:
        event_id = event.get('id')
        if not event_id:
            continue
        # One failed/unsupported event does not discard the rest of the import.
        try:
            with repo.conn.transaction():
                repo.conn.execute('SELECT pg_advisory_xact_lock(74185245)')
                existing = repo.conn.execute('SELECT * FROM sessions WHERE gcal_event_id=%s AND gcal_owner=%s',(event_id,username)).fetchone()
                pending = repo.conn.execute("SELECT 1 FROM calendar_sync_jobs WHERE provider='google' AND owner=%s AND event_id=%s AND status='Pendiente'",(username,event_id)).fetchone()
                if pending:
                    raise ValueError('Hay cambios locales pendientes; reintenta la sincronización antes de importar.')
                if event.get('status') == 'cancelled':
                    if existing:
                        if repo._factura_viva_de('sessions',existing['id']):
                            raise ValueError('Una cita facturada no puede cancelarse desde Google.')
                        repo.update_session(existing['id'],case_id=existing['case_id'],session_date=existing['session_date'],
                            end_date=existing['end_date'],start_time=existing['start_time'],end_time=existing['end_time'],
                            consult_type=existing['consult_type'],notes=existing['notes'] or '',status='Cancelada',
                            permitir_solape=True,username=username)
                        result.cancelled += 1
                    continue
                parsed = _parse_google_event(event)
                if not parsed:
                    continue
                # Preserve all-day spans and cross-midnight appointments without losing dates.
                kwargs = {k:v for k,v in parsed.items() if k not in ('event_id',)}
                if existing:
                    repo.update_session(existing['id'],case_id=existing['case_id'],
                        status='Pendiente' if existing['status']=='Cancelada' else existing['status'],
                        permitir_solape=True,username=username,**kwargs)
                    repo.conn.execute('UPDATE sessions SET gcal_event_id=%s WHERE id=%s',(event_id,existing['id']))
                    result.updated += 1
                else:
                    sid = repo.create_session(client_id=None,case_id=None,status='Pendiente',created_at=now_iso(),
                        permitir_solape=True,**kwargs)
                    repo.conn.execute('UPDATE sessions SET gcal_event_id=%s,gcal_owner=%s WHERE id=%s',(event_id,username,sid))
                    result.imported += 1
        except (ValueError,KeyError,TypeError):
            result.skipped += 1
    if result.skipped:
        result.warnings.append('Algunos eventos tienen cambios locales pendientes o fechas incompatibles o facturas que impiden la cancelación. No se sobrescribieron; reintenta después de revisar la sincronización.')
    return result

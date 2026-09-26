"""Durable Google changes committed with the local appointment, retried explicitly."""
import uuid
from psycopg2.extras import Json
from aglegal.db import now_iso
from . import google_calendar as gcal


def queue(repo, row, operation, actor):
    row = dict(row)
    previous = repo.conn.execute("SELECT * FROM calendar_sync_jobs WHERE session_id=%s AND provider='google'", (row['id'],)).fetchone()
    owner = row.get('gcal_owner') or (previous['owner'] if previous else None)
    if not owner and operation == 'create' and repo.get_google_tokens(actor):
        owner = actor
    if not owner:
        return
    event_id = row.get('gcal_event_id') or (previous['event_id'] if previous else None) or ('ag' + uuid.uuid4().hex)
    if previous and previous['status'] == 'Sincronizado' and not row.get('gcal_event_id') and operation != 'delete':
        event_id = 'ag' + uuid.uuid4().hex
    if row.get('status') == 'Cancelada':
        operation = 'delete'
    if operation != 'delete' and not row.get('gcal_event_id'):
        operation = 'create'
    repo.conn.execute("""INSERT INTO calendar_sync_jobs(session_id,provider,owner,event_id,operation,payload,updated_at)
        VALUES(%s,'google',%s,%s,%s,%s,%s) ON CONFLICT(session_id,provider) DO UPDATE SET
        owner=excluded.owner,event_id=excluded.event_id,operation=excluded.operation,payload=excluded.payload,
        status='Pendiente',error='',updated_at=excluded.updated_at""",
        (row['id'],owner,event_id,operation,Json(row),now_iso()))
    repo.conn.execute('UPDATE sessions SET gcal_owner=%s WHERE id=%s',(owner,row['id']))


def process(repo, *, session_id=None, owner=None):
    where, params = "provider='google' AND status='Pendiente'", []
    if session_id is not None:
        where += ' AND session_id=%s'
        params.append(session_id)
    if owner is not None:
        where += ' AND owner=%s'
        params.append(owner)
    ids = repo.conn.execute(f'SELECT id FROM calendar_sync_jobs WHERE {where} ORDER BY id LIMIT 50',tuple(params)).fetchall()
    completed = failed = 0
    for candidate in ids:
        # Serialize against appointment writes and concurrent retries; reread current payload.
        with repo.conn.transaction():
            repo.conn.execute('SELECT pg_advisory_xact_lock(74185245)')
            job = repo.conn.execute("SELECT * FROM calendar_sync_jobs WHERE id=%s AND status='Pendiente' FOR UPDATE",(candidate['id'],)).fetchone()
            if not job:
                continue
            try:
                token = repo.get_google_tokens(job['owner'])
                if not token:
                    raise gcal.CalendarSyncError('La cuenta propietaria debe volver a conectar Google Calendar.')
                if job['operation'] == 'delete':
                    gcal.delete_event(token,job['event_id'],repo=repo)
                    repo.conn.execute('UPDATE sessions SET gcal_event_id=NULL WHERE id=%s',(job['session_id'],))
                elif job['operation'] == 'create':
                    event_id = gcal.create_event(token,job['payload'],repo=repo,event_id=job['event_id'])
                    repo.conn.execute('UPDATE sessions SET gcal_event_id=%s WHERE id=%s',(event_id,job['session_id']))
                else:
                    gcal.update_event(token,job['event_id'],job['payload'],repo=repo)
                repo.conn.execute("UPDATE calendar_sync_jobs SET status='Sincronizado',error='',attempts=attempts+1,updated_at=%s WHERE id=%s",(now_iso(),job['id']))
                repo.conn.execute("UPDATE google_tokens SET last_error='' WHERE username=%s",(job['owner'],))
                completed += 1
            except Exception as exc:
                error = gcal.safe_error(exc)
                repo.conn.execute('UPDATE calendar_sync_jobs SET error=%s,attempts=attempts+1,updated_at=%s WHERE id=%s',(error,now_iso(),job['id']))
                repo.conn.execute('UPDATE google_tokens SET last_error=%s WHERE username=%s',(error,job['owner']))
                failed += 1
    return {'completed':completed,'failed':failed}


def summary(repo, username):
    row = repo.get_google_tokens(username)
    pending = repo.conn.execute("SELECT COUNT(*) AS n FROM calendar_sync_jobs WHERE provider='google' AND owner=%s AND status='Pendiente'",(username,)).fetchone()['n']
    return {'connected':row is not None,'error':row['last_error'] if row else '', 'pending':pending}


def session_error(repo, session_id):
    job = repo.conn.execute("SELECT error FROM calendar_sync_jobs WHERE session_id=%s AND provider='google' AND status='Pendiente'",(session_id,)).fetchone()
    return (job['error'] or 'Sincronización pendiente con Google Calendar.') if job else None

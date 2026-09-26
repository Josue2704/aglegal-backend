"""Short-lived, single-use OAuth challenges tied to the initiating browser."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from ..config import get_settings


def begin(repo, username, provider, response):
    state = secrets.token_urlsafe(32)
    digest = hashlib.sha256(state.encode()).hexdigest()
    repo.conn.execute('DELETE FROM calendar_oauth_states WHERE expires_at<now()')
    repo.conn.execute('''INSERT INTO calendar_oauth_states(digest,username,provider,expires_at)
        VALUES(%s,%s,%s,%s)''', (digest,username,provider,datetime.now(timezone.utc)+timedelta(minutes=10)))
    repo.conn.commit()
    response.set_cookie(f'{provider}_oauth',state,max_age=600,httponly=True,samesite='lax',
                        secure=get_settings().frontend_url.startswith('https://'),path='/')
    return state


def consume(repo, provider, state, cookie):
    if not state or not cookie or not secrets.compare_digest(state,cookie):
        raise HTTPException(400,'La autorización no corresponde a este navegador. Vuelve a conectar Calendar.')
    digest=hashlib.sha256(state.encode()).hexdigest()
    row=repo.conn.execute('''DELETE FROM calendar_oauth_states WHERE digest=%s AND provider=%s
        AND expires_at>now() RETURNING username''',(digest,provider)).fetchone()
    repo.conn.commit()
    if not row:
        raise HTTPException(400,'La autorización expiró o ya fue utilizada. Vuelve a conectar Calendar.')
    active=repo.conn.execute('SELECT 1 FROM users WHERE username=%s AND active=1',(row['username'],)).fetchone()
    if not active:
        raise HTTPException(403,'La cuenta del sistema está inactiva')
    return row['username']

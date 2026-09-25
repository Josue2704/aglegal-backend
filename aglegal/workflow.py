"""Operaciones de apertura y trazabilidad del trabajo."""
from functools import wraps
from .db import now_iso
from psycopg2.extras import Json


def workflow_atomic(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        with self.conn.transaction():
            self.conn.execute('SELECT pg_advisory_xact_lock(74185245)')
            return fn(self, *args, **kwargs)
    return run


def record_event(repo, entity_type, entity_id, event, actor='', details=None):
    repo.conn.execute('''INSERT INTO workflow_events(entity_type,entity_id,event,actor,details,created_at)
        VALUES(%s,%s,%s,%s,%s,%s)''',
        (entity_type,entity_id,event,str(actor or ''),Json(details or {}),now_iso()))

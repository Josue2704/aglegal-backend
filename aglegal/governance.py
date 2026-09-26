"""Approval queue with immutable snapshots and optimistic conflict detection."""
import json
from datetime import date, timedelta
from .db import now_iso
from .workflow import workflow_atomic, record_event


def snapshot(repo, entity, entity_id):
    if entity not in ('cuenta','forecast'):
        raise ValueError('Tipo de propuesta inválido')
    if not entity_id:
        return None
    table = 'plan_cuentas' if entity == 'cuenta' else 'forecast'
    row = repo.conn.execute(f'SELECT * FROM {table} WHERE id=%s',(entity_id,)).fetchone()
    if not row:
        raise ValueError('Registro no encontrado')
    return json.loads(json.dumps(dict(row),default=str))


@workflow_atomic
def propose(repo, *, entity, entity_id, action, payload, reason, actor):
    if not reason.strip():
        raise ValueError('Documenta el motivo de la propuesta')
    if action not in ('crear','editar','eliminar') or (action=='eliminar' and entity!='forecast'):
        raise ValueError('Acción inválida')
    before = snapshot(repo,entity,entity_id)
    if (action=='crear') != (entity_id is None):
        raise ValueError('Identificador inválido para la acción')
    row = repo.conn.execute("""INSERT INTO financial_requests(entity,entity_id,action,payload,before_value,reason,requester,created_at)
        VALUES(%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s) RETURNING *""",
        (entity,entity_id,action,json.dumps(payload),json.dumps(before),reason.strip(),actor,now_iso())).fetchone()
    return dict(row)


@workflow_atomic
def decide(repo, request_id, *, approve, evidence, actor):
    if not evidence.strip():
        raise ValueError('Documenta la decisión')
    r = repo.conn.execute('SELECT * FROM financial_requests WHERE id=%s FOR UPDATE',(request_id,)).fetchone()
    if not r or r['status']!='Pendiente':
        raise ValueError('La propuesta ya fue resuelta o no existe')
    entity_id = r['entity_id']
    if approve:
        if snapshot(repo,r['entity'],entity_id) != r['before_value']:
            raise ValueError('El registro cambió desde la propuesta. Rechaza y prepara una nueva versión')
        data = dict(r['payload']); data.pop('motivo',None)
        if r['entity']=='cuenta':
            if r['action']=='crear':
                entity_id = repo.create_cuenta(**data,created_at=now_iso())
            else:
                repo.update_cuenta(entity_id,**data)
        else:
            if r['action']=='eliminar':
                repo.delete_forecast(entity_id)
            else:
                data['volumen_meta_text'] = str(data.pop('volumen_meta') or 0)
                data['ticket_objetivo_text'] = str(data.pop('ticket_objetivo') or 0)
                if r['action']=='crear':
                    entity_id = repo.create_forecast(**data,created_at=now_iso())
                else:
                    repo.update_forecast(entity_id,**data)
    after = snapshot(repo,r['entity'],entity_id) if approve and r['action']!='eliminar' else None
    repo.conn.execute("""UPDATE financial_requests SET status=%s,entity_id=%s,after_value=%s::jsonb,
        reviewer=%s,evidence=%s,reviewed_at=%s WHERE id=%s""",
        ('Aprobada' if approve else 'Rechazada',entity_id,json.dumps(after),actor,evidence.strip(),now_iso(),request_id))
    record_event(repo,'financial_request',request_id,'Aprobada' if approve else 'Rechazada',actor,
        dict(before=r['before_value'],after=after,reason=r['reason'],evidence=evidence))
    return dict(repo.conn.execute('SELECT * FROM financial_requests WHERE id=%s',(request_id,)).fetchone())


def schedule_catalog_review(repo, solicitud_id, responsible, created_at):
    review = repo.conn.execute("""INSERT INTO catalog_reviews(solicitud_id,responsible,activated_at,due_date)
        VALUES(%s,%s,%s,%s) RETURNING id""",(solicitud_id,responsible,created_at,
        (date.fromisoformat(created_at[:10])+timedelta(days=30)).isoformat())).fetchone()['id']
    for user in repo.conn.execute('SELECT id FROM users WHERE active=1').fetchall():
        repo.conn.execute("""INSERT INTO internal_notifications(user_id,message,review_id,created_at)
            VALUES(%s,%s,%s,%s)""",(user['id'],f'Catálogo actualizado: solicitud #{solicitud_id}. Revisión de uso a los 30 días.',review,created_at))

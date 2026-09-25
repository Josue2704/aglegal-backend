from concurrent.futures import ThreadPoolExecutor
from datetime import date
import pytest
from aglegal.db import now_iso, connect
from aglegal.repositories import Repository


def op(repo, cat, **kwargs):
    args=dict(prospecto_nombre='Prospecto apertura',service_id=cat['servicio_id'],
        canal_captacion='Referido',origen_negocio='Orgánico',created_at=now_iso(),honorarios_estimados_text='500',
        proxima_accion='Confirmar aceptación',fecha_proxima_accion=date.today().isoformat())
    args.update(kwargs)
    return repo.create_oportunidad(**args)


def counts(repo):
    return tuple(repo.conn.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']
                 for table in ('clients','cases','case_tasks','opportunity_conversions','workflow_events'))


def test_failed_opening_rolls_back_all(repo,catalogo,apertura,monkeypatch):
    oid=op(repo,catalogo)
    before=counts(repo)
    def fail(*args,**kwargs):raise ValueError('Fallo tardío')
    monkeypatch.setattr(repo,'_asignar_originador_desde_origen',fail)
    with pytest.raises(ValueError,match='tardío'):
        repo.transition_oportunidad(oid,nuevo_estado='Ganado',crear_cliente=True,**apertura)
    assert counts(repo)==before
    assert repo.get_oportunidad(oid)['estado']=='Prospecto'


def test_missing_service_never_creates_client(repo,catalogo,apertura):
    oid=op(repo,catalogo,service_id=None)
    before=counts(repo)
    with pytest.raises(ValueError,match='servicio'):
        repo.transition_oportunidad(oid,nuevo_estado='Ganado',crear_cliente=True,**apertura)
    assert counts(repo)==before


def test_concurrent_conversion_is_one_opening(repo,catalogo,apertura):
    oid=op(repo,catalogo)
    def convert(_):
        conn=connect()
        try:return Repository(conn).transition_oportunidad(oid,nuevo_estado='Ganado',crear_cliente=True,**apertura)
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(convert,range(2)))
    assert ids[0]==ids[1]
    assert repo.conn.execute('SELECT count(*) AS n FROM cases WHERE opportunity_id=%s',(oid,)).fetchone()['n']==1
    assert len(repo.list_case_tasks(ids[0]))==1
    assert repo.get_case(ids[0])['honorarios_contratados_cents']==90000
    event=repo.workflow_history('case',ids[0])[0]
    assert event['details']['alcance']==apertura['alcance']
    assert repo.workflow_history('oportunidad',oid)[0]['details']['seguimiento']=='Confirmar aceptación'


def test_link_existing_client_and_validate_plan(repo,catalogo,apertura):
    oid=op(repo,catalogo)
    before=repo.conn.execute('SELECT count(*) AS n FROM clients').fetchone()['n']
    with pytest.raises(ValueError,match='tarea inicial'):
        repo.transition_oportunidad(oid,nuevo_estado='Ganado',client_id_existente=catalogo['cliente_id'],
                                    **dict(apertura,tareas_iniciales=[]))
    cid=repo.transition_oportunidad(oid,nuevo_estado='Ganado',client_id_existente=catalogo['cliente_id'],**apertura)
    assert repo.get_case(cid)['client_id']==catalogo['cliente_id']
    assert repo.conn.execute('SELECT count(*) AS n FROM clients').fetchone()['n']==before


def test_result_required_and_reopening_keeps_history(repo,catalogo,apertura):
    cid=repo.transition_oportunidad(op(repo,catalogo),nuevo_estado='Ganado',crear_cliente=True,**apertura)
    tid=repo.list_case_tasks(cid)[0]['id']
    for close in (lambda:repo.set_case_task_done(tid,True),lambda:repo.set_case_task_estado(tid,'Hecha')):
        with pytest.raises(ValueError,match='obtuvo'):close()
    repo.set_case_task_done(tid,True,'Documentos revisados',username='admin')
    repo.set_case_task_done(tid,False,username='admin')
    history=repo.workflow_history('task',tid)
    assert history[0]['event']=='Reabierta'
    assert history[0]['details']['resultado_anterior']=='Documentos revisados'
    assert history[1]['details']['resultado']=='Documentos revisados'

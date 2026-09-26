from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from aglegal.db import now_iso, connect
from aglegal.repositories import Repository
from aglegal.governance import propose, decide
from aglegal.indicators import explorer
from tests.test_api_modulos import app_client, _as, ADMIN, SIN_PERMISOS
from tests.test_financial_workflow import setup_case, receipt, expense_account, direct_cost, MONTH


def test_paid_cases_rebalanced_together_without_changing_cash(repo,catalogo):
    a=setup_case(repo,catalogo);b=setup_case(repo,catalogo)
    receipt(repo,catalogo,a,500);receipt(repo,catalogo,b,1000,'02')
    account=expense_account(repo,catalogo)
    originals=repo.list_comisiones(personal_id=catalogo['persona_id'])
    for row in originals: repo.approve_commission(row['id'],evidence='Origen validado',eligible=True,actor='admin')
    payment=repo.settle_commissions(commission_ids=[r['id'] for r in originals],payment_date=date.today().isoformat(),reference='PAGO',account_id=account,request_key=uuid.uuid4().hex,actor='admin')
    direct_cost(repo,catalogo,a,account,200)
    rows=repo.list_comisiones(personal_id=catalogo['persona_id'])
    assert sum(r['comision_cents'] for r in rows)==13600
    assert repo.get_expense(payment['expense_id'])['amount_cents']==16000
    assert all(repo.get_comision(r['id'])['estado']=='Pagada' for r in originals)
    adjustments=[r for r in rows if r['estado']=='Calculada']
    assert sum(r['comision_cents'] for r in adjustments)==-2400
    assert all(r['mes_reconocimiento']>MONTH for r in adjustments)
    ids=[r['id'] for r in rows]
    repo._resincronizar_comisiones_caso(a,revertir=False,created_at=now_iso());repo.conn.commit()
    assert [r['id'] for r in repo.list_comisiones(personal_id=catalogo['persona_id'])]==ids


def test_excluded_commission_stays_excluded_on_later_recalculation(repo,catalogo):
    a=setup_case(repo,catalogo);b=setup_case(repo,catalogo)
    income=receipt(repo,catalogo,a,1000)
    row=repo.list_comisiones(case_id=a)[0]
    repo.approve_commission(row['id'],evidence='No originó el negocio',eligible=False,actor='admin')
    receipt(repo,catalogo,b,1200,'02')
    direct_cost(repo,catalogo,a,expense_account(repo,catalogo),100)
    assert not any(r['estado']!='Anulada' for r in repo.list_comisiones(case_id=a))
    assert sum(r['comision_cents'] for r in repo.list_comisiones(case_id=b))==12400
    assert repo.conn.execute('SELECT 1 FROM commission_exclusions WHERE income_id=%s',(income,)).fetchone()


def test_concurrent_costs_rebalance_month_once(repo,catalogo):
    a=setup_case(repo,catalogo);b=setup_case(repo,catalogo);account=expense_account(repo,catalogo)
    receipt(repo,catalogo,a,500);receipt(repo,catalogo,b,1000,'02')
    def cost(cid):
        conn=connect()
        try:return direct_cost(Repository(conn),catalogo,cid,account,100)
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(cost,[a,b]))
    assert sum(r['comision_cents'] for r in repo.list_comisiones(personal_id=catalogo['persona_id']))==13600


def test_different_months_do_not_share_tiers(repo,catalogo):
    a=setup_case(repo,catalogo);b=setup_case(repo,catalogo)
    receipt(repo,catalogo,a,1500)
    next_month=(date.today().replace(day=28)+timedelta(days=4)).replace(day=1).isoformat()
    repo.create_income(client_id=catalogo['cliente_id'],case_id=b,amount_text='500',income_date=next_month,created_at=now_iso(),account_id=catalogo['cuenta_id'])
    direct_cost(repo,catalogo,a,expense_account(repo,catalogo),200)
    assert sum(r['comision_cents'] for r in repo.list_comisiones(case_id=a))==13600
    assert sum(r['comision_cents'] for r in repo.list_comisiones(case_id=b))==5000


def test_financial_proposals_require_approval_and_keep_versions(repo,catalogo):
    original=dict(repo.get_cuenta(catalogo['cuenta_id']))
    data={k:original[k] for k in ('grupo','subgrupo','nombre','naturaleza','category_id','family_id','centro_costo','afecta_utilidad','regla_de_uso','estado')}
    data['nombre']='Cuenta aprobada'
    first=propose(repo,entity='cuenta',entity_id=original['id'],action='editar',payload=data,reason='Nombre más claro',actor='asistente')
    stale=propose(repo,entity='cuenta',entity_id=original['id'],action='editar',payload=data,reason='Versión anterior',actor='asistente')
    assert repo.get_cuenta(original['id'])['nombre']==original['nombre']
    approved=decide(repo,first['id'],approve=True,evidence='Revisado por socio',actor='admin')
    assert approved['before_value']['nombre']==original['nombre']
    assert approved['after_value']['nombre']=='Cuenta aprobada'
    with pytest.raises(ValueError,match='cambió'):decide(repo,stale['id'],approve=True,evidence='Revisado',actor='admin')
    assert decide(repo,stale['id'],approve=False,evidence='Reemplazada',actor='admin')['status']=='Rechazada'
    with pytest.raises(ValueError,match='resuelta'):decide(repo,first['id'],approve=True,evidence='Repetición',actor='admin')


def test_financial_api_does_not_delegate_admin_approval(app_client,repo,catalogo):
    user=dict(SIN_PERMISOS,permissions={'finanzas.crear','finanzas.ver','gobierno_catalogo.aprobar'})
    _as(app_client,user)
    try:
        body=dict(account_code='EGR-'+uuid.uuid4().hex[:3].upper().replace('0','A').replace('1','B')+'-999',tipo='Egreso',grupo='Gastos',nombre='Propuesta',naturaleza='Operativo',centro_costo='Administración',motivo='Cuenta necesaria')
        response=app_client.post('/finanzas/cuentas',json=body)
        assert response.status_code==201,response.text
        request=response.json();assert request['status']=='Pendiente'
        assert not repo.conn.execute('SELECT 1 FROM plan_cuentas WHERE account_code=%s',(body['account_code'],)).fetchone()
        assert app_client.post(f"/finanzas/propuestas/{request['id']}/decision",json=dict(approve=True,evidence='Revisado')).status_code==403
        assert app_client.post('/solicitudes-catalogo/999/transicion',json=dict(estado='Aprobado',aprobador='admin')).status_code==403
    finally:_as(app_client,ADMIN)


def test_file_permissions_enforced_for_read_upload_delete(app_client,repo,catalogo,tmp_path,monkeypatch):
    from api.app.routers import attachments
    monkeypatch.setattr(attachments,'_DATA_DIR',tmp_path)
    cid=setup_case(repo,catalogo)
    _as(app_client,ADMIN)
    upload=app_client.post('/attachments/upload',data=dict(entity_type='case',entity_id=cid),files={'file':('evidencia.txt',b'prueba','text/plain')})
    assert upload.status_code==201,upload.text
    aid=upload.json()['id']
    _as(app_client,SIN_PERMISOS)
    try:
        assert app_client.get(f'/attachments/download/{aid}').status_code==403
        assert app_client.delete(f'/attachments/{aid}').status_code==403
        assert app_client.post('/attachments/upload',data=dict(entity_type='case',entity_id=cid),files={'file':('otra.txt',b'no','text/plain')}).status_code==403
        _as(app_client,dict(SIN_PERMISOS,permissions={'expedientes.ver'}))
        assert app_client.get(f'/attachments/download/{aid}').content==b'prueba'
        assert app_client.delete(f'/attachments/{aid}').status_code==403
        _as(app_client,dict(SIN_PERMISOS,permissions={'tareas.crear'}))
        assert app_client.get('/cases/choices').status_code==200
        assert app_client.get('/cases').status_code==403
        assert set(app_client.get('/cases/choices').json()[0])=={'id','title','responsible_username'}
    finally:_as(app_client,ADMIN)
    assert app_client.delete(f'/attachments/{aid}').status_code==204


def test_derived_state_and_filtered_explorer_reconcile(repo,catalogo):
    cid=setup_case(repo,catalogo);receipt(repo,catalogo,cid,3000)
    assert repo.get_case(cid)['estado_cobro']=='Cobrado'
    assert next(r for r in repo.list_cases(estado_cobro='Cobrado') if r['id']==cid)['saldo_pendiente_cents']==0
    account=expense_account(repo,catalogo)
    direct_cost(repo,catalogo,cid,account,200)
    repo.create_expense(detail='Gasto compartido',amount_text='80',expense_date=MONTH+'-01',notes='',created_at=now_iso(),account_id=account)
    result=explorer(repo,desde=MONTH,hasta=MONTH,client_id=catalogo['cliente_id'])
    assert result['totals']['income']==300000
    assert result['totals']['cost']==20000
    assert result['totals']['cases']==1
    assert result['totals']['ticket']==300000
    assert result['shared_expenses']>=8000
    assert sum(r['operating_cash'] for r in result['categories'])==result['totals']['operating_cash']
    assert all(r['client_id']==catalogo['cliente_id'] for r in result['rows'])


def test_forecast_versions_and_approved_deletion(repo,catalogo):
    family=repo.create_familia(category_id=catalogo['categoria_id'],nombre='Meta auditada',created_at=now_iso())
    r=propose(repo,entity='forecast',entity_id=None,action='crear',payload=dict(family_id=family,mes=MONTH,volumen_meta=2,ticket_objetivo=100,margen_directo_objetivo_pct=.5),reason='Plan inicial',actor='asistente')
    approved=decide(repo,r['id'],approve=True,evidence='Presupuesto aprobado',actor='admin')
    fid=approved['entity_id']
    assert approved['after_value']['ingreso_proyectado_cents']==20000
    update=propose(repo,entity='forecast',entity_id=fid,action='editar',payload=dict(volumen_meta=3,ticket_objetivo=100,margen_directo_objetivo_pct=.5),reason='Más demanda',actor='asistente')
    changed=decide(repo,update['id'],approve=True,evidence='Demanda confirmada',actor='admin')
    assert changed['before_value']['volumen_meta']==2 and changed['after_value']['volumen_meta']==3
    deletion=propose(repo,entity='forecast',entity_id=fid,action='eliminar',payload={},reason='Cancelar meta',actor='asistente')
    assert repo.get_forecast(fid)['volumen_meta']==3
    removed=decide(repo,deletion['id'],approve=True,evidence='Cambio de plan aprobado',actor='admin')
    assert removed['before_value']['volumen_meta']==3 and removed['after_value'] is None
    with pytest.raises(ValueError):repo.get_forecast(fid)


def test_catalog_notification_and_thirty_day_review(app_client,repo,codigo_unico):
    _as(app_client,ADMIN)
    response=app_client.post('/solicitudes-catalogo',json=dict(tipo_solicitud='Alta',tipo_registro='Categoria',nombre_propuesto='Revisión '+codigo_unico,codigo_propuesto=codigo_unico))
    assert response.status_code==201,response.text
    sid=response.json()['id']
    review=next(r for r in app_client.get('/solicitudes-catalogo/seguimiento').json() if r['solicitud_id']==sid)
    assert review['responsible']==ADMIN['username']
    assert review['due_date']==(date.today()+timedelta(days=30)).isoformat()
    notification=next(n for n in app_client.get('/solicitudes-catalogo/notificaciones').json() if n['review_id']==review['id'])
    assert not notification['read_at']
    assert app_client.post(f"/solicitudes-catalogo/notificaciones/{notification['id']}/leida").status_code==200
    assert app_client.post(f"/solicitudes-catalogo/seguimiento/{review['id']}/completar",json={'evidence':'Uso verificado'}).status_code==422
    repo.conn.execute('UPDATE catalog_reviews SET due_date=%s WHERE id=%s',(date.today().isoformat(),review['id']));repo.conn.commit()
    assert app_client.post(f"/solicitudes-catalogo/seguimiento/{review['id']}/completar",json={'evidence':'Usado sin duplicidad; mantener activo'}).status_code==200
    row=repo.conn.execute('SELECT * FROM catalog_reviews WHERE id=%s',(review['id'],)).fetchone()
    assert row['status']=='Completada' and row['evidence'] and row['reviewer']==ADMIN['username']


def test_manual_opening_requires_attribution_and_tracks_changes(app_client,repo,catalogo):
    body=dict(client_id=catalogo['cliente_id'],title='Apertura auditada',status='Abierto',priority='Media',opened_at=MONTH+'-01',
        service_id=catalogo['servicio_id'],honorarios_contratados=500,responsible_username='admin',
        alcance='Servicio aceptado',condiciones_cobro='Al cierre',revision_confirmada=True,mes_cobro_esperado=MONTH,probabilidad_cobro=.7,
        tareas_iniciales=[dict(titulo='Revisar',due_date=MONTH+'-02')])
    _as(app_client,ADMIN)
    assert app_client.post('/cases',json=body).status_code==422
    body.update(origen_negocio='Andrea',canal_captacion='Referido',tipo_comercial='Cliente nuevo')
    assert app_client.post('/cases',json=body).status_code==422
    body.update(origen_negocio='Orgánico')
    created=app_client.post('/cases',json=body);assert created.status_code==201,created.text
    cid=created.json()['id'];assert not repo.list_negocio_originadores(cid)
    body.update(canal_captacion='Google')
    assert app_client.put(f'/cases/{cid}',json=body).status_code==422
    assert repo.get_case(cid)['canal_captacion']=='Referido'
    body['motivo_atribucion']='El cliente confirmó la búsqueda en Google'
    updated=app_client.put(f'/cases/{cid}',json=body);assert updated.status_code==200,updated.text
    assert updated.json()['canal_captacion']=='Google'
    history=app_client.get(f'/cases/{cid}/historial').json()
    assert any(r['event']=='Atribución comercial modificada' for r in history)


@pytest.mark.parametrize('grants,expected',[
    (set(),(403,403,403)),
    ({'expedientes.ver'},(403,200,403)),
    ({'tareas.ver'},(403,403,200)),
])
def test_real_login_permission_matrix(app_client,repo,grants,expected):
    from api.app.deps import get_current_user
    _as(app_client,ADMIN)
    perms=app_client.get('/roles/permissions').json()
    ids=[p['id'] for p in perms if p['module']+'.'+p['action'] in grants]
    name='Auditor '+uuid.uuid4().hex[:8]
    role=app_client.post('/roles',json=dict(name=name,permission_ids=ids)).json()
    username='audit_'+uuid.uuid4().hex[:8];password=uuid.uuid4().hex
    uid=repo.create_user(username=username,password=password,full_name='Prueba de acceso',role=name,active=True,created_at=now_iso())
    repo.assign_user_role(uid,role['id'])
    login=app_client.post('/auth/login',json=dict(username=username,password=password))
    assert login.status_code==200
    app_client.app_ref.dependency_overrides.pop(get_current_user,None)
    try:
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        assert tuple(app_client.get(path,headers=headers).status_code for path in ('/clients','/cases','/cases/tasks'))==expected
        if grants:
            assert app_client.get('/cases/choices',headers=headers).status_code==200
        assert app_client.get('/users',headers=headers).status_code==403
    finally:_as(app_client,ADMIN)


def test_migration_keeps_prior_noneligible_decisions(repo,catalogo):
    from aglegal.db import _migrate
    cid=setup_case(repo,catalogo);iid=receipt(repo,catalogo,cid,500)
    original=repo.list_comisiones(case_id=cid)[0]
    repo.approve_commission(original['id'],eligible=False,evidence='Gestión administrativa sin origen',actor='admin')
    repo.conn.execute('DELETE FROM commission_exclusions WHERE income_id=%s',(iid,))
    repo.conn.execute("UPDATE meta SET value='50' WHERE key='schema_version'")
    repo.conn.commit();_migrate(repo.conn);repo.conn.commit()
    repo.reconocer_comision_income(iid,created_at=now_iso())
    assert not any(r['estado']!='Anulada' for r in repo.list_comisiones(case_id=cid))


def test_family_filter_keeps_case_costs_and_shared_expenses_visible(repo,catalogo):
    family=repo.create_familia(category_id=catalogo['categoria_id'],nombre='Familia auditada',created_at=now_iso())
    repo.conn.execute('UPDATE plan_cuentas SET family_id=%s WHERE id=%s',(family,catalogo['cuenta_id']));repo.conn.commit()
    cid=setup_case(repo,catalogo);receipt(repo,catalogo,cid,500)
    account=expense_account(repo,catalogo);direct_cost(repo,catalogo,cid,account,100)
    result=explorer(repo,desde=MONTH,hasta=MONTH,family_id=family)
    assert result['totals']['income']==50000
    assert result['totals']['cost']==10000
    assert sum(r['operating_budget'] for r in result['categories'])==result['totals']['operating_budget']


@pytest.mark.parametrize('value',[-10,0,float('nan'),float('inf'),101])
def test_invalid_participation_cannot_enter_reconciliation(repo,catalogo,value):
    cid=setup_case(repo,catalogo)
    with pytest.raises(ValueError,match='participación'):
        repo.set_negocio_originadores(cid,originadores=[dict(personal_id=catalogo['persona_id'],porcentaje_participacion=value,tipo_origen='Cliente nuevo')],created_at=now_iso())
    assert repo.list_negocio_originadores(cid)[0]['porcentaje_participacion']==100


def test_origin_profit_includes_costs_before_the_first_receipt(repo,catalogo):
    cid=setup_case(repo,catalogo)
    direct_cost(repo,catalogo,cid,expense_account(repo,catalogo),100)
    person=repo.get_persona(catalogo['persona_id'])['persona']
    row=next(r for r in repo.ingresos_por_origen(desde=MONTH,hasta=MONTH) if r['origen']==person)
    assert row['ingresos_cents']==0 and row['utilidad_directa_cents']==-10000
    assert any(c['id']==cid for c in row['expedientes'])


def test_paid_partial_invoice_does_not_report_invoice_debt(repo,catalogo):
    from tests.test_billing_payments import invoice,pay
    cid=setup_case(repo,catalogo);inv=invoice(repo,catalogo,cid)
    repo.update_invoice_status(inv,'Enviada')
    assert repo.get_case(cid)['estado_cobro']=='Facturado pendiente de cobro'
    pay(repo,catalogo,inv,100)
    assert repo.get_case(cid)['estado_cobro']=='En ejecución'
    repo.conn.execute("UPDATE cases SET status='Cerrado' WHERE id=%s",(cid,));repo.conn.commit()
    assert repo.get_case(cid)['estado_cobro']=='Finalizado pendiente de facturar'

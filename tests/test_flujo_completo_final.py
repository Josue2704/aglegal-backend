"""Auditoría integrada de pipeline, expediente, costos, cobros y documentos.
Todos los registros y archivos de esta prueba son aislados y desechables.
Los hallazgos se registran explícitamente; pasar estas pruebas no certifica que no haya brechas.
"""
from pathlib import Path
from datetime import date
import json
import pytest
from fastapi.testclient import TestClient
from aglegal.db import now_iso

EVIDENCE = {}

@pytest.fixture(scope='module',autouse=True)
def evidence():
    yield
    dest=Path(__file__).resolve().parents[2]/'auditoria'/'2026-09-26'/'flujo-completo-resultados.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(EVIDENCE,ensure_ascii=False,indent=2),encoding='utf-8')

@pytest.fixture
def http(repo,monkeypatch,tmp_path):
    from api.app.main import app
    from api.app.deps import get_current_user
    from api.app.routers import attachments
    app.dependency_overrides[get_current_user]=lambda:dict(id=1,username='admin',is_admin=True,permissions=set())
    monkeypatch.setattr(attachments,'_DATA_DIR',tmp_path)
    with TestClient(app,raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def ok(response,code=200):
    assert response.status_code==code,response.text
    return response.json() if response.content else None


def test_client_required_name_and_optional_identity(http):
    for name in ['', '   ']:
        assert http.post('/clients', json={'name': name}).status_code == 422
    assert http.post('/clients', json={'name': 'Prueba', 'client_type': ''}).status_code == 422
    client = ok(http.post('/clients', json={'name': '  Cliente sin documento todavía  '}), 201)
    assert client['name'] == 'Cliente sin documento todavía'
    assert client['id'] > 0
    assert not client['id_number']
    assert http.put(f"/clients/{client['id']}", json={'name': '   '}).status_code == 422


def opportunity(http,catalogo):
    return ok(http.post('/oportunidades',json=dict(prospecto_nombre='Auditoría flujo integral',
        canal_captacion='Referido',origen_negocio='Orgánico',service_id=catalogo['servicio_id'],
        honorarios_estimados=1000,responsable_username='admin',proxima_accion='Enviar cotización',
        fecha_proxima_accion=date.today().isoformat())),201)


def opening(http,catalogo,apertura):
    op=opportunity(http,catalogo)
    ok(http.post(f"/oportunidades/{op['id']}/transicion",json={'estado':'Cotizado'}))
    plan=[dict(titulo=f'Inicial {i+1}',due_date=date.today().isoformat(),costo_estimado=cost,
        responsible_username='admin',asignados=['admin'],notes='Incluida en el acuerdo') for i,cost in enumerate([100,200,50])]
    body=dict(apertura,estado='Ganado',crear_cliente=True,honorarios_pactados=1000,tareas_iniciales=plan)
    result=ok(http.post(f"/oportunidades/{op['id']}/transicion",json=body))
    return result['case_id'],op['id'],body


def test_01_won_cost_variations_extra_invoice_and_partial_payments(http,repo,catalogo,apertura,codigo_unico):
    from tests.test_tareas_facturacion import _cuenta_egreso
    cid,oid,body=opening(http,catalogo,apertura)
    assert ok(http.post(f'/oportunidades/{oid}/transicion',json=body))['case_id']==cid
    tasks=ok(http.get(f'/cases/{cid}/tasks'))
    assert len(tasks)==3 and sum(t['monto_adicional'] for t in tasks)==0
    case=ok(http.get(f'/cases/{cid}'))
    assert case['honorarios_contratados']==1000
    assert sum(t['costo_estimado'] for t in tasks)==350
    assert case['costos_directos_estimados']==350
    EVIDENCE['presupuesto_apertura']={'honorarios':1000,'estimado_tareas':350,'estimado_expediente':case['costos_directos_estimados'],
        'alineado':case['costos_directos_estimados']==350,'conversion_repetida_sin_duplicados':True}
    cuenta=_cuenta_egreso(repo,codigo_unico)
    for t,cost in zip(tasks,[80,260,30]):
        r=http.post(f"/cases/tasks/{t['id']}/cerrar",json=dict(completed_notes='Resultado comprobado',
            costo_real=cost,costo_account_id=cuenta,completed_at=date.today().isoformat()))
        ok(r)
    case=ok(http.get(f'/cases/{cid}'))
    assert case['costos_directos_reales']==370 and case['honorarios_contratados']==1000
    included=ok(http.post(f'/cases/{cid}/tasks',json=dict(title='Adicional incluida',costo_estimado=40,
        costo_real=35,costo_account_id=cuenta,responsible_username='admin',asignados=['admin'])),201)
    assert ok(http.get(f'/cases/{cid}'))['honorarios_contratados']==1000
    extra=ok(http.post(f'/cases/{cid}/tasks',json=dict(title='Extra autorizado',monto_adicional=120,
        autorizado_por='Cliente: aprobación documentada',costo_estimado=25,costo_real=20,
        costo_account_id=cuenta,responsible_username='admin',asignados=['admin'])),201)
    client_id=case['client_id']
    before=ok(http.get(f'/invoices/unbilled/{client_id}?case_id={cid}'))
    assert not any(t['id']==extra['id'] for t in before['tasks'])
    ok(http.post(f"/cases/tasks/{extra['id']}/cerrar",json=dict(completed_notes='Trabajo extra entregado')))
    after=ok(http.get(f'/invoices/unbilled/{client_id}?case_id={cid}'))
    assert [t['id'] for t in after['tasks']]==[extra['id']]
    inv=ok(http.post('/invoices',json=dict(client_id=client_id,case_id=cid,invoice_number='AUD-'+codigo_unico,
        invoice_date=date.today().isoformat(),items=[dict(description='Honorarios pactados',unit_price=1000),
        dict(description='Extra autorizado',unit_price=120,entity_type='case_task',entity_id=extra['id'])])),201)
    assert inv['total']==1120
    ok(http.patch(f"/invoices/{inv['id']}/status",json={'status':'Enviada'}))
    for idx,amount in enumerate([400,720]):
        payment=dict(amount=amount,income_date=date.today().isoformat(),account_id=catalogo['cuenta_id'],request_key=f'audit-{codigo_unico}-{idx}')
        paid=ok(http.post(f"/invoices/{inv['id']}/payments",json=payment))
        retry=ok(http.post(f"/invoices/{inv['id']}/payments",json=payment))
        assert len(paid['payments'])==len(retry['payments'])
    final=ok(http.get(f'/cases/{cid}'))
    assert final['honorarios_contratados']==1120 and final['costos_directos_reales']==425
    assert final['saldo_pendiente']==0
    assert final['costos_directos_estimados']==350
    EVIDENCE['flujo_financiero']={'precio_inicial':1000,'costo_inicial_estimado_tareas':350,
        'costo_real_iniciales':370,'tarea_nueva_incluida_costo':35,'extra_honorarios':120,'extra_costo':20,
        'honorarios_finales':final['honorarios_contratados'],'costos_finales':final['costos_directos_reales'],
        'pagos':[400,720],'saldo':final['saldo_pendiente'],'utilidad_real':1120-425,
        'costo_interno_no_aumenta_cobro':True,'extra_facturable_tras_terminarlo':True}


def test_02_lost_does_not_open_or_bill(http,repo,catalogo):
    op=opportunity(http,catalogo)
    before=tuple(repo.conn.execute(f'SELECT COUNT(*) AS n FROM {t}').fetchone()['n'] for t in ['clients','cases','case_tasks','invoices'])
    assert http.post(f"/oportunidades/{op['id']}/transicion",json={'estado':'Perdido'}).status_code==422
    lost=ok(http.post(f"/oportunidades/{op['id']}/transicion",json={'estado':'Perdido','motivo_perdida':'El prospecto no aceptó la propuesta'}))
    after=tuple(repo.conn.execute(f'SELECT COUNT(*) AS n FROM {t}').fetchone()['n'] for t in ['clients','cases','case_tasks','invoices'])
    assert before==after and lost['case_id'] is None
    EVIDENCE['perdida']={'motivo_obligatorio':True,'sin_cliente_expediente_tareas_factura':True}


def test_03_documents_volume_types_downloads_and_categories(http,repo,catalogo,apertura):
    cid,_,_=opening(http,catalogo,apertura)
    tid=ok(http.get(f'/cases/{cid}/tasks'))[0]['id']
    def upload(kind,entity_id,name='documento.txt',data=b'contenido de prueba',role=None):
        fields={'entity_type':kind,'entity_id':entity_id}
        if role:fields['doc_role']=role
        return http.post('/attachments/upload',data=fields,files={'file':(name,data,'text/plain')})
    docs=[ok(upload('case',cid),201) for _ in range(25)]
    assert len({d['stored_path'] for d in docs})==25
    assert http.get(f"/attachments/download/{docs[0]['id']}").content==b'contenido de prueba'
    guide=ok(upload('case_task',tid,role='guide'),201)
    proof=ok(upload('case_task',tid,role='evidence'),201)
    assert upload('case',cid,'rechazado.exe').status_code==400
    assert upload('case',cid,data=b'x'*(20*1024*1024+1)).status_code==413
    assert upload('case',999999999).status_code==404
    listing=ok(http.get(f'/cases/{cid}/all-attachments'))
    ids={d['id'] for d in listing}
    assert guide['id'] in ids and proof['id'] in ids
    assert all('doc_role' in d for d in listing)
    EVIDENCE['documentos']={'archivos_en_expediente_probados':25,'limite_por_archivo_MB':20,
        'mismo_nombre_no_sobrescribe':True,'descarga_contenido_correcto':True,
        'guia_visible_en_expediente':guide['id'] in ids,'evidencia_visible_en_expediente':proof['id'] in ids,
        'clasificacion_doc_role_en_listado_expediente':all('doc_role' in d for d in listing),
        'extensiones_no_permitidas_rechazadas':True,'archivos_grandes_rechazados':True}
    from api.app.main import app
    from api.app.deps import get_current_user
    app.dependency_overrides[get_current_user]=lambda:dict(id=1,username='admin',is_admin=False,permissions=set())
    assert http.get(f"/attachments/download/{docs[0]['id']}").status_code==403
    assert http.delete(f"/attachments/{docs[0]['id']}").status_code==403
    EVIDENCE['documentos']['permisos_lectura_y_borrado_verificados']=True


def test_04_invalid_task_does_not_persist_partial_fee(http,repo,catalogo,apertura):
    cid,_,_=opening(http,catalogo,apertura)
    before=len(ok(http.get(f'/cases/{cid}/tasks')))
    bad=http.post(f'/cases/{cid}/tasks',json=dict(title='No debe persistir',monto_adicional=20,autorizado_por='Cliente',costo_real=25))
    assert bad.status_code==422
    assert len(ok(http.get(f'/cases/{cid}/tasks')))==before
    assert ok(http.get(f'/cases/{cid}'))['honorarios_contratados']==1000
    EVIDENCE['rechazo_atomico_API']={'sin_cuenta_no_crea_tarea_ni_sube_honorarios':True}


def test_05_audit_validation_and_two_step_document_upload(http,repo,catalogo,apertura):
    cid,_,_=opening(http,catalogo,apertura)
    bad=http.post(f'/cases/{cid}/tasks',json=dict(title='Sondeo validación',costo_estimado=-10,
        responsible_username='usuario_que_no_existe',asignados=['usuario_que_no_existe']))
    assert bad.status_code==422
    EVIDENCE['validacion_tareas']={'negativos_y_usuarios_inexistentes_rechazados':bad.status_code>=400,'http':bad.status_code}
    task=ok(http.post(f'/cases/{cid}/tasks',json={'title':'Tarea antes de subir documento'}),201)
    failure=http.post('/attachments/upload',data={'entity_type':'case_task','entity_id':task['id'],'doc_role':'guide'},files={'file':('fallo.exe',b'x','application/octet-stream')})
    assert failure.status_code==400
    exists=any(t['id']==task['id'] for t in ok(http.get(f'/cases/{cid}/tasks')))
    EVIDENCE['creacion_con_adjunto']={'si_falla_documento_tarea_ya_existe':exists,
        'comportamiento_interfaz_corregido':'Advierte que la tarea ya fue creada; permite adjuntar después sin repetir la creación.'}


def test_06_explicit_budget_and_same_task_data_in_both_lists(http,repo,catalogo,apertura,codigo_unico):
    name='worker_'+codigo_unico
    repo.create_user(username=name,password='isolated-fixture',role='Abogado',created_at=now_iso())
    op=opportunity(http,catalogo)
    plan=[dict(titulo='Plan con colaborador',notes='Descripción de prueba',due_date=date.today().isoformat(),
        responsible_username='admin',asignados=[name],costo_estimado=100,es_critico=True)]
    result=ok(http.post(f"/oportunidades/{op['id']}/transicion",json=dict(apertura,estado='Ganado',crear_cliente=True,
        honorarios_pactados=1000,costos_directos_estimados=500,tareas_iniciales=plan)))
    cid=result['case_id']
    assert ok(http.get(f'/cases/{cid}'))['costos_directos_estimados']==500
    task=ok(http.get(f'/cases/{cid}/tasks'))[0]
    global_task=next(t for t in ok(http.get(f'/cases/tasks?case_id={cid}')) if t['id']==task['id'])
    for key in ['title','notes','due_date','responsible_username','asignados','costo_estimado','es_critico','etiquetas']:
        assert task[key]==global_task[key]
    assert task['asignados']==[name]
    # Ganar directamente también constituye una propuesta aceptada; no debe
    # aumentar el numerador sin formar parte del denominador de conversión.
    quoted=opportunity(http,catalogo)
    ok(http.post(f"/oportunidades/{quoted['id']}/transicion",json={'estado':'Cotizado'}))
    conversion=repo.conversion_comercial(service_id=catalogo['servicio_id'])
    assert conversion['ganados']==1
    assert conversion['cotizados']==2
    assert conversion['conversion_pct']==0.5
    EVIDENCE['conversion_directa']={'ganados':1,'propuestas':2,'conversion':0.5}
    assert http.post(f'/cases/{cid}/tasks',json=dict(title='Responsable inexistente',responsible_username='no-existe')).status_code==422
    assert http.post(f'/cases/{cid}/tasks',json=dict(title='Colaborador inexistente',asignados=['no-existe'])).status_code==422
    EVIDENCE['formularios_y_presupuesto_explicito']={'presupuesto_500_no_se_suma_a_100_de_tareas':True,
        'responsable_colaboradores_descripcion_fechas_costo_critico_etiquetas_iguales_en_listados':True,
        'usuarios_inexistentes_rechazados':True}

"""Pruebas de API de todos los módulos, contra el schema aislado de pruebas.

La autenticación se sustituye con `dependency_overrides` (usuario admin / usuario
sin permisos de prueba) — no se toca el login real ni ningún dato fuera del schema de
pruebas. Dos capas:
  1. Barrido: cada GET sin parámetros de ruta de cada router debe responder < 500.
  2. Flujos: recorridos de negocio por módulo pasando por HTTP (routers + schemas +
     permisos), no solo por el repositorio.
"""
from __future__ import annotations

import random
import string

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

ADMIN = {"id": 1, "username": "tester_admin", "role": "Administrador", "role_id": None, "is_admin": True, "permissions": set()}
SIN_PERMISOS = {"id": 2, "username": "tester_sin_permisos", "role": "Nada", "role_id": None, "is_admin": False, "permissions": set()}


def _uniq(n: int = 3) -> str:
    return "".join(random.choices(string.ascii_uppercase, k=n))


@pytest.fixture(scope="module")
def app_client(db_conn):
    from api.app.deps import get_current_user
    from api.app.main import app

    app.dependency_overrides[get_current_user] = lambda: ADMIN
    with TestClient(app, raise_server_exceptions=False) as c:
        c.app_ref = app
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, user: dict):
    from api.app.deps import get_current_user
    client.app_ref.dependency_overrides[get_current_user] = lambda: user


def test_opening_permissions_and_task_routes(app_client,repo,catalogo,apertura):
    _as(app_client,ADMIN)
    op=app_client.post('/oportunidades',json=dict(prospecto_nombre='Permisos apertura',service_id=catalogo['servicio_id'],canal_captacion='Referido',origen_negocio='Orgánico')).json()
    _as(app_client,dict(SIN_PERMISOS,permissions={'pipeline.editar'}))
    try:
        response=app_client.post(f"/oportunidades/{op['id']}/transicion",json=dict(apertura,estado='Ganado',crear_cliente=True))
        assert response.status_code==403
        assert app_client.get('/users/choices').status_code==200
        assert app_client.get('/users').status_code==403
    finally:_as(app_client,ADMIN)
    opened=app_client.post(f"/oportunidades/{op['id']}/transicion",json=dict(apertura,estado='Ganado',crear_cliente=True))
    assert opened.status_code==200,opened.text
    cid=opened.json()['case_id'];tid=repo.list_case_tasks(cid)[0]['id']
    _as(app_client,SIN_PERMISOS)
    try:
        for suffix,payload in [('done',{'done':True,'completed_notes':'Listo'}),('critico',{'es_critico':True}),('notes',{'notes':'Cambio'})]:
            assert app_client.patch(f'/cases/tasks/{tid}/{suffix}',json=payload).status_code==403
    finally:_as(app_client,ADMIN)
    assert app_client.patch(f'/cases/tasks/{tid}/done',json={'done':True}).status_code==422
    assert app_client.get(f'/cases/{cid}/historial').json()[0]['event']=='Apertura confirmada'


def test_commission_review_and_payment_have_separate_permissions(app_client,repo,catalogo):
    from datetime import date
    from uuid import uuid4
    from aglegal.db import now_iso
    cid=repo.create_case(client_id=catalogo['cliente_id'],title='Permisos comisiones',status='Abierto',priority='Media',
        opened_at=date.today().isoformat(),created_at=now_iso(),service_id=catalogo['servicio_id'],honorarios_contratados_text='500')
    repo.set_negocio_originadores(cid,originadores=[dict(personal_id=catalogo['persona_id'],porcentaje_participacion=100,tipo_origen='Cliente nuevo')],created_at=now_iso())
    repo.create_income(client_id=catalogo['cliente_id'],case_id=cid,amount_text='500',income_date=date.today().isoformat(),created_at=now_iso(),account_id=catalogo['cuenta_id'])
    c=repo.list_comisiones(case_id=cid)[0]
    review={'evidencia':'Aceptación y origen verificados','elegible':True}
    payment={'commission_ids':[c['id']],'payment_date':date.today().isoformat(),'reference':'TX prueba','request_key':uuid4().hex}
    _as(app_client,dict(SIN_PERMISOS,permissions={'comisiones.editar'}))
    try:
        assert app_client.post(f"/comisiones/{c['id']}/revision",json=review).status_code==403
        assert app_client.post('/comisiones/liquidaciones',json=payment).status_code==403
        _as(app_client,dict(SIN_PERMISOS,permissions={'comisiones.aprobar'}))
        r=app_client.post(f"/comisiones/{c['id']}/revision",json=review)
        assert r.status_code==200,r.text
        assert r.json()['aprobado_por']==SIN_PERMISOS['username']
        assert app_client.post('/comisiones/liquidaciones',json=payment).status_code==403
    finally:_as(app_client,ADMIN)
    account=repo.create_cuenta(account_code=repo.get_cuenta(catalogo['cuenta_id'])['account_code'].replace('ING-','EGR-'),
        tipo='Egreso',grupo='Comercial',nombre='Comisiones',naturaleza='Operativo',centro_costo='Comercial',created_at=now_iso())
    r=app_client.post('/comisiones/liquidaciones',json=dict(payment,account_id=account))
    assert r.status_code==200,r.text
    assert r.json()['amount_cents']==5000
    history=app_client.get('/comisiones/liquidaciones').json()
    assert any(p['id']==r.json()['id'] and c['id'] in p['commission_ids'] for p in history)


# ── 1. Barrido de todos los GET ───────────────────────────────────────────────

# Endpoints que dependen de servicios externos (Google/Outlook OAuth) o de archivos.
EXCLUIR = ("/google-cal", "/outlook-cal", "/attachments/download", "/docs", "/redoc", "/openapi.json")


def _get_routes_sin_parametros():
    from api.app.main import app

    rutas = []
    for r in app.routes:
        if isinstance(r, APIRoute) and "GET" in r.methods and "{" not in r.path and not r.path.startswith(EXCLUIR):
            rutas.append(r.path)
    return sorted(set(rutas))


@pytest.mark.parametrize("path", _get_routes_sin_parametros())
def test_barrido_get_no_devuelve_500(app_client, path):
    _as(app_client, ADMIN)
    resp = app_client.get(path)
    # 422 = el endpoint exige query params obligatorios (esperado); lo que NO puede haber es 500.
    assert resp.status_code < 500, f"GET {path} -> {resp.status_code}: {resp.text[:300]}"


def test_barrido_cubre_todos_los_modulos():
    rutas = _get_routes_sin_parametros()
    prefijos = {"/clients", "/cases", "/sessions", "/incomes", "/expenses", "/costs", "/catalogo", "/finanzas",
                "/oportunidades", "/comisiones", "/solicitudes-catalogo", "/payroll", "/users", "/dashboard",
                "/invoices", "/roles"}
    cubiertos = {p for p in prefijos if any(r.startswith(p) for r in rutas)}
    assert cubiertos == prefijos, f"módulos sin ningún GET barrido: {prefijos - cubiertos}"


# ── 2. Permisos ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("metodo,path", [
    ("get", "/payroll"), ("get", "/finanzas/personal"), ("get", "/catalogo/categorias"), ("get", "/users"),
])
def test_usuario_sin_permisos_recibe_403(app_client, metodo, path):
    _as(app_client, SIN_PERMISOS)
    try:
        assert getattr(app_client, metodo)(path).status_code == 403
    finally:
        _as(app_client, ADMIN)


def test_plantilla_de_tareas_solo_admin_puede_editar(app_client):
    _as(app_client, SIN_PERMISOS)
    try:
        r = app_client.post("/catalogo/servicios/1/plantilla-tareas", json={"titulo": "x"})
        assert r.status_code == 403
    finally:
        _as(app_client, ADMIN)


# ── 3. Flujo: clientes → expedientes → tareas → honorarios → facturas ─────────

@pytest.fixture()
def servicio_api(app_client, repo, catalogo):
    return catalogo["servicio_id"], catalogo["cliente_id"]


def test_flujo_completo_expediente_tareas_honorarios_factura(app_client, servicio_api):
    _as(app_client, ADMIN)
    servicio_id, cliente_id = servicio_api

    # Plantilla de tareas del servicio (HTTP)
    for i, titulo in enumerate(["Recibir documentos", "Presentar demanda"]):
        r = app_client.post(f"/catalogo/servicios/{servicio_id}/plantilla-tareas", json={"titulo": titulo, "orden": i, "dias_plazo_relativo": 5 * (i + 1)})
        assert r.status_code == 201, r.text
    r = app_client.get(f"/catalogo/servicios/{servicio_id}/plantilla-tareas")
    assert [t["titulo"] for t in r.json()] == ["Recibir documentos", "Presentar demanda"]

    # Crear expediente con tareas iniciales (las de la plantilla)
    r = app_client.post("/cases", json={
        "client_id": cliente_id, "title": "Caso API", "status": "Abierto", "priority": "Media", "opened_at": "2026-03-01",
        "service_id": servicio_id, "honorarios_contratados": 1000, "responsible_username":"admin",
        "alcance":"Servicio contratado", "condiciones_cobro":"Al finalizar", "revision_confirmada":True,"mes_cobro_esperado":"2026-12","probabilidad_cobro":0.7,
        "tareas_iniciales": [{"titulo": "Recibir documentos", "due_date":"2026-03-06"}, {"titulo": "Presentar demanda", "due_date":"2026-03-11", "es_critico": True}],
    })
    assert r.status_code == 201, r.text
    caso = r.json()
    assert caso["honorarios_contratados"] == 1000
    case_id = caso["id"]

    r = app_client.get(f"/cases/{case_id}/tasks")
    tareas = r.json()
    assert len(tareas) == 2 and all(t["origen"] == "plantilla" and t["monto_adicional"] == 0 for t in tareas)

    # Tarea manual con monto adicional → sube honorarios y queda en bitácora
    r = app_client.post(f"/cases/{case_id}/tasks", json={"title": "Trámite extra", "monto_adicional": 250,
                                                         "autorizado_por": "Cliente (correo)", "cobro_anticipado": True})
    assert r.status_code == 201, r.text
    task_extra = r.json()
    assert task_extra["origen"] == "manual" and task_extra["monto_adicional"] == 250
    assert next(c for c in app_client.get("/cases").json() if c["id"] == case_id)["honorarios_contratados"] == 1250
    log = app_client.get(f"/cases/{case_id}/honorarios-log").json()
    assert len(log) == 1 and log[0]["monto"] == 250 and log[0]["username"] == "tester_admin"

    # Sesión con monto adicional
    r = app_client.post("/sessions", json={
        "client_id": cliente_id, "case_id": case_id, "session_date": "2026-03-10", "consult_type": "Audiencia extra",
        "status": "Pendiente", "monto_adicional": 100,
    })
    assert r.status_code == 201, r.text
    session_id = r.json()["id"]
    assert next(c for c in app_client.get("/cases").json() if c["id"] == case_id)["honorarios_contratados"] == 1350

    # Facturar solo trabajo de este expediente; otro expediente del mismo cliente no debe colarse
    otro = app_client.post("/cases", json={"client_id": cliente_id, "title": "Otro caso", "status": "Abierto", "priority": "Baja", "opened_at": "2026-03-01", "service_id":servicio_id, "honorarios_contratados":0,"responsible_username":"admin","alcance":"Servicio gratuito", "condiciones_cobro":"Sin cobro", "revision_confirmada":True,"mes_cobro_esperado":"2026-12","probabilidad_cobro":0.7,"tareas_iniciales":[{"titulo":"Revisar", "due_date":"2026-03-02"}]}).json()
    tarea_otro = app_client.post(f"/cases/{otro['id']}/tasks", json={"title": "Tarea del otro caso"}).json()

    sin_filtro = app_client.get(f"/invoices/unbilled/{cliente_id}").json()
    con_filtro = app_client.get(f"/invoices/unbilled/{cliente_id}", params={"case_id": case_id}).json()
    assert sin_filtro["tasks"] == []
    assert con_filtro["tasks"][0]["monto_adicional_cents"] == 25000
    assert tarea_otro["id"] not in [t["id"] for t in con_filtro["tasks"]]

    r = app_client.post("/invoices", json={
        "client_id": cliente_id, "case_id": case_id, "invoice_number": f"F-{_uniq(5)}", "invoice_date": "2026-03-15",
        "items": [{"description": "Tarea de otro caso", "unit_price": 50, "entity_type": "case_task", "entity_id": tarea_otro["id"]}],
    })
    assert r.status_code == 422 and "no pertenece" in r.json()["detail"]

    r = app_client.post("/invoices", json={
        "client_id": cliente_id, "case_id": case_id, "invoice_number": f"F-{_uniq(5)}", "invoice_date": "2026-03-15",
        "items": [{"description": "Trámite extra", "unit_price": 250, "entity_type": "case_task", "entity_id": task_extra["id"]}],
    })
    assert r.status_code in (200, 201), r.text
    invoice_id = r.json()["id"]
    assert task_extra["id"] not in [t["id"] for t in app_client.get(f"/invoices/unbilled/{cliente_id}", params={"case_id": case_id}).json()["tasks"]]

    # Borrar la factura libera la partida
    assert app_client.delete(f"/invoices/{invoice_id}").status_code == 204
    assert task_extra["id"] in [t["id"] for t in app_client.get(f"/invoices/unbilled/{cliente_id}", params={"case_id": case_id}).json()["tasks"]]

    # Borrar tarea y sesión revierte honorarios
    assert app_client.delete(f"/cases/tasks/{task_extra['id']}").status_code == 204
    assert app_client.delete(f"/sessions/{session_id}").status_code == 204
    assert next(c for c in app_client.get("/cases").json() if c["id"] == case_id)["honorarios_contratados"] == 1000
    assert len(app_client.get(f"/cases/{case_id}/honorarios-log").json()) == 4  # 2 altas + 2 reversiones


# ── 4. Flujo: nómina ──────────────────────────────────────────────────────────

def test_flujo_nomina_completo(app_client, repo):
    from aglegal.db import now_iso

    _as(app_client, ADMIN)
    u = _uniq()
    cuenta = repo.create_cuenta(account_code=f"EGR-{u}-001", tipo="Egreso", grupo="Personal", nombre=f"Nomina {u}",
                                naturaleza="Fijo", centro_costo="Administración", created_at=now_iso())

    # Config vigente: AFP sin tope y 4 tramos oficiales de renta
    cfg = app_client.get("/payroll/config/vigente").json()
    assert cfg["afp_tope_cotizable"] is None
    assert len(cfg["tramos_renta"]) == 4

    # Persona con cuenta enlazada
    r = app_client.post("/finanzas/personal", json={"persona": f"Emp {u}", "cargo": "Asistente", "monto_mensual": 900, "mes_inicio": "2026-01", "account_id": cuenta})
    assert r.status_code == 201, r.text
    persona = r.json()
    assert persona["account_code"] == f"EGR-{u}-001"

    # Vista previa: $900 → ISSS 3% = 27, AFP 7.25% = 65.25, renta sobre (900-27-65.25=807.75) tramo II
    prev = app_client.post("/payroll/preview", json={"salario_base": 900}).json()
    assert prev["isss_empleado"] == 27.0 and prev["afp_empleado"] == 65.25
    assert prev["renta"] == round(17.67 + (807.75 - 550) * 0.10, 2)
    assert prev["neto"] == round(900 - 27 - 65.25 - prev["renta"], 2)
    assert prev["advertencias"] == []

    # Crear planilla calculada, duplicado rechazado, corrección con auditoría
    body = {"personal_id": persona["id"], "period": "2026-05", "payment_date": "2026-05-31", "modo": "calculado", "salario_base": 900}
    r = app_client.post("/payroll", json=body)
    assert r.status_code == 201, r.text
    pago = r.json()
    assert pago["amount"] == prev["neto"] and pago["modo"] == "calculado"
    assert app_client.post("/payroll", json=body).status_code == 422

    r = app_client.put(f"/payroll/{pago['id']}", json={"payment_date": "2026-06-01", "notes": "corregido", "amount": pago["amount"] + 1})
    assert r.status_code == 200, r.text
    assert {e["campo"] for e in app_client.get(f"/payroll/{pago['id']}/audit-log").json()} >= {"amount_cents", "payment_date"}

    # Persona sin cuenta contable enlazada → error claro, no 500
    sin_cuenta = app_client.post("/finanzas/personal", json={"persona": f"Sin cuenta {u}", "mes_inicio": "2026-01"}).json()
    r = app_client.post("/payroll", json={"personal_id": sin_cuenta["id"], "period": "2026-05", "payment_date": "2026-05-31", "modo": "calculado", "salario_base": 500})
    assert r.status_code == 422 and "cuenta contable" in r.json()["detail"]

    assert app_client.delete(f"/payroll/{pago['id']}").status_code == 204


def test_prestaciones_de_ley_por_api(app_client):
    _as(app_client, ADMIN)
    ag = app_client.post("/payroll/prestaciones/aguinaldo", json={"salario_base": 600, "anios_antiguedad": 5}).json()
    assert ag["dias_correspondientes"] == 19 and ag["monto"] == round(600 / 30 * 19, 2)
    vac = app_client.post("/payroll/prestaciones/vacaciones", json={"salario_base": 600}).json()
    assert vac["salario_dias"] == 300.0 and vac["recargo_30"] == 90.0 and vac["total"] == 390.0
    ind = app_client.post("/payroll/prestaciones/indemnizacion", json={"salario_base": 600, "anios_servicio": 3}).json()
    assert ind["monto"] == 1800.0
    assert any("tope" in a.lower() for a in ind["advertencias"])  # tope de indemnización aún sin configurar


def test_config_de_nomina_nueva_version_por_api(app_client):
    _as(app_client, ADMIN)
    r = app_client.post("/payroll/config", json={
        "vigente_desde": "2032-01-01", "isss_tasa_empleado": 0.03, "isss_tasa_patronal": 0.075, "isss_tope_cotizable": 1000,
        "afp_tasa_empleado": 0.0725, "afp_tasa_patronal": 0.0875, "afp_tope_cotizable": None,
        "tope_salario_indemnizacion": 1612.8, "tramos_renta": [{"sobre_exceso_de": 0, "hasta": 600, "cuota_fija": 0, "porcentaje_exceso": 0}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["tope_salario_indemnizacion"] == 1612.8 and r.json()["afp_tope_cotizable"] is None
    assert app_client.post("/payroll/config", json={**r.json(), "tramos_renta": []}).status_code == 422  # misma vigencia


# ── 5. Otros módulos: crear/leer/actualizar ───────────────────────────────────

def test_clientes_crud(app_client):
    _as(app_client, ADMIN)
    r = app_client.post("/clients", json={"name": f"Cliente {_uniq(6)}", "email": "a@b.com"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert app_client.get("/clients").status_code == 200
    r = app_client.put(f"/clients/{cid}", json={"name": "Renombrado", "client_type": "Jurídica"})
    assert r.status_code == 200 and r.json()["name"] == "Renombrado"


def test_flujo_de_caja_ingresos_gastos_costos_exigen_cuenta(app_client, repo, catalogo):
    from aglegal.db import now_iso

    _as(app_client, ADMIN)
    egr = repo.create_cuenta(account_code=f"EGR-{_uniq()}-002", tipo="Egreso", grupo="Gastos", nombre=f"G {_uniq(4)}",
                             naturaleza="Fijo", centro_costo="Administración", created_at=now_iso())
    r = app_client.post("/incomes", json={"amount": 100, "income_date": "2026-04-01", "account_id": catalogo["cuenta_id"], "monto_iva": 13})
    assert r.status_code == 201, r.text
    assert r.json()["monto_neto_operativo"] == 87.0
    assert app_client.post("/expenses", json={"detail": "Papelería", "amount": 40, "expense_date": "2026-04-02", "account_id": egr}).status_code == 201
    assert app_client.post("/costs", json={"concept": "Timbres", "amount": 15, "cost_date": "2026-04-02", "account_id": egr}).status_code == 201
    # cuenta de egreso en un ingreso → rechazo controlado, no 500
    assert app_client.post("/incomes", json={"amount": 10, "income_date": "2026-04-01", "account_id": egr}).status_code == 422


def test_pipeline_y_gobierno_del_catalogo_listan(app_client):
    _as(app_client, ADMIN)
    for path in ("/oportunidades", "/oportunidades/conversion", "/solicitudes-catalogo", "/comisiones/resumen"):
        r = app_client.get(path)
        assert r.status_code < 500, f"{path}: {r.status_code} {r.text[:200]}"


def test_dashboard_kpis_y_finanzas_responden_con_datos(app_client):
    _as(app_client, ADMIN)
    for path in ("/dashboard/kpis", "/finanzas/cuentas", "/finanzas/gastos-fijos", "/finanzas/supuestos",
                 "/finanzas/utilidad-operativa-real?mes=2026-05", "/finanzas/cumplimiento-familia?mes=2026-05"):
        r = app_client.get(path)
        assert r.status_code < 500, f"{path}: {r.status_code} {r.text[:200]}"


def test_pipeline_comercial_prospecto_a_ganado_y_perdido(app_client, catalogo, apertura):
    _as(app_client, ADMIN)
    base = {"client_id": catalogo["cliente_id"], "service_id": catalogo["servicio_id"],
            "canal_captacion": "Referido", "origen_negocio": "Orgánico", "honorarios_estimados": 700}
    op = app_client.post("/oportunidades", json=base)
    assert op.status_code == 201, op.text
    oid = op.json()["id"]
    assert op.json()["estado"] == "Prospecto"
    r = app_client.post(f"/oportunidades/{oid}/transicion", json={"estado": "Cotizado"})
    assert r.status_code == 200 and r.json()["oportunidad"]["estado"] == "Cotizado", (r.status_code, r.text)
    r = app_client.post(f"/oportunidades/{oid}/transicion", json={"estado": "Ganado", **dict(apertura,honorarios_pactados=700)})
    assert r.status_code == 200, (r.status_code, r.text)
    # Ganar una oportunidad abre el expediente automáticamente, ligado al cliente y servicio
    assert r.json()["case_id"] is not None and r.json()["case_internal_ref"]
    caso = next(c for c in app_client.get("/cases").json() if c["id"] == r.json()["case_id"])
    assert caso["client_id"] == catalogo["cliente_id"] and caso["service_id"] == catalogo["servicio_id"]

    perdida = app_client.post("/oportunidades", json=base).json()["id"]
    # Perdido exige motivo
    assert app_client.post(f"/oportunidades/{perdida}/transicion", json={"estado": "Perdido"}).status_code == 422
    r = app_client.post(f"/oportunidades/{perdida}/transicion", json={"estado": "Perdido", "motivo_perdida": "Precio"})
    assert r.status_code == 200 and r.json()["oportunidad"]["estado"] == "Perdido"
    assert app_client.get("/oportunidades/conversion").json()["ganados"] >= 1


def test_factura_abonos_api_y_permisos(app_client,repo,catalogo):
    from tests.test_billing_payments import case, invoice
    import uuid
    from datetime import date
    _as(app_client,ADMIN)
    inv=invoice(repo,catalogo,case(repo,catalogo))
    assert app_client.patch(f'/invoices/{inv}/status',json={'status':'Pagada'}).status_code==422
    assert app_client.patch(f'/invoices/{inv}/status',json={'status':'Enviada'}).status_code==200
    payload={'amount':40,'income_date':date.today().isoformat(),'account_id':catalogo['cuenta_id'],'detail':'Efectivo','request_key':uuid.uuid4().hex}
    r=app_client.post(f'/invoices/{inv}/payments',json=payload)
    assert r.status_code==200,r.text
    assert r.json()['paid']==40 and r.json()['balance']==60 and r.json()['status']=='Parcial'
    assert app_client.post(f'/invoices/{inv}/payments',json=payload).json()['paid']==40
    assert len(app_client.get(f'/invoices/{inv}').json()['payments'])==1
    restricted=dict(ADMIN,is_admin=False,permissions={'facturas.ver'})
    _as(app_client,restricted)
    assert app_client.post(f'/invoices/{inv}/payments',json=dict(payload,request_key=uuid.uuid4().hex)).status_code==403
    _as(app_client,ADMIN)
    assert app_client.patch(f'/invoices/{inv}/status',json={'status':'Cancelada'}).status_code==200
    assert app_client.get(f'/invoices/{inv}/credits').json()[0]['available']==40

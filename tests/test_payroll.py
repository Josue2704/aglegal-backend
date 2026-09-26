"""Repositorio de nómina: enlace Personal→cuenta contable, modo calculado vs manual,
unicidad de planilla mensual por persona, y edición con bitácora de auditoría."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


@pytest.fixture()
def cuenta_personal(repo, codigo_unico):
    now = now_iso()
    return repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-001", tipo="Egreso", grupo="Personal", nombre=f"Nómina {codigo_unico}",
        naturaleza="Fijo", centro_costo="Administración", created_at=now,
    )


@pytest.fixture()
def persona_con_cuenta(repo, codigo_unico, cuenta_personal):
    now = now_iso()
    return repo.create_persona(
        persona=f"Colaborador {codigo_unico}", cargo="Asistente", monto_mensual_text="800",
        mes_inicio="2026-01", account_id=cuenta_personal, created_at=now,
    )


@pytest.fixture()
def payroll_config_vigente(repo):
    """La config sembrada en la migración v35 ya cubre 'hoy' en la mayoría de entornos de
    prueba, pero la creamos explícita aquí para no depender de la fecha del seed."""
    try:
        return repo.get_payroll_config_vigente()
    except ValueError:
        config_id = repo.create_payroll_config(
            vigente_desde="2020-01-01",
            isss_tasa_empleado=0.03, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
            afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )
        return next(r for r in repo.list_payroll_config_historial() if r["id"] == config_id)


def test_planilla_calculada_requiere_persona_del_catalogo(repo, payroll_config_vigente):
    with pytest.raises(ValueError, match="catálogo"):
        repo.create_payroll(
            period="2026-08", payment_date="2026-08-31", notes="", created_at=now_iso(),
            modo="calculado", salario_base_text="800",
        )


def test_planilla_calculada_requiere_cuenta_contable_enlazada(repo, codigo_unico, payroll_config_vigente):
    now = now_iso()
    persona_id = repo.create_persona(persona=f"Sin cuenta {codigo_unico}", mes_inicio="2026-01", created_at=now)
    with pytest.raises(ValueError, match="cuenta contable enlazada"):
        repo.create_payroll(
            period="2026-08", payment_date="2026-08-31", notes="", created_at=now,
            personal_id=persona_id, modo="calculado", salario_base_text="800",
        )


def test_planilla_calculada_persiste_el_desglose_completo(repo, persona_con_cuenta, payroll_config_vigente):
    payroll_id = repo.create_payroll(
        period="2026-08", payment_date="2026-08-31", notes="Agosto", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
        horas_extra_cantidad=5, bonificaciones_text="50",
    )
    row = repo.get_payroll(payroll_id)
    assert row["modo"] == "calculado"
    assert row["salario_base_cents"] == 80_000
    assert row["bonificaciones_cents"] == 5_000
    assert row["horas_extra_monto_cents"] > 0
    assert row["isss_empleado_cents"] > 0
    assert row["afp_empleado_cents"] > 0
    # El neto persistido en amount_cents debe coincidir con devengado - deducciones
    assert row["amount_cents"] == row["total_devengado_cents"] - row["total_descuentos_cents"]
    # Y debe haber creado el gasto espejo enlazado a la cuenta explícita de la persona
    assert row["expense_id"] is not None


def test_no_se_puede_duplicar_la_planilla_calculada_del_mismo_mes(repo, persona_con_cuenta, payroll_config_vigente):
    repo.create_payroll(
        period="2026-09", payment_date="2026-09-30", notes="", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
    )
    with pytest.raises(ValueError, match="Ya existe una planilla"):
        repo.create_payroll(
            period="2026-09", payment_date="2026-09-30", notes="", created_at=now_iso(),
            personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
        )


def test_pago_manual_no_bloquea_duplicados_del_mismo_mes(repo, persona_con_cuenta):
    """Un bono suelto sí puede repetirse en el mismo periodo — la unicidad solo aplica a
    la planilla mensual calculada."""
    repo.create_payroll(
        period="2026-10", payment_date="2026-10-15", notes="Bono 1", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="100",
    )
    payroll_id = repo.create_payroll(
        period="2026-10", payment_date="2026-10-20", notes="Bono 2", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="50",
    )
    assert repo.get_payroll(payroll_id)["amount_cents"] == 5_000


def test_editar_planilla_registra_bitacora_de_auditoria(repo, persona_con_cuenta):
    payroll_id = repo.create_payroll(
        period="2026-11", payment_date="2026-11-30", notes="Original", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="500",
    )
    repo.update_payroll(payroll_id, payment_date="2026-12-01", notes="Corregido", amount_text="550", username="tester")
    row = repo.get_payroll(payroll_id)
    assert row["amount_cents"] == 55_000
    assert row["payment_date"] == "2026-12-01"
    log = repo.list_payroll_audit_log(payroll_id)
    campos_cambiados = {entry["campo"] for entry in log}
    assert {"amount_cents", "payment_date", "notes"} <= campos_cambiados
    assert all(entry["username"] == "tester" for entry in log)


def test_config_de_nomina_es_versionada_y_no_se_edita(repo):
    config_id = repo.create_payroll_config(
        vigente_desde="2030-01-01",
        isss_tasa_empleado=0.03, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
        afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
        tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
        horas_jornada_mensual=240, created_at=now_iso(),
    )
    with pytest.raises(ValueError, match="Ya existe"):
        repo.create_payroll_config(
            vigente_desde="2030-01-01",
            isss_tasa_empleado=0.04, isss_tasa_patronal=0.08, isss_tope_cotizable_text="1200",
            afp_tasa_empleado=0.08, afp_tasa_patronal=0.09, afp_tope_cotizable_text="1200",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )
    vigente_futura = repo.get_payroll_config_vigente(fecha="2030-06-01")
    assert vigente_futura["id"] == config_id


def test_tasa_de_ley_fuera_de_rango_es_rechazada(repo):
    with pytest.raises(ValueError, match="tasa"):
        repo.create_payroll_config(
            vigente_desde="2031-01-01",
            isss_tasa_empleado=1.5, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
            afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )


def _calculated(repo, person, **extra):
    return repo.create_payroll(personal_id=person, period='2026-08', payment_date='2026-08-31',
        modo='calculado', salario_base_text='800', notes='', created_at=now_iso(), **extra)


def test_cash_moves_only_when_each_payroll_component_is_paid(repo, persona_con_cuenta):
    pid = _calculated(repo, persona_con_cuenta)
    p = repo.get_payroll(pid)
    assert p['cash_model'] == 'separado'
    assert repo.get_expense(p['expense_id'])['amount_cents'] == p['amount_cents']
    rows = [r for r in repo.list_payroll_obligations() if r['payroll_id'] == pid]
    assert {r['kind'] for r in rows} == {'ISSS','AFP','ISR'}
    assert p['amount_cents'] + sum(r['amount_cents'] for r in rows) == p['costo_empresa_cents']
    paid = []
    for r in rows:
        eid = repo.pay_payroll_obligation(r['id'], payment_date='2026-09-05', reference='Transferencia', actor='tester')
        # A retry cannot create a second expense.
        assert repo.pay_payroll_obligation(r['id'], payment_date='2026-09-05', reference='Transferencia', actor='tester') == eid
        e = repo.get_expense(eid)
        assert e['amount_cents'] == r['amount_cents'] and e['expense_date'] == '2026-09-05'
        assert e['account_id'] == repo.get_expense(p['expense_id'])['account_id']
        paid.append(eid)
    with pytest.raises(ValueError, match='obligaciones'):
        repo.delete_payroll(pid)
    with pytest.raises(ValueError, match='Nóminas'):
        repo.delete_expense(paid[0])
    for r, eid in zip(rows,paid):
        repo.reverse_payroll_obligation(r['id'],reason='Referencia incorrecta',actor='tester')
        assert repo.get_expense(eid) is None
    repo.delete_payroll(pid,username='tester')
    assert repo.get_expense(p['expense_id']) is None
    assert not [r for r in repo.list_payroll_obligations() if r['payroll_id'] == pid]
    assert repo.conn.execute("SELECT 1 FROM workflow_events WHERE entity_type='payroll' AND entity_id=%s AND event='Anulación'",(pid,)).fetchone()


def test_calculated_net_cannot_diverge_and_expense_cannot_be_edited_directly(repo, persona_con_cuenta):
    pid = _calculated(repo,persona_con_cuenta)
    p = repo.get_payroll(pid)
    with pytest.raises(ValueError, match='neto calculado'):
        repo.update_payroll(pid,payment_date='2026-08-31',notes='',amount_text='1',username='tester')
    with pytest.raises(ValueError, match='Nóminas'):
        repo.update_expense(p['expense_id'],detail='Cambio externo',amount_text='1',expense_date='2026-08-31',notes='')
    with pytest.raises(ValueError, match='Nóminas'):
        repo.delete_expense(p['expense_id'])
    assert repo.get_payroll(pid)['amount_cents'] == p['amount_cents']


def test_failed_payroll_insert_does_not_leave_an_orphan_expense(repo, persona_con_cuenta, monkeypatch):
    before = len(repo.list_expenses())
    execute = repo.conn.execute
    def fail(sql, params=()):
        if sql.startswith('INSERT INTO payrolls'):
            raise RuntimeError('simulated failure')
        return execute(sql,params)
    with monkeypatch.context() as patch:
        patch.setattr(repo.conn,'execute',fail)
        with pytest.raises(RuntimeError):
            _calculated(repo,persona_con_cuenta)
    assert len(repo.list_expenses()) == before
    assert not repo.conn.execute('SELECT 1 FROM payrolls WHERE personal_id=%s',(persona_con_cuenta,)).fetchone()


@pytest.mark.parametrize('period,payment_date,amount', [
    ('2026-99','2026-08-31','50'),('2026-08','2026-02-30','50'),
    ('2026-08','2026-08-31','0'),('2026-08','2026-08-31','-1'),
    ('2025-12','2026-08-31','50'),
])
def test_invalid_manual_payroll_cannot_write_expenses(repo,persona_con_cuenta,period,payment_date,amount):
    before=len(repo.list_expenses())
    with pytest.raises(ValueError):
        repo.create_payroll(personal_id=persona_con_cuenta,period=period,payment_date=payment_date,
                            notes='',created_at=now_iso(),amount_text=amount)
    assert len(repo.list_expenses()) == before


def test_preview_can_warn_but_negative_payment_cannot_be_saved(repo,persona_con_cuenta):
    before=len(repo.list_expenses())
    with pytest.raises(ValueError,match='negativo'):
        _calculated(repo,persona_con_cuenta,descuento_prestamos_text='900')
    assert len(repo.list_expenses()) == before


def test_concurrent_duplicate_payroll_leaves_exactly_one_expense(repo,persona_con_cuenta):
    from concurrent.futures import ThreadPoolExecutor
    from aglegal.db import connect
    from aglegal.repositories import Repository
    before=len(repo.list_expenses())
    def create():
        conn=connect()
        try:
            return _calculated(Repository(conn),persona_con_cuenta)
        except ValueError as exc:
            assert 'Ya existe' in str(exc)
            return None
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:create(),range(2)))
    assert sum(r is not None for r in results)==1
    assert len(repo.list_expenses()) == before+1


def test_payroll_permissions_are_independent_of_finance_and_config_roundtrips(repo,persona_con_cuenta):
    from fastapi.testclient import TestClient
    from api.app.main import app
    from api.app.deps import get_current_user
    user=dict(id=1,username='payroll_only',role='Nóminas',is_admin=False,
              permissions={'nominas.ver','nominas.crear','nominas.editar'})
    app.dependency_overrides[get_current_user]=lambda:user
    try:
        with TestClient(app) as client:
            response=client.get('/payroll/personal')
            assert response.status_code==200
            assert any(r['id']==persona_con_cuenta for r in response.json())
            assert client.get('/finanzas/personal').status_code==403
            assert client.get('/payroll/obligaciones').status_code==200
            cfg=client.get('/payroll/config/vigente').json()
            assert cfg['tramos_renta'][0]['hasta']==550
            assert cfg['tramos_renta'][1]['cuota_fija']==17.67
            saved=client.post('/payroll/config',json={**cfg,'vigente_desde':'2035-01-01'})
            assert saved.status_code==201,saved.text
            assert saved.json()['tramos_renta']==cfg['tramos_renta']
            user['permissions']={'nominas.ver'}
            assert client.post('/payroll',json=dict(employee_name='No autorizado',period='2026-08',payment_date='2026-08-31',amount=10)).status_code==403
            assert client.post('/payroll/obligaciones/1/pagar',json=dict(payment_date='2026-08-31',reference='No autorizado')).status_code==403
            assert client.post('/payroll/config',json={**cfg,'vigente_desde':'2036-01-01'}).status_code==403
    finally:
        app.dependency_overrides.clear()


def test_manual_external_person_has_explicit_account(repo,cuenta_personal):
    pid=repo.create_payroll(employee_name='Colaborador externo',account_id=cuenta_personal,
        amount_text='75.50',period='2026-08',payment_date='2026-08-31',notes='Ajuste calculado',created_at=now_iso())
    row=repo.get_payroll(pid)
    assert row['personal_id'] is None
    assert repo.get_expense(row['expense_id'])['account_id']==cuenta_personal
    assert row['amount_cents']==7550


def test_payroll_neither_settles_nor_recreates_commissions(repo,catalogo,cuenta_personal):
    import uuid
    from datetime import date
    person=catalogo['persona_id']
    repo.conn.execute('UPDATE personal SET account_id=%s WHERE id=%s',(cuenta_personal,person));repo.conn.commit()
    month=date.today().isoformat()[:7]
    case=repo.create_case(client_id=catalogo['cliente_id'],title='Nómina y comisión',status='Abierto',priority='Media',
        opened_at=month+'-01',created_at=now_iso(),honorarios_contratados_text='1000',service_id=catalogo['servicio_id'])
    repo.set_negocio_originadores(case,originadores=[dict(personal_id=person,porcentaje_participacion=100,tipo_origen='Cliente nuevo')],created_at=now_iso())
    repo.create_income(client_id=catalogo['cliente_id'],case_id=case,amount_text='500',income_date=month+'-01',
                       created_at=now_iso(),account_id=catalogo['cuenta_id'])
    commission=repo.list_comisiones(case_id=case)[0]
    pid=_calculated(repo,person)
    assert repo.get_comision(commission['id'])['estado']=='Calculada'
    repo.approve_commission(commission['id'],eligible=True,evidence='Origen comprobado',actor='tester')
    settled=repo.settle_commissions(commission_ids=[commission['id']],payment_date=date.today().isoformat(),
        reference='Pago separado',account_id=cuenta_personal,request_key=uuid.uuid4().hex,actor='tester')
    assert settled['expense_id'] != repo.get_payroll(pid)['expense_id']
    repo.delete_payroll(pid)
    assert repo.get_comision(commission['id'])['estado']=='Pagada'
    assert repo.get_expense(settled['expense_id']) is not None

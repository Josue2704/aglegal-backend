from datetime import date
from concurrent.futures import ThreadPoolExecutor
import uuid
import pytest
from aglegal.db import now_iso, connect
from aglegal.repositories import Repository

MONTH = date.today().isoformat()[:7]


def setup_case(repo, cat):
    cid=repo.create_case(client_id=cat['cliente_id'], title='Control financiero',status='Abierto',priority='Media',
        opened_at=MONTH+'-01',created_at=now_iso(),service_id=cat['servicio_id'],honorarios_contratados_text='3000',
        mes_cobro_esperado=MONTH,probabilidad_cobro=0.4)
    repo.set_negocio_originadores(cid,originadores=[dict(personal_id=cat['persona_id'],porcentaje_participacion=100,tipo_origen='Cliente nuevo')],created_at=now_iso())
    return cid


def receipt(repo,cat,cid,amount,day='01'):
    return repo.create_income(client_id=cat['cliente_id'],case_id=cid,amount_text=str(amount),
        income_date=MONTH+'-'+day,created_at=now_iso(),account_id=cat['cuenta_id'])


def expense_account(repo,cat):
    return repo.create_cuenta(account_code=repo.get_cuenta(cat['cuenta_id'])['account_code'].replace('ING-','EGR-'),tipo='Egreso',grupo='Gastos',
        nombre='Comisiones y costos',naturaleza='Operativo',centro_costo='Administración',created_at=now_iso())


def direct_cost(repo,cat,cid,account,amount):
    return repo.create_cost(client_id=cat['cliente_id'],case_id=cid,detail='Costo real',amount_text=str(amount),
        cost_date=MONTH+'-01',notes='',created_at=now_iso(),account_id=account)


def current(repo,cid):
    return [c for c in repo.list_comisiones(case_id=cid) if c['estado']!='Anulada' and c['ajusta_a_commission_id'] is None]


def test_first_recover_costs_then_commission(repo,catalogo):
    cid=setup_case(repo,catalogo); acct=expense_account(repo,catalogo)
    direct_cost(repo,catalogo,cid,acct,200)
    receipt(repo,catalogo,cid,100)
    assert sum(c['comision_cents'] for c in current(repo,cid))==0
    receipt(repo,catalogo,cid,400,'02')
    assert sum(c['base_utilidad_directa_cents'] for c in current(repo,cid))==30000
    assert sum(c['comision_cents'] for c in current(repo,cid))==3000
    receipt(repo,catalogo,cid,500,'03')
    assert sum(c['comision_cents'] for c in current(repo,cid))==8000


def test_late_cost_invalidates_approval_and_recomputes(repo,catalogo):
    cid=setup_case(repo,catalogo); receipt(repo,catalogo,cid,500)
    original=current(repo,cid)[0]
    repo.approve_commission(original['id'], evidence='Negocio originado y aceptación documentada',eligible=True,actor='admin')
    direct_cost(repo,catalogo,cid,expense_account(repo,catalogo),200)
    assert repo.get_comision(original['id'])['estado']=='Anulada'
    replacement=current(repo,cid)[0]
    assert replacement['estado']=='Calculada' and replacement['comision_cents']==3000


def test_settlement_requires_approval_is_idempotent_and_cash_once(repo,catalogo):
    cid=setup_case(repo,catalogo); receipt(repo,catalogo,cid,500)
    c=current(repo,cid)[0]; acct=expense_account(repo,catalogo)
    args=dict(commission_ids=[c['id']],payment_date=date.today().isoformat(),reference='Transferencia comprobada',
        account_id=acct,request_key=uuid.uuid4().hex,actor='admin')
    with pytest.raises(ValueError,match='aprobadas'):repo.settle_commissions(**args)
    with pytest.raises(ValueError,match='Documenta'):repo.approve_commission(c['id'],evidence='',eligible=True,actor='admin')
    repo.approve_commission(c['id'],evidence='Origen y aceptación verificados',eligible=True,actor='admin')
    first=repo.settle_commissions(**args)
    assert repo.settle_commissions(**args)['id']==first['id']
    assert repo.get_expense(first['expense_id'])['amount_cents']==5000
    assert repo.get_comision(c['id'])['estado']=='Pagada'
    with pytest.raises(ValueError):repo.settle_commissions(**dict(args,request_key=uuid.uuid4().hex))
    with pytest.raises(ValueError):repo.delete_expense(first['expense_id'])
    with pytest.raises(ValueError):repo.update_expense(first['expense_id'],detail='Cambiar',amount_text='1',expense_date=date.today().isoformat(),notes='',account_id=acct)


def test_noneligible_does_not_leave_payable_accrual(repo,catalogo):
    cid=setup_case(repo,catalogo); receipt(repo,catalogo,cid,500)
    c=current(repo,cid)[0]
    repo.approve_commission(c['id'],evidence='Solo seguimiento administrativo',eligible=False,actor='admin')
    assert repo.get_comision(c['id'])['estado']=='Anulada'
    assert sum(c['comision_cents'] for c in repo.list_comisiones(case_id=cid))==0


def test_paid_correction_keeps_expense_and_creates_future_credit(repo,catalogo):
    cid=setup_case(repo,catalogo); receipt(repo,catalogo,cid,500)
    c=current(repo,cid)[0]; acct=expense_account(repo,catalogo)
    repo.approve_commission(c['id'],evidence='Elegible',eligible=True,actor='admin')
    payment=repo.settle_commissions(commission_ids=[c['id']],payment_date=date.today().isoformat(),reference='TX',account_id=acct,request_key=uuid.uuid4().hex,actor='admin')
    direct_cost(repo,catalogo,cid,acct,200)
    adjustment=next(c for c in repo.list_comisiones(case_id=cid) if c['ajusta_a_commission_id'])
    assert adjustment['mes_reconocimiento']>MONTH
    assert adjustment['estado']=='Calculada' and adjustment['comision_cents']==-5000
    assert repo.get_expense(payment['expense_id'])['amount_cents']==5000
    replacement=next(c for c in current(repo,cid) if c['estado']=='Calculada')
    repo.approve_commission(replacement['id'],evidence='Costo actualizado',eligible=True,actor='admin')
    with pytest.raises(ValueError,match='ajustes pendientes'):
        repo.settle_commissions(commission_ids=[replacement['id']],payment_date=date.today().isoformat(),reference='TX2',account_id=acct,request_key=uuid.uuid4().hex,actor='admin')


def test_concurrent_payment_only_one_expense(repo,catalogo):
    cid=setup_case(repo,catalogo); receipt(repo,catalogo,cid,500); c=current(repo,cid)[0]
    repo.approve_commission(c['id'],evidence='Elegible',eligible=True,actor='admin')
    args=dict(commission_ids=[c['id']],payment_date=date.today().isoformat(),reference='TX',account_id=expense_account(repo,catalogo),request_key=uuid.uuid4().hex,actor='admin')
    def pay(_):
        conn=connect()
        try:return Repository(conn).settle_commissions(**args)['id']
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool: ids=list(pool.map(pay,range(2)))
    assert ids[0]==ids[1]


def test_probability_and_projection_are_distinct(repo,catalogo):
    cid=setup_case(repo,catalogo)
    row=next(r for r in repo.cartera_pendiente_ponderada(mes=MONTH)['casos'] if r['id']==cid)
    assert row['probabilidad_cobro']==0.4 and row['saldo_ponderado_cents']==120000
    d=repo.proyeccion_cierre_mes(mes=MONTH)
    assert d['proyeccion_comercial_cents']==d['meta_ingresos_cents']+d['cartera_ponderada_mes_cents']
    assert d['proyeccion_cierre_cents']==d['cobrado_mes_cents']+d['cartera_ponderada_mes_cents']


@pytest.mark.parametrize('probability',[float('nan'),float('inf'),-0.1,1.1])
def test_invalid_probability_rolls_back(repo,catalogo,probability):
    before=repo.conn.execute('SELECT count(*) AS n FROM cases').fetchone()['n']
    with pytest.raises(ValueError):repo.create_case(client_id=catalogo['cliente_id'],title='Invalid',status='Abierto',priority='Media',opened_at=MONTH+'-01',created_at=now_iso(),probabilidad_cobro=probability)
    assert repo.conn.execute('SELECT count(*) AS n FROM cases').fetchone()['n']==before


def test_inactive_service_cannot_be_won(repo,catalogo,apertura):
    op=repo.create_oportunidad(client_id=catalogo['cliente_id'],service_id=catalogo['servicio_id'],canal_captacion='Referido',origen_negocio='Orgánico',created_at=now_iso())
    repo.conn.execute("UPDATE servicios SET estado='Inactivo' WHERE id=%s",(catalogo['servicio_id'],));repo.conn.commit()
    with pytest.raises(ValueError,match='activo'):repo.transition_oportunidad(op,nuevo_estado='Ganado',**apertura)
    assert repo.get_oportunidad(op)['case_id'] is None


def test_opening_needs_collection_plan(repo,catalogo,apertura):
    op=repo.create_oportunidad(client_id=catalogo['cliente_id'],service_id=catalogo['servicio_id'],canal_captacion='Referido',origen_negocio='Orgánico',created_at=now_iso())
    with pytest.raises(ValueError,match='mes esperado'):repo.transition_oportunidad(op,nuevo_estado='Ganado',**dict(apertura,mes_cobro_esperado=None))
    assert repo.get_oportunidad(op)['case_id'] is None


def test_backdated_receipt_and_deletion_reallocate_recovered_costs(repo,catalogo):
    cid=setup_case(repo,catalogo); acct=expense_account(repo,catalogo)
    direct_cost(repo,catalogo,cid,acct,200)
    later=receipt(repo,catalogo,cid,400,'10')
    earlier=receipt(repo,catalogo,cid,100,'02')
    assert sum(c['comision_cents'] for c in repo.list_comisiones(case_id=cid))==3000
    assert sum(c['base_utilidad_directa_cents'] for c in current(repo,cid) if c['income_id']==later)==30000
    repo.delete_income(earlier)
    assert sum(c['comision_cents'] for c in repo.list_comisiones(case_id=cid))==2000


def test_compensate_paid_adjustment_and_new_accrual_without_double_cash(repo,catalogo,monkeypatch):
    from datetime import timedelta
    from aglegal import financial_workflow
    cid=setup_case(repo,catalogo); acct=expense_account(repo,catalogo)
    receipt(repo,catalogo,cid,500)
    c=current(repo,cid)[0]
    repo.approve_commission(c['id'],evidence='Negocio verificado',eligible=True,actor='admin')
    first=repo.settle_commissions(commission_ids=[c['id']],payment_date=date.today().isoformat(),reference='TX1',account_id=acct,request_key=uuid.uuid4().hex,actor='admin')
    direct_cost(repo,catalogo,cid,acct,200)
    receipt(repo,catalogo,cid,500,'02')
    pending=[c for c in repo.list_comisiones(case_id=cid) if c['estado']=='Calculada']
    assert sum(c['comision_cents'] for c in pending)==3000
    for c in pending:repo.approve_commission(c['id'],evidence='Ajuste y nueva utilidad revisados',eligible=True,actor='admin')
    next_month=(date.today().replace(day=28)+timedelta(days=4)).replace(day=1)
    class NextDate(date):
        @classmethod
        def today(cls):return next_month
    monkeypatch.setattr(financial_workflow,'date',NextDate)
    second=repo.settle_commissions(commission_ids=[c['id'] for c in pending],payment_date=next_month.isoformat(),reference='TX2',account_id=acct,request_key=uuid.uuid4().hex,actor='admin')
    assert first['amount_cents']+second['amount_cents']==8000
    assert all(repo.get_comision(c['id'])['estado']=='Pagada' for c in pending)


def test_days_use_active_applications_and_ignore_cancelled_reference(repo,catalogo):
    cid=setup_case(repo,catalogo)
    def invoice(day):
        inv=repo.create_invoice(client_id=catalogo['cliente_id'],case_id=cid,invoice_number=uuid.uuid4().hex,
            invoice_date='2044-01-'+day,due_date=None,notes='',firm_name=None,firm_phone=None,firm_email=None,
            firm_address=None,firm_tax_id=None,created_at=now_iso(),items=[dict(description='Honorarios',quantity=1,unit_price=100)])
        repo.update_invoice_status(inv,'Enviada');return inv
    a=invoice('01'); b=invoice('11')
    iid=repo.create_income(client_id=catalogo['cliente_id'],case_id=cid,amount_text='200',income_date='2044-01-21',account_id=catalogo['cuenta_id'],created_at=now_iso())
    for inv in [a,b]:repo.register_invoice_payment(inv,amount=100,income_id=iid,request_key=uuid.uuid4().hex)
    result=repo.dias_promedio_cobro(desde='2044-01',hasta='2044-01')
    assert result['cobros_medidos']==2 and result['promedio_dias']==15
    repo.update_invoice_status(a,'Cancelada')
    result=repo.dias_promedio_cobro(desde='2044-01',hasta='2044-01')
    assert result['cobros_medidos']==1 and result['promedio_dias']==10


def test_conversion_filters_month_origin_service(repo,catalogo,apertura):
    op=repo.create_oportunidad(client_id=catalogo['cliente_id'],service_id=catalogo['servicio_id'],canal_captacion='Referido',origen_negocio='Orgánico',created_at=now_iso())
    repo.transition_oportunidad(op,nuevo_estado='Ganado',**apertura)
    assert repo.conversion_comercial(mes=MONTH,origen='Orgánico',service_id=catalogo['servicio_id'])['ganados']==1
    assert repo.conversion_comercial(mes='2000-01',service_id=catalogo['servicio_id'])['ganados']==0
    assert repo.conversion_comercial(mes=MONTH,origen='Andrea',service_id=catalogo['servicio_id'])['ganados']==0


def test_channel_report_keeps_unattributed_income(repo,catalogo,apertura):
    op=repo.create_oportunidad(client_id=catalogo['cliente_id'],service_id=catalogo['servicio_id'],canal_captacion='Referido',origen_negocio='Orgánico',created_at=now_iso())
    cid=repo.transition_oportunidad(op,nuevo_estado='Ganado',**apertura)
    before=sum(r['ingresos_cents'] for r in repo.ingresos_por_origen(desde=MONTH,hasta=MONTH,agrupar_por='canal'))
    receipt(repo,catalogo,cid,100)
    after=repo.ingresos_por_origen(desde=MONTH,hasta=MONTH,agrupar_por='canal')
    assert sum(r['ingresos_cents'] for r in after)-before==10000
    assert any(r['origen']=='Referido' for r in after)

import pytest
import uuid
from datetime import date
from tests.test_financial_workflow import setup_case, receipt, expense_account, direct_cost, MONTH
from tests.test_api_modulos import app_client, _as, ADMIN, SIN_PERMISOS

def test_monthly_tiers_after_cost_in_another_case(repo, catalogo):
    a=setup_case(repo,catalogo);b=setup_case(repo,catalogo)
    receipt(repo,catalogo,a,500)
    receipt(repo,catalogo,b,1000,'02')
    direct_cost(repo,catalogo,a,expense_account(repo,catalogo),200)
    actual=sum(c['comision_cents'] for c in repo.list_comisiones(personal_id=catalogo['persona_id'],mes=MONTH))
    expected=repo._formula_comision_tramos(130000)
    assert actual==expected, f'Monthly total: {actual/100}; expected: {expected/100}'

def test_summary_excludes_replaced_commission_bases(repo,catalogo):
    a=setup_case(repo,catalogo);receipt(repo,catalogo,a,500)
    direct_cost(repo,catalogo,a,expense_account(repo,catalogo),200)
    summary=next(r for r in repo.resumen_comisiones_mes(MONTH) if r['personal_id']==catalogo['persona_id'])
    assert summary['total_utilidad_directa_cents']==30000


def test_summary_preserves_paid_base_when_adjustment_belongs_to_next_period(repo,catalogo):
    cid=setup_case(repo,catalogo);receipt(repo,catalogo,cid,500)
    account=expense_account(repo,catalogo)
    commission=repo.list_comisiones(case_id=cid)[0]
    repo.approve_commission(commission['id'],evidence='Origen revisado',eligible=True,actor='admin')
    repo.settle_commissions(commission_ids=[commission['id']],payment_date=date.today().isoformat(),
        reference='Pago probado',account_id=account,request_key=uuid.uuid4().hex,actor='admin')
    direct_cost(repo,catalogo,cid,account,200)
    summary=next(r for r in repo.resumen_comisiones_mes(MONTH) if r['personal_id']==catalogo['persona_id'])
    assert summary['total_utilidad_directa_cents']==50000
    assert summary['total_comision_cents']==5000


@pytest.mark.parametrize('path', ['/clients', '/cases', '/cases/tasks', '/attachments?entity_type=case&entity_id=1'])
def test_operational_reads_require_module_permission(app_client, path):
    _as(app_client, SIN_PERMISOS)
    try:
        assert app_client.get(path).status_code == 403
    finally:
        _as(app_client, ADMIN)


def test_positive_balance_remains_in_aging_even_if_marked_paid(repo, catalogo):
    cid=setup_case(repo,catalogo)
    repo.update_case(cid,title='Saldo no cobrado',status='Abierto',priority='Media',opened_at='2001-01-01',
        closed_at=None,service_id=catalogo['servicio_id'],honorarios_contratados_text='3000',
        mes_cobro_esperado='2001-01',probabilidad_cobro=.7,estado_cobro='Cobrado')
    assert any(r['case_id']==cid for r in repo.aging_cartera()['casos'])
    assert any(r['id']==cid for r in repo.dashboard_alerts()['overdue_billing'])

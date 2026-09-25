"""Facturas, pagos y anticipos sin duplicar ni borrar caja."""
from datetime import date
import uuid
import pytest
from aglegal.db import now_iso
from api.app.schemas.invoice import UnbilledTask, InvoiceItemIn


def case(repo, cat):
    return repo.create_case(client_id=cat['cliente_id'], title='Pagos', service_id=cat['servicio_id'],
        honorarios_contratados_text='1000', status='Abierto', priority='Media', opened_at='2026-01-01', created_at=now_iso())


def invoice(repo, cat, cid, items=None):
    return repo.create_invoice(client_id=cat['cliente_id'], case_id=cid, invoice_number='TEST-'+uuid.uuid4().hex,
        invoice_date='2026-01-01', due_date=None, notes='', firm_name=None, firm_phone=None, firm_email=None,
        firm_address=None, firm_tax_id=None, created_at=now_iso(),
        items=items or [dict(description='Honorarios', quantity=1, unit_price=100)])


def pay(repo, cat, inv, amount):
    return repo.register_invoice_payment(inv, amount=amount, income_date=date.today().isoformat(),
        account_id=cat['cuenta_id'], request_key=uuid.uuid4().hex)


def task(repo, cid, ready=True):
    return repo.create_case_task(case_id=cid, title='Extra', due_date=None, created_at=now_iso(),
        monto_adicional_text='120', autorizado_por='Cliente', cobro_anticipado=ready)


def line(tid):
    return dict(description='Extra', quantity=1, unit_price=120, entity_type='case_task', entity_id=tid)


def test_partial_payment_and_final(repo, catalogo):
    inv=invoice(repo,catalogo,case(repo,catalogo))
    with pytest.raises(ValueError): pay(repo,catalogo,inv,10)
    repo.update_invoice_status(inv,'Enviada')
    iid=pay(repo,catalogo,inv,40)
    assert repo.get_invoice(inv)['status']=='Parcial'
    assert repo.get_invoice(inv)['balance_cents']==6000
    assert repo.get_income(iid)['income_date']==date.today().isoformat()
    pay(repo,catalogo,inv,60)
    assert repo.get_invoice(inv)['status']=='Pagada'
    with pytest.raises(ValueError): pay(repo,catalogo,inv,1)


def test_idempotency(repo,catalogo):
    inv=invoice(repo,catalogo,case(repo,catalogo)); repo.update_invoice_status(inv,'Enviada')
    args=dict(amount=40,income_date=date.today().isoformat(),account_id=catalogo['cuenta_id'],request_key=uuid.uuid4().hex)
    first=repo.register_invoice_payment(inv,**args)
    assert repo.register_invoice_payment(inv,**args)==first
    assert len(repo.list_invoice_payments(inv))==1
    with pytest.raises(ValueError): repo.register_invoice_payment(inv,**dict(args,amount=41))


def test_cancel_preserves_cash_and_credit(repo,catalogo):
    cid=case(repo,catalogo); inv=invoice(repo,catalogo,cid); repo.update_invoice_status(inv,'Enviada')
    iid=pay(repo,catalogo,inv,60)
    repo.update_invoice_status(inv,'Cancelada')
    assert repo.get_income(iid)['amount_cents']==6000
    assert repo.list_invoice_payments(inv)[0]['released_at']
    replacement=invoice(repo,catalogo,cid);repo.update_invoice_status(replacement,'Enviada')
    assert repo.available_invoice_credits(replacement)[0]['available']==60
    repo.register_invoice_payment(replacement,amount=60,income_id=iid,request_key=uuid.uuid4().hex)
    assert repo.get_invoice(replacement)['balance_cents']==4000
    assert not repo.available_invoice_credits(replacement)
    with pytest.raises(ValueError):repo.delete_income(iid)
    with pytest.raises(ValueError):repo.delete_invoice(inv)


def test_advance_applied_without_new_cash(repo,catalogo):
    cid=case(repo,catalogo)
    iid=repo.create_income(amount_text='200',income_date='2026-01-01',created_at=now_iso(),
        client_id=catalogo['cliente_id'],case_id=cid,account_id=catalogo['cuenta_id'])
    for _ in range(2):
        inv=invoice(repo,catalogo,cid);repo.update_invoice_status(inv,'Enviada')
        repo.register_invoice_payment(inv,amount=100,income_id=iid,request_key=uuid.uuid4().hex)
        assert repo.get_invoice(inv)['status']=='Pagada'
    assert len([i for i in repo.list_incomes() if i['case_id']==cid])==1


def test_extra_eligibility_price_and_duplicate(repo,catalogo):
    cid=case(repo,catalogo);tid=task(repo,cid,False)
    assert not repo.get_unbilled_items(catalogo['cliente_id'],cid)['tasks']
    repo.set_case_task_done(tid,True,"Trabajo concluido")
    wire=UnbilledTask(**repo.get_unbilled_items(catalogo['cliente_id'],cid)['tasks'][0]).model_dump()
    assert wire['monto_adicional_cents']==12000
    with pytest.raises(ValueError,match='repetirse'):invoice(repo,catalogo,cid,[line(tid),line(tid)])
    with pytest.raises(ValueError,match='precio'):invoice(repo,catalogo,cid,[dict(line(tid),unit_price=10)])
    inv=invoice(repo,catalogo,cid,[line(tid)]);repo.update_invoice_status(inv,'Cancelada')
    assert repo.get_unbilled_items(catalogo['cliente_id'],cid)['tasks'][0]['id']==tid


def test_reimbursement_keeps_net(repo,catalogo,codigo_unico):
    cid=case(repo,catalogo)
    account=repo.create_cuenta(account_code=f'EGR-{codigo_unico}-001',tipo='Egreso',grupo='Gastos',
        nombre='Gasto prueba',naturaleza='Variable',centro_costo='Operación jurídica',created_at=now_iso())
    cost=repo.create_cost(client_id=catalogo['cliente_id'],case_id=cid,detail='Tasa',amount_text='25',
        monto_reembolsable_text='25',cost_date='2026-01-01',notes='',created_at=now_iso(),account_id=account)
    repo.create_cost(client_id=catalogo['cliente_id'],case_id=cid,detail='Interno',amount_text='10',
        cost_date='2026-01-01',notes='',created_at=now_iso(),account_id=account)
    assert len(repo.get_unbilled_items(catalogo['cliente_id'],cid)['costs'])==1
    inv=invoice(repo,catalogo,cid,[dict(description='Honorario',quantity=1,unit_price=120),
        dict(description='Reembolso',quantity=1,unit_price=25,entity_type='cost',entity_id=cost)])
    repo.update_invoice_status(inv,'Enviada')
    incomes=[repo.get_income(pay(repo,catalogo,inv,amount)) for amount in (60,85)]
    assert sum(i['monto_reembolsable_cents'] for i in incomes)==2500
    assert sum(i['monto_neto_operativo_cents'] for i in incomes)==12000
    assert repo.get_invoice(inv)['paid_cents']==14500


def test_small_payment_after_fee_only_advance(repo,catalogo,codigo_unico):
    cid=case(repo,catalogo)
    account=repo.create_cuenta(account_code=f'EGR-{codigo_unico}-002',tipo='Egreso',grupo='Gastos',
        nombre='Tasa prueba',naturaleza='Variable',centro_costo='Operación jurídica',created_at=now_iso())
    cost=repo.create_cost(client_id=catalogo['cliente_id'],case_id=cid,detail='Tasa',amount_text='25',
        monto_reembolsable_text='25',cost_date='2026-01-01',notes='',created_at=now_iso(),account_id=account)
    inv=invoice(repo,catalogo,cid,[dict(description='Honorarios',quantity=1,unit_price=120),
        dict(description='Reembolso',quantity=1,unit_price=25,entity_type='cost',entity_id=cost)])
    repo.update_invoice_status(inv,'Enviada')
    advance=repo.create_income(amount_text='120',income_date='2026-01-01',created_at=now_iso(),
        client_id=catalogo['cliente_id'],case_id=cid,account_id=catalogo['cuenta_id'])
    repo.register_invoice_payment(inv,amount=120,income_id=advance,request_key=uuid.uuid4().hex)
    for amount in (1,24):
        received=repo.get_income(pay(repo,catalogo,inv,amount))
        assert received['monto_reembolsable_cents']==amount*100
        assert received['monto_neto_operativo_cents']==0
    assert repo.get_invoice(inv)['status']=='Pagada'
    assert not repo.get_invoice(inv)['needs_review']


def test_removing_draft_item_releases_it(repo,catalogo):
    cid=case(repo,catalogo);tid=task(repo,cid)
    inv=invoice(repo,catalogo,cid,[line(tid)]);row=repo.get_invoice(inv)
    repo.update_invoice(inv,invoice_number=row['invoice_number'],invoice_date=row['invoice_date'],due_date=None,status='Borrador',
        notes='',firm_name=None,firm_phone=None,firm_email=None,firm_address=None,firm_tax_id=None,created_at=now_iso(),
        items=[dict(description='Base',quantity=1,unit_price=100)])
    assert repo.get_unbilled_items(catalogo['cliente_id'],cid)['tasks'][0]['id']==tid


def test_wrong_client_overbilling_and_negative(repo,catalogo):
    cid=case(repo,catalogo)
    with pytest.raises(ValueError,match='[Cc]liente'):invoice(repo,dict(catalogo,cliente_id=-1),cid)
    with pytest.raises(ValueError,match='superan'):
        invoice(repo,catalogo,cid,[dict(description='Exceso',quantity=1,unit_price=1001)])
    with pytest.raises(ValueError):InvoiceItemIn(description='Negativo',unit_price=-1)


def test_invalid_payment_atomic(repo,catalogo):
    cid=case(repo,catalogo);inv=invoice(repo,catalogo,cid);repo.update_invoice_status(inv,'Enviada')
    with pytest.raises(ValueError):
        repo.register_invoice_payment(inv,amount=100,income_date=date.today().isoformat(),account_id=None,request_key=uuid.uuid4().hex)
    assert repo.get_invoice(inv)['status']=='Enviada'
    assert not repo.list_invoice_payments(inv)
    assert not [i for i in repo.list_incomes() if i['case_id']==cid]
    with pytest.raises(ValueError):repo.update_invoice_status(inv,'Pagada')


def test_concurrent_reservation_and_payments(repo,catalogo):
    from concurrent.futures import ThreadPoolExecutor
    from aglegal.db import connect
    from aglegal.repositories import Repository
    cid=case(repo,catalogo);tid=task(repo,cid)
    def reserve(_):
        conn=connect()
        try:
            return invoice(Repository(conn),catalogo,cid,[line(tid)])
        except ValueError:
            return None
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(reserve,range(2)))
    assert sum(r is not None for r in results)==1
    inv=next(r for r in results if r)
    repo.update_invoice_status(inv,'Enviada')
    def receive(_):
        conn=connect()
        try:
            return pay(Repository(conn),catalogo,inv,80)
        except ValueError:
            return None
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(receive,range(2)))
    assert sum(r is not None for r in results)==1
    assert repo.get_invoice(inv)['paid_cents']==8000


def test_legacy_migration_preserves_cash_and_marks_missing_payments(repo,catalogo):
    from aglegal.db import _migrate
    cid=case(repo,catalogo);inv=invoice(repo,catalogo,cid)
    iid=repo.create_income(amount_text='40',income_date='2026-01-01',created_at=now_iso(),
        client_id=catalogo['cliente_id'],case_id=cid,account_id=catalogo['cuenta_id'])
    repo.conn.execute('UPDATE incomes SET invoice_id=%s WHERE id=%s',(inv,iid))
    repo.conn.execute("UPDATE invoices SET status='Pagada' WHERE id=%s",(inv,))
    repo.conn.execute("UPDATE meta SET value='44' WHERE key='schema_version'")
    _migrate(repo.conn);repo.conn.commit()
    assert repo.get_income(iid)['amount_cents']==4000
    assert repo.get_invoice(inv)['paid_cents']==4000
    assert repo.get_invoice(inv)['needs_review']
    assert len(repo.list_invoice_payments(inv))==1
    _migrate(repo.conn);repo.conn.commit()
    assert len(repo.list_invoice_payments(inv))==1


def test_issued_invoice_cannot_be_edited(repo,catalogo):
    inv=invoice(repo,catalogo,case(repo,catalogo));repo.update_invoice_status(inv,'Enviada')
    with pytest.raises(ValueError,match='Solo se pueden editar'):
        repo.update_invoice(inv,invoice_number='Changed',invoice_date='2026-01-01',due_date=None,status='Enviada',
            notes='',firm_name=None,firm_phone=None,firm_email=None,firm_address=None,firm_tax_id=None,created_at=now_iso(),
            items=[dict(description='New total',quantity=1,unit_price=1)])
    assert repo.get_invoice(inv)['total_cents']==10000


def test_rounding_and_sequence_are_consistent(repo,catalogo):
    cid=case(repo,catalogo)
    inv=invoice(repo,catalogo,cid,[dict(description='Fracción',quantity=3,unit_price=0.335)])
    row=repo.get_invoice_items(inv)[0]
    assert row['unit_price_cents']==34 and row['subtotal_cents']==102
    assert repo.get_invoice(inv)['total_cents']==102
    first=repo.next_invoice_number();repo.delete_invoice(inv)
    second=repo.next_invoice_number()
    assert int(second.split('-')[1])>int(first.split('-')[1])

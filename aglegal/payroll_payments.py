"""Separate employee payments from subsequent statutory remittances."""
from datetime import date
from decimal import Decimal

from .db import now_iso
from .workflow import workflow_atomic, record_event


class PayrollPaymentsRepository:
    @staticmethod
    def payroll_payment_date(value):
        try:
            return date.fromisoformat((value or '').strip()).isoformat()
        except ValueError:
            raise ValueError('Fecha de pago inválida: usa YYYY-MM-DD') from None

    def guard_payroll_expense(self, expense_id):
        if self.conn.execute('SELECT 1 FROM payrolls WHERE expense_id=%s', (expense_id,)).fetchone() or self.conn.execute(
            'SELECT 1 FROM payroll_obligations WHERE expense_id=%s', (expense_id,)
        ).fetchone():
            raise ValueError('Este gasto pertenece a Nóminas; corrígelo o anúlalo desde ese módulo')

    def list_payroll_obligations(self):
        return list(self.conn.execute('''SELECT o.*, p.employee_name, p.personal_id, p.period FROM payroll_obligations o
            JOIN payrolls p ON p.id=o.payroll_id ORDER BY p.period DESC,p.id DESC,o.kind''').fetchall())

    @workflow_atomic
    def pay_payroll_obligation(self, obligation_id, *, payment_date, reference, actor):
        payment_date = self.payroll_payment_date(payment_date)
        reference = (reference or '').strip()
        if not reference:
            raise ValueError('Indica la referencia o comprobante del pago')
        row = self.conn.execute('SELECT * FROM payroll_obligations WHERE id=%s', (obligation_id,)).fetchone()
        if not row:
            raise ValueError('Obligación no encontrada')
        if row['expense_id']:
            if row['payment_date'] == payment_date and row['reference'] == reference:
                return row['expense_id']
            raise ValueError('Esta obligación ya está pagada')
        payroll = self.get_payroll(row['payroll_id'])
        if payment_date < payroll['payment_date']:
            raise ValueError('El pago de obligaciones no puede preceder al pago de la planilla')
        expense = self.get_expense(payroll['expense_id'])
        expense_id = self.create_expense(
            detail=f"Nómina {row['kind']} - {payroll['employee_name']} - {payroll['period']}",
            amount_text=str(Decimal(row['amount_cents']) / 100), expense_date=payment_date,
            notes=reference, account_id=expense['account_id'], created_at=now_iso())
        self.conn.execute('''UPDATE payroll_obligations SET expense_id=%s,payment_date=%s,reference=%s,actor=%s
            WHERE id=%s''', (expense_id,payment_date,reference,actor,obligation_id))
        record_event(self,'payroll',row['payroll_id'],'Pago de obligación',actor,
                     dict(obligation_id=obligation_id,kind=row['kind'],amount_cents=row['amount_cents'],
                          expense_id=expense_id,payment_date=payment_date,reference=reference))
        return expense_id

    @workflow_atomic
    def reverse_payroll_obligation(self, obligation_id, *, reason, actor):
        if not (reason or '').strip():
            raise ValueError('Indica el motivo de la anulación')
        row = self.conn.execute('SELECT * FROM payroll_obligations WHERE id=%s',(obligation_id,)).fetchone()
        if not row or not row['expense_id']:
            raise ValueError('La obligación no tiene un pago para anular')
        record_event(self,'payroll',row['payroll_id'],'Anulación de obligación',actor,
                     dict(obligation_id=obligation_id,expense_id=row['expense_id'],reference=row['reference'],
                          payment_date=row['payment_date'],amount_cents=row['amount_cents'],reason=reason.strip()))
        self.conn.execute('''UPDATE payroll_obligations SET expense_id=NULL,payment_date=NULL,
            reference=NULL,actor=NULL WHERE id=%s''',(obligation_id,))
        self.conn.execute('DELETE FROM expenses WHERE id=%s',(row['expense_id'],))

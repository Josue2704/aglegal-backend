"""Controles de cobro y liquidación de compensación variable."""
from datetime import date
import math

from .db import now_iso
from .workflow import workflow_atomic, record_event


class FinancialWorkflowRepository:
    def require_active_service(self, service_id):
        if self.get_servicio(service_id)['estado'] != 'Activo':
            raise ValueError('El servicio debe estar activo para abrir el expediente')

    def validate_collection_plan(self, mes, probability, opened_at):
        if not mes or probability is None:
            raise ValueError('Indica mes esperado y probabilidad de cobro')
        if self._clean_mes(mes, 'Mes de cobro esperado') < opened_at[:7]:
            raise ValueError('El mes de cobro esperado no puede ser anterior a la apertura')
        self._validate_probability(probability)

    @staticmethod
    def _validate_probability(value):
        if value is not None and (not math.isfinite(float(value)) or not 0 <= float(value) <= 1):
            raise ValueError('La probabilidad de cobro debe estar entre 0 y 100%')

    def save_collection_probability(self, case_id, value):
        self._validate_probability(value)
        self.conn.execute('UPDATE cases SET probabilidad_cobro=%s WHERE id=%s', (value, case_id))

    def incomplete_collection_plans(self):
        return [dict(r) for r in self.conn.execute('''SELECT cs.id, cs.title FROM cases cs
            WHERE cs.archived_at IS NULL
              AND (cs.mes_cobro_esperado IS NULL OR cs.probabilidad_cobro IS NULL)
              AND cs.honorarios_contratados_cents > COALESCE((SELECT SUM(monto_neto_operativo_cents)
                    FROM incomes WHERE case_id=cs.id),0) ORDER BY cs.id''').fetchall()]

    @workflow_atomic
    def approve_commission(self, commission_id, *, evidence, eligible, actor):
        c = self.get_comision(commission_id)
        if c['estado'] != 'Calculada':
            raise ValueError('Solo se revisan comisiones calculadas pendientes de aprobación')
        if not evidence.strip():
            raise ValueError('Documenta el origen del negocio y la revisión de elegibilidad')
        if not eligible:
            if c['ajusta_a_commission_id'] is not None:
                raise ValueError('Un ajuste de una comisión pagada debe compensarse en la liquidación')
            self.revertir_comision(commission_id, created_at=now_iso(), motivo=evidence.strip(), commit=False)
        else:
            self.conn.execute("UPDATE comisiones SET estado='Aprobada' WHERE id=%s", (commission_id,))
        self.conn.execute('UPDATE comisiones SET evidencia=%s, aprobado_por=%s, aprobado_at=%s WHERE id=%s',
                          (evidence.strip(), actor, now_iso(), commission_id))
        record_event(self, 'comision', commission_id, 'Aprobada' if eligible else 'No elegible', actor,
                     {'evidencia': evidence.strip()})
        return self.get_comision(commission_id)

    def list_commission_settlements(self, personal_id=None):
        return [dict(r) for r in self.conn.execute('''SELECT s.*, p.persona AS persona_nombre,
            (SELECT json_agg(c.id ORDER BY c.id) FROM comisiones c WHERE c.liquidacion_id=s.id) AS commission_ids
            FROM commission_settlements s JOIN personal p ON p.id=s.personal_id
            WHERE (%s::integer IS NULL OR s.personal_id=%s) ORDER BY s.id DESC''',
            (personal_id,personal_id)).fetchall()]

    @workflow_atomic
    def settle_commissions(self, *, commission_ids, payment_date, reference, account_id, request_key, actor):
        ids = sorted(set(int(i) for i in commission_ids))
        if not ids or len(ids) != len(commission_ids) or not request_key.strip() or not reference.strip():
            raise ValueError('Selecciona comisiones y registra una referencia o comprobante de pago')
        date.fromisoformat(payment_date)
        if payment_date > date.today().isoformat():
            raise ValueError('No puedes registrar como realizado un pago futuro')
        previous = self.conn.execute('SELECT * FROM commission_settlements WHERE request_key=%s',(request_key,)).fetchone()
        if previous:
            applied = [r['id'] for r in self.conn.execute('SELECT id FROM comisiones WHERE liquidacion_id=%s ORDER BY id',(previous['id'],)).fetchall()]
            expense = self.get_expense(previous['expense_id']) if previous['expense_id'] else None
            if applied != ids or previous['payment_date'] != payment_date or previous['reference'] != reference.strip() or (expense and expense['account_id'] != account_id):
                raise ValueError('La referencia de solicitud ya corresponde a otra liquidación')
            return dict(previous)
        rows = [self.get_comision(i) for i in ids]
        people = {c['personal_id'] for c in rows}
        if len(people) != 1 or any(c['estado'] != 'Aprobada' or c['liquidacion_id'] for c in rows):
            raise ValueError('Selecciona comisiones aprobadas, sin pagar, de una sola persona')
        person = rows[0]['personal_id']
        # No permite omitir un ajuste pendiente y pagar de más a la misma persona.
        credits = self.conn.execute("""SELECT id FROM comisiones WHERE personal_id=%s
            AND comision_cents < 0 AND liquidacion_id IS NULL AND estado IN ('Calculada','Aprobada')""", (person,)).fetchall()
        if any(c['id'] not in ids for c in credits):
            raise ValueError('Revisa e incluye los ajustes pendientes de esta persona antes de pagar')
        if any(payment_date[:7] < c['mes_reconocimiento'] for c in rows):
            raise ValueError('El pago no puede anticipar el período de reconocimiento')
        total = sum(c['comision_cents'] for c in rows)
        if total < 0:
            raise ValueError('El saldo es a favor del despacho; consérvalo para compensar próximas comisiones')
        expense_id = None
        if total:
            expense_id = self.create_expense(detail=f"Liquidación de comisiones — {rows[0]['persona_nombre']}",
                amount_text=str(total / 100), expense_date=payment_date, notes=reference.strip(),
                account_id=account_id, created_at=now_iso())
        cur = self.conn.execute('''INSERT INTO commission_settlements(personal_id,amount_cents,payment_date,
            reference,actor,expense_id,request_key,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
            (person,total,payment_date,reference.strip(),actor,expense_id,request_key,now_iso()))
        settlement = int(cur.lastrowid)
        for c in rows:
            self.conn.execute("UPDATE comisiones SET estado='Pagada',liquidacion_id=%s WHERE id=%s",(settlement,c['id']))
            record_event(self,'comision',c['id'],'Liquidada',actor,{'liquidacion_id':settlement,'referencia':reference.strip()})
        return dict(self.conn.execute('SELECT * FROM commission_settlements WHERE id=%s',(settlement,)).fetchone())

    def guard_commission_expense(self, expense_id):
        if self.conn.execute('SELECT 1 FROM commission_settlements WHERE expense_id=%s',(expense_id,)).fetchone():
            raise ValueError('Este gasto pertenece a una liquidación de comisiones y conserva el comprobante original')

"""Facturación y aplicaciones de pagos. El dinero recibido nunca nace de un estado."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from psycopg2.extras import Json
from .db import now_iso


def cents(value) -> int:
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or n > Decimal('100000000'):
            raise ValueError('Importe inválido')
        return int((n * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError):
        raise ValueError('Importe inválido') from None


def money(value: int) -> str:
    return str(Decimal(value) / 100)


def atomic(fn):
    @wraps(fn)
    def operation(self, *args, **kwargs):
        try:
            # Serializa reservas, edición y aplicaciones; evita dobles cobros concurrentes.
            self.conn.execute('SELECT pg_advisory_xact_lock(74185245)')
            result = fn(self, *args, **kwargs)
            self.conn.commit()
            return result
        except Exception:
            self.conn.rollback()
            raise
    return operation


class BillingRepository:
    _TABLA_POR_ENTIDAD = {
        'session': ('sessions', 'la cita'), 'case_task': ('case_tasks', 'la tarea'),
        'time_entry': ('case_time_entries', 'el registro de horas'), 'cost': ('costs', 'el costo'),
    }
    _INVOICE_SELECT = """SELECT i.*, c.name AS client_name, ca.title AS case_title,
        COALESCE(p.paid_cents, 0) AS paid_cents, COALESCE(p.reimb_paid, 0) AS reimb_paid,
        COALESCE(x.reimbursement_total_cents, 0) AS reimbursement_total_cents,
        COALESCE(p.paid_cents, 0)>0 AS has_income
        FROM invoices i JOIN clients c ON c.id=i.client_id LEFT JOIN cases ca ON ca.id=i.case_id
        LEFT JOIN (SELECT invoice_id, SUM(amount_cents) AS paid_cents, SUM(reimbursement_cents) AS reimb_paid
            FROM invoice_payments WHERE released_at IS NULL GROUP BY invoice_id) p ON p.invoice_id=i.id
        LEFT JOIN (SELECT invoice_id, SUM(subtotal_cents) AS reimbursement_total_cents
            FROM invoice_items WHERE charge_type='Reembolso' GROUP BY invoice_id) x ON x.invoice_id=i.id"""

    def _invoice_view(self, row):
        if not row:
            return None
        result = dict(row)
        paid, total = int(row['paid_cents']), int(row['total_cents'])
        result['balance_cents'] = 0 if row['status']=='Cancelada' else max(0, total - paid)
        result['needs_review'] = bool(paid > total or row['reimb_paid'] > row['reimbursement_total_cents']
            or (row['status'] == 'Pagada' and paid < total)
            or (paid >= total > 0 and row['reimb_paid'] != row['reimbursement_total_cents']))
        if row['status'] not in ('Borrador', 'Cancelada'):
            result['status'] = 'Pagada' if total > 0 and paid >= total else 'Parcial' if paid else 'Enviada'
        result['overdue'] = bool(result['status'] in ('Enviada', 'Parcial')
            and row['due_date'] and row['due_date'] < date.today().isoformat() and result['balance_cents'] > 0)
        return result

    def list_invoices(self, client_id=None):
        where, args = (' WHERE i.client_id=%s', (client_id,)) if client_id else ('', ())
        return [self._invoice_view(r) for r in self.conn.execute(self._INVOICE_SELECT + where + ' ORDER BY i.id DESC', args).fetchall()]

    def get_invoice(self, invoice_id):
        return self._invoice_view(self.conn.execute(self._INVOICE_SELECT + ' WHERE i.id=%s', (invoice_id,)).fetchone())

    def get_invoice_items(self, invoice_id):
        return list(self.conn.execute('SELECT * FROM invoice_items WHERE invoice_id=%s ORDER BY id', (invoice_id,)).fetchall())

    def list_invoice_payments(self, invoice_id):
        return list(self.conn.execute("""SELECT p.*, i.income_date, i.detail, ac.nombre AS account_name
            FROM invoice_payments p JOIN incomes i ON i.id=p.income_id
            LEFT JOIN plan_cuentas ac ON ac.id=i.account_id WHERE p.invoice_id=%s ORDER BY p.id""", (invoice_id,)).fetchall())

    def next_invoice_number(self):
        # Reserva un consecutivo, nunca reutiliza números por haber eliminado borradores.
        while True:
            n = self.conn.execute("SELECT nextval('invoice_number_seq') AS n").fetchone()['n']
            number = f'FAC-{n:04d}'
            if not self.conn.execute('SELECT id FROM invoices WHERE invoice_number=%s',(number,)).fetchone():
                return number

    def _factura_viva_de(self, tabla, entidad_id):
        if tabla not in {v[0] for v in self._TABLA_POR_ENTIDAD.values()}:
            raise ValueError('Origen inválido')
        return self.conn.execute(f"""SELECT f.* FROM {tabla} t JOIN invoices f ON f.id=t.invoice_id
            WHERE t.id=%s AND f.status <> 'Cancelada'""", (entidad_id,)).fetchone()

    def _release_invoice_items(self, invoice_id):
        for table, _ in self._TABLA_POR_ENTIDAD.values():
            self.conn.execute(f'UPDATE {table} SET invoice_id=NULL WHERE invoice_id=%s', (invoice_id,))

    def _validate_invoice_items(self, client_id, case_id, items, invoice_id=None):
        if not self.conn.execute('SELECT id FROM clients WHERE id=%s', (client_id,)).fetchone():
            raise ValueError('Cliente no encontrado')
        if case_id:
            case = self.conn.execute('SELECT * FROM cases WHERE id=%s FOR UPDATE', (case_id,)).fetchone()
            if not case or case['client_id'] != client_id:
                raise ValueError('El expediente no pertenece al cliente')
        if not items:
            raise ValueError('Agrega al menos una partida a la factura')
        seen, prepared = set(), []
        for item in items:
            it = dict(item)
            it['description'] = str(it.get('description') or '').strip()
            if not it['description']:
                raise ValueError('Cada partida necesita descripción')
            qty = Decimal(str(it.get('quantity', 1)))
            if not qty.is_finite() or qty <= 0 or qty > 1000000:
                raise ValueError('La cantidad debe ser positiva')
            unit = cents(it.get('unit_price', 0))
            subtotal = int((Decimal(unit) * qty).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            if subtotal <= 0 or subtotal > 10000000000:
                raise ValueError('Cada partida debe tener un importe positivo')
            kind = it.get('charge_type') or 'Honorario'
            et, eid = it.get('entity_type'), it.get('entity_id')
            if bool(et) != bool(eid) or (et and et not in self._TABLA_POR_ENTIDAD):
                raise ValueError('Tipo de partida desconocido o referencia incompleta')
            if et:
                if (et, eid) in seen:
                    raise ValueError('La misma partida no puede repetirse en una factura')
                seen.add((et, eid))
                table = self._TABLA_POR_ENTIDAD[et][0]
                row = self.conn.execute(f'SELECT * FROM {table} WHERE id=%s FOR UPDATE', (eid,)).fetchone()
                if not row:
                    raise ValueError('Partida no encontrada')
                owner = row.get('client_id')
                if et in ('case_task', 'time_entry'):
                    owner = self.conn.execute('SELECT client_id FROM cases WHERE id=%s', (row['case_id'],)).fetchone()['client_id']
                if owner != client_id or (row.get('case_id') or None) != (case_id or None):
                    raise ValueError('La partida no pertenece al cliente y expediente seleccionados')
                live = self._factura_viva_de(table, eid)
                if live and live['id'] != invoice_id:
                    raise ValueError(f"La partida ya está reservada o facturada en {live['invoice_number']}")
                # Los borradores también conservan el importe autorizado de su origen.
                if et == 'case_task':
                    if not row['monto_adicional_cents'] or not row.get('autorizado_por'):
                        raise ValueError('La tarea no tiene un extra autorizado; puede estar incluida en el contrato')
                    if not row['done'] and not row.get('cobro_anticipado'):
                        raise ValueError('Completa la tarea o acuerda expresamente el cobro anticipado')
                    if qty != 1 or unit != row['monto_adicional_cents']:
                        raise ValueError('El precio debe coincidir con el honorario autorizado de la tarea')
                    kind = 'Honorario'
                elif et == 'cost':
                    if not row['monto_reembolsable_cents'] or qty != 1 or unit != row['monto_reembolsable_cents']:
                        raise ValueError('Solo se factura el importe reembolsable del gasto')
                    kind = 'Reembolso'
                elif et == 'session' and row['status'] != 'Finalizada':
                    raise ValueError('La sesión debe estar finalizada')
                elif et == 'time_entry' and (not row['billable'] or qty != Decimal(str(row['hours']))):
                    raise ValueError('Las horas deben coincidir con el registro facturable')
            if kind not in ('Honorario', 'Reembolso'):
                raise ValueError('Naturaleza del cargo inválida')
            if kind == 'Reembolso' and et != 'cost':
                raise ValueError('Selecciona el gasto reembolsable; no lo registres como línea manual')
            it.update(quantity=qty, unit_price_cents=unit, subtotal_cents=subtotal, charge_type=kind)
            prepared.append(it)
        if case_id:
            reserved = self.conn.execute("""SELECT COALESCE(SUM(it.subtotal_cents),0) AS total
                FROM invoice_items it JOIN invoices i ON i.id=it.invoice_id
                WHERE i.case_id=%s AND i.status<>'Cancelada' AND i.id<>%s AND it.charge_type='Honorario'""",
                (case_id, invoice_id or -1)).fetchone()['total']
            fees = sum(it['subtotal_cents'] for it in prepared if it['charge_type']=='Honorario')
            if fees + reserved > case['honorarios_contratados_cents']:
                raise ValueError('Los honorarios superan lo contratado pendiente de facturar. Revisa extras o partidas ya facturadas')
        return prepared

    @staticmethod
    def _invoice_dates(invoice_date, due_date):
        try:
            emitted = date.fromisoformat(invoice_date)
            if due_date and date.fromisoformat(due_date) < emitted:
                raise ValueError('El vencimiento no puede ser anterior a la emisión')
        except (TypeError, ValueError) as e:
            raise ValueError('Fechas de factura inválidas: usa una emisión válida y vencimiento posterior o igual') from e

    def _write_invoice_items(self, invoice_id, items, created_at):
        for it in items:
            self.conn.execute("""INSERT INTO invoice_items(invoice_id,description,quantity,unit_price_cents,
                subtotal_cents,charge_type,entity_type,entity_id,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (invoice_id,it['description'],it['quantity'],it['unit_price_cents'],it['subtotal_cents'],
                 it['charge_type'],it.get('entity_type'),it.get('entity_id'),created_at))
            if it.get('entity_type'):
                table = self._TABLA_POR_ENTIDAD[it['entity_type']][0]
                self.conn.execute(f'UPDATE {table} SET invoice_id=%s WHERE id=%s', (invoice_id,it['entity_id']))

    @atomic
    def create_invoice(self, client_id, case_id, invoice_number, invoice_date, due_date, notes,
            firm_name, firm_phone, firm_email, firm_address, firm_tax_id, items, created_at):
        self._invoice_dates(invoice_date, due_date)
        number = (invoice_number or '').strip() or self.next_invoice_number()
        if self.conn.execute('SELECT id FROM invoices WHERE invoice_number=%s', (number,)).fetchone():
            raise ValueError('Ya existe una factura con el número indicado')
        prepared = self._validate_invoice_items(client_id, case_id, items)
        total = sum(it['subtotal_cents'] for it in prepared)
        inv = self.conn.execute("""INSERT INTO invoices(client_id,case_id,invoice_number,invoice_date,due_date,status,
            notes,firm_name,firm_phone,firm_email,firm_address,firm_tax_id,total_cents,created_at)
            VALUES(%s,%s,%s,%s,%s,'Borrador',%s,%s,%s,%s,%s,%s,%s,%s)""",
            (client_id,case_id,number,invoice_date,due_date,notes,firm_name,firm_phone,firm_email,firm_address,firm_tax_id,total,created_at)).lastrowid
        self._write_invoice_items(inv, prepared, created_at)
        return inv

    @atomic
    def update_invoice(self, invoice_id, invoice_number, invoice_date, due_date, status, notes,
            firm_name, firm_phone, firm_email, firm_address, firm_tax_id, items, created_at):
        inv = self.get_invoice(invoice_id)
        if not inv or inv['status'] != 'Borrador' or self.list_invoice_payments(invoice_id):
            raise ValueError('Solo se pueden editar borradores sin pagos. Cancela el documento y prepara uno nuevo si corresponde')
        if status not in ('Borrador','Enviada'):
            raise ValueError('Usa Emitir factura o Registrar pago; el pago no se cambia manualmente')
        self._invoice_dates(invoice_date, due_date)
        if not (invoice_number or '').strip():
            raise ValueError('Número de factura requerido')
        if self.conn.execute('SELECT id FROM invoices WHERE invoice_number=%s AND id<>%s', (invoice_number,invoice_id)).fetchone():
            raise ValueError('Ya existe otra factura con el número indicado')
        prepared = self._validate_invoice_items(inv['client_id'], inv['case_id'], items, invoice_id)
        self._release_invoice_items(invoice_id)
        self.conn.execute('DELETE FROM invoice_items WHERE invoice_id=%s', (invoice_id,))
        self._write_invoice_items(invoice_id, prepared, created_at)
        self.conn.execute("""UPDATE invoices SET invoice_number=%s,invoice_date=%s,due_date=%s,status=%s,notes=%s,
            firm_name=%s,firm_phone=%s,firm_email=%s,firm_address=%s,firm_tax_id=%s,total_cents=%s WHERE id=%s""",
            (invoice_number,invoice_date,due_date,status,notes,firm_name,firm_phone,firm_email,firm_address,firm_tax_id,
             sum(it['subtotal_cents'] for it in prepared),invoice_id))

    @atomic
    def update_invoice_status(self, invoice_id, status):
        inv = self.get_invoice(invoice_id)
        if not inv:
            raise ValueError('Factura no encontrada')
        if status == inv['status'] and status in ('Borrador','Enviada','Cancelada'):
            return
        if inv['status']=='Cancelada':
            raise ValueError('Una factura cancelada no se reactiva; prepara una nueva')
        if status == 'Cancelada':
            self._release_invoice_items(invoice_id)
            self.conn.execute("""UPDATE invoice_payments SET released_at=%s,release_reason='Factura cancelada: saldo disponible para aplicar'
                WHERE invoice_id=%s AND released_at IS NULL""", (now_iso(),invoice_id))
        elif status == 'Enviada' and inv['status']=='Borrador':
            items = [dict(it,unit_price=money(it['unit_price_cents'])) for it in self.get_invoice_items(invoice_id)]
            self._validate_invoice_items(inv['client_id'],inv['case_id'],items,invoice_id)
        else:
            raise ValueError('Estado de factura inválido: emite el borrador o registra un pago; no se marca Pagada manualmente')
        self.conn.execute('UPDATE invoices SET status=%s WHERE id=%s', (status,invoice_id))

    @atomic
    def delete_invoice(self, invoice_id):
        inv = self.get_invoice(invoice_id)
        if not inv or inv['status']!='Borrador' or self.list_invoice_payments(invoice_id):
            raise ValueError('Solo se eliminan borradores sin pagos. Las facturas emitidas se cancelan conservando su historial')
        self._release_invoice_items(invoice_id)
        self.conn.execute('DELETE FROM invoices WHERE id=%s', (invoice_id,))

    def auto_income_from_invoice(self, invoice_id):
        raise ValueError('Registra el pago con su fecha real; una factura no genera dinero automáticamente')

    def _income_available(self, income_id):
        return self.conn.execute("""SELECT i.*, COALESCE(p.used,0) AS used,
            COALESCE(p.reimb,0) AS reimb_used FROM incomes i
            LEFT JOIN (SELECT income_id,SUM(amount_cents) AS used,SUM(reimbursement_cents) AS reimb
                FROM invoice_payments WHERE released_at IS NULL GROUP BY income_id) p ON p.income_id=i.id
            WHERE i.id=%s""", (income_id,)).fetchone()

    def available_invoice_credits(self, invoice_id):
        inv = self.get_invoice(invoice_id)
        if not inv:
            raise ValueError('Factura no encontrada')
        rows = self.conn.execute('SELECT id FROM incomes WHERE client_id=%s AND case_id IS NOT DISTINCT FROM %s ORDER BY income_date,id',
            (inv['client_id'],inv['case_id'])).fetchall()
        result=[]
        for row in rows:
            inc = self._income_available(row['id'])
            # Impuestos y fondos de terceros no se aplican como honorarios ni reembolsos.
            available = inc['amount_cents'] - inc['monto_iva_cents'] - inc['monto_fondos_terceros_cents'] - inc['used']
            fee_available = inc['monto_neto_operativo_cents'] - (inc['used']-inc['reimb_used'])
            reimb_available = inc['monto_reembolsable_cents']-inc['reimb_used']
            reimb_left = max(0,inv['reimbursement_total_cents']-inv['reimb_paid'])
            applicable = min(max(0,fee_available),max(0,inv['balance_cents']-reimb_left)) + min(max(0,reimb_available),reimb_left)
            if available > 0:
                result.append(dict(id=inc['id'],income_date=inc['income_date'],detail=inc['detail'],
                    available=available/100, applicable=applicable/100, reimbursement_available=(inc['monto_reembolsable_cents']-inc['reimb_used'])/100))
        return result

    @atomic
    def register_invoice_payment(self, invoice_id, *, amount, income_date=None, account_id=None,
            detail='', income_id=None, request_key, username='sistema'):
        amount_cents = cents(amount)
        payload = dict(invoice_id=invoice_id,amount_cents=amount_cents,income_date=income_date,
            account_id=account_id,detail=detail,income_id=income_id)
        prev = self.conn.execute('SELECT * FROM invoice_payments WHERE request_key=%s', (request_key,)).fetchone()
        if prev:
            if prev['request_payload'] != payload:
                raise ValueError('La referencia de operación ya se usó con otros datos')
            return prev['income_id']
        inv = self.get_invoice(invoice_id)
        if not inv or inv['status'] not in ('Enviada','Parcial'):
            raise ValueError('Solo se reciben pagos de facturas emitidas con saldo pendiente')
        if inv['needs_review']:
            raise ValueError('Revisa las aplicaciones históricas antes de registrar otro pago')
        if amount_cents <= 0 or amount_cents > inv['balance_cents']:
            raise ValueError('El pago debe ser positivo y no superar el saldo de la factura')
        reimb_left = max(0, inv['reimbursement_total_cents'] - inv['reimb_paid'])
        fee_left = inv['balance_cents'] - reimb_left
        if income_id:
            self.conn.execute('SELECT id FROM incomes WHERE id=%s FOR UPDATE', (income_id,))
            inc = self._income_available(income_id)
            if not inc or inc['client_id'] != inv['client_id'] or inc['case_id'] != inv['case_id']:
                raise ValueError('El anticipo debe pertenecer al mismo cliente y expediente')
            available_reimb = inc['monto_reembolsable_cents'] - inc['reimb_used']
            available_fees = inc['monto_neto_operativo_cents'] - (inc['used'] - inc['reimb_used'])
            fees = min(amount_cents, max(0,available_fees), fee_left)
            reimbursement = amount_cents - fees
            if reimbursement > min(available_reimb,reimb_left):
                raise ValueError('El saldo del anticipo no cubre este importe con la misma clasificación de honorarios y reembolsos')
        else:
            try:
                paid_on = date.fromisoformat(income_date or '')
                if paid_on > date.today():
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('Indica la fecha real del pago, no una fecha futura') from None
            # Distribución proporcional acumulada, con cierre exacto del último centavo.
            target = int((Decimal(inv['paid_cents'] + amount_cents) * inv['reimbursement_total_cents']
                / inv['total_cents']).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            reimbursement = min(amount_cents, reimb_left, max(amount_cents-fee_left, target-inv['reimb_paid'],0))
            income_id = self.create_income(amount_text=money(amount_cents),income_date=income_date,created_at=now_iso(),
                client_id=inv['client_id'],case_id=inv['case_id'],account_id=account_id,
                detail=f"Factura {inv['invoice_number']} · {detail.strip() or 'Pago recibido'}",
                monto_reembolsable_text=money(reimbursement), commit=False)
            self.conn.execute('UPDATE incomes SET invoice_id=%s WHERE id=%s',(invoice_id,income_id))
        self.conn.execute("""INSERT INTO invoice_payments(invoice_id,income_id,amount_cents,reimbursement_cents,
            request_key,request_payload,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (invoice_id,income_id,amount_cents,reimbursement,request_key,Json(payload),username,now_iso()))
        self.conn.execute('UPDATE invoices SET status=%s WHERE id=%s',(self.get_invoice(invoice_id)['status'],invoice_id))
        return income_id

    def guard_allocated_income(self, income_id):
        self.conn.execute('SELECT pg_advisory_xact_lock(74185245)')
        if self.conn.execute('SELECT id FROM invoice_payments WHERE income_id=%s LIMIT 1', (income_id,)).fetchone():
            raise ValueError('Este ingreso tiene historial de aplicaciones a facturas y no se puede alterar ni eliminar')

    def billing_summary(self, client_id, case_id):
        if not case_id:
            return None
        case = self.get_case(case_id)
        if not case or case['client_id'] != client_id:
            raise ValueError('El expediente no pertenece al cliente')
        extra = self.conn.execute('SELECT COALESCE(SUM(monto_adicional_cents),0) AS n FROM case_tasks WHERE case_id=%s', (case_id,)).fetchone()['n']
        invoices = [i for i in self.list_invoices(client_id) if i['case_id']==case_id and i['status']!='Cancelada']
        fees = sum(i['total_cents']-i['reimbursement_total_cents'] for i in invoices)
        return dict(contract_total=case['honorarios_contratados_cents']/100, task_extras=extra/100,
            reserved_or_invoiced=fees/100, unbilled_fees=max(0,case['honorarios_contratados_cents']-fees)/100,
            outstanding_invoices=sum(i['balance_cents'] for i in invoices if i['status']!='Borrador')/100)

    def get_unbilled_items(self, client_id, case_id=None):
        extra, params = (' AND case_id=%s',(client_id,case_id)) if case_id else (' AND case_id IS NULL',(client_id,))
        sessions = self.conn.execute("SELECT id,session_date,consult_type,notes FROM sessions WHERE client_id=%s AND invoice_id IS NULL AND status='Finalizada'"+extra+' ORDER BY session_date',params).fetchall()
        task_extra, tp = (' AND ca.id=%s',(client_id,case_id)) if case_id else ('',(client_id,))
        tasks = self.conn.execute("""SELECT ct.*, ca.title AS case_title FROM case_tasks ct JOIN cases ca ON ca.id=ct.case_id
            WHERE ca.client_id=%s AND ct.invoice_id IS NULL AND ct.monto_adicional_cents>0
            AND COALESCE(TRIM(ct.autorizado_por),'')<>'' AND (ct.done=1 OR ct.cobro_anticipado)"""+task_extra+' ORDER BY ct.id',tp).fetchall()
        costs = self.conn.execute("""SELECT id,concept,detail,monto_reembolsable_cents AS amount_cents,cost_date
            FROM costs WHERE client_id=%s AND invoice_id IS NULL AND monto_reembolsable_cents>0"""+extra+' ORDER BY cost_date',params).fetchall()
        hours = self.conn.execute("""SELECT te.*,ca.title AS case_title FROM case_time_entries te JOIN cases ca ON ca.id=te.case_id
            WHERE ca.client_id=%s AND te.billable=1 AND te.invoice_id IS NULL"""+task_extra+' ORDER BY te.work_date',tp).fetchall()
        return dict(sessions=sessions,tasks=tasks if case_id else [],costs=costs,time_entries=hours if case_id else [],summary=self.billing_summary(client_id,case_id))

    def _cuenta_ingreso_sugerida(self, case_id: int | None) -> int | None:
        """Cuenta de ingreso sugerida (00_PARA_DESARROLLADOR, "Nuevo expediente"): la misma
        con la que ya se cobró este expediente; si es el primer cobro, la de la categoría del
        servicio; y si tampoco hay, ING-OTR-001 u otra cuenta de ingreso activa.

        Lo primero importa: la categoría del servicio y la familia que factura no siempre
        coinciden —una compraventa es un servicio notarial (NOT) pero se cobra con
        ING-RAI-001 y cuenta para FAM-03 Inmobiliario, como el ejemplo MOV-2026-0001 del
        Archivo Maestro—. Sin esto, el anticipo que el abogado registró a mano y el cobro
        que genera la factura caían en familias distintas y partían el expediente en dos."""
        if case_id:
            row = self.conn.execute(
                """SELECT i.account_id AS id FROM incomes i
                   JOIN plan_cuentas pc ON pc.id = i.account_id AND pc.estado='Activo'
                   WHERE i.case_id=%s
                   GROUP BY i.account_id
                   ORDER BY SUM(i.monto_neto_operativo_cents) DESC, i.account_id
                   LIMIT 1""",
                (int(case_id),),
            ).fetchone()
            if row:
                return int(row["id"])
            row = self.conn.execute(
                """SELECT pc.id FROM cases cs
                   JOIN servicios sv ON sv.id = cs.service_id
                   JOIN subcategorias sc ON sc.id = sv.subcategory_id
                   JOIN plan_cuentas pc ON pc.category_id = sc.category_id AND pc.tipo='Ingreso' AND pc.estado='Activo'
                   WHERE cs.id=%s ORDER BY pc.account_code LIMIT 1""",
                (int(case_id),),
            ).fetchone()
            if row:
                return int(row["id"])
        row = self.conn.execute(
            "SELECT id FROM plan_cuentas WHERE tipo='Ingreso' AND estado='Activo' "
            "ORDER BY (account_code = 'ING-OTR-001') DESC, account_code LIMIT 1"
        ).fetchone()
        return int(row["id"]) if row else None


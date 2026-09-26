"""Reconcile entitlements in receipt order, independently of payment/adjustment dates."""
from collections import defaultdict


def reconcile(repo, created_at):
    incomes = repo.conn.execute('''SELECT i.*, cs.title AS case_label FROM incomes i
        JOIN cases cs ON cs.id=i.case_id ORDER BY i.income_date,i.id''').fetchall()
    costs = {r['case_id']: int(r['total']) for r in repo.conn.execute('''SELECT case_id,
        SUM(monto_neto_operativo_cents) AS total FROM costs GROUP BY case_id''').fetchall()}
    origins = defaultdict(list)
    for row in repo.conn.execute('SELECT * FROM negocio_originadores ORDER BY personal_id').fetchall():
        origins[row['case_id']].append(row)
    excluded = {(r['income_id'], r['personal_id']) for r in repo.conn.execute('SELECT * FROM commission_exclusions').fetchall()}
    current = {(r['income_id'], r['personal_id']): r for r in repo.conn.execute('''SELECT c.* FROM comisiones c
        WHERE c.ajusta_a_commission_id IS NULL AND NOT EXISTS
        (SELECT 1 FROM comisiones a WHERE a.ajusta_a_commission_id=c.id)''').fetchall()}
    collected, accumulated = defaultdict(int), defaultdict(int)
    desired = {}
    for income in incomes:
        cid = income['case_id']; prior = collected[cid]
        collected[cid] += int(income['monto_neto_operativo_cents'])
        profit = max(0, collected[cid]-costs.get(cid, 0))-max(0, prior-costs.get(cid, 0))
        month = income['income_date'][:7]
        allocated = 0
        for index, origin in enumerate(origins[cid]):
            # Deterministic cent allocation keeps the total participation equal to profit.
            share = profit-allocated if index == len(origins[cid])-1 else round(profit*float(origin['porcentaje_participacion'])/100)
            allocated += share
            key = (income['id'], origin['personal_id'])
            if key in excluded:
                continue
            group = (origin['personal_id'], month)
            cross = origin['tipo_origen'] == 'Venta cruzada'
            before = 0 if cross else accumulated[group]
            after = before+share
            amount = round(share*.05) if cross else repo._formula_comision_tramos(after)-repo._formula_comision_tramos(before)
            if not cross:
                accumulated[group] = after
            desired[key] = dict(income_id=income['id'], case_id=cid, personal_id=origin['personal_id'],
                tipo_origen=origin['tipo_origen'], porcentaje_participacion=float(origin['porcentaje_participacion']),
                base_utilidad_directa_cents=share, comision_cents=amount, base_acumulada_antes_cents=before,
                base_acumulada_despues_cents=after, fecha_cobro=income['income_date'], case_label=income['case_label'])
    compare = ('case_id','tipo_origen','porcentaje_participacion','base_utilidad_directa_cents',
               'comision_cents','base_acumulada_antes_cents','base_acumulada_despues_cents')
    for key, old in current.items():
        new = desired.get(key)
        if new is None or old['fecha_cobro'][:7] != new['fecha_cobro'][:7] or any(old[f] != new[f] for f in compare):
            repo.revertir_comision(old['id'], created_at=created_at,
                motivo='Corrección y recálculo mensual por cobros, costos u originadores', commit=False, exclude=False)
        else:
            desired.pop(key)
    for key, row in desired.items():
        # Historical paid rows remain untouched. Their reversal and replacement are
        # booked in the adjustment period, but tiers always use the original receipts.
        adjustment = repo.conn.execute('''SELECT MAX(a.mes_reconocimiento) AS mes FROM comisiones a
            JOIN comisiones c ON c.id=a.ajusta_a_commission_id
            WHERE c.income_id=%s AND c.personal_id=%s AND c.liquidacion_id IS NOT NULL''', key).fetchone()['mes']
        month = max(row['fecha_cobro'][:7], adjustment or '')
        columns = list(row)+['mes_reconocimiento','created_at']
        repo.conn.execute(f"INSERT INTO comisiones({','.join(columns)}) VALUES({','.join(['%s']*len(columns))})",
            tuple(row.values())+(month,created_at))

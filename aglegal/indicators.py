"""Comparable financial dimensions. Shared expenses remain explicitly unallocated."""
from collections import defaultdict
from datetime import date


def explorer(repo, *, desde, hasta, category_id=None, subcategory_id=None, service_id=None,
             family_id=None, client_id=None, origen_negocio=None):
    repo._meses_rango(repo._clean_mes(desde,'Desde'),repo._clean_mes(hasta,'Hasta'))
    filters=dict(category_id=category_id,subcategory_id=subcategory_id,service_id=service_id,
                 family_id=family_id,client_id=client_id,origen_negocio=origen_negocio)
    rows=[]
    for table,kind,dt in [('incomes','Ingreso','income_date'),('costs','Costo directo','cost_date'),('expenses','Gasto operativo','expense_date')]:
        case='m.case_id' if table!='expenses' else 'NULL::integer'
        client='m.client_id' if table!='expenses' else 'NULL::integer'
        extra=' AND COALESCE(pc.afecta_utilidad,TRUE)' if table=='expenses' else ''
        # Direct costs follow the case's principal revenue family, as in the monthly budget report.
        family = "COALESCE((SELECT pa.family_id FROM incomes inc JOIN plan_cuentas pa ON pa.id=inc.account_id WHERE inc.case_id=m.case_id AND pa.family_id IS NOT NULL GROUP BY pa.family_id ORDER BY SUM(inc.monto_neto_operativo_cents) DESC,pa.family_id LIMIT 1),(SELECT f.id FROM familias f WHERE f.category_id=sb.category_id))" if table=='costs' else 'pc.family_id'
        rows.extend(dict(r) for r in repo.conn.execute(f"""SELECT m.id,%s AS kind,m.{dt} AS fecha,
            m.monto_neto_operativo_cents AS cents,m.detail AS description,{case} AS case_id,
            COALESCE({client},cs.client_id) AS client_id,cl.name AS client_name,cs.title AS case_title,
            sv.id AS service_id,sv.nombre AS service_name,sb.id AS subcategory_id,sb.nombre AS subcategory_name,
            ca.id AS category_id,ca.nombre AS category_name,{family} AS family_id,fa.nombre AS family_name,
            COALESCE(NULLIF(cs.origen_negocio,''),'Sin clasificar') AS origen_negocio
            FROM {table} m LEFT JOIN cases cs ON cs.id={case}
            LEFT JOIN clients cl ON cl.id=COALESCE({client},cs.client_id)
            LEFT JOIN servicios sv ON sv.id=COALESCE(m.service_id,cs.service_id)
            LEFT JOIN subcategorias sb ON sb.id=sv.subcategory_id
            LEFT JOIN plan_cuentas pc ON pc.id=m.account_id
            LEFT JOIN categorias ca ON ca.id=COALESCE(sb.category_id,pc.category_id)
            LEFT JOIN familias fa ON fa.id={family}
            WHERE substring(m.{dt},1,7) BETWEEN %s AND %s {extra}
            ORDER BY m.{dt},m.id""",(kind,desde,hasta)).fetchall())
    # Accrual is shown separately; settled commissions already appear in cash expenses.
    rows.extend(dict(r) for r in repo.conn.execute("""SELECT c.id,'Comisión devengada' AS kind,
        c.mes_reconocimiento||'-01' AS fecha,c.comision_cents AS cents,c.estado AS description,
        c.case_id,cs.client_id,cl.name AS client_name,cs.title AS case_title,
        sv.id AS service_id,sv.nombre AS service_name,sb.id AS subcategory_id,sb.nombre AS subcategory_name,
        ca.id AS category_id,ca.nombre AS category_name,pc.family_id,fa.nombre AS family_name,
        COALESCE(NULLIF(cs.origen_negocio,''),'Sin clasificar') AS origen_negocio
        FROM comisiones c LEFT JOIN cases cs ON cs.id=c.case_id
        LEFT JOIN clients cl ON cl.id=cs.client_id LEFT JOIN servicios sv ON sv.id=cs.service_id
        LEFT JOIN subcategorias sb ON sb.id=sv.subcategory_id LEFT JOIN categorias ca ON ca.id=sb.category_id
        LEFT JOIN incomes i ON i.id=c.income_id LEFT JOIN plan_cuentas pc ON pc.id=i.account_id
        LEFT JOIN familias fa ON fa.id=pc.family_id
        WHERE c.mes_reconocimiento BETWEEN %s AND %s AND c.estado<>'Anulada' ORDER BY c.id""",(desde,hasta)).fetchall())
    for month in repo._meses_rango(desde,hasta):
        for r in repo.conn.execute("""SELECT g.id,g.concepto AS description,g.monto_mensual_cents AS cents,
            pc.category_id,ca.nombre AS category_name,pc.family_id,fa.nombre AS family_name
            FROM gastos_fijos g LEFT JOIN plan_cuentas pc ON pc.id=g.account_id
            LEFT JOIN categorias ca ON ca.id=pc.category_id LEFT JOIN familias fa ON fa.id=pc.family_id
            WHERE g.estado='Activo' AND g.mes_inicio<=%s AND (g.mes_fin IS NULL OR g.mes_fin>=%s)""",(month,month)).fetchall():
            rows.append(dict(r,kind='Gasto fijo presupuestado',fecha=month+'-01',case_id=None,client_id=None,
                client_name=None,case_title=None,service_id=None,service_name=None,subcategory_id=None,subcategory_name=None,origen_negocio='Sin clasificar'))
    case_rows=[dict(r) for r in repo.list_cases()]
    for r in case_rows:r['origen_negocio']=r['origen_negocio'] or 'Sin clasificar'
    case_options=[dict(category_id=r['category_id'],category_name=r['category_nombre'],
        subcategory_id=r['subcategory_id'],subcategory_name=r['subcategory_nombre'],service_id=r['service_id'],service_name=r['service_nombre'],
        family_id=r['family_id'],family_name=r['family_nombre'],client_id=r['client_id'],client_name=r['client_name'],origen_negocio=r['origen_negocio']) for r in case_rows]
    family_options=[dict(family_id=r['id'],family_name=r['nombre'],category_id=r['category_id'],category_name=r['category_nombre']) for r in repo.list_familias()]
    options={}
    for field,label in [('category_id','category_name'),('subcategory_id','subcategory_name'),('service_id','service_name'),('family_id','family_name'),('client_id','client_name'),('origen_negocio','origen_negocio')]:
        choices={r[field]:r[label] for r in rows+case_options+family_options if r.get(field) is not None}
        options[field]=[dict(value=k,label=v or str(k)) for k,v in sorted(choices.items(),key=lambda x:str(x[1]))]
    selected=[r for r in rows if all(value is None or r.get(key)==value for key,value in filters.items())]
    totals=defaultdict(int)
    categories={}
    for r in selected:
        totals[r['kind']]+=int(r['cents'])
        group=categories.setdefault(r['category_id'],dict(category_id=r['category_id'],name=r['category_name'] or 'Compartidos / sin categoría',income=0,cost=0,expense=0,commission=0,fixed=0))
        key={'Ingreso':'income','Costo directo':'cost','Gasto operativo':'expense','Comisión devengada':'commission','Gasto fijo presupuestado':'fixed'}[r['kind']]
        group[key]+=int(r['cents'])
    for r in categories.values():
        r['operating_cash']=r['income']-r['cost']-r['expense']
        r['operating_budget']=r['income']-r['cost']-r['fixed']-r['commission']
    cases={('case',r['case_id']) if r['case_id'] else ('income',r['id']) for r in selected if r['kind']=='Ingreso'}
    income_ids={r['id'] for r in selected if r['kind']=='Ingreso'}
    days=[]; missing=0
    for r in repo.conn.execute("""SELECT i.id,cs.id AS case_id,i.income_date,
        COALESCE(inv.invoice_date,cs.fecha_cierre_real) AS reference,inv.id AS invoice_id
        FROM incomes i LEFT JOIN cases cs ON cs.id=i.case_id
        LEFT JOIN invoice_payments p ON p.income_id=i.id AND p.released_at IS NULL
        LEFT JOIN invoices inv ON inv.id=p.invoice_id AND inv.status<>'Cancelada'
        WHERE substring(i.income_date,1,7) BETWEEN %s AND %s""",(desde,hasta)).fetchall():
        if r['id'] not in income_ids:continue
        delta=(date.fromisoformat(r['income_date'][:10])-date.fromisoformat(r['reference'][:10])).days if r['reference'] else -1
        if delta<0:missing+=1
        else:days.append(dict(r,days=delta))
    common=[r for r in rows if r['kind']=='Gasto operativo' and r['category_id'] is None]
    for r in selected:
        r['url']=f"/cases?case_id={r['case_id']}" if r['case_id'] else '/cashflow'
    selected_cases=[r for r in case_rows if all(value is None or r.get(key)==value for key,value in filters.items())]
    portfolio=[dict(id=r['id'],title=r['title'],client_id=r['client_id'],estado_cobro=r['estado_cobro'],
        mes=r['mes_cobro_esperado'],balance=r['saldo_pendiente_cents'],
        probability=float(r['probabilidad_cobro']) if r['probabilidad_cobro'] is not None else None,
        weighted=round(r['saldo_pendiente_cents']*float(r['probabilidad_cobro'])) if r['probabilidad_cobro'] is not None else None)
        for r in selected_cases if r['saldo_pendiente_cents']>0 and r['mes_cobro_esperado'] and desde<=r['mes_cobro_esperado']<=hasta]
    frequency={}
    for r in selected_cases:
        if desde<=r['opened_at'][:7]<=hasta:
            frequency.setdefault(r['service_id'],dict(service_id=r['service_id'],service=r['service_nombre'] or 'Sin servicio',cases=[]))['cases'].append(dict(id=r['id'],title=r['title']))
    goal_supported=all(filters[k] is None for k in ('subcategory_id','service_id','client_id','origen_negocio'))
    goals=[dict(r) for r in repo.conn.execute("""SELECT f.*,fa.category_id,fa.nombre AS family_name FROM forecast f
        JOIN familias fa ON fa.id=f.family_id WHERE f.mes BETWEEN %s AND %s ORDER BY f.mes,f.id""",(desde,hasta)).fetchall()
        if (family_id is None or r['family_id']==family_id) and (category_id is None or r['category_id']==category_id)] if goal_supported else []
    goal_income=sum(r['ingreso_proyectado_cents'] for r in goals)
    goal_volume=sum(r['volumen_meta'] for r in goals)
    # Each month/family counts an expediente once, consistent with authorized forecast granularity.
    goal_keys={(r['mes'],r['family_id']) for r in goals}
    comparable=[r for r in rows if r['kind']=='Ingreso' and (r['fecha'][:7],r['family_id']) in goal_keys]
    goal_actual_income=sum(r['cents'] for r in comparable)
    volume_keys={(r['fecha'][:7],r['family_id'],r['case_id'] or ('income',r['id'])) for r in comparable}
    opportunities=[dict(r) for r in repo.conn.execute("""SELECT o.id,o.estado,o.fecha_cotizado,o.fecha_prospecto,o.service_id,o.client_id,o.origen_negocio,
        sb.id AS subcategory_id,sb.category_id,fa.id AS family_id FROM oportunidades o
        LEFT JOIN servicios sv ON sv.id=o.service_id LEFT JOIN subcategorias sb ON sb.id=sv.subcategory_id
        LEFT JOIN familias fa ON fa.category_id=sb.category_id
        WHERE substring(COALESCE(o.fecha_cotizado,o.fecha_prospecto),1,7) BETWEEN %s AND %s""",(desde,hasta)).fetchall()
        if all(value is None or r.get(key)==value for key,value in filters.items())]
    quoted=sum(1 for r in opportunities if r['fecha_cotizado'])
    won=sum(1 for r in opportunities if r['fecha_cotizado'] and r['estado']=='Ganado')
    profitability={}
    for r in selected:
        if r['kind'] not in ('Ingreso','Costo directo'):continue
        group=profitability.setdefault(r['service_id'],dict(service=r['service_name'] or 'Sin servicio',income=0,cost=0))
        group['income' if r['kind']=='Ingreso' else 'cost']+=r['cents']
    for r in profitability.values():
        r['profit']=r['income']-r['cost'];r['margin']=r['profit']/r['income'] if r['income'] else None
    extra=dict(portfolio=portfolio,portfolio_total=sum(r['balance'] for r in portfolio),
        portfolio_weighted=sum(r['weighted'] or 0 for r in portfolio),missing_probability=sum(r['probability'] is None for r in portfolio),
        frequency=list(frequency.values()),profitability=list(profitability.values()),goals=goals,
        goals_supported=goal_supported,goal_income=goal_income,goal_actual_income=goal_actual_income,goal_volume=goal_volume,actual_volume=len(volume_keys),
        projected=goal_income+sum(r['weighted'] or 0 for r in portfolio) if goal_supported else None,
        income_compliance=goal_actual_income/goal_income if goal_income else None,
        volume_compliance=len(volume_keys)/goal_volume if goal_volume else None,
        quoted=quoted,won=won,conversion=won/quoted if quoted else None,opportunities=opportunities)
    return dict(extra=extra,desde=desde,hasta=hasta,filters=filters,options=options,rows=selected,categories=list(categories.values()),
        totals=dict(income=totals['Ingreso'],cost=totals['Costo directo'],expense=totals['Gasto operativo'],
                    commission=totals['Comisión devengada'],operating_cash=totals['Ingreso']-totals['Costo directo']-totals['Gasto operativo'],
                    fixed=totals['Gasto fijo presupuestado'],operating_budget=totals['Ingreso']-totals['Costo directo']-totals['Gasto fijo presupuestado']-totals['Comisión devengada'],
                    cases=len(cases),ticket=round(totals['Ingreso']/len(cases)) if cases else None,
                    days_average=round(sum(r['days'] for r in days)/len(days),1) if days else None,
                    measured=len(days),without_reference=missing),days=days,
        shared_expenses=sum(int(r['cents']) for r in common),shared_fixed=sum(int(r['cents']) for r in rows if r['kind']=='Gasto fijo presupuestado' and r['category_id'] is None),
        allocation_rule='Los gastos se atribuyen por servicio o cuenta contable. Los compartidos se muestran por separado, sin reparto ficticio. Las comisiones devengadas se informan aparte: los pagos ya forman parte de los gastos de caja.',
        threshold='Verde ≥100%; amarillo ≥85% y <100%; rojo <85%.')

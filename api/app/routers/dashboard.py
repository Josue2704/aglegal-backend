from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, RepoDep, require_permission
from ..access import require_any
from ..schemas.dashboard import (
    CashflowTotals,
    GrossProfitItem,
    MonthlyMetrics,
    MonthlyPoint,
    TopItem,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_can_view = require_permission("dashboard", "ver")


@router.get("/upcoming-sessions")
def upcoming_sessions(
    current_user: CurrentUser,
    repo: RepoDep,
    days: int = 7,
    _: dict = _can_view,
) -> list[dict]:
    if not current_user['is_admin'] and 'agenda.ver' not in current_user['permissions']:
        return []
    return [dict(r) for r in repo.upcoming_sessions(days=days)]


@router.get("/alerts")
def alerts(current_user: CurrentUser, repo: RepoDep, stale_days: int = 15, _: dict = require_any('dashboard.ver','tareas.ver','expedientes.ver','pipeline.ver','finanzas.ver','comisiones.ver','flujo_caja.ver')) -> dict:
    result=repo.dashboard_alerts(stale_days=stale_days)
    modules={'overdue_tasks':'tareas','critical_tasks':'tareas','stale_cases':'expedientes',
        'overdue_billing':'flujo_caja','budget_deviation':'finanzas','seguimiento_vencido':'pipeline','casos_sin_originador':'comisiones'}
    return {k:v if current_user['is_admin'] or modules[k]+'.ver' in current_user['permissions'] else ([] if isinstance(v,list) else None) for k,v in result.items()}


@router.get("/search")
def global_search(
    q: str,
    current_user: CurrentUser,
    repo: RepoDep,
    limit: int = 8,
    _: dict = require_any('dashboard.ver','clientes.ver','expedientes.ver','agenda.ver','facturas.ver','tareas.ver','pipeline.ver'),
) -> dict:
    if not q or len(q.strip()) < 2:
        return {"clients": [], "cases": [], "sessions": [], "invoices": [], "tasks": [], "oportunidades": []}
    result=repo.global_search(q.strip(), limit=limit)
    modules={'clients':'clientes','cases':'expedientes','sessions':'agenda','invoices':'facturas','tasks':'tareas','oportunidades':'pipeline'}
    return {k:v if current_user['is_admin'] or modules[k]+'.ver' in current_user['permissions'] else [] for k,v in result.items()}


@router.get("/kpis", response_model=MonthlyMetrics)
def monthly_kpis(current_user: CurrentUser, repo: RepoDep, _: dict = _can_view) -> MonthlyMetrics:
    m = repo.dashboard_metrics_month()
    incomes = m["incomes_cents"] / 100
    expenses = m["expenses_cents"] / 100
    return MonthlyMetrics(
        clients_attended=m["clients_attended"],
        sessions_total=m["sessions_total"],
        sessions_finalized=m["sessions_finalized"],
        incomes=incomes,
        expenses=expenses,
        balance=incomes - expenses,
    )


@router.get("/cashflow")
def cashflow(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    _: dict = _can_view,
) -> dict:
    total_in, total_ex = repo.cashflow_totals(start_date=start_date, end_date=end_date)
    total_costs = repo.cost_totals(start_date=start_date, end_date=end_date)
    monthly = repo.cashflow_monthly(start_date=start_date, end_date=end_date)
    totals = CashflowTotals(
        total_incomes=total_in / 100,
        total_expenses=total_ex / 100,
        total_costs=total_costs / 100,
        balance=(total_in - total_ex - total_costs) / 100,
    )
    chart = [MonthlyPoint(month=m, incomes=i / 100, expenses=e / 100) for m, i, e in monthly]
    return {"totals": totals, "monthly_chart": chart}


@router.get("/top-clients", response_model=list[TopItem])
def top_clients(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
    _: dict = _can_view,
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_clients_by_revenue(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/top-services", response_model=list[TopItem])
def top_services(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
    _: dict = _can_view,
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_services_by_revenue(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/top-expenses", response_model=list[TopItem])
def top_expenses(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
    _: dict = _can_view,
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_expenses_by_account(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/gross-profit/services", response_model=list[GrossProfitItem])
def gross_profit_services(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
    _: dict = _can_view,
) -> list[GrossProfitItem]:
    rows = repo.top_services_by_gross_profit(start_date=start_date, end_date=end_date, limit=limit)
    return [GrossProfitItem(name=n, revenue=r / 100, cost=c / 100, gross_profit=g / 100) for n, r, c, g in rows]


@router.get("/cashflow-by-client")
def cashflow_by_client(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    _: dict = _can_view,
) -> list[dict]:
    return repo.cashflow_by_client(start_date=start_date, end_date=end_date)


@router.get("/gross-profit/clients", response_model=list[GrossProfitItem])
def gross_profit_clients(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
    _: dict = _can_view,
) -> list[GrossProfitItem]:
    rows = repo.top_clients_by_gross_profit(start_date=start_date, end_date=end_date, limit=limit)
    return [GrossProfitItem(name=n, revenue=r / 100, cost=c / 100, gross_profit=g / 100) for n, r, c, g in rows]


@router.get("/rentabilidad-abogado")
def rentabilidad_abogado(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    _: dict = _can_view,
) -> list[dict]:
    rows = repo.rentabilidad_por_abogado(start_date=start_date, end_date=end_date)
    return [
        {
            "responsable": r["responsable"],
            "ingresos": r["ingresos_cents"] / 100,
            "costos": r["costos_cents"] / 100,
            "utilidad_directa": r["utilidad_directa_cents"] / 100,
            "margen_pct": r["margen_pct"],
        }
        for r in rows
    ]

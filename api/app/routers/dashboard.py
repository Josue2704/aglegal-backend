from __future__ import annotations

from fastapi import APIRouter

from ..deps import CurrentUser, RepoDep
from ..schemas.dashboard import (
    CashflowTotals,
    GrossProfitItem,
    MonthlyMetrics,
    MonthlyPoint,
    TopItem,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/upcoming-sessions")
def upcoming_sessions(
    current_user: CurrentUser,
    repo: RepoDep,
    days: int = 7,
) -> list[dict]:
    return [dict(r) for r in repo.upcoming_sessions(days=days)]


@router.get("/alerts")
def alerts(current_user: CurrentUser, repo: RepoDep) -> dict:
    return repo.dashboard_alerts()


@router.get("/search")
def global_search(
    q: str,
    current_user: CurrentUser,
    repo: RepoDep,
    limit: int = 8,
) -> dict:
    if not q or len(q.strip()) < 2:
        return {"clients": [], "cases": [], "sessions": []}
    return repo.global_search(q.strip(), limit=limit)


@router.get("/kpis", response_model=MonthlyMetrics)
def monthly_kpis(current_user: CurrentUser, repo: RepoDep) -> MonthlyMetrics:
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
        categories_total=m["categories_total"],
    )


@router.get("/cashflow")
def cashflow(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
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
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_clients_by_revenue(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/top-services", response_model=list[TopItem])
def top_services(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_services_by_revenue(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/top-expenses", response_model=list[TopItem])
def top_expenses(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
) -> list[TopItem]:
    return [TopItem(name=n, amount=a / 100) for n, a in repo.top_expenses_by_category(start_date=start_date, end_date=end_date, limit=limit)]


@router.get("/gross-profit/services", response_model=list[GrossProfitItem])
def gross_profit_services(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
) -> list[GrossProfitItem]:
    rows = repo.top_services_by_gross_profit(start_date=start_date, end_date=end_date, limit=limit)
    return [GrossProfitItem(name=n, revenue=r / 100, cost=c / 100, gross_profit=g / 100) for n, r, c, g in rows]


@router.get("/cashflow-by-client")
def cashflow_by_client(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    return repo.cashflow_by_client(start_date=start_date, end_date=end_date)


@router.get("/gross-profit/clients", response_model=list[GrossProfitItem])
def gross_profit_clients(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 8,
) -> list[GrossProfitItem]:
    rows = repo.top_clients_by_gross_profit(start_date=start_date, end_date=end_date, limit=limit)
    return [GrossProfitItem(name=n, revenue=r / 100, cost=c / 100, gross_profit=g / 100) for n, r, c, g in rows]

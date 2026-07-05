from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.income import IncomeIn, IncomeOut

router = APIRouter(prefix="/incomes", tags=["incomes"])


@router.get("", response_model=list[IncomeOut])
def list_incomes(
    current_user: LawyerRequired,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[IncomeOut]:
    return [IncomeOut.from_row(row) for row in repo.list_incomes_range(start_date=start_date, end_date=end_date)]


@router.post("", response_model=IncomeOut, status_code=201)
def create_income(body: IncomeIn, current_user: LawyerRequired, repo: RepoDep) -> IncomeOut:
    income_id = repo.create_income(
        amount_text=str(body.amount),
        income_date=body.income_date,
        client_id=body.client_id,
        category_id=body.category_id,
        case_id=body.case_id,
        detail=body.detail,
        invoice_id=body.invoice_id,
        created_at=now_iso(),
    )
    rows = repo.list_incomes_range(start_date=None, end_date=None)
    row = next((r for r in rows if r["id"] == income_id), None)
    return IncomeOut.from_row(row)


@router.put("/{income_id}", response_model=IncomeOut)
def update_income(income_id: int, body: IncomeIn, current_user: LawyerRequired, repo: RepoDep) -> IncomeOut:
    from fastapi import HTTPException
    repo.update_income(
        income_id,
        amount_text=str(body.amount),
        income_date=body.income_date,
        client_id=body.client_id,
        category_id=body.category_id,
        case_id=body.case_id,
        detail=body.detail,
    )
    row = repo.get_income(income_id)
    if not row:
        raise HTTPException(404, "Ingreso no encontrado")
    return IncomeOut.from_row(row)


@router.delete("/{income_id}", status_code=204)
def delete_income(income_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_income(income_id)

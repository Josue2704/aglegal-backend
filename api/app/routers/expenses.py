from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.expense import ExpenseIn, ExpenseOut

router = APIRouter(prefix="/expenses", tags=["expenses"])


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[ExpenseOut]:
    return [ExpenseOut.from_row(row) for row in repo.list_expenses_range(start_date=start_date, end_date=end_date)]


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense(body: ExpenseIn, current_user: LawyerRequired, repo: RepoDep) -> ExpenseOut:
    expense_id = repo.create_expense(
        category_id=body.category_id,
        detail=body.detail,
        amount_text=str(body.amount),
        expense_date=body.expense_date,
        notes=body.notes,
        created_at=now_iso(),
    )
    rows = repo.list_expenses_range(start_date=None, end_date=None)
    row = next((r for r in rows if r["id"] == expense_id), None)
    return ExpenseOut.from_row(row)


@router.put("/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, body: ExpenseIn, current_user: LawyerRequired, repo: RepoDep) -> ExpenseOut:
    from fastapi import HTTPException
    repo.update_expense(
        expense_id,
        category_id=body.category_id,
        detail=body.detail,
        amount_text=str(body.amount),
        expense_date=body.expense_date,
        notes=body.notes,
    )
    row = repo.get_expense(expense_id)
    if not row:
        raise HTTPException(404, "Gasto no encontrado")
    return ExpenseOut.from_row(row)


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_expense(expense_id)

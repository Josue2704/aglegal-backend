from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.payroll import PayrollIn, PayrollOut

router = APIRouter(prefix="/payroll", tags=["payroll"])


@router.get("", response_model=list[PayrollOut])
def list_payroll(current_user: CurrentUser, repo: RepoDep) -> list[PayrollOut]:
    return [PayrollOut.from_row(row) for row in repo.list_payrolls()]


@router.post("", response_model=PayrollOut, status_code=201)
def create_payroll(body: PayrollIn, current_user: LawyerRequired, repo: RepoDep) -> PayrollOut:
    payroll_id = repo.create_payroll(
        employee_name=body.employee_name,
        role=body.role,
        period=body.period,
        amount_text=str(body.amount),
        payment_date=body.payment_date,
        notes=body.notes,
        created_at=now_iso(),
    )
    rows = repo.list_payrolls()
    row = next((r for r in rows if r["id"] == payroll_id), None)
    return PayrollOut.from_row(row)


@router.delete("/{payroll_id}", status_code=204)
def delete_payroll(payroll_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_payroll(payroll_id)

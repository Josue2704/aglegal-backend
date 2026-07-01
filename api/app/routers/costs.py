from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep
from ..schemas.cost import CostIn, CostOut

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("", response_model=list[CostOut])
def list_costs(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[CostOut]:
    return [CostOut.from_row(row) for row in repo.list_costs_range(start_date=start_date, end_date=end_date)]


@router.get("/totals")
def cost_totals(
    current_user: CurrentUser,
    repo: RepoDep,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    total = repo.cost_totals(start_date=start_date, end_date=end_date)
    return {"total": total / 100}


@router.post("", response_model=CostOut, status_code=201)
def create_cost(body: CostIn, current_user: CurrentUser, repo: RepoDep) -> CostOut:
    cost_id = repo.create_cost(
        client_id=body.client_id,
        case_id=body.case_id,
        category_id=body.category_id,
        detail=body.detail,
        amount_text=str(body.amount),
        cost_date=body.cost_date,
        notes=body.notes,
        created_at=now_iso(),
    )
    rows = repo.list_costs_range(start_date=None, end_date=None)
    row = next((r for r in rows if r["id"] == cost_id), None)
    return CostOut.from_row(row)


@router.put("/{cost_id}", response_model=CostOut)
def update_cost(cost_id: int, body: CostIn, current_user: CurrentUser, repo: RepoDep) -> CostOut:
    from fastapi import HTTPException
    repo.update_cost(
        cost_id,
        client_id=body.client_id,
        case_id=body.case_id,
        category_id=body.category_id,
        detail=body.detail,
        amount_text=str(body.amount),
        cost_date=body.cost_date,
        notes=body.notes,
    )
    row = repo.get_cost(cost_id)
    if not row:
        raise HTTPException(404, "Costo no encontrado")
    return CostOut.from_row(row)


@router.delete("/{cost_id}", status_code=204)
def delete_cost(cost_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_cost(cost_id)

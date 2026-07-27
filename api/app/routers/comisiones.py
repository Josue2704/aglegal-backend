from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.comisiones import ComisionOut, OriginadorOut, OriginadoresSetIn, ResumenComisionOut

router = APIRouter(prefix="/comisiones", tags=["comisiones"])


@router.get("/originadores/{case_id}", response_model=list[OriginadorOut])
def list_originadores(
    case_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("comisiones", "ver")
) -> list[OriginadorOut]:
    return [OriginadorOut.from_row(row) for row in repo.list_negocio_originadores(case_id)]


@router.put("/originadores/{case_id}", response_model=list[OriginadorOut])
def set_originadores(case_id: int, body: OriginadoresSetIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("comisiones", "editar")) -> list[OriginadorOut]:
    try:
        repo.set_negocio_originadores(
            case_id,
            originadores=[o.model_dump() for o in body.originadores],
            created_at=now_iso(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return [OriginadorOut.from_row(row) for row in repo.list_negocio_originadores(case_id)]


@router.get("", response_model=list[ComisionOut])
def list_comisiones(
    current_user: CurrentUser, repo: RepoDep,
    personal_id: int | None = None, mes: str | None = None, case_id: int | None = None,
    _: dict = require_permission("comisiones", "ver"),
) -> list[ComisionOut]:
    return [ComisionOut.from_row(row) for row in repo.list_comisiones(personal_id=personal_id, mes=mes, case_id=case_id)]


@router.get("/resumen", response_model=list[ResumenComisionOut])
def resumen_comisiones(current_user: CurrentUser, repo: RepoDep, mes: str, _: dict = require_permission("comisiones", "ver")) -> list[ResumenComisionOut]:
    return [ResumenComisionOut.from_row(row) for row in repo.resumen_comisiones_mes(mes)]


@router.post("/reconocer", response_model=list[ComisionOut])
def reconocer_comision(income_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("comisiones", "editar")) -> list[ComisionOut]:
    try:
        rows = repo.reconocer_comision_income(income_id, created_at=now_iso())
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return [ComisionOut.from_row(row) for row in rows]


@router.post("/{commission_id}/revertir", response_model=ComisionOut)
def revertir_comision(commission_id: int, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("comisiones", "editar")) -> ComisionOut:
    try:
        row = repo.revertir_comision(commission_id, created_at=now_iso())
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return ComisionOut.from_row(row)

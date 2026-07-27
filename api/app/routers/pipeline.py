from __future__ import annotations

from fastapi import APIRouter

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.pipeline import (
    ConversionComercialOut,
    OportunidadIn,
    OportunidadOut,
    OportunidadTransicion,
    OportunidadTransicionOut,
    OportunidadUpdate,
)

router = APIRouter(prefix="/oportunidades", tags=["pipeline"])


@router.get("", response_model=list[OportunidadOut])
def list_oportunidades(
    current_user: CurrentUser, repo: RepoDep, estado: str | None = None, q: str | None = None,
    _: dict = require_permission("pipeline", "ver"),
) -> list[OportunidadOut]:
    return [OportunidadOut.from_row(row) for row in repo.list_oportunidades(estado=estado, q=q)]


@router.get("/conversion", response_model=ConversionComercialOut)
def conversion_comercial(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "ver")) -> ConversionComercialOut:
    return ConversionComercialOut(**repo.conversion_comercial())


@router.post("", response_model=OportunidadOut, status_code=201)
def create_oportunidad(body: OportunidadIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "crear")) -> OportunidadOut:
    op_id = repo.create_oportunidad(
        client_id=body.client_id, prospecto_nombre=body.prospecto_nombre, prospecto_contacto=body.prospecto_contacto,
        service_id=body.service_id, canal_captacion=body.canal_captacion, origen_negocio=body.origen_negocio,
        created_at=now_iso(),
    )
    return OportunidadOut.from_row(repo.get_oportunidad(op_id))


@router.put("/{oportunidad_id}", response_model=OportunidadOut)
def update_oportunidad(oportunidad_id: int, body: OportunidadUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "editar")) -> OportunidadOut:
    repo.update_oportunidad(
        oportunidad_id, client_id=body.client_id, prospecto_nombre=body.prospecto_nombre, prospecto_contacto=body.prospecto_contacto,
        service_id=body.service_id, canal_captacion=body.canal_captacion, origen_negocio=body.origen_negocio,
    )
    return OportunidadOut.from_row(repo.get_oportunidad(oportunidad_id))


@router.post("/{oportunidad_id}/transicion", response_model=OportunidadTransicionOut)
def transicionar_oportunidad(oportunidad_id: int, body: OportunidadTransicion, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "editar")) -> OportunidadTransicionOut:
    case_id = repo.transition_oportunidad(
        oportunidad_id, nuevo_estado=body.estado, motivo_perdida=body.motivo_perdida, usuario_id=current_user["id"],
    )
    row = repo.get_oportunidad(oportunidad_id)
    return OportunidadTransicionOut(oportunidad=OportunidadOut.from_row(row), case_id=case_id, case_internal_ref=row["case_internal_ref"])

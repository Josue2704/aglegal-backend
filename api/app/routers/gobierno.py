from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.gobierno import SolicitudIn, SolicitudOut, SolicitudTransicion, SolicitudUpdate

router = APIRouter(prefix="/solicitudes-catalogo", tags=["gobierno"])


@router.get("", response_model=list[SolicitudOut])
def list_solicitudes(
    current_user: CurrentUser, repo: RepoDep,
    estado: str | None = None, tipo_registro: str | None = None, q: str | None = None,
) -> list[SolicitudOut]:
    return [SolicitudOut.from_row(row) for row in repo.list_solicitudes(estado=estado, tipo_registro=tipo_registro, q=q)]


@router.post("", response_model=SolicitudOut, status_code=201)
def create_solicitud(body: SolicitudIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "crear")) -> SolicitudOut:
    try:
        solicitud_id = repo.create_solicitud(
            tipo_solicitud=body.tipo_solicitud, tipo_registro=body.tipo_registro, nombre_propuesto=body.nombre_propuesto,
            categoria_padre=body.categoria_padre, subcategoria_padre=body.subcategoria_padre, codigo_propuesto=body.codigo_propuesto,
            descripcion=body.descripcion, motivo=body.motivo, etiquetas=body.etiquetas,
            solicitante=current_user["username"], created_at=now_iso(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(repo.get_solicitud(solicitud_id))


@router.put("/{solicitud_id}", response_model=SolicitudOut)
def update_solicitud(solicitud_id: int, body: SolicitudUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "editar")) -> SolicitudOut:
    try:
        repo.update_solicitud(
            solicitud_id, nombre_propuesto=body.nombre_propuesto, categoria_padre=body.categoria_padre,
            subcategoria_padre=body.subcategoria_padre, codigo_propuesto=body.codigo_propuesto,
            descripcion=body.descripcion, motivo=body.motivo, etiquetas=body.etiquetas,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(repo.get_solicitud(solicitud_id))


@router.post("/{solicitud_id}/transicion", response_model=SolicitudOut)
def transicion_solicitud(solicitud_id: int, body: SolicitudTransicion, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("categorias", "editar")) -> SolicitudOut:
    try:
        row = repo.transition_solicitud(
            solicitud_id, estado=body.estado, resultado_revision_duplicidad=body.resultado_revision_duplicidad,
            aprobador=body.aprobador, observaciones=body.observaciones, created_at=now_iso(),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(row)

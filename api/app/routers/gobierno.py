from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from ..schemas.gobierno import SolicitudIn, SolicitudOut, SolicitudTransicion, SolicitudUpdate

router = APIRouter(prefix="/solicitudes-catalogo", tags=["gobierno"])

# Transiciones que representan una decisión formal de gobierno (aprobar/rechazar/
# activar/desactivar) exigen el permiso "aprobar", distinto de editar campos comunes.
_ESTADOS_APROBACION = {"Aprobado", "Rechazado", "Activo", "Inactivo"}


@router.get("", response_model=list[SolicitudOut])
def list_solicitudes(
    current_user: CurrentUser, repo: RepoDep,
    estado: str | None = None, tipo_registro: str | None = None, q: str | None = None,
    _: dict = require_permission("gobierno_catalogo", "ver"),
) -> list[SolicitudOut]:
    return [SolicitudOut.from_row(row) for row in repo.list_solicitudes(estado=estado, tipo_registro=tipo_registro, q=q)]


@router.post("", response_model=SolicitudOut, status_code=201)
def create_solicitud(body: SolicitudIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("gobierno_catalogo", "crear")) -> SolicitudOut:
    try:
        solicitud_id = repo.create_solicitud(
            tipo_solicitud=body.tipo_solicitud, tipo_registro=body.tipo_registro, nombre_propuesto=body.nombre_propuesto,
            categoria_padre=body.categoria_padre, subcategoria_padre=body.subcategoria_padre, codigo_propuesto=body.codigo_propuesto,
            descripcion=body.descripcion, motivo=body.motivo, etiquetas=body.etiquetas,
            solicitante=current_user["username"], created_at=now_iso(), entity_id=body.entity_id,
            unidad_cobro_propuesta=body.unidad_cobro_propuesta, responsable_sugerido_propuesto=body.responsable_sugerido_propuesto,
            tarifa_referencia_propuesta_text=str(body.tarifa_referencia_propuesta) if body.tarifa_referencia_propuesta is not None else "",
            costo_referencia_propuesta_text=str(body.costo_referencia_propuesta) if body.costo_referencia_propuesta is not None else "",
            horas_estandar_propuesta=body.horas_estandar_propuesta, estado_propuesto=body.estado_propuesto,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(repo.get_solicitud(solicitud_id))


@router.put("/{solicitud_id}", response_model=SolicitudOut)
def update_solicitud(solicitud_id: int, body: SolicitudUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("gobierno_catalogo", "editar")) -> SolicitudOut:
    try:
        repo.update_solicitud(
            solicitud_id, nombre_propuesto=body.nombre_propuesto, categoria_padre=body.categoria_padre,
            subcategoria_padre=body.subcategoria_padre, codigo_propuesto=body.codigo_propuesto,
            descripcion=body.descripcion, motivo=body.motivo, etiquetas=body.etiquetas,
            unidad_cobro_propuesta=body.unidad_cobro_propuesta, responsable_sugerido_propuesto=body.responsable_sugerido_propuesto,
            tarifa_referencia_propuesta_text=str(body.tarifa_referencia_propuesta) if body.tarifa_referencia_propuesta is not None else "",
            costo_referencia_propuesta_text=str(body.costo_referencia_propuesta) if body.costo_referencia_propuesta is not None else "",
            horas_estandar_propuesta=body.horas_estandar_propuesta, estado_propuesto=body.estado_propuesto,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(repo.get_solicitud(solicitud_id))


@router.post("/{solicitud_id}/transicion", response_model=SolicitudOut)
def transicion_solicitud(solicitud_id: int, body: SolicitudTransicion, current_user: CurrentUser, repo: RepoDep) -> SolicitudOut:
    accion = "aprobar" if body.estado in _ESTADOS_APROBACION else "editar"
    perm_key = f"gobierno_catalogo.{accion}"
    if not current_user["is_admin"] and perm_key not in current_user["permissions"]:
        raise HTTPException(403, f"Sin permiso: {perm_key}")
    try:
        row = repo.transition_solicitud(
            solicitud_id, estado=body.estado, resultado_revision_duplicidad=body.resultado_revision_duplicidad,
            aprobador=body.aprobador, observaciones=body.observaciones, created_at=now_iso(), usuario_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(row)

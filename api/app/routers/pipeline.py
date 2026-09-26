from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, RepoDep, require_permission
from aglegal.repositories import MOTIVOS_PERDIDA
from ..schemas.pipeline import (
    ConversionComercialOut,
    OportunidadIn,
    OportunidadOut,
    OportunidadTransicion,
    OportunidadTransicionOut,
    OportunidadUpdate,
)

router = APIRouter(prefix="/oportunidades", tags=["pipeline"])


@router.get('/originadores')
def originadores(current_user: CurrentUser, repo: RepoDep, _: dict = require_permission('pipeline','editar')):
    return [dict(r) for r in repo.conn.execute("SELECT id,persona FROM personal WHERE estado='Activo' ORDER BY persona").fetchall()]


@router.get("", response_model=list[OportunidadOut])
def list_oportunidades(
    current_user: CurrentUser, repo: RepoDep, estado: str | None = None, q: str | None = None,
    _: dict = require_permission("pipeline", "ver"),
) -> list[OportunidadOut]:
    return [OportunidadOut.from_row(row) for row in repo.list_oportunidades(estado=estado, q=q)]


@router.get("/motivos-perdida", response_model=list[str])
def motivos_perdida(current_user: CurrentUser, _: dict = require_permission("pipeline", "ver")) -> list[str]:
    return MOTIVOS_PERDIDA


@router.get("/conversion", response_model=ConversionComercialOut)
def conversion_comercial(current_user: CurrentUser, repo: RepoDep, mes: str | None = None, origen: str | None = None, service_id: int | None = None, _: dict = require_permission("pipeline", "ver")) -> ConversionComercialOut:
    data = repo.conversion_comercial(mes=mes, origen=origen, service_id=service_id)
    data["valor_pipeline"] = data.pop("valor_pipeline_cents", 0) / 100
    return ConversionComercialOut(**data)


@router.get("/contactos-parecidos")
def contactos_parecidos(
    nombre: str, current_user: CurrentUser, repo: RepoDep, contacto: str = "",
    _: dict = require_permission("pipeline", "ver"),
) -> dict:
    """¿Ya es cliente, ya tiene oportunidad abierta o es contraparte nuestra? Se consulta
    mientras se escribe el nombre, antes de registrar el prospecto."""
    return repo.buscar_contactos_parecidos(nombre=nombre, contacto=contacto)


@router.post("", response_model=OportunidadOut, status_code=201)
def create_oportunidad(body: OportunidadIn, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "crear")) -> OportunidadOut:
    op_id = repo.create_oportunidad(
        client_id=body.client_id, prospecto_nombre=body.prospecto_nombre, prospecto_contacto=body.prospecto_contacto,
        service_id=body.service_id, canal_captacion=body.canal_captacion, origen_negocio=body.origen_negocio,
        honorarios_estimados_text=str(body.honorarios_estimados) if body.honorarios_estimados is not None else "",
        responsable_username=body.responsable_username, proxima_accion=body.proxima_accion,
        fecha_proxima_accion=body.fecha_proxima_accion, created_at=now_iso(), username=current_user["username"],
    )
    return OportunidadOut.from_row(repo.get_oportunidad(op_id))


@router.put("/{oportunidad_id}", response_model=OportunidadOut)
def update_oportunidad(oportunidad_id: int, body: OportunidadUpdate, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "editar")) -> OportunidadOut:
    repo.update_oportunidad(
        oportunidad_id, client_id=body.client_id, prospecto_nombre=body.prospecto_nombre, prospecto_contacto=body.prospecto_contacto,
        service_id=body.service_id, canal_captacion=body.canal_captacion, origen_negocio=body.origen_negocio,
        honorarios_estimados_text=str(body.honorarios_estimados) if body.honorarios_estimados is not None else "",
        responsable_username=body.responsable_username, proxima_accion=body.proxima_accion,
        fecha_proxima_accion=body.fecha_proxima_accion, username=current_user["username"],
    )
    return OportunidadOut.from_row(repo.get_oportunidad(oportunidad_id))


@router.post("/{oportunidad_id}/transicion", response_model=OportunidadTransicionOut)
def transicionar_oportunidad(oportunidad_id: int, body: OportunidadTransicion, current_user: CurrentUser, repo: RepoDep, _: dict = require_permission("pipeline", "editar")) -> OportunidadTransicionOut:
    if body.estado == 'Ganado' and not current_user['is_admin']:
        needed = {'expedientes.crear', 'tareas.crear'}
        op = repo.get_oportunidad(oportunidad_id)
        if not op['client_id'] and not body.client_id_existente:
            needed.add('clientes.crear')
        if not needed.issubset(current_user['permissions']):
            raise HTTPException(403, 'Para abrir desde pipeline necesitas: ' + ', '.join(sorted(needed)))
    case_id = repo.transition_oportunidad(
        oportunidad_id, nuevo_estado=body.estado, motivo_perdida=body.motivo_perdida, usuario_id=current_user["id"],
        motivo_perdida_tipo=body.motivo_perdida_tipo, crear_cliente=body.crear_cliente,
        cliente_documento=body.cliente_documento, cliente_telefono=body.cliente_telefono,
        cliente_email=body.cliente_email, responsable_expediente=body.responsable_expediente,
        client_id_existente=body.client_id_existente, honorarios_pactados=body.honorarios_pactados, costos_directos_estimados=body.costos_directos_estimados,
        alcance=body.alcance, condiciones_cobro=body.condiciones_cobro,
        revision_confirmada=body.revision_confirmada, revision_observaciones=body.revision_observaciones,
        opposing_party=body.opposing_party, tareas_iniciales=[t.model_dump() for t in body.tareas_iniciales],
        originador_id=body.originador_id,
        mes_cobro_esperado=body.mes_cobro_esperado, probabilidad_cobro=body.probabilidad_cobro,
    )
    row = repo.get_oportunidad(oportunidad_id)
    return OportunidadTransicionOut(oportunidad=OportunidadOut.from_row(row), case_id=case_id, case_internal_ref=row["case_internal_ref"])


@router.get('/{oportunidad_id}/historial')
def historial(oportunidad_id: int, current_user: CurrentUser, repo: RepoDep,
              _: dict = require_permission('pipeline','ver')):
    repo.get_oportunidad(oportunidad_id)
    return repo.workflow_history('oportunidad', oportunidad_id)

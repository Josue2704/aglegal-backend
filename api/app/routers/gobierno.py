from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, RepoDep, require_permission
from ..schemas.gobierno import SolicitudIn, SolicitudOut, SolicitudTransicion, SolicitudUpdate

router = APIRouter(prefix="/solicitudes-catalogo", tags=["gobierno"])

# Transiciones que representan una decisión formal de gobierno (aprobar/rechazar/
# activar/desactivar) exigen el permiso "aprobar", distinto de editar campos comunes.
_ESTADOS_APROBACION = {"Aprobado", "Rechazado", "Activo", "Inactivo"}


from pydantic import BaseModel


class ReviewEvidence(BaseModel):
    evidence: str


@router.get('/seguimiento', dependencies=[require_permission('gobierno_catalogo','ver')])
def catalog_followup(current_user: CurrentUser, repo: RepoDep):
    return [dict(r) for r in repo.conn.execute('SELECT r.*,s.nombre_propuesto FROM catalog_reviews r JOIN solicitudes_catalogo s ON s.id=r.solicitud_id ORDER BY r.due_date,r.id').fetchall()]


@router.post('/seguimiento/{review_id}/completar')
def complete_review(review_id: int, body: ReviewEvidence, current_user: AdminRequired, repo: RepoDep):
    from datetime import date
    from aglegal.workflow import record_event
    if not body.evidence.strip():
        raise ValueError('Documenta uso real, duplicidades y resultado de la revisión')
    with repo.conn.transaction():
        row=repo.conn.execute('SELECT * FROM catalog_reviews WHERE id=%s FOR UPDATE',(review_id,)).fetchone()
        if not row or row['status']!='Pendiente':
            raise ValueError('Revisión inexistente o completada')
        if row['due_date']>date.today().isoformat():
            raise ValueError('La revisión de uso se completa al cumplirse los 30 días')
        repo.conn.execute("UPDATE catalog_reviews SET status='Completada',evidence=%s,reviewed_at=%s,reviewer=%s WHERE id=%s",
            (body.evidence.strip(),now_iso(),current_user['username'],review_id))
        record_event(repo,'catalog_review',review_id,'Revisión completada',current_user['username'],dict(evidence=body.evidence))
    return {'status':'Completada'}


@router.get('/notificaciones')
def catalog_notifications(current_user: CurrentUser, repo: RepoDep):
    return [dict(r) for r in repo.conn.execute('SELECT * FROM internal_notifications WHERE user_id=%s ORDER BY id DESC',(current_user['id'],)).fetchall()]


@router.post('/notificaciones/{notification_id}/leida')
def read_notification(notification_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.conn.execute('UPDATE internal_notifications SET read_at=%s WHERE id=%s AND user_id=%s',(now_iso(),notification_id,current_user['id']))
    repo.conn.commit()
    return {'ok':True}


@router.get("", response_model=list[SolicitudOut])
def list_solicitudes(
    current_user: CurrentUser, repo: RepoDep,
    estado: str | None = None, tipo_registro: str | None = None, q: str | None = None,
    _: dict = require_permission("gobierno_catalogo", "ver"),
) -> list[SolicitudOut]:
    return [SolicitudOut.from_row(row) for row in repo.list_solicitudes(estado=estado, tipo_registro=tipo_registro, q=q)]


@router.get("/duplicados")
def buscar_duplicados(
    current_user: CurrentUser, repo: RepoDep, tipo_registro: str, nombre: str,
    _: dict = require_permission("gobierno_catalogo", "ver"),
) -> list[dict]:
    """Revisión de duplicidad asistida: nombres del catálogo existente parecidos al propuesto,
    por similitud de texto — el aprobador sigue decidiendo, esto solo evita que tenga que
    recordarlo de memoria."""
    return repo.buscar_posibles_duplicados(tipo_registro=tipo_registro, nombre=nombre)


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
        # Un administrador no necesita que otra persona apruebe su propia solicitud —
        # el proceso de revisión/aprobación es para cuando quien pide el cambio no es
        # quien tiene la última palabra sobre el Catálogo Maestro. Se auto-aprueba
        # encadenando las mismas transiciones que seguiría un aprobador humano, así
        # que queda la misma trazabilidad (aprobador, fecha, nota de activación).
        if current_user["is_admin"]:
            ts = now_iso()
            repo.transition_solicitud(solicitud_id, estado="En revisión", created_at=ts, usuario_id=current_user["id"])
            repo.transition_solicitud(
                solicitud_id, estado="Aprobado", aprobador=current_user["username"],
                resultado_revision_duplicidad="Auto-aprobado: solicitado y aprobado por un administrador",
                observaciones="Creado y aprobado automáticamente (administrador)",
                created_at=now_iso(), usuario_id=current_user["id"],
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
    if body.estado in _ESTADOS_APROBACION and not current_user['is_admin']:
        raise HTTPException(403,'La decisión corresponde al socio administrador')
    accion = "aprobar" if body.estado in _ESTADOS_APROBACION else "editar"
    perm_key = f"gobierno_catalogo.{accion}"
    if not current_user["is_admin"] and perm_key not in current_user["permissions"]:
        raise HTTPException(403, f"Sin permiso: {perm_key}")
    try:
        row = repo.transition_solicitud(
            solicitud_id, estado=body.estado, resultado_revision_duplicidad=body.resultado_revision_duplicidad,
            aprobador=current_user["username"], observaciones=body.observaciones, created_at=now_iso(), usuario_id=current_user["id"],
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return SolicitudOut.from_row(row)

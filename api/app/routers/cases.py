from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, LawyerRequired, RepoDep, require_permission
from ..schemas.case import (
    CaseTaskCierreIn,
    CaseTaskEstadoIn,
    CaseAttachmentOut, CaseHonorariosLogOut, CaseIn, CaseOut, CaseTaskCriticoUpdate, CaseTaskDone, CaseTaskIn,
    CaseTaskUpdate,
    CaseTaskNotesUpdate, CaseTaskResponsibleUpdate,
    CaseTaskOut, CaseTimeEntryIn, CaseTimeEntryOut, CaseUpdate, ConflictoInteresOut, GlobalCaseTaskOut, TiempoAtencionOut,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
def list_cases(
    current_user: CurrentUser,
    repo: RepoDep,
    search: str | None = None,
    status: str | None = None,
    estado_cobro: str | None = None,
    client_id: int | None = None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    service_id: int | None = None,
    archived: bool = False,
) -> list[CaseOut]:
    return [
        CaseOut.from_row(row)
        for row in repo.list_cases(
            search=search, status=status, estado_cobro=estado_cobro, client_id=client_id,
            category_id=category_id, subcategory_id=subcategory_id, service_id=service_id,
            archived=archived,
        )
    ]


@router.get("/conflicto-interes", response_model=ConflictoInteresOut)
def conflicto_interes(nombre: str, current_user: CurrentUser, repo: RepoDep) -> ConflictoInteresOut:
    """Cruza un nombre de contraparte propuesto contra clientes y contrapartes de otros
    expedientes activos — no bloquea nada, solo avisa antes de aceptar el caso."""
    return ConflictoInteresOut(**repo.check_conflicto_interes(nombre))


@router.get("/tiempos-atencion", response_model=list[TiempoAtencionOut])
def tiempos_atencion(
    current_user: CurrentUser, repo: RepoDep, category_id: int | None = None, subcategory_id: int | None = None, service_id: int | None = None,
) -> list[TiempoAtencionOut]:
    """Días promedio de atención por servicio — para filtrar tiempos por tipo de servicio."""
    return [TiempoAtencionOut.from_row(row) for row in repo.tiempos_atencion(category_id=category_id, subcategory_id=subcategory_id, service_id=service_id)]


@router.get("/choices")
def case_choices(current_user: CurrentUser, repo: RepoDep, client_id: int | None = None) -> list[dict]:
    return [{"id": cid, "title": title} for cid, title in repo.case_choices(client_id=client_id)]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseIn, current_user: CurrentUser, repo: RepoDep) -> CaseOut:
    if not current_user["is_admin"] and "expedientes.crear" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: expedientes.crear")
    case_id = repo.create_case(
        client_id=body.client_id,
        title=body.title,
        status=body.status,
        priority=body.priority,
        opened_at=body.opened_at,
        notes=body.notes,
        internal_ref=body.internal_ref,
        official_ref=body.official_ref,
        opposing_party=body.opposing_party,
        court_entity=body.court_entity,
        responsible_username=body.responsible_username,
        created_at=now_iso(),
        service_id=body.service_id,
        honorarios_contratados_text=str(body.honorarios_contratados) if body.honorarios_contratados is not None else "",
        costos_directos_estimados_text=str(body.costos_directos_estimados) if body.costos_directos_estimados is not None else "",
        mes_cobro_esperado=body.mes_cobro_esperado,
        estado_cobro=body.estado_cobro,
        fecha_cierre_estimada=body.fecha_cierre_estimada,
        proxima_accion=body.proxima_accion,
        tareas_iniciales=[t.model_dump() for t in body.tareas_iniciales],
    )
    rows = repo.list_cases()
    row = next((r for r in rows if r["id"] == case_id), None)
    if not row:
        raise HTTPException(500, "Error al recuperar el caso creado")
    return CaseOut.from_row(row)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: int, body: CaseUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseOut:
    if not current_user["is_admin"] and "expedientes.editar" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: expedientes.editar")
    repo.update_case(
        case_id,
        title=body.title,
        status=body.status,
        priority=body.priority,
        opened_at=body.opened_at,
        closed_at=body.closed_at,
        notes=body.notes,
        internal_ref=body.internal_ref,
        official_ref=body.official_ref,
        opposing_party=body.opposing_party,
        court_entity=body.court_entity,
        responsible_username=body.responsible_username,
        service_id=body.service_id,
        honorarios_contratados_text=str(body.honorarios_contratados) if body.honorarios_contratados is not None else "",
        costos_directos_estimados_text=str(body.costos_directos_estimados) if body.costos_directos_estimados is not None else "",
        mes_cobro_esperado=body.mes_cobro_esperado,
        estado_cobro=body.estado_cobro,
        fecha_cierre_estimada=body.fecha_cierre_estimada,
        fecha_cierre_real=body.fecha_cierre_real,
        proxima_accion=body.proxima_accion,
    )
    rows = repo.list_cases()
    row = next((r for r in rows if r["id"] == case_id), None)
    if not row:
        raise HTTPException(404, "Caso no encontrado")
    return CaseOut.from_row(row)


@router.delete("/{case_id}", status_code=204)
def archive_case(case_id: int, current_user: LawyerRequired, repo: RepoDep):
    """Antes borraba el expediente sin posibilidad de recuperarlo. Ahora lo archiva
    (papelera) — el purgado permanente vive aparte, en /{case_id}/purge."""
    repo.archive_case(case_id, archived_at=now_iso())


@router.post("/{case_id}/restore", response_model=CaseOut)
def restore_case(case_id: int, current_user: LawyerRequired, repo: RepoDep) -> CaseOut:
    repo.restore_case(case_id)
    rows = repo.list_cases(archived=False)
    row = next((r for r in rows if r["id"] == case_id), None)
    if not row:
        raise HTTPException(404, "Caso no encontrado")
    return CaseOut.from_row(row)


@router.delete("/{case_id}/purge", status_code=204)
def purge_case(case_id: int, current_user: AdminRequired, repo: RepoDep):
    """Borrado real y permanente — solo desde la papelera, solo administrador."""
    repo.delete_case(case_id)


# --- Tasks ---

def _tarea(repo, task_id: int):
    """Releer la tarea con sus etiquetas y asignados — un SELECT * se los deja fuera."""
    row = repo.conn.execute(
        f"SELECT ct.*{repo._SELECT_TAREA_EXTRAS} FROM case_tasks ct WHERE ct.id=%s", (int(task_id),)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Tarea no encontrada")
    return row


@router.get("/tasks", response_model=list[GlobalCaseTaskOut])
def list_all_tasks(
    current_user: CurrentUser,
    repo: RepoDep,
    done: bool | None = None,
    search: str | None = None,
    case_id: int | None = None,
    estado: str | None = None,
    etiqueta_id: int | None = None,
    asignado: str | None = None,
) -> list[GlobalCaseTaskOut]:
    return [
        GlobalCaseTaskOut.from_row(r)
        for r in repo.list_all_case_tasks(done=done, search=search, case_id=case_id, estado=estado,
                                          etiqueta_id=etiqueta_id, asignado=asignado)
    ]


@router.get("/{case_id}/tasks", response_model=list[CaseTaskOut])
def list_tasks(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseTaskOut]:
    return [CaseTaskOut.from_row(row) for row in repo.list_case_tasks(case_id)]


@router.post("/{case_id}/tasks", response_model=CaseTaskOut, status_code=201)
def create_task(case_id: int, body: CaseTaskIn, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    if not current_user["is_admin"] and "tareas.crear" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: tareas.crear")
    task_id = repo.create_case_task(
        case_id=case_id,
        title=body.title,
        due_date=body.due_date,
        notes=body.notes,
        responsible_username=body.responsible_username,
        es_critico=body.es_critico,
        monto_adicional_text=str(body.monto_adicional) if body.monto_adicional is not None else "0",
        costo_real_text=str(body.costo_real) if body.costo_real is not None else "0",
        costo_account_id=body.costo_account_id,
        costo_es_reembolsable=body.costo_es_reembolsable,
        autorizado_por=body.autorizado_por,
        fecha_autorizacion=body.fecha_autorizacion,
        costo_estimado_text=str(body.costo_estimado) if body.costo_estimado is not None else "0",
        asignados=body.asignados,
        etiqueta_ids=body.etiqueta_ids,
        estado=body.estado,
        username=current_user["username"],
        created_at=now_iso(),
    )
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.put("/tasks/{task_id}", response_model=CaseTaskOut)
def update_task(task_id: int, body: CaseTaskUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    """El costo de una diligencia casi nunca se sabe al crear la tarea, sino al volver de
    hacerla: esta ruta permite completarlo (y corregir el cobro) sin rehacer la tarea."""
    if not current_user["is_admin"] and "tareas.editar" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: tareas.editar")
    repo.update_case_task(
        task_id,
        title=body.title,
        due_date=body.due_date,
        notes=body.notes,
        responsible_username=body.responsible_username,
        es_critico=body.es_critico,
        monto_adicional_text=str(body.monto_adicional) if body.monto_adicional is not None else "0",
        costo_real_text=str(body.costo_real) if body.costo_real is not None else "0",
        costo_account_id=body.costo_account_id,
        costo_es_reembolsable=body.costo_es_reembolsable,
        autorizado_por=body.autorizado_por,
        fecha_autorizacion=body.fecha_autorizacion,
        completed_at=body.completed_at,
        costo_estimado_text=str(body.costo_estimado) if body.costo_estimado is not None else None,
        asignados=body.asignados,
        etiqueta_ids=body.etiqueta_ids,
        username=current_user["username"],
    )
    row = repo.conn.execute("SELECT * FROM case_tasks WHERE id=%s", (task_id,)).fetchone()
    return CaseTaskOut.from_row(row)


@router.patch("/tasks/{task_id}/critico", response_model=CaseTaskOut)
def set_task_critico(task_id: int, body: CaseTaskCriticoUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    repo.set_case_task_critico(task_id, body.es_critico)
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.patch("/tasks/{task_id}/responsible", response_model=CaseTaskOut)
def set_task_responsible(task_id: int, body: CaseTaskResponsibleUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    if not current_user["is_admin"] and "tareas.editar" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: tareas.editar")
    repo.set_case_task_responsible(task_id, body.responsible_username)
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.patch("/tasks/{task_id}/done", response_model=CaseTaskOut)
def set_task_done(task_id: int, body: CaseTaskDone, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    repo.set_case_task_done(task_id, body.done, body.completed_notes, username=current_user["username"])
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.patch("/tasks/{task_id}/estado", response_model=CaseTaskOut)
def set_task_estado(task_id: int, body: CaseTaskEstadoIn, current_user: CurrentUser, repo: RepoDep,
                    _: dict = require_permission("tareas", "editar")) -> CaseTaskOut:
    """Mover la tarjeta de columna en el tablero."""
    repo.set_case_task_estado(task_id, body.estado, username=current_user["username"],
                              completed_notes=body.completed_notes)
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.post("/tasks/{task_id}/cerrar", response_model=CaseTaskOut)
def cerrar_task(task_id: int, body: CaseTaskCierreIn, current_user: CurrentUser, repo: RepoDep,
                _: dict = require_permission("tareas", "editar")) -> CaseTaskOut:
    """Cerrar la tarea con la fecha real, el costo final y lo que se obtuvo."""
    repo.cerrar_case_task(
        task_id,
        completed_at=body.completed_at,
        completed_notes=body.completed_notes,
        costo_real_text=str(body.costo_real) if body.costo_real is not None else None,
        costo_account_id=body.costo_account_id,
        costo_es_reembolsable=body.costo_es_reembolsable,
        username=current_user["username"],
    )
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.patch("/tasks/{task_id}/notes", response_model=CaseTaskOut)
def update_task_notes(task_id: int, body: CaseTaskNotesUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    repo.update_case_task_notes(task_id, body.notes, body.completed_notes)
    return CaseTaskOut.from_row(_tarea(repo, task_id))


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_case_task(task_id, username=current_user["username"])


@router.get("/{case_id}/honorarios-log", response_model=list[CaseHonorariosLogOut])
def get_case_honorarios_log(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseHonorariosLogOut]:
    return [CaseHonorariosLogOut.from_row(row) for row in repo.list_case_honorarios_log(case_id)]


# --- Sessions por caso ---

@router.get("/{case_id}/sessions")
def list_case_sessions(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[dict]:
    return [dict(row) for row in repo.list_sessions_by_case(case_id)]


# --- Adjuntos por caso (caso + sesiones) ---

@router.get("/{case_id}/all-attachments", response_model=list[CaseAttachmentOut])
def list_case_all_attachments(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseAttachmentOut]:
    return [CaseAttachmentOut(**dict(row)) for row in repo.list_case_all_attachments(case_id)]


# --- Registro de horas (servicios cobrados "Por hora") ---

@router.get("/{case_id}/time-entries", response_model=list[CaseTimeEntryOut])
def list_time_entries(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseTimeEntryOut]:
    return [CaseTimeEntryOut.from_row(r) for r in repo.list_case_time_entries(case_id)]


@router.post("/{case_id}/time-entries", response_model=CaseTimeEntryOut, status_code=201)
def create_time_entry(case_id: int, body: CaseTimeEntryIn, current_user: CurrentUser, repo: RepoDep) -> CaseTimeEntryOut:
    if not current_user["is_admin"] and "expedientes.editar" not in current_user["permissions"]:
        raise HTTPException(403, "Sin permiso: expedientes.editar")
    entry_id = repo.create_case_time_entry(
        case_id=case_id,
        username=body.username or current_user["username"],
        work_date=body.work_date,
        hours=body.hours,
        description=body.description,
        billable=body.billable,
        created_at=now_iso(),
    )
    row = repo.conn.execute("SELECT * FROM case_time_entries WHERE id=%s", (entry_id,)).fetchone()
    return CaseTimeEntryOut.from_row(row)


@router.delete("/time-entries/{entry_id}", status_code=204)
def delete_time_entry(entry_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_case_time_entry(entry_id)


# Declarada al final: las rutas fijas (/tasks, /choices, /conflicto-interes...) deben
# resolverse antes que este comodín.
@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: int, current_user: CurrentUser, repo: RepoDep) -> CaseOut:
    rows = repo.list_cases(case_id=case_id)
    if not rows:
        raise HTTPException(404, "Expediente no encontrado")
    return CaseOut.from_row(rows[0])

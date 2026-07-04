from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.case import CaseAttachmentOut, CaseIn, CaseOut, CaseTaskDone, CaseTaskIn, CaseTaskNotesUpdate, CaseTaskOut, CaseUpdate, GlobalCaseTaskOut

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
def list_cases(
    current_user: CurrentUser,
    repo: RepoDep,
    search: str | None = None,
    status: str | None = None,
    client_id: int | None = None,
) -> list[CaseOut]:
    return [CaseOut.from_row(row) for row in repo.list_cases(search=search, status=status, client_id=client_id)]


@router.get("/choices")
def case_choices(current_user: CurrentUser, repo: RepoDep, client_id: int | None = None) -> list[dict]:
    return [{"id": cid, "title": title} for cid, title in repo.case_choices(client_id=client_id)]


@router.post("", response_model=CaseOut, status_code=201)
def create_case(body: CaseIn, current_user: CurrentUser, repo: RepoDep) -> CaseOut:
    case_id = repo.create_case(
        client_id=body.client_id,
        service_area=body.service_area,
        title=body.title,
        status=body.status,
        priority=body.priority,
        opened_at=body.opened_at,
        notes=body.notes,
        service_product_id=body.service_product_id,
        internal_ref=body.internal_ref,
        official_ref=body.official_ref,
        opposing_party=body.opposing_party,
        court_entity=body.court_entity,
        responsible_username=body.responsible_username,
        created_at=now_iso(),
    )
    rows = repo.list_cases()
    row = next((r for r in rows if r["id"] == case_id), None)
    if not row:
        raise HTTPException(500, "Error al recuperar el caso creado")
    return CaseOut.from_row(row)


@router.put("/{case_id}", response_model=CaseOut)
def update_case(case_id: int, body: CaseUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseOut:
    repo.update_case(
        case_id,
        service_area=body.service_area,
        title=body.title,
        status=body.status,
        priority=body.priority,
        opened_at=body.opened_at,
        closed_at=body.closed_at,
        notes=body.notes,
        service_product_id=body.service_product_id,
        internal_ref=body.internal_ref,
        official_ref=body.official_ref,
        opposing_party=body.opposing_party,
        court_entity=body.court_entity,
        responsible_username=body.responsible_username,
    )
    rows = repo.list_cases()
    row = next((r for r in rows if r["id"] == case_id), None)
    if not row:
        raise HTTPException(404, "Caso no encontrado")
    return CaseOut.from_row(row)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_case(case_id)


# --- Tasks ---

@router.get("/tasks", response_model=list[GlobalCaseTaskOut])
def list_all_tasks(
    current_user: CurrentUser,
    repo: RepoDep,
    done: bool | None = None,
    search: str | None = None,
    case_id: int | None = None,
) -> list[GlobalCaseTaskOut]:
    return [GlobalCaseTaskOut.from_row(r) for r in repo.list_all_case_tasks(done=done, search=search, case_id=case_id)]


@router.get("/{case_id}/tasks", response_model=list[CaseTaskOut])
def list_tasks(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseTaskOut]:
    return [CaseTaskOut.from_row(row) for row in repo.list_case_tasks(case_id)]


@router.post("/{case_id}/tasks", response_model=CaseTaskOut, status_code=201)
def create_task(case_id: int, body: CaseTaskIn, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    task_id = repo.create_case_task(
        case_id=case_id,
        title=body.title,
        due_date=body.due_date,
        notes=body.notes,
        responsible_username=body.responsible_username,
        created_at=now_iso(),
    )
    row = repo.conn.execute("SELECT * FROM case_tasks WHERE id=%s", (task_id,)).fetchone()
    return CaseTaskOut.from_row(row)


@router.patch("/tasks/{task_id}/done", response_model=CaseTaskOut)
def set_task_done(task_id: int, body: CaseTaskDone, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    repo.set_case_task_done(task_id, body.done, body.completed_notes)
    row = repo.conn.execute("SELECT * FROM case_tasks WHERE id=%s", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Tarea no encontrada")
    return CaseTaskOut.from_row(row)


@router.patch("/tasks/{task_id}/notes", response_model=CaseTaskOut)
def update_task_notes(task_id: int, body: CaseTaskNotesUpdate, current_user: CurrentUser, repo: RepoDep) -> CaseTaskOut:
    repo.update_case_task_notes(task_id, body.notes, body.completed_notes)
    row = repo.conn.execute("SELECT * FROM case_tasks WHERE id=%s", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Tarea no encontrada")
    return CaseTaskOut.from_row(row)


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_case_task(task_id)


# --- Sessions por caso ---

@router.get("/{case_id}/sessions")
def list_case_sessions(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[dict]:
    return [dict(row) for row in repo.list_sessions_by_case(case_id)]


# --- Adjuntos por caso (caso + sesiones) ---

@router.get("/{case_id}/all-attachments", response_model=list[CaseAttachmentOut])
def list_case_all_attachments(case_id: int, current_user: CurrentUser, repo: RepoDep) -> list[CaseAttachmentOut]:
    return [CaseAttachmentOut(**dict(row)) for row in repo.list_case_all_attachments(case_id)]

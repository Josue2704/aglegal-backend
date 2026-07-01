from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from aglegal.db import now_iso
from aglegal.repositories import ATTACH_ENTITY_TYPES

from ..deps import CurrentUser, DbDep, RepoDep
from ..schemas.attachment import AttachmentOut

router = APIRouter(prefix="/attachments", tags=["attachments"])

_DATA_DIR = Path("data")


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    entity_type: str,
    entity_id: int,
    current_user: CurrentUser,
    repo: RepoDep,
) -> list[AttachmentOut]:
    return [AttachmentOut(**dict(row)) for row in repo.list_attachments(entity_type=entity_type, entity_id=entity_id)]


@router.post("/upload", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    current_user: CurrentUser,
    conn: DbDep,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    file: UploadFile = File(...),
) -> AttachmentOut:
    if entity_type not in ATTACH_ENTITY_TYPES:
        raise HTTPException(400, f"Tipo inválido. Valores permitidos: {ATTACH_ENTITY_TYPES}")

    suffix = Path(file.filename or "file").suffix
    token = uuid.uuid4().hex[:12]
    dest = _DATA_DIR / "attachments" / entity_type / str(entity_id) / f"{token}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(await file.read())

    cur = conn.execute(
        "INSERT INTO attachments(entity_type, entity_id, original_name, stored_path, created_at) VALUES(?,?,?,?,?)",
        (entity_type, entity_id, file.filename or dest.name, str(dest.as_posix()), now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM attachments WHERE id=?", (cur.lastrowid,)).fetchone()
    return AttachmentOut(**dict(row))


@router.get("/download/{attachment_id}")
def download_attachment(attachment_id: int, current_user: CurrentUser, conn: DbDep) -> FileResponse:
    row = conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Adjunto no encontrado")
    path = Path(str(row["stored_path"]))
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado en disco")
    return FileResponse(path, filename=str(row["original_name"]))


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_attachment(attachment_id)

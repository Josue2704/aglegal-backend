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


_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

_ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".odt", ".ods",
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".txt", ".csv", ".zip",
}


_VALID_DOC_ROLES = {"guide", "evidence"}


@router.post("/upload", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    current_user: CurrentUser,
    conn: DbDep,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    file: UploadFile = File(...),
    doc_role: str | None = Form(None),
) -> AttachmentOut:
    if entity_type not in ATTACH_ENTITY_TYPES:
        raise HTTPException(400, f"Tipo inválido. Valores permitidos: {ATTACH_ENTITY_TYPES}")

    suffix = Path(file.filename or "file").suffix.lower()
    if suffix not in _ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Tipo de archivo no permitido: {suffix}")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "El archivo supera el límite de 20 MB")

    role = doc_role if doc_role in _VALID_DOC_ROLES else None

    token = uuid.uuid4().hex[:12]
    dest = _DATA_DIR / "attachments" / entity_type / str(entity_id) / f"{token}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)

    cur = conn.execute(
        "INSERT INTO attachments(entity_type, entity_id, original_name, stored_path, doc_role, created_at) VALUES(%s,%s,%s,%s,%s,%s)",
        (entity_type, entity_id, file.filename or dest.name, str(dest.as_posix()), role, now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM attachments WHERE id=%s", (cur.lastrowid,)).fetchone()
    return AttachmentOut(**dict(row))


@router.get("/download/{attachment_id}")
def download_attachment(attachment_id: int, current_user: CurrentUser, conn: DbDep) -> FileResponse:
    row = conn.execute("SELECT * FROM attachments WHERE id=%s", (attachment_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Adjunto no encontrado")
    path = Path(str(row["stored_path"]))
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado en disco")
    return FileResponse(path, filename=str(row["original_name"]))


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: int, current_user: CurrentUser, repo: RepoDep):
    repo.delete_attachment(attachment_id)

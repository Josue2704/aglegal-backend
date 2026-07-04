from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.client import ClientIn, ClientOut, HistoryItem

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(current_user: CurrentUser, repo: RepoDep, search: str | None = None) -> list[ClientOut]:
    return [ClientOut(**dict(row)) for row in repo.list_clients(search=search)]


@router.get("/choices")
def client_choices(current_user: CurrentUser, repo: RepoDep) -> list[dict]:
    return [{"id": cid, "name": name} for cid, name in repo.client_choices()]


@router.post("", response_model=ClientOut, status_code=201)
def create_client(body: ClientIn, current_user: CurrentUser, repo: RepoDep) -> ClientOut:
    client_id = repo.create_client(
        name=body.name,
        client_type=body.client_type,
        id_number=body.id_number,
        phone=body.phone,
        phone2=body.phone2,
        email=body.email,
        address=body.address,
        notes=body.notes,
        created_at=now_iso(),
    )
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    return ClientOut(**dict(row))


@router.put("/{client_id}", response_model=ClientOut)
def update_client(client_id: int, body: ClientIn, current_user: CurrentUser, repo: RepoDep) -> ClientOut:
    repo.update_client(
        client_id,
        name=body.name,
        client_type=body.client_type,
        id_number=body.id_number,
        phone=body.phone,
        phone2=body.phone2,
        email=body.email,
        address=body.address,
        notes=body.notes,
    )
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")
    return ClientOut(**dict(row))


@router.delete("/{client_id}", status_code=204)
def delete_client(client_id: int, current_user: LawyerRequired, repo: RepoDep):
    repo.delete_client(client_id)


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, current_user: CurrentUser, repo: RepoDep) -> ClientOut:
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")
    return ClientOut(**dict(row))


@router.get("/{client_id}/history", response_model=list[HistoryItem])
def client_history(client_id: int, current_user: CurrentUser, repo: RepoDep) -> list[HistoryItem]:
    return [HistoryItem(**item) for item in repo.client_history(client_id)]

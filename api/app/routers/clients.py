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
    if not current_user["is_admin"] and "clientes.crear" not in current_user["permissions"]:
        from fastapi import HTTPException
        raise HTTPException(403, "Sin permiso: clientes.crear")
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
    if not current_user["is_admin"] and "clientes.editar" not in current_user["permissions"]:
        from fastapi import HTTPException
        raise HTTPException(403, "Sin permiso: clientes.editar")
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


@router.get("/{client_id}/statement")
def client_statement(client_id: int, current_user: CurrentUser, repo: RepoDep) -> dict:
    """Estado de cuenta completo del cliente: sesiones, facturas, pagos y saldo."""
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")

    # Sessions summary
    sessions = repo.conn.execute(
        """SELECT id, session_date, start_time, end_time, consult_type, status, notes
           FROM sessions WHERE client_id=%s ORDER BY session_date DESC""",
        (client_id,),
    ).fetchall()

    sessions_by_status: dict[str, int] = {}
    for s in sessions:
        sessions_by_status[s["status"]] = sessions_by_status.get(s["status"], 0) + 1

    # Cases
    cases = repo.conn.execute(
        "SELECT id, title, status, priority, created_at FROM cases WHERE client_id=%s ORDER BY created_at DESC",
        (client_id,),
    ).fetchall()

    # Invoices
    invoices = repo.conn.execute(
        """SELECT id, invoice_number, issued_at, total_cents, status
           FROM invoices WHERE client_id=%s ORDER BY issued_at DESC""",
        (client_id,),
    ).fetchall()

    total_invoiced_cents = sum(int(i["total_cents"] or 0) for i in invoices)
    paid_invoices_cents = sum(
        int(i["total_cents"] or 0) for i in invoices if str(i["status"]).lower() == "pagada"
    )
    pending_invoices_cents = total_invoiced_cents - paid_invoices_cents

    # Incomes linked to client
    incomes = repo.conn.execute(
        """SELECT id, amount_cents, description, income_date, category_id
           FROM incomes WHERE client_id=%s ORDER BY income_date DESC""",
        (client_id,),
    ).fetchall()
    total_received_cents = sum(int(i["amount_cents"] or 0) for i in incomes)

    return {
        "client": dict(row),
        "sessions": {
            "total": len(sessions),
            "by_status": sessions_by_status,
            "list": [dict(s) for s in sessions[:20]],
        },
        "cases": {
            "total": len(cases),
            "list": [dict(c) for c in cases],
        },
        "financial": {
            "total_invoiced_cents": total_invoiced_cents,
            "paid_invoices_cents": paid_invoices_cents,
            "pending_invoices_cents": pending_invoices_cents,
            "total_received_cents": total_received_cents,
            "balance_cents": pending_invoices_cents - total_received_cents,
            "invoices": [dict(i) for i in invoices],
            "incomes": [dict(i) for i in incomes[:20]],
        },
    }

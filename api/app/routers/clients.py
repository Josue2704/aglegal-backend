from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import AdminRequired, CurrentUser, LawyerRequired, RepoDep, require_permission
from ..schemas.client import ClientIn, ClientOut, HistoryItem

from ..access import require_any, check

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut], dependencies=[require_permission('clientes', 'ver')])
def list_clients(current_user: CurrentUser, repo: RepoDep, search: str | None = None, archived: bool = False) -> list[ClientOut]:
    return [ClientOut(**dict(row)) for row in repo.list_clients(search=search, archived=archived)]


@router.get("/choices", dependencies=[require_any('clientes.ver','clientes.crear','clientes.editar','expedientes.ver','expedientes.crear','expedientes.editar','tareas.ver','tareas.crear','tareas.editar','agenda.ver','agenda.crear','agenda.editar','pipeline.ver','pipeline.crear','pipeline.editar','flujo_caja.ver','flujo_caja.crear','flujo_caja.editar','facturas.ver','facturas.crear','facturas.editar')])
def client_choices(current_user: CurrentUser, repo: RepoDep) -> list[dict]:
    return [{"id": cid, "name": name} for cid, name in repo.client_choices()]


@router.post("", response_model=ClientOut, status_code=201, dependencies=[require_permission('clientes', 'crear')])
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


@router.put("/{client_id}", response_model=ClientOut, dependencies=[require_permission('clientes', 'editar')])
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


@router.delete("/{client_id}", status_code=204, dependencies=[require_permission('clientes', 'eliminar')])
def archive_client(client_id: int, current_user: CurrentUser, repo: RepoDep):
    """Antes borraba el cliente sin posibilidad de recuperarlo. Ahora lo archiva
    (papelera) — el registro y su historial se conservan, solo desaparece de las
    vistas activas. El purgado permanente vive aparte, en /{client_id}/purge."""
    repo.archive_client(client_id, archived_at=now_iso())


@router.post("/{client_id}/restore", response_model=ClientOut, dependencies=[require_permission('clientes', 'editar')])
def restore_client(client_id: int, current_user: CurrentUser, repo: RepoDep) -> ClientOut:
    repo.restore_client(client_id)
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")
    return ClientOut(**dict(row))


@router.delete("/{client_id}/purge", status_code=204)
def purge_client(client_id: int, current_user: AdminRequired, repo: RepoDep):
    """Borrado real y permanente — solo desde la papelera, solo administrador."""
    repo.delete_client(client_id)


@router.get("/{client_id}", response_model=ClientOut, dependencies=[require_permission('clientes', 'ver')])
def get_client(client_id: int, current_user: CurrentUser, repo: RepoDep) -> ClientOut:
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")
    return ClientOut(**dict(row))


@router.get("/{client_id}/history", response_model=list[HistoryItem], dependencies=[require_permission('clientes', 'ver')])
def client_history(client_id: int, current_user: CurrentUser, repo: RepoDep) -> list[HistoryItem]:
    check(current_user, 'agenda.ver')
    check(current_user, 'flujo_caja.ver')
    return [HistoryItem(**item) for item in repo.client_history(client_id)]


@router.get("/{client_id}/statement", dependencies=[require_permission('clientes', 'ver')])
def client_statement(client_id: int, current_user: CurrentUser, repo: RepoDep) -> dict:
    """Estado de cuenta completo del cliente: sesiones, facturas, pagos y saldo."""
    row = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (client_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Cliente no encontrado")

    check(current_user, 'facturas.ver')
    check(current_user, 'flujo_caja.ver')
    check(current_user, 'agenda.ver')
    check(current_user, 'expedientes.ver')
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
    invoices = [dict(i,issued_at=i['invoice_date']) for i in repo.list_invoices(client_id)
                if i['status'] not in ('Borrador','Cancelada')]
    total_invoiced_cents = sum(i['total_cents'] for i in invoices)
    paid_invoices_cents = sum(i['paid_cents'] for i in invoices)
    pending_invoices_cents = sum(i['balance_cents'] for i in invoices)

    # Incomes linked to client
    incomes = repo.conn.execute(
        """SELECT id, amount_cents, detail AS description, income_date
           FROM incomes WHERE client_id=%s ORDER BY income_date DESC""",
        (client_id,),
    ).fetchall()
    total_received_cents = sum(int(i["amount_cents"] or 0) for i in incomes)

    # Indicadores de cliente (Fase 6): servicios contratados, facturación acumulada,
    # fecha del último servicio, recurrencia (2+ expedientes distintos).
    servicios_contratados = repo.conn.execute(
        "SELECT COUNT(DISTINCT service_id) AS n FROM cases WHERE client_id=%s AND service_id IS NOT NULL",
        (client_id,),
    ).fetchone()["n"]
    ultimo_servicio_row = repo.conn.execute(
        "SELECT MAX(opened_at) AS fecha FROM cases WHERE client_id=%s",
        (client_id,),
    ).fetchone()
    facturacion_acumulada_row = repo.conn.execute(
        "SELECT COALESCE(SUM(monto_neto_operativo_cents), 0) AS total FROM incomes WHERE client_id=%s",
        (client_id,),
    ).fetchone()
    indicadores = {
        "servicios_contratados": int(servicios_contratados or 0),
        "facturacion_acumulada_cents": int(facturacion_acumulada_row["total"] or 0),
        "ultimo_servicio": ultimo_servicio_row["fecha"],
        "expedientes_totales": len(cases),
        "cliente_recurrente": len(cases) >= 2,
    }

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
            "balance_cents": pending_invoices_cents,
            "invoices": [dict(i) for i in invoices],
            "incomes": [dict(i) for i in incomes[:20]],
        },
        "indicadores": indicadores,
    }

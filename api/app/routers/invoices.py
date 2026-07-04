from __future__ import annotations

from fastapi import APIRouter, HTTPException

from aglegal.db import now_iso

from ..deps import CurrentUser, LawyerRequired, RepoDep
from ..schemas.invoice import (
    InvoiceIn,
    InvoiceItemOut,
    InvoiceOut,
    InvoiceStatusUpdate,
    InvoiceUpdate,
    UnbilledCost,
    UnbilledItems,
    UnbilledSession,
    UnbilledTask,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


def _load(repo, invoice_id: int) -> InvoiceOut:
    row = repo.get_invoice(invoice_id)
    if not row:
        raise HTTPException(404, "Factura no encontrada")
    items = [InvoiceItemOut.from_row(r) for r in repo.get_invoice_items(invoice_id)]
    return InvoiceOut.from_row(row, items)


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    current_user: CurrentUser,
    repo: RepoDep,
    client_id: int | None = None,
) -> list[InvoiceOut]:
    rows = repo.list_invoices(client_id=client_id)
    result = []
    for row in rows:
        inv_id = int(row["id"])
        items = [InvoiceItemOut.from_row(r) for r in repo.get_invoice_items(inv_id)]
        result.append(InvoiceOut.from_row(row, items))
    return result


@router.get("/next-number")
def next_invoice_number(current_user: CurrentUser, repo: RepoDep) -> dict:
    return {"invoice_number": repo.next_invoice_number()}


@router.get("/unbilled/{client_id}", response_model=UnbilledItems)
def unbilled_items(
    client_id: int,
    current_user: CurrentUser,
    repo: RepoDep,
) -> UnbilledItems:
    data = repo.get_unbilled_items(client_id)
    sessions = [
        UnbilledSession(
            id=r["id"],
            session_date=r["session_date"],
            consult_type=r["consult_type"],
            notes=r.get("notes"),
        )
        for r in data["sessions"]
    ]
    tasks = [
        UnbilledTask(
            id=r["id"],
            title=r["title"],
            due_date=r.get("due_date"),
            case_title=r.get("case_title"),
            case_id=r.get("case_id"),
        )
        for r in data["tasks"]
    ]
    costs = [
        UnbilledCost(
            id=r["id"],
            concept=r["concept"],
            detail=r.get("detail"),
            amount=r["amount_cents"] / 100,
            cost_date=r["cost_date"],
        )
        for r in data["costs"]
    ]
    return UnbilledItems(sessions=sessions, tasks=tasks, costs=costs)


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, current_user: CurrentUser, repo: RepoDep) -> InvoiceOut:
    return _load(repo, invoice_id)


@router.post("", response_model=InvoiceOut, status_code=201)
def create_invoice(body: InvoiceIn, current_user: LawyerRequired, repo: RepoDep) -> InvoiceOut:
    items = [item.model_dump() for item in body.items]
    invoice_id = repo.create_invoice(
        client_id=body.client_id,
        case_id=body.case_id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        due_date=body.due_date,
        notes=body.notes,
        firm_name=body.firm_name,
        firm_phone=body.firm_phone,
        firm_email=body.firm_email,
        firm_address=body.firm_address,
        firm_tax_id=body.firm_tax_id,
        items=items,
        created_at=now_iso(),
    )
    return _load(repo, invoice_id)


@router.put("/{invoice_id}", response_model=InvoiceOut)
def update_invoice(
    invoice_id: int,
    body: InvoiceUpdate,
    current_user: LawyerRequired,
    repo: RepoDep,
) -> InvoiceOut:
    if not repo.get_invoice(invoice_id):
        raise HTTPException(404, "Factura no encontrada")
    items = [item.model_dump() for item in body.items]
    repo.update_invoice(
        invoice_id,
        invoice_number=body.invoice_number,
        invoice_date=body.invoice_date,
        due_date=body.due_date,
        status=body.status,
        notes=body.notes,
        firm_name=body.firm_name,
        firm_phone=body.firm_phone,
        firm_email=body.firm_email,
        firm_address=body.firm_address,
        firm_tax_id=body.firm_tax_id,
        items=items,
        created_at=now_iso(),
    )
    return _load(repo, invoice_id)


@router.patch("/{invoice_id}/status", response_model=InvoiceOut)
def update_status(
    invoice_id: int,
    body: InvoiceStatusUpdate,
    current_user: LawyerRequired,
    repo: RepoDep,
) -> InvoiceOut:
    if not repo.get_invoice(invoice_id):
        raise HTTPException(404, "Factura no encontrada")
    repo.update_invoice_status(invoice_id, body.status)
    return _load(repo, invoice_id)


@router.delete("/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int, current_user: LawyerRequired, repo: RepoDep):
    if not repo.get_invoice(invoice_id):
        raise HTTPException(404, "Factura no encontrada")
    repo.delete_invoice(invoice_id)

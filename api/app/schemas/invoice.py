from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class InvoiceItemIn(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    entity_type: str | None = None
    entity_id: int | None = None


class InvoiceIn(BaseModel):
    client_id: int
    case_id: int | None = None
    invoice_number: str
    invoice_date: str
    due_date: str | None = None
    notes: str | None = None
    firm_name: str | None = None
    firm_phone: str | None = None
    firm_email: str | None = None
    firm_address: str | None = None
    firm_tax_id: str | None = None
    items: list[InvoiceItemIn] = []


class InvoiceUpdate(BaseModel):
    invoice_number: str
    invoice_date: str
    due_date: str | None = None
    notes: str | None = None
    firm_name: str | None = None
    firm_phone: str | None = None
    firm_email: str | None = None
    firm_address: str | None = None
    firm_tax_id: str | None = None
    status: str = "Borrador"
    items: list[InvoiceItemIn] = []


class InvoiceStatusUpdate(BaseModel):
    status: str


class InvoiceItemOut(BaseModel):
    id: int
    invoice_id: int
    description: str
    quantity: float
    unit_price: float
    subtotal: float
    entity_type: str | None
    entity_id: int | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> InvoiceItemOut:
        d = dict(row)
        unit_price = (d.get("unit_price_cents") or 0) / 100
        qty = float(d.get("quantity") or 1)
        return cls(
            id=d["id"],
            invoice_id=d["invoice_id"],
            description=d["description"],
            quantity=qty,
            unit_price=unit_price,
            subtotal=round(unit_price * qty, 2),
            entity_type=d.get("entity_type"),
            entity_id=d.get("entity_id"),
            created_at=d["created_at"],
        )


class InvoiceOut(BaseModel):
    id: int
    invoice_number: str
    client_id: int
    client_name: str | None
    case_id: int | None
    case_title: str | None
    invoice_date: str
    due_date: str | None
    status: str
    notes: str | None
    firm_name: str | None
    firm_phone: str | None
    firm_email: str | None
    firm_address: str | None
    firm_tax_id: str | None
    total: float
    has_income: bool = False
    items: list[InvoiceItemOut] = []
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any, items: list[InvoiceItemOut] | None = None) -> InvoiceOut:
        d = dict(row)
        return cls(
            id=d["id"],
            invoice_number=d["invoice_number"],
            client_id=d["client_id"],
            client_name=d.get("client_name"),
            case_id=d.get("case_id"),
            case_title=d.get("case_title"),
            invoice_date=d["invoice_date"],
            due_date=d.get("due_date"),
            status=d["status"],
            notes=d.get("notes"),
            firm_name=d.get("firm_name"),
            firm_phone=d.get("firm_phone"),
            firm_email=d.get("firm_email"),
            firm_address=d.get("firm_address"),
            firm_tax_id=d.get("firm_tax_id"),
            total=(d.get("total_cents") or 0) / 100,
            has_income=bool(d.get("has_income", 0)),
            items=items or [],
            created_at=d["created_at"],
        )


class UnbilledSession(BaseModel):
    id: int
    session_date: str
    consult_type: str
    notes: str | None


class UnbilledTask(BaseModel):
    id: int
    title: str
    due_date: str | None
    case_title: str | None
    case_id: int | None


class UnbilledCost(BaseModel):
    id: int
    concept: str
    detail: str | None
    amount: float
    cost_date: str


class UnbilledItems(BaseModel):
    sessions: list[UnbilledSession]
    tasks: list[UnbilledTask]
    costs: list[UnbilledCost]

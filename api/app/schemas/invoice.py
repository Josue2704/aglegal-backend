from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InvoiceItemIn(BaseModel):
    description: str = Field(min_length=1)
    quantity: float = Field(default=1.0, gt=0, le=1000000, allow_inf_nan=False)
    unit_price: float = Field(gt=0, le=100000000, allow_inf_nan=False)
    charge_type: str = "Honorario"
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


class InvoicePaymentIn(BaseModel):
    amount: float = Field(gt=0, allow_inf_nan=False)
    income_date: str | None = None
    account_id: int | None = None
    detail: str = ""
    income_id: int | None = None
    request_key: str = Field(min_length=8, max_length=100)


class InvoiceItemOut(BaseModel):
    id: int
    invoice_id: int
    description: str
    quantity: float
    unit_price: float
    subtotal: float
    charge_type: str = "Honorario"
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
            subtotal=(d.get("subtotal_cents") or 0) / 100,
            charge_type=d.get("charge_type", "Honorario"),
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
    paid: float = 0
    balance: float = 0
    reimbursement_total: float = 0
    overdue: bool = False
    needs_review: bool = False
    payments: list[dict] = []
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
            paid=d.get('paid_cents', 0) / 100,
            balance=d.get('balance_cents', 0) / 100,
            reimbursement_total=d.get('reimbursement_total_cents', 0) / 100,
            overdue=d.get('overdue', False),
            needs_review=d.get('needs_review', False),
            items=items or [],
            created_at=d["created_at"],
        )


class UnbilledSession(BaseModel):
    id: int
    session_date: str
    consult_type: str
    notes: str | None


class UnbilledTask(BaseModel):
    monto_adicional_cents: int = 0
    costo_real_cents: int = 0
    costo_es_reembolsable: bool = False
    cobro_anticipado: bool = False
    completed_at: str | None = None
    completed_notes: str | None = None
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


class UnbilledTimeEntry(BaseModel):
    id: int
    work_date: str
    hours: float
    description: str | None
    case_title: str | None
    case_id: int | None


class UnbilledItems(BaseModel):
    summary: dict | None = None
    sessions: list[UnbilledSession]
    tasks: list[UnbilledTask]
    costs: list[UnbilledCost]
    time_entries: list[UnbilledTimeEntry] = []

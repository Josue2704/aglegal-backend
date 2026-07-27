from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class IncomeIn(BaseModel):
    amount: float
    income_date: str
    client_id: int | None = None
    case_id: int | None = None
    detail: str = ""
    invoice_id: int | None = None
    account_id: int | None = None
    service_id: int | None = None
    monto_iva: float | None = None
    monto_reembolsable: float | None = None


class IncomeOut(BaseModel):
    id: int
    amount: float
    income_date: str
    client_id: int | None = None
    client_name: str | None = None
    case_id: int | None = None
    case_title: str | None = None
    detail: str | None = None
    concept: str
    invoice_id: int | None = None
    invoice_number: str | None = None
    created_at: str
    account_id: int | None = None
    account_code: str | None = None
    account_nombre: str | None = None
    service_id: int | None = None
    service_code: str | None = None
    service_nombre: str | None = None
    monto_iva: float = 0
    monto_reembolsable: float = 0
    monto_neto_operativo: float = 0

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> IncomeOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        d["monto_iva"] = (d.pop("monto_iva_cents", 0) or 0) / 100
        d["monto_reembolsable"] = (d.pop("monto_reembolsable_cents", 0) or 0) / 100
        d["monto_neto_operativo"] = (d.pop("monto_neto_operativo_cents", 0) or 0) / 100
        return cls(**d)

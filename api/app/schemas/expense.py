from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ExpenseIn(BaseModel):
    detail: str
    amount: float
    expense_date: str
    notes: str = ""
    account_id: int | None = None
    monto_iva: float | None = None
    monto_reembolsable: float | None = None


class ExpenseOut(BaseModel):
    id: int
    detail: str | None = None
    concept: str
    amount: float
    expense_date: str
    notes: str | None = None
    created_at: str
    account_id: int | None = None
    account_code: str | None = None
    account_nombre: str | None = None
    monto_iva: float = 0
    monto_reembolsable: float = 0
    monto_neto_operativo: float = 0

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ExpenseOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        d["monto_iva"] = (d.pop("monto_iva_cents", 0) or 0) / 100
        d["monto_reembolsable"] = (d.pop("monto_reembolsable_cents", 0) or 0) / 100
        d["monto_neto_operativo"] = (d.pop("monto_neto_operativo_cents", 0) or 0) / 100
        return cls(**d)

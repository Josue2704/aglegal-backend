from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PayrollIn(BaseModel):
    employee_name: str
    role: str = ""
    period: str
    amount: float
    payment_date: str
    notes: str = ""


class PayrollOut(BaseModel):
    id: int
    employee_name: str
    role: str | None = None
    period: str
    amount: float
    payment_date: str
    notes: str | None = None
    expense_id: int | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> PayrollOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        return cls(**d)

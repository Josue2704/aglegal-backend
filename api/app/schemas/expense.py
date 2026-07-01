from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ExpenseIn(BaseModel):
    category_id: int | None = None
    detail: str
    amount: float
    expense_date: str
    notes: str = ""


class ExpenseOut(BaseModel):
    id: int
    category_id: int | None = None
    category_name: str | None = None
    detail: str | None = None
    concept: str
    amount: float
    expense_date: str
    notes: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ExpenseOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        return cls(**d)

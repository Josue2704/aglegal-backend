from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CostIn(BaseModel):
    client_id: int | None = None
    case_id: int | None = None
    category_id: int | None = None
    detail: str
    amount: float
    cost_date: str
    notes: str = ""


class CostOut(BaseModel):
    id: int
    client_id: int | None = None
    client_name: str | None = None
    case_id: int | None = None
    case_title: str | None = None
    category_id: int | None = None
    category_name: str | None = None
    product_name: str | None = None
    detail: str | None = None
    concept: str
    amount: float
    cost_date: str
    notes: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CostOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        return cls(**d)

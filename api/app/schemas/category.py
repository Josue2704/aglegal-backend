from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CategoryIn(BaseModel):
    kind: str
    name: str


class CategoryUpdate(BaseModel):
    name: str


class CategoryOut(BaseModel):
    id: int
    kind: str
    name: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CategoryOut:
        return cls(**dict(row))


class ServiceProductIn(BaseModel):
    category_id: int
    name: str
    description: str = ""
    base_price: float | None = None
    active: bool = True
    service_area: str | None = None


class ServiceProductUpdate(BaseModel):
    category_id: int
    name: str
    description: str = ""
    base_price: float | None = None
    active: bool = True
    service_area: str | None = None


class ServiceProductOut(BaseModel):
    id: int
    category_id: int
    category_name: str | None = None
    name: str
    description: str | None = None
    base_price: float | None = None
    active: bool
    service_area: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ServiceProductOut:
        d = dict(row)
        cents = d.pop("base_price_cents", None)
        d["base_price"] = cents / 100 if cents is not None else None
        d["active"] = bool(d.get("active", 1))
        return cls(**d)

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CaseIn(BaseModel):
    client_id: int
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    notes: str = ""
    service_product_id: int | None = None


class CaseUpdate(BaseModel):
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str = ""
    service_product_id: int | None = None


class CaseOut(BaseModel):
    id: int
    client_id: int
    client_name: str | None = None
    service_area: str
    title: str
    status: str
    priority: str
    opened_at: str
    closed_at: str | None = None
    notes: str | None = None
    service_product_id: int | None = None
    product_name: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseOut:
        return cls(**dict(row))


class CaseAttachmentOut(BaseModel):
    id: int
    entity_type: str
    entity_id: int
    original_name: str
    stored_path: str
    created_at: str
    session_date: str | None = None
    session_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


class CaseTaskIn(BaseModel):
    title: str
    due_date: str | None = None


class CaseTaskDone(BaseModel):
    done: bool


class CaseTaskOut(BaseModel):
    id: int
    case_id: int
    title: str
    done: bool
    due_date: str | None = None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CaseTaskOut:
        d = dict(row)
        d["done"] = bool(d.get("done", 0))
        return cls(**d)

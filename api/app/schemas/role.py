from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class PermissionOut(BaseModel):
    id: int
    module: str
    action: str
    label: str

    @classmethod
    def from_row(cls, row: Any) -> "PermissionOut":
        d = dict(row)
        return cls(id=d["id"], module=d["module"], action=d["action"], label=d["label"])


class RoleOut(BaseModel):
    id: int
    name: str
    description: str | None
    is_system: bool
    permission_count: int = 0
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> "RoleOut":
        d = dict(row)
        return cls(
            id=d["id"], name=d["name"], description=d.get("description"),
            is_system=bool(d.get("is_system", 0)),
            permission_count=int(d.get("permission_count", 0)),
            created_at=d["created_at"],
        )


class RoleDetailOut(RoleOut):
    permissions: list[PermissionOut] = []


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str
    description: str | None = None
    permission_ids: list[int] = []

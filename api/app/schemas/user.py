from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str = ""
    role: str = "Usuario"
    active: bool = True


class UserUpdate(BaseModel):
    full_name: str = ""
    role: str = "Usuario"
    active: bool = True


class PasswordChange(BaseModel):
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str | None = None
    role: str | None = None
    active: bool
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> UserOut:
        d = dict(row)
        d["active"] = bool(d.get("active", 1))
        return cls(**d)

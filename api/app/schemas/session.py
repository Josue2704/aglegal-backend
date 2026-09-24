from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SessionIn(BaseModel):
    client_id: int | None = None
    case_id: int | None = None
    session_date: str
    start_time: str | None = None
    end_time: str | None = None
    consult_type: str
    notes: str = ""
    status: str
    monto_adicional: float | None = None
    # El usuario ya vio el aviso de que choca con otra cita y decidió agendarla igual.
    permitir_solape: bool = False


class SessionOut(BaseModel):
    id: int
    client_id: int | None = None
    client_name: str | None = None
    case_id: int | None = None
    case_title: str | None = None
    session_date: str
    start_time: str | None = None
    end_time: str | None = None
    consult_type: str
    notes: str | None = None
    status: str
    monto_adicional: float = 0
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> SessionOut:
        d = dict(row)
        d["monto_adicional"] = (d.pop("monto_adicional_cents", 0) or 0) / 100
        return cls(**d)

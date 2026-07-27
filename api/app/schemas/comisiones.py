from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class OriginadorIn(BaseModel):
    personal_id: int
    porcentaje_participacion: float
    tipo_origen: str


class OriginadoresSetIn(BaseModel):
    originadores: list[OriginadorIn]


class OriginadorOut(BaseModel):
    id: int
    case_id: int
    personal_id: int
    person_code: str
    persona_nombre: str
    porcentaje_participacion: float
    tipo_origen: str
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> OriginadorOut:
        d = dict(row)
        d["porcentaje_participacion"] = float(d["porcentaje_participacion"])
        return cls(**d)


class ComisionOut(BaseModel):
    id: int
    income_id: int
    income_date: str
    case_id: int
    case_title: str
    personal_id: int
    person_code: str
    persona_nombre: str
    tipo_origen: str
    porcentaje_participacion: float
    base_utilidad_directa: float
    comision: float
    mes_reconocimiento: str
    ajusta_a_commission_id: int | None
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ComisionOut:
        d = dict(row)
        d["porcentaje_participacion"] = float(d["porcentaje_participacion"])
        d["base_utilidad_directa"] = (d.pop("base_utilidad_directa_cents", 0) or 0) / 100
        d["comision"] = (d.pop("comision_cents", 0) or 0) / 100
        return cls(**d)


class ResumenComisionOut(BaseModel):
    personal_id: int
    person_code: str
    persona_nombre: str
    total_comision: float
    total_utilidad_directa: float
    movimientos: int
    ajustes: int

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ResumenComisionOut:
        d = dict(row)
        d["total_comision"] = (d.pop("total_comision_cents", 0) or 0) / 100
        d["total_utilidad_directa"] = (d.pop("total_utilidad_directa_cents", 0) or 0) / 100
        return cls(**d)

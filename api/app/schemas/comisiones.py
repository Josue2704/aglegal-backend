from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from aglegal.repositories import Repository


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


class TramoComisionOut(BaseModel):
    tasa: float
    monto: float


class ComisionOut(BaseModel):
    client_id: int | None = None
    client_name: str | None = None
    estado: str = 'Calculada'
    evidencia: str = ''
    aprobado_por: str | None = None
    aprobado_at: str | None = None
    liquidacion_id: int | None = None
    id: int
    income_id: int | None  # NULL si el cobro fue eliminado — la comisión queda en el historial
    income_date: str | None
    case_id: int
    case_title: str | None
    personal_id: int
    person_code: str
    persona_nombre: str
    tipo_origen: str
    porcentaje_participacion: float
    base_utilidad_directa: float
    comision: float
    mes_reconocimiento: str
    ajusta_a_commission_id: int | None
    motivo: str | None = None
    tramos: list[TramoComisionOut]
    created_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ComisionOut:
        d = dict(row)
        d["porcentaje_participacion"] = float(d["porcentaje_participacion"])
        d["base_utilidad_directa"] = (d.pop("base_utilidad_directa_cents", 0) or 0) / 100
        d["comision"] = (d.pop("comision_cents", 0) or 0) / 100
        antes = d.pop("base_acumulada_antes_cents", None)
        despues = d.pop("base_acumulada_despues_cents", None)
        d["tramos"] = [
            TramoComisionOut(tasa=t["tasa"], monto=t["monto_cents"] / 100)
            for t in Repository.desglose_tramos_comision(d["tipo_origen"], antes, despues)
        ]
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

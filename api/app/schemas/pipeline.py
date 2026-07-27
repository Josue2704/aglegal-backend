from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class OportunidadIn(BaseModel):
    client_id: int | None = None
    prospecto_nombre: str = ""
    prospecto_contacto: str = ""
    service_id: int | None = None
    canal_captacion: str
    origen_negocio: str


class OportunidadUpdate(BaseModel):
    client_id: int | None = None
    prospecto_nombre: str = ""
    prospecto_contacto: str = ""
    service_id: int | None = None
    canal_captacion: str
    origen_negocio: str


class OportunidadTransicion(BaseModel):
    estado: str
    motivo_perdida: str | None = None


class OportunidadOut(BaseModel):
    id: int
    client_id: int | None
    client_name: str | None = None
    prospecto_nombre: str | None
    prospecto_contacto: str | None
    service_id: int | None
    service_code: str | None = None
    service_nombre: str | None = None
    canal_captacion: str
    origen_negocio: str
    estado: str
    motivo_perdida: str | None
    case_id: int | None
    case_internal_ref: str | None = None
    fecha_prospecto: str
    fecha_cotizado: str | None
    fecha_cierre: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> OportunidadOut:
        return cls(**dict(row))


class OportunidadTransicionOut(BaseModel):
    oportunidad: OportunidadOut
    case_id: int | None
    case_internal_ref: str | None = None


class ConversionComercialOut(BaseModel):
    prospectos: int
    cotizados: int
    ganados: int
    perdidos: int
    conversion_pct: float | None

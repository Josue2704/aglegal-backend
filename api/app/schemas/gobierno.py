from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SolicitudIn(BaseModel):
    tipo_solicitud: str
    tipo_registro: str
    nombre_propuesto: str
    categoria_padre: str | None = None
    subcategoria_padre: str | None = None
    codigo_propuesto: str
    descripcion: str = ""
    motivo: str = ""
    etiquetas: str = ""


class SolicitudUpdate(BaseModel):
    nombre_propuesto: str
    categoria_padre: str | None = None
    subcategoria_padre: str | None = None
    codigo_propuesto: str
    descripcion: str = ""
    motivo: str = ""
    etiquetas: str = ""


class SolicitudTransicion(BaseModel):
    estado: str
    resultado_revision_duplicidad: str | None = None
    aprobador: str | None = None
    observaciones: str | None = None


class SolicitudOut(BaseModel):
    id: int
    solicitud_code: str
    fecha_solicitud: str
    tipo_solicitud: str
    tipo_registro: str
    nombre_propuesto: str
    categoria_padre: str | None
    subcategoria_padre: str | None
    codigo_propuesto: str
    codigo_definitivo: str | None
    descripcion: str | None
    motivo: str | None
    etiquetas: str | None
    solicitante: str
    resultado_revision_duplicidad: str | None
    aprobador: str | None
    fecha_aprobacion: str | None
    estado: str
    observaciones: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> SolicitudOut:
        return cls(**dict(row))

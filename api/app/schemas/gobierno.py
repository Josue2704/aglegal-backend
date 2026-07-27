from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class SolicitudIn(BaseModel):
    tipo_solicitud: str
    tipo_registro: str
    nombre_propuesto: str
    categoria_padre: str | None = None
    subcategoria_padre: str | None = None
    codigo_propuesto: str = ""
    descripcion: str = ""
    motivo: str = ""
    etiquetas: str = ""
    entity_id: int | None = None
    unidad_cobro_propuesta: str | None = None
    responsable_sugerido_propuesto: str | None = None
    tarifa_referencia_propuesta: float | None = None
    costo_referencia_propuesta: float | None = None
    horas_estandar_propuesta: float | None = None
    estado_propuesto: str | None = None


class SolicitudUpdate(BaseModel):
    nombre_propuesto: str
    categoria_padre: str | None = None
    subcategoria_padre: str | None = None
    codigo_propuesto: str = ""
    descripcion: str = ""
    motivo: str = ""
    etiquetas: str = ""
    unidad_cobro_propuesta: str | None = None
    responsable_sugerido_propuesto: str | None = None
    tarifa_referencia_propuesta: float | None = None
    costo_referencia_propuesta: float | None = None
    horas_estandar_propuesta: float | None = None
    estado_propuesto: str | None = None


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
    entity_id: int | None = None
    unidad_cobro_propuesta: str | None = None
    responsable_sugerido_propuesto: str | None = None
    tarifa_referencia_propuesta: float | None = None
    costo_referencia_propuesta: float | None = None
    horas_estandar_propuesta: float | None = None
    estado_propuesto: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> SolicitudOut:
        d = dict(row)
        tarifa_cents = d.pop("tarifa_referencia_propuesta_cents", None)
        costo_cents = d.pop("costo_referencia_propuesta_cents", None)
        d["tarifa_referencia_propuesta"] = (tarifa_cents / 100) if tarifa_cents is not None else None
        d["costo_referencia_propuesta"] = (costo_cents / 100) if costo_cents is not None else None
        return cls(**d)

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


# --- Categorías

class CategoriaOut(BaseModel):
    id: int
    category_code: str
    nombre: str
    estado: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CategoriaOut:
        return cls(**dict(row))


# --- Subcategorías

class SubcategoriaOut(BaseModel):
    id: int
    subcategory_code: str
    category_id: int
    category_code: str
    category_nombre: str
    nombre: str
    estado: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> SubcategoriaOut:
        return cls(**dict(row))


# --- Familias

class FamiliaOut(BaseModel):
    id: int
    family_code: str
    nombre: str
    category_id: int
    category_code: str
    category_nombre: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> FamiliaOut:
        return cls(**dict(row))


# --- Servicios

class ServicioOut(BaseModel):
    id: int
    service_code: str
    subcategory_id: int
    subcategory_code: str
    subcategory_nombre: str
    category_id: int
    category_code: str
    category_nombre: str
    nombre: str
    etiquetas: str
    unidad_cobro: str
    responsable_sugerido: str
    tarifa_referencia: float
    costo_referencia: float
    margen_referencia: float
    horas_estandar: float
    estado: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ServicioOut:
        d = dict(row)
        d["tarifa_referencia"] = (d.pop("tarifa_referencia_cents", 0) or 0) / 100
        d["costo_referencia"] = (d.pop("costo_referencia_cents", 0) or 0) / 100
        d["margen_referencia"] = (d.pop("margen_referencia_cents", 0) or 0) / 100
        d["horas_estandar"] = float(d.get("horas_estandar") or 0)
        d["etiquetas"] = d.get("etiquetas") or ""
        return cls(**d)


class ServicioChoice(BaseModel):
    id: int
    service_code: str
    nombre: str
    category_id: int
    category_code: str
    subcategory_id: int
    subcategory_code: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ServicioChoice:
        return cls(**dict(row))


class HistorialEntryOut(BaseModel):
    id: int
    tipo_registro: str
    entity_id: int
    version_anterior: dict
    usuario_id: int | None
    fecha_cambio: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> HistorialEntryOut:
        return cls(**dict(row))

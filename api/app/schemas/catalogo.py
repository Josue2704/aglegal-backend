from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# --- Categorías

class CategoriaIn(BaseModel):
    category_code: str = Field(..., min_length=2, max_length=4)
    nombre: str


class CategoriaUpdate(BaseModel):
    nombre: str
    estado: str


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

class SubcategoriaIn(BaseModel):
    category_id: int
    subcategory_code: str = Field(..., min_length=2, max_length=4)
    nombre: str


class SubcategoriaUpdate(BaseModel):
    nombre: str
    estado: str


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

class FamiliaIn(BaseModel):
    category_id: int
    nombre: str


class FamiliaUpdate(BaseModel):
    nombre: str


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

class ServicioIn(BaseModel):
    subcategory_id: int
    nombre: str
    etiquetas: str = ""
    unidad_cobro: str = "Por definir"
    responsable_sugerido: str = "Por definir"
    tarifa_referencia: float | None = None
    costo_referencia: float | None = None
    horas_estandar: float = 0
    estado: str = "Activo"


class ServicioUpdate(BaseModel):
    nombre: str
    etiquetas: str = ""
    unidad_cobro: str = "Por definir"
    responsable_sugerido: str = "Por definir"
    tarifa_referencia: float | None = None
    costo_referencia: float | None = None
    horas_estandar: float = 0
    estado: str = "Activo"


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

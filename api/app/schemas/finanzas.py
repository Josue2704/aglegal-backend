from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


# --- Plan de cuentas

class CuentaIn(BaseModel):
    account_code: str
    tipo: str
    grupo: str
    subgrupo: str = ""
    nombre: str
    naturaleza: str
    category_id: int | None = None
    family_id: int | None = None
    centro_costo: str
    afecta_utilidad: bool = True
    regla_de_uso: str = ""


class CuentaUpdate(BaseModel):
    grupo: str
    subgrupo: str = ""
    nombre: str
    naturaleza: str
    category_id: int | None = None
    family_id: int | None = None
    centro_costo: str
    afecta_utilidad: bool = True
    regla_de_uso: str = ""
    estado: str


class CuentaOut(BaseModel):
    id: int
    account_code: str
    tipo: str
    grupo: str
    subgrupo: str | None
    nombre: str
    naturaleza: str
    category_id: int | None
    category_code: str | None = None
    category_nombre: str | None = None
    family_id: int | None
    family_code: str | None = None
    family_nombre: str | None = None
    centro_costo: str
    afecta_utilidad: bool
    estado: str
    regla_de_uso: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> CuentaOut:
        d = dict(row)
        d["afecta_utilidad"] = bool(d.get("afecta_utilidad"))
        return cls(**d)


# --- Personal

class PersonaIn(BaseModel):
    persona: str
    cargo: str = ""
    monto_mensual: float | None = None
    mes_inicio: str
    mes_fin: str | None = None


class PersonaUpdate(BaseModel):
    persona: str
    cargo: str = ""
    monto_mensual: float | None = None
    mes_inicio: str
    mes_fin: str | None = None
    estado: str


class PersonaOut(BaseModel):
    id: int
    person_code: str
    persona: str
    cargo: str | None
    monto_mensual: float
    mes_inicio: str
    mes_fin: str | None
    estado: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> PersonaOut:
        d = dict(row)
        d["monto_mensual"] = (d.pop("monto_mensual_cents", 0) or 0) / 100
        return cls(**d)


# --- Gastos fijos

class GastoFijoIn(BaseModel):
    concepto: str
    tipo: str = "Fijo"
    monto_mensual: float | None = None
    mes_inicio: str
    mes_fin: str | None = None


class GastoFijoUpdate(BaseModel):
    concepto: str
    tipo: str = "Fijo"
    monto_mensual: float | None = None
    mes_inicio: str
    mes_fin: str | None = None
    estado: str


class GastoFijoOut(BaseModel):
    id: int
    expense_code: str
    concepto: str
    tipo: str
    monto_mensual: float
    mes_inicio: str
    mes_fin: str | None
    estado: str
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> GastoFijoOut:
        d = dict(row)
        d["monto_mensual"] = (d.pop("monto_mensual_cents", 0) or 0) / 100
        return cls(**d)


# --- Supuestos financieros

class SupuestosIn(BaseModel):
    periodo: str
    costo_variable_pct: float
    margen_operativo_meta_pct: float
    margen_seguridad_pct: float


class SupuestosUpdate(BaseModel):
    costo_variable_pct: float
    margen_operativo_meta_pct: float
    margen_seguridad_pct: float


class SupuestosOut(BaseModel):
    id: int
    periodo: str
    costo_variable_pct: float
    margen_operativo_meta_pct: float
    margen_seguridad_pct: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> SupuestosOut:
        d = dict(row)
        d["costo_variable_pct"] = float(d["costo_variable_pct"])
        d["margen_operativo_meta_pct"] = float(d["margen_operativo_meta_pct"])
        d["margen_seguridad_pct"] = float(d["margen_seguridad_pct"])
        return cls(**d)


# --- Punto de equilibrio

class PuntoEquilibrioOut(BaseModel):
    mes: str
    gastos_fijos: float
    costo_variable_pct: float
    margen_operativo_meta_pct: float
    margen_seguridad_pct: float
    punto_equilibrio: float
    meta_segura: float
    ventas_margen_meta: float | None

    @classmethod
    def from_calc(cls, d: dict) -> PuntoEquilibrioOut:
        return cls(
            mes=d["mes"],
            gastos_fijos=d["gastos_fijos_cents"] / 100,
            costo_variable_pct=d["costo_variable_pct"],
            margen_operativo_meta_pct=d["margen_operativo_meta_pct"],
            margen_seguridad_pct=d["margen_seguridad_pct"],
            punto_equilibrio=d["punto_equilibrio_cents"] / 100,
            meta_segura=d["meta_segura_cents"] / 100,
            ventas_margen_meta=(d["ventas_margen_meta_cents"] / 100) if d["ventas_margen_meta_cents"] is not None else None,
        )


# --- Presupuesto por familia (forecast) y proyección de cierre de mes

class ForecastIn(BaseModel):
    family_id: int
    mes: str
    volumen_meta: float | None = None
    ticket_objetivo: float | None = None
    margen_directo_objetivo_pct: float


class ForecastUpdate(BaseModel):
    volumen_meta: float | None = None
    ticket_objetivo: float | None = None
    margen_directo_objetivo_pct: float


class ForecastOut(BaseModel):
    id: int
    family_id: int
    family_code: str
    family_nombre: str
    mes: str
    volumen_meta: int
    ticket_objetivo: float
    ingreso_proyectado: float
    margen_directo_objetivo_pct: float
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> ForecastOut:
        d = dict(row)
        d["ticket_objetivo"] = (d.pop("ticket_objetivo_cents", 0) or 0) / 100
        d["ingreso_proyectado"] = (d.pop("ingreso_proyectado_cents", 0) or 0) / 100
        d["margen_directo_objetivo_pct"] = float(d["margen_directo_objetivo_pct"])
        return cls(**d)


class CarteraCasoOut(BaseModel):
    id: int
    title: str
    estado_cobro: str
    mes_cobro_esperado: str | None
    saldo_pendiente: float
    probabilidad_cobro: float
    saldo_ponderado: float


class CarteraPonderadaOut(BaseModel):
    mes: str | None
    total_pendiente: float
    total_ponderado: float
    casos: list[CarteraCasoOut]

    @classmethod
    def from_calc(cls, d: dict) -> CarteraPonderadaOut:
        return cls(
            mes=d["mes"],
            total_pendiente=d["total_pendiente_cents"] / 100,
            total_ponderado=d["total_ponderado_cents"] / 100,
            casos=[
                CarteraCasoOut(
                    id=c["id"], title=c["title"], estado_cobro=c["estado_cobro"], mes_cobro_esperado=c["mes_cobro_esperado"],
                    saldo_pendiente=c["saldo_pendiente_cents"] / 100,
                    probabilidad_cobro=c["probabilidad_cobro"],
                    saldo_ponderado=c["saldo_ponderado_cents"] / 100,
                )
                for c in d["casos"]
            ],
        )


class ProyeccionCierreMesOut(BaseModel):
    mes: str
    cobrado_mes: float
    cartera_ponderada_mes: float
    proyeccion_cierre: float
    meta_ingresos: float
    cumplimiento_proyectado_pct: float | None

    @classmethod
    def from_calc(cls, d: dict) -> ProyeccionCierreMesOut:
        return cls(
            mes=d["mes"],
            cobrado_mes=d["cobrado_mes_cents"] / 100,
            cartera_ponderada_mes=d["cartera_ponderada_mes_cents"] / 100,
            proyeccion_cierre=d["proyeccion_cierre_cents"] / 100,
            meta_ingresos=d["meta_ingresos_cents"] / 100,
            cumplimiento_proyectado_pct=d["cumplimiento_proyectado_pct"],
        )

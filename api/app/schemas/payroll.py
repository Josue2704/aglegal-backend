from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class PayrollIn(BaseModel):
    employee_name: str = ""
    role: str = ""
    period: str
    payment_date: str
    notes: str = ""
    personal_id: int | None = None
    modo: str = "manual"
    # modo="manual": monto ya calculado fuera del sistema (bono suelto, ajuste, etc.)
    amount: float | None = None
    # modo="calculado": el motor calcula el neto a partir de estas variables
    salario_base: float | None = None
    horas_extra_cantidad: float = 0
    nocturnidad_horas: float = 0
    bonificaciones: float = 0
    otros_ingresos: float = 0
    descuento_faltas: float = 0
    descuento_prestamos: float = 0
    otros_descuentos: float = 0


class PayrollUpdate(BaseModel):
    payment_date: str
    notes: str = ""
    amount: float


class PayrollOut(BaseModel):
    id: int
    employee_name: str
    role: str | None = None
    period: str
    amount: float
    payment_date: str
    notes: str | None = None
    expense_id: int | None = None
    personal_id: int | None = None
    created_at: str
    modo: str
    salario_base: float | None = None
    horas_extra_cantidad: float = 0
    horas_extra_monto: float = 0
    nocturnidad_horas: float = 0
    nocturnidad_monto: float = 0
    bonificaciones: float = 0
    otros_ingresos: float = 0
    descuento_faltas: float = 0
    descuento_prestamos: float = 0
    otros_descuentos: float = 0
    isss_empleado: float = 0
    afp_empleado: float = 0
    renta: float = 0
    isss_patronal: float = 0
    afp_patronal: float = 0
    total_devengado: float = 0
    total_descuentos: float = 0

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_row(cls, row: Any) -> PayrollOut:
        d = dict(row)
        d["amount"] = (d.pop("amount_cents") or 0) / 100
        salario_base_cents = d.pop("salario_base_cents", None)
        d["salario_base"] = (salario_base_cents / 100) if salario_base_cents is not None else None
        for campo_cents, campo in (
            ("horas_extra_monto_cents", "horas_extra_monto"),
            ("nocturnidad_monto_cents", "nocturnidad_monto"),
            ("bonificaciones_cents", "bonificaciones"),
            ("otros_ingresos_cents", "otros_ingresos"),
            ("descuento_faltas_cents", "descuento_faltas"),
            ("descuento_prestamos_cents", "descuento_prestamos"),
            ("otros_descuentos_cents", "otros_descuentos"),
            ("isss_empleado_cents", "isss_empleado"),
            ("afp_empleado_cents", "afp_empleado"),
            ("renta_cents", "renta"),
            ("isss_patronal_cents", "isss_patronal"),
            ("afp_patronal_cents", "afp_patronal"),
            ("total_devengado_cents", "total_devengado"),
            ("total_descuentos_cents", "total_descuentos"),
        ):
            d.pop(campo_cents, None)
            d[campo] = (row[campo_cents] or 0) / 100
        d.pop("salario_base_cents", None)
        d.pop("payroll_config_id", None)
        return cls(**d)


class PayrollPreviewIn(BaseModel):
    salario_base: float
    horas_extra_cantidad: float = 0
    nocturnidad_horas: float = 0
    bonificaciones: float = 0
    otros_ingresos: float = 0
    descuento_faltas: float = 0
    descuento_prestamos: float = 0
    otros_descuentos: float = 0
    fecha: str | None = None


class PayrollPreviewOut(BaseModel):
    salario_base: float
    horas_extra_monto: float
    nocturnidad_monto: float
    bonificaciones: float
    otros_ingresos: float
    total_devengado: float
    isss_empleado: float
    afp_empleado: float
    renta: float
    descuento_faltas: float
    descuento_prestamos: float
    otros_descuentos: float
    total_descuentos: float
    isss_patronal: float
    afp_patronal: float
    neto: float
    advertencias: list[str] = []

    @classmethod
    def from_calculo(cls, c: Any) -> PayrollPreviewOut:
        return cls(
            salario_base=c.salario_base_cents / 100,
            horas_extra_monto=c.horas_extra_monto_cents / 100,
            nocturnidad_monto=c.nocturnidad_monto_cents / 100,
            bonificaciones=c.bonificaciones_cents / 100,
            otros_ingresos=c.otros_ingresos_cents / 100,
            total_devengado=c.total_devengado_cents / 100,
            isss_empleado=c.isss_empleado_cents / 100,
            afp_empleado=c.afp_empleado_cents / 100,
            renta=c.renta_cents / 100,
            descuento_faltas=c.descuento_faltas_cents / 100,
            descuento_prestamos=c.descuento_prestamos_cents / 100,
            otros_descuentos=c.otros_descuentos_cents / 100,
            total_descuentos=c.total_descuentos_cents / 100,
            isss_patronal=c.isss_patronal_cents / 100,
            afp_patronal=c.afp_patronal_cents / 100,
            neto=c.neto_cents / 100,
            advertencias=c.advertencias,
        )


class PayrollConfigTramoRenta(BaseModel):
    sobre_exceso_de: float
    hasta: float | None = None
    cuota_fija: float
    porcentaje_exceso: float


class PayrollConfigIn(BaseModel):
    vigente_desde: str
    isss_tasa_empleado: float
    isss_tasa_patronal: float
    isss_tope_cotizable: float
    afp_tasa_empleado: float
    afp_tasa_patronal: float
    afp_tope_cotizable: float
    tramos_renta: list[PayrollConfigTramoRenta] = []
    recargo_hora_extra_pct: float = 0.5
    recargo_nocturnidad_pct: float = 0.25
    horas_jornada_mensual: float = 240
    notas: str = ""


class PayrollConfigOut(BaseModel):
    id: int
    vigente_desde: str
    isss_tasa_empleado: float
    isss_tasa_patronal: float
    isss_tope_cotizable: float
    afp_tasa_empleado: float
    afp_tasa_patronal: float
    afp_tope_cotizable: float
    tramos_renta: list[dict]
    recargo_hora_extra_pct: float
    recargo_nocturnidad_pct: float
    horas_jornada_mensual: float
    notas: str | None = None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> PayrollConfigOut:
        d = dict(row)
        d["isss_tope_cotizable"] = (d.pop("isss_tope_cotizable_cents") or 0) / 100
        d["afp_tope_cotizable"] = (d.pop("afp_tope_cotizable_cents") or 0) / 100
        return cls(**d)

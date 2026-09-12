"""Motor de cálculo de planilla (El Salvador).

Toma un salario base y las variables del mes (horas extra, nocturnidad, bonos,
descuentos) más la configuración de ley vigente (`payroll_config`, versionada porque
las tasas cambian) y devuelve el desglose completo: devengado, deducciones de ley,
otras deducciones y neto a pagar.

Este módulo es intencionalmente una función pura sin acceso a base de datos — recibe
la configuración ya resuelta como parámetro — para que sea trivial de probar y de
reutilizar tanto en el endpoint de vista previa como en la creación real de la planilla.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PayrollConfig:
    isss_tasa_empleado: float
    isss_tasa_patronal: float
    isss_tope_cotizable_cents: int
    afp_tasa_empleado: float
    afp_tasa_patronal: float
    afp_tope_cotizable_cents: int
    tramos_renta: list[dict]
    recargo_hora_extra_pct: float
    recargo_nocturnidad_pct: float
    horas_jornada_mensual: float
    id: int | None = None


@dataclass
class PayrollCalculo:
    salario_base_cents: int
    horas_extra_cantidad: float
    horas_extra_monto_cents: int
    nocturnidad_horas: float
    nocturnidad_monto_cents: int
    bonificaciones_cents: int
    otros_ingresos_cents: int
    total_devengado_cents: int
    isss_empleado_cents: int
    afp_empleado_cents: int
    renta_cents: int
    descuento_faltas_cents: int
    descuento_prestamos_cents: int
    otros_descuentos_cents: int
    total_descuentos_cents: int
    isss_patronal_cents: int
    afp_patronal_cents: int
    neto_cents: int
    advertencias: list[str] = field(default_factory=list)


def _renta_sobre_base(base_imponible_cents: int, tramos: list[dict]) -> int:
    """Aplica la tabla de tramos de retención de renta sobre la base imponible.

    Cada tramo: {hasta_cents: int|None, sobre_exceso_de_cents: int, cuota_fija_cents: int,
    porcentaje_exceso: float}. `hasta_cents=None` marca el último tramo (sin techo).
    Los tramos deben venir ordenados de menor a mayor.
    """
    if base_imponible_cents <= 0:
        return 0
    for tramo in tramos:
        techo = tramo.get("hasta_cents")
        if techo is None or base_imponible_cents <= techo:
            exceso = max(0, base_imponible_cents - int(tramo["sobre_exceso_de_cents"]))
            cuota = int(tramo["cuota_fija_cents"]) + round(exceso * float(tramo["porcentaje_exceso"]))
            return max(0, int(cuota))
    return 0


def calcular_planilla(
    *,
    salario_base_cents: int,
    config: PayrollConfig,
    horas_extra_cantidad: float = 0,
    nocturnidad_horas: float = 0,
    bonificaciones_cents: int = 0,
    otros_ingresos_cents: int = 0,
    descuento_faltas_cents: int = 0,
    descuento_prestamos_cents: int = 0,
    otros_descuentos_cents: int = 0,
) -> PayrollCalculo:
    if salario_base_cents < 0:
        raise ValueError("El salario base no puede ser negativo")
    for nombre, valor in (
        ("horas extra", horas_extra_cantidad),
        ("horas de nocturnidad", nocturnidad_horas),
    ):
        if valor < 0:
            raise ValueError(f"Las {nombre} no pueden ser negativas")
    for nombre, valor in (
        ("bonificaciones", bonificaciones_cents),
        ("otros ingresos", otros_ingresos_cents),
        ("descuento por faltas", descuento_faltas_cents),
        ("descuento por préstamos", descuento_prestamos_cents),
        ("otros descuentos", otros_descuentos_cents),
    ):
        if valor < 0:
            raise ValueError(f"El monto de {nombre} no puede ser negativo")

    advertencias: list[str] = []

    valor_hora_ordinaria = salario_base_cents / config.horas_jornada_mensual if config.horas_jornada_mensual else 0
    valor_hora_extra = valor_hora_ordinaria * (1 + config.recargo_hora_extra_pct)
    horas_extra_monto_cents = round(valor_hora_extra * horas_extra_cantidad)

    valor_hora_nocturna = valor_hora_ordinaria * config.recargo_nocturnidad_pct
    nocturnidad_monto_cents = round(valor_hora_nocturna * nocturnidad_horas)

    # El descuento por faltas se resta del devengado, no de las deducciones de ley —
    # una falta reduce el salario base real del mes, no es una "deducción" sobre lo trabajado.
    salario_devengado_base = max(0, salario_base_cents - descuento_faltas_cents)
    if descuento_faltas_cents > salario_base_cents:
        advertencias.append(
            "El descuento por faltas supera el salario base — se limitó a 0, revisa el dato ingresado."
        )

    total_devengado_cents = (
        salario_devengado_base
        + horas_extra_monto_cents
        + nocturnidad_monto_cents
        + bonificaciones_cents
        + otros_ingresos_cents
    )

    # ISSS y AFP se calculan sobre el salario devengado regular (sin horas extra ni bonos
    # ocasionales, que no cotizan) y respetan el tope de cotización de ley.
    base_cotizable_isss = min(salario_devengado_base, config.isss_tope_cotizable_cents)
    base_cotizable_afp = min(salario_devengado_base, config.afp_tope_cotizable_cents)
    isss_empleado_cents = round(base_cotizable_isss * config.isss_tasa_empleado)
    isss_patronal_cents = round(base_cotizable_isss * config.isss_tasa_patronal)
    afp_empleado_cents = round(base_cotizable_afp * config.afp_tasa_empleado)
    afp_patronal_cents = round(base_cotizable_afp * config.afp_tasa_patronal)

    if not config.tramos_renta:
        advertencias.append(
            "La tabla de retención de renta (ISR) no está configurada — no se retuvo renta en este "
            "cálculo. Complétala en Configuración → Nómina antes de usar esto como planilla real."
        )
        renta_cents = 0
    else:
        # La renta se retiene sobre la base imponible: devengado menos las cotizaciones de
        # ley del empleado (ISSS/AFP no son renta gravable).
        base_imponible = total_devengado_cents - isss_empleado_cents - afp_empleado_cents
        renta_cents = _renta_sobre_base(base_imponible, config.tramos_renta)

    total_descuentos_cents = (
        isss_empleado_cents
        + afp_empleado_cents
        + renta_cents
        + descuento_prestamos_cents
        + otros_descuentos_cents
    )
    neto_cents = total_devengado_cents - total_descuentos_cents
    if neto_cents < 0:
        advertencias.append(
            "El neto a pagar resultó negativo — las deducciones superan lo devengado. Revisa los montos."
        )

    return PayrollCalculo(
        salario_base_cents=salario_base_cents,
        horas_extra_cantidad=horas_extra_cantidad,
        horas_extra_monto_cents=horas_extra_monto_cents,
        nocturnidad_horas=nocturnidad_horas,
        nocturnidad_monto_cents=nocturnidad_monto_cents,
        bonificaciones_cents=bonificaciones_cents,
        otros_ingresos_cents=otros_ingresos_cents,
        total_devengado_cents=total_devengado_cents,
        isss_empleado_cents=isss_empleado_cents,
        afp_empleado_cents=afp_empleado_cents,
        renta_cents=renta_cents,
        descuento_faltas_cents=descuento_faltas_cents,
        descuento_prestamos_cents=descuento_prestamos_cents,
        otros_descuentos_cents=otros_descuentos_cents,
        total_descuentos_cents=total_descuentos_cents,
        isss_patronal_cents=isss_patronal_cents,
        afp_patronal_cents=afp_patronal_cents,
        neto_cents=neto_cents,
        advertencias=advertencias,
    )

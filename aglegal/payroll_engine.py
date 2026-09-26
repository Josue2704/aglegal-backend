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
from math import isfinite


@dataclass
class PayrollConfig:
    isss_tasa_empleado: float
    isss_tasa_patronal: float
    afp_tasa_empleado: float
    afp_tasa_patronal: float
    tramos_renta: list[dict]
    recargo_hora_extra_pct: float
    recargo_nocturnidad_pct: float
    horas_jornada_mensual: float
    # None = sin tope de cotización. AFP no tiene tope desde la Ley Integral del Sistema
    # de Pensiones; ISSS sí lo tiene hoy ($1,000) pero se deja igual de opcional por si
    # la ley vuelve a cambiarlo.
    isss_tope_cotizable_cents: int | None = None
    afp_tope_cotizable_cents: int | None = None
    # Tope del salario base a considerar para indemnización (Art. 58 CT, ligado a un
    # múltiplo del salario mínimo vigente) — None = sin tope configurado todavía.
    tope_salario_indemnizacion_cents: int | None = None
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
        if not isfinite(valor) or valor < 0:
            raise ValueError(f"Las {nombre} no pueden ser negativas")
    for nombre, valor in (
        ("bonificaciones", bonificaciones_cents),
        ("otros ingresos", otros_ingresos_cents),
        ("descuento por faltas", descuento_faltas_cents),
        ("descuento por préstamos", descuento_prestamos_cents),
        ("otros descuentos", otros_descuentos_cents),
    ):
        if not isfinite(valor) or valor < 0:
            raise ValueError(f"El monto de {nombre} no puede ser negativo")

    advertencias: list[str] = []
    if horas_extra_cantidad and config.recargo_hora_extra_pct < 1:
        advertencias.append("El recargo diurno configurado es menor al 100%; corrige la configuración antes de pagar horas extra")

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

    # Remuneración salarial: incluye extras, nocturnidad y bonos por servicios.
    # Gratificaciones extraordinarias/viáticos no pertenecen a estos campos.
    base_cotizable_isss = (total_devengado_cents if config.isss_tope_cotizable_cents is None
                          else min(total_devengado_cents, config.isss_tope_cotizable_cents))
    base_cotizable_afp = (total_devengado_cents if config.afp_tope_cotizable_cents is None
                         else min(total_devengado_cents, config.afp_tope_cotizable_cents))
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


# ── Prestaciones de ley (Código de Trabajo de El Salvador) ────────────────────
# Estas tres son cálculos independientes de la planilla mensual — se pagan una vez al
# año (aguinaldo, vacaciones) o al terminar la relación laboral (indemnización), no cada
# mes, así que viven como funciones aparte en vez de dentro de calcular_planilla().
# Los días/porcentajes de ley (15/19/21 días, 30%, 30 días/año) son fijos por artículo
# del Código de Trabajo y rara vez cambian — a diferencia de ISSS/AFP/renta no se
# versionan en payroll_config, pero si una reforma los toca hay que actualizar esta
# constante y los tests que la fijan.

@dataclass
class AguinaldoResultado:
    dias_correspondientes: float
    salario_diario_cents: int
    monto_cents: int
    proporcional: bool
    advertencias: list[str] = field(default_factory=list)


def calcular_aguinaldo(*, salario_base_cents: int, anios_antiguedad: float, dias_trabajados_en_anio: int | None = None) -> AguinaldoResultado:
    """Art. 198 Código de Trabajo: 15 días (1 a <3 años), 19 días (3 a <10 años),
    21 días (10+ años); proporcional sobre la base de 15 días si lleva menos de 1 año."""
    if salario_base_cents < 0:
        raise ValueError("El salario base no puede ser negativo")
    if anios_antiguedad < 0:
        raise ValueError("Los años de antigüedad no pueden ser negativos")
    salario_diario_cents = salario_base_cents / 30
    advertencias: list[str] = []
    if anios_antiguedad < 1:
        dias = dias_trabajados_en_anio if dias_trabajados_en_anio is not None else round(anios_antiguedad * 365)
        if dias_trabajados_en_anio is None:
            advertencias.append("No se indicaron días trabajados en el año — se estimó a partir de la antigüedad en años.")
        monto = round(salario_diario_cents * 15 / 365 * dias)
        return AguinaldoResultado(dias_correspondientes=15 * dias / 365, salario_diario_cents=round(salario_diario_cents), monto_cents=monto, proporcional=True, advertencias=advertencias)
    dias = 15 if anios_antiguedad < 3 else 19 if anios_antiguedad < 10 else 21
    monto = round(salario_diario_cents * dias)
    return AguinaldoResultado(dias_correspondientes=dias, salario_diario_cents=round(salario_diario_cents), monto_cents=monto, proporcional=False, advertencias=advertencias)


@dataclass
class VacacionesResultado:
    salario_dias_cents: int
    recargo_30_cents: int
    total_cents: int


def calcular_vacaciones(*, salario_base_cents: int, dias: float = 15, recargo_pct: float = 0.30) -> VacacionesResultado:
    """Art. 177 CT: 15 días de salario + 30% de recargo sobre ese mismo salario."""
    if salario_base_cents < 0:
        raise ValueError("El salario base no puede ser negativo")
    if dias < 0:
        raise ValueError("Los días de vacación no pueden ser negativos")
    salario_diario_cents = salario_base_cents / 30
    salario_dias_cents = round(salario_diario_cents * dias)
    recargo_cents = round(salario_dias_cents * recargo_pct)
    return VacacionesResultado(salario_dias_cents=salario_dias_cents, recargo_30_cents=recargo_cents, total_cents=salario_dias_cents + recargo_cents)


@dataclass
class IndemnizacionResultado:
    salario_base_usado_cents: int
    tope_aplicado: bool
    anios_servicio: float
    monto_cents: int
    advertencias: list[str] = field(default_factory=list)


def calcular_indemnizacion(*, salario_base_cents: int, anios_servicio: float, tope_salario_cents: int | None) -> IndemnizacionResultado:
    """Art. 58 CT: 30 días de salario por cada año de servicio (fracciones proporcionales),
    sobre el salario base topado a un múltiplo del salario mínimo vigente si se conoce ese tope."""
    if salario_base_cents < 0:
        raise ValueError("El salario base no puede ser negativo")
    if anios_servicio < 0:
        raise ValueError("Los años de servicio no pueden ser negativos")
    advertencias: list[str] = []
    tope_aplicado = tope_salario_cents is not None and salario_base_cents > tope_salario_cents
    salario_usado = min(salario_base_cents, tope_salario_cents) if tope_salario_cents is not None else salario_base_cents
    if tope_salario_cents is None:
        advertencias.append(
            "No hay un tope de salario configurado para indemnización (ligado al salario mínimo vigente) "
            "— se usó el salario base completo sin topar. Configúralo en Configuración → Nómina si el "
            "salario de esta persona supera el tope legal."
        )
    # 30 días de salario por año = el salario mensual completo por cada año de servicio.
    monto = round(salario_usado * anios_servicio)
    return IndemnizacionResultado(salario_base_usado_cents=salario_usado, tope_aplicado=tope_aplicado, anios_servicio=anios_servicio, monto_cents=monto, advertencias=advertencias)

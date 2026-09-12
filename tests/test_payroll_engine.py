"""Motor de cálculo de planilla — pruebas puras, sin base de datos."""
from __future__ import annotations

import pytest

from aglegal.payroll_engine import (
    PayrollConfig,
    calcular_aguinaldo,
    calcular_indemnizacion,
    calcular_planilla,
    calcular_vacaciones,
)

# AFP no tiene tope de cotización desde la Ley Integral del Sistema de Pensiones — el
# fixture por defecto refleja eso (afp_tope_cotizable_cents=None). ISSS sí conserva su
# tope de $1,000 hoy (confirmado, Decreto Ejecutivo No. 10 / fuentes oficiales vigentes).
CONFIG_BASE = PayrollConfig(
    isss_tasa_empleado=0.03,
    isss_tasa_patronal=0.075,
    isss_tope_cotizable_cents=100_000,
    afp_tasa_empleado=0.0725,
    afp_tasa_patronal=0.0875,
    afp_tope_cotizable_cents=None,
    tramos_renta=[],
    recargo_hora_extra_pct=0.5,
    recargo_nocturnidad_pct=0.25,
    horas_jornada_mensual=240,
)


def test_salario_simple_sin_tramos_de_renta_no_retiene_isr_pero_avisa():
    c = calcular_planilla(salario_base_cents=80_000, config=CONFIG_BASE)
    assert c.renta_cents == 0
    assert any("renta" in a.lower() for a in c.advertencias)
    assert c.isss_empleado_cents == round(80_000 * 0.03)
    assert c.afp_empleado_cents == round(80_000 * 0.0725)
    assert c.neto_cents == 80_000 - c.isss_empleado_cents - c.afp_empleado_cents


def test_isss_respeta_su_tope_de_cotizacion():
    # Salario de $2,000 (200,000 cents) muy por encima del tope de ISSS de $1,000 (100,000 cents)
    c = calcular_planilla(salario_base_cents=200_000, config=CONFIG_BASE)
    assert c.isss_empleado_cents == round(100_000 * 0.03)


def test_afp_sin_tope_configurado_cotiza_sobre_el_salario_completo():
    # AFP no tiene tope de cotización (Ley Integral del Sistema de Pensiones) — a
    # diferencia de ISSS, un salario alto cotiza AFP sobre el 100% del salario devengado.
    c = calcular_planilla(salario_base_cents=200_000, config=CONFIG_BASE)
    assert c.afp_empleado_cents == round(200_000 * 0.0725)


def test_afp_con_tope_configurado_explicitamente_si_lo_respeta():
    config_con_tope = PayrollConfig(**{**CONFIG_BASE.__dict__, "afp_tope_cotizable_cents": 100_000})
    c = calcular_planilla(salario_base_cents=200_000, config=config_con_tope)
    assert c.afp_empleado_cents == round(100_000 * 0.0725)


def test_horas_extra_se_pagan_con_recargo_sobre_el_valor_hora_ordinario():
    # Salario 80,000 cents ($800, bajo el tope de $1,000) / 240 horas = $3.33/hora ordinaria;
    # extra con 50% de recargo = $5/hora
    c = calcular_planilla(salario_base_cents=80_000, config=CONFIG_BASE, horas_extra_cantidad=10)
    valor_hora_extra = (80_000 / 240) * 1.5
    assert c.horas_extra_monto_cents == round(valor_hora_extra * 10)
    # Las horas extra suman al devengado pero NO cotizan ISSS/AFP (solo el salario base sí)
    assert c.isss_empleado_cents == round(80_000 * 0.03)


def test_nocturnidad_aplica_su_propio_recargo():
    c = calcular_planilla(salario_base_cents=240_000, config=CONFIG_BASE, nocturnidad_horas=8)
    # $10/hora * 0.25 recargo * 8 horas = $20 = 2000 cents
    assert c.nocturnidad_monto_cents == 2_000


def test_descuento_por_faltas_reduce_el_salario_devengado_no_las_deducciones_de_ley():
    c = calcular_planilla(salario_base_cents=100_000, config=CONFIG_BASE, descuento_faltas_cents=10_000)
    assert c.total_devengado_cents == 90_000
    # ISSS/AFP se calculan sobre el salario YA reducido por faltas
    assert c.isss_empleado_cents == round(90_000 * 0.03)


def test_descuento_por_faltas_mayor_al_salario_se_limita_a_cero_y_avisa():
    c = calcular_planilla(salario_base_cents=50_000, config=CONFIG_BASE, descuento_faltas_cents=90_000)
    assert c.total_devengado_cents == 0
    assert any("faltas" in a.lower() for a in c.advertencias)


def test_tramos_de_renta_se_aplican_sobre_la_base_imponible():
    config = PayrollConfig(**{**CONFIG_BASE.__dict__, "tramos_renta": [
        {"sobre_exceso_de_cents": 0, "hasta_cents": 60_000, "cuota_fija_cents": 0, "porcentaje_exceso": 0},
        {"sobre_exceso_de_cents": 60_000, "hasta_cents": None, "cuota_fija_cents": 0, "porcentaje_exceso": 0.10},
    ]})
    c = calcular_planilla(salario_base_cents=100_000, config=config)
    base_imponible = 100_000 - c.isss_empleado_cents - c.afp_empleado_cents
    esperado = round((base_imponible - 60_000) * 0.10)
    assert c.renta_cents == esperado
    assert not c.advertencias


def test_neto_negativo_se_permite_pero_avisa():
    c = calcular_planilla(salario_base_cents=10_000, config=CONFIG_BASE, descuento_prestamos_cents=50_000)
    assert c.neto_cents < 0
    assert any("negativo" in a.lower() for a in c.advertencias)


def test_bonificaciones_y_otros_ingresos_no_cotizan_ni_generan_renta_extra_en_isss_afp():
    con_bono = calcular_planilla(salario_base_cents=100_000, config=CONFIG_BASE, bonificaciones_cents=50_000)
    sin_bono = calcular_planilla(salario_base_cents=100_000, config=CONFIG_BASE)
    assert con_bono.isss_empleado_cents == sin_bono.isss_empleado_cents
    assert con_bono.afp_empleado_cents == sin_bono.afp_empleado_cents
    assert con_bono.total_devengado_cents == sin_bono.total_devengado_cents + 50_000


@pytest.mark.parametrize("campo", ["horas_extra_cantidad", "nocturnidad_horas"])
def test_horas_negativas_son_rechazadas(campo):
    with pytest.raises(ValueError):
        calcular_planilla(salario_base_cents=100_000, config=CONFIG_BASE, **{campo: -1})


def test_salario_negativo_es_rechazado():
    with pytest.raises(ValueError):
        calcular_planilla(salario_base_cents=-1, config=CONFIG_BASE)


# Tabla real de retención de ISR mensual — Decreto Ejecutivo No. 10 (30/abr/2025),
# Ministerio de Hacienda de El Salvador, vigente desde mayo 2025.
TRAMOS_RENTA_OFICIALES_2025 = [
    {"sobre_exceso_de_cents": 0, "hasta_cents": 55_000, "cuota_fija_cents": 0, "porcentaje_exceso": 0},
    {"sobre_exceso_de_cents": 55_000, "hasta_cents": 89_524, "cuota_fija_cents": 1_767, "porcentaje_exceso": 0.10},
    {"sobre_exceso_de_cents": 89_524, "hasta_cents": 203_810, "cuota_fija_cents": 6_000, "porcentaje_exceso": 0.20},
    {"sobre_exceso_de_cents": 203_810, "hasta_cents": None, "cuota_fija_cents": 28_857, "porcentaje_exceso": 0.30},
]


def test_tabla_oficial_de_renta_no_retiene_bajo_el_minimo_exento():
    config = PayrollConfig(**{**CONFIG_BASE.__dict__, "tramos_renta": TRAMOS_RENTA_OFICIALES_2025})
    # $500 de salario base con las deducciones de ISSS/AFP cae claramente bajo los $550 exentos
    c = calcular_planilla(salario_base_cents=50_000, config=config)
    assert c.renta_cents == 0


def test_tabla_oficial_de_renta_aplica_tramo_ii_con_su_cuota_fija():
    config = PayrollConfig(**{**CONFIG_BASE.__dict__, "tramos_renta": TRAMOS_RENTA_OFICIALES_2025})
    c = calcular_planilla(salario_base_cents=80_000, config=config)
    base_imponible = 80_000 - c.isss_empleado_cents - c.afp_empleado_cents
    assert 55_000 < base_imponible <= 89_524
    esperado = 1_767 + round((base_imponible - 55_000) * 0.10)
    assert c.renta_cents == esperado


class TestAguinaldo:
    def test_menos_de_un_anio_es_proporcional(self):
        r = calcular_aguinaldo(salario_base_cents=50_000, anios_antiguedad=0.5, dias_trabajados_en_anio=180)
        assert r.proporcional is True
        assert r.monto_cents == round((50_000 / 30) * 15 / 365 * 180)

    def test_de_uno_a_tres_anios_son_15_dias(self):
        r = calcular_aguinaldo(salario_base_cents=90_000, anios_antiguedad=2)
        assert r.dias_correspondientes == 15
        assert r.monto_cents == round((90_000 / 30) * 15)

    def test_de_tres_a_diez_anios_son_19_dias(self):
        r = calcular_aguinaldo(salario_base_cents=90_000, anios_antiguedad=5)
        assert r.dias_correspondientes == 19

    def test_diez_anios_o_mas_son_21_dias(self):
        r = calcular_aguinaldo(salario_base_cents=90_000, anios_antiguedad=12)
        assert r.dias_correspondientes == 21

    def test_antiguedad_negativa_es_rechazada(self):
        with pytest.raises(ValueError):
            calcular_aguinaldo(salario_base_cents=90_000, anios_antiguedad=-1)


class TestVacaciones:
    def test_15_dias_mas_30_por_ciento_de_recargo(self):
        r = calcular_vacaciones(salario_base_cents=90_000)
        salario_dias = round((90_000 / 30) * 15)
        assert r.salario_dias_cents == salario_dias
        assert r.recargo_30_cents == round(salario_dias * 0.30)
        assert r.total_cents == salario_dias + round(salario_dias * 0.30)


class TestIndemnizacion:
    def test_30_dias_por_anio_sin_tope_usa_salario_completo(self):
        r = calcular_indemnizacion(salario_base_cents=100_000, anios_servicio=3, tope_salario_cents=None)
        assert r.tope_aplicado is False
        assert r.monto_cents == 300_000
        assert any("tope" in a.lower() for a in r.advertencias)

    def test_con_tope_configurado_topa_el_salario_usado(self):
        r = calcular_indemnizacion(salario_base_cents=200_000, anios_servicio=2, tope_salario_cents=161_280)
        assert r.tope_aplicado is True
        assert r.salario_base_usado_cents == 161_280
        assert r.monto_cents == round(161_280 * 2)
        assert not r.advertencias

    def test_fraccion_de_anio_es_proporcional(self):
        r = calcular_indemnizacion(salario_base_cents=60_000, anios_servicio=2.5, tope_salario_cents=None)
        assert r.monto_cents == round(60_000 * 2.5)

"""Motor de cálculo de planilla — pruebas puras, sin base de datos."""
from __future__ import annotations

import pytest

from aglegal.payroll_engine import PayrollConfig, calcular_planilla

CONFIG_BASE = PayrollConfig(
    isss_tasa_empleado=0.03,
    isss_tasa_patronal=0.075,
    isss_tope_cotizable_cents=100_000,
    afp_tasa_empleado=0.0725,
    afp_tasa_patronal=0.0875,
    afp_tope_cotizable_cents=100_000,
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


def test_isss_y_afp_respetan_el_tope_de_cotizacion():
    # Salario de $2,000 (200,000 cents) muy por encima del tope de $1,000 (100,000 cents)
    c = calcular_planilla(salario_base_cents=200_000, config=CONFIG_BASE)
    assert c.isss_empleado_cents == round(100_000 * 0.03)
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

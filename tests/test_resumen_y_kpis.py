"""Resumen mensual consolidado (17_Resumen_Mensual) y los KPIs de la hoja 14 que faltaban:
009 ticket promedio, 015 ingresos por origen, 016 días de cobro, más el aging de cartera.

Las pruebas usan años lejanos (2032 en adelante) porque `gastos_fijos`, `forecast` y los
cobros son globales dentro del schema de pruebas: compartir un mes con otra prueba cruzaría
los totales."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


def _familia(repo, catalogo):
    return repo.create_familia(category_id=catalogo["categoria_id"], nombre="Familia resumen", created_at=now_iso())


def _caso(repo, catalogo, *, honorarios="10000", opened_at, **kw):
    return repo.create_case(
        client_id=catalogo["cliente_id"], title="Caso resumen", service_id=catalogo["servicio_id"],
        honorarios_contratados_text=honorarios, costos_directos_estimados_text="0",
        status="Abierto", priority="Media", opened_at=opened_at, created_at=now_iso(), **kw,
    )


def _cobro(repo, catalogo, case_id, monto, fecha, **kw):
    return repo.create_income(
        amount_text=monto, income_date=fecha, created_at=now_iso(), client_id=catalogo["cliente_id"],
        case_id=case_id, account_id=catalogo["cuenta_id"], **kw,
    )


# ── Resumen mensual (hoja 17) ─────────────────────────────────────────────────

def test_resumen_mensual_compara_meta_contra_realidad(repo, catalogo, codigo_unico):
    """La estructura de la hoja 17: meta, real, cumplimiento, utilidad mínima y brecha."""
    periodo, now = "2032", now_iso()
    repo.create_supuestos(periodo=periodo, costo_variable_pct=0.1, margen_operativo_meta_pct=0.2,
                          margen_seguridad_pct=0.15, created_at=now)
    familia_id = _familia(repo, catalogo)
    # Meta de enero: 4 casos × $250 = $1,000, con 80% de margen directo objetivo.
    repo.create_forecast(family_id=familia_id, mes=f"{periodo}-01", volumen_meta_text="4",
                         ticket_objetivo_text="250", margen_directo_objetivo_pct=0.8, created_at=now)

    cuenta_egreso = repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-001", tipo="Egreso", grupo="Operación", nombre=f"Egresos {codigo_unico}",
        naturaleza="Directo", centro_costo="Operación jurídica", created_at=now,
    )
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    _cobro(repo, catalogo, caso, "800", f"{periodo}-01-15")
    repo.create_cost(case_id=caso, detail="Publicación", amount_text="100", cost_date=f"{periodo}-01-20",
                     notes="", created_at=now, account_id=cuenta_egreso)

    enero = next(m for m in repo.resumen_mensual(desde=f"{periodo}-01", hasta=f"{periodo}-01")["meses"])

    assert enero["meta_ingresos_cents"] == 100_000          # 4 × $250
    assert enero["ingresos_reales_cents"] == 80_000
    assert enero["cumplimiento_ingresos_pct"] == 0.8        # $800 / $1,000
    assert enero["meta_utilidad_directa_cents"] == 80_000   # $1,000 × 80%
    assert enero["utilidad_directa_real_cents"] == 70_000   # $800 − $100
    assert enero["utilidad_operativa_minima_cents"] == 20_000  # $1,000 × 20% de margen meta
    # La utilidad operativa siempre es la directa menos gastos fijos y comisiones del mes.
    assert enero["utilidad_operativa_real_cents"] == (
        enero["utilidad_directa_real_cents"] - enero["gastos_fijos_cents"] - enero["comisiones_cents"]
    )
    assert enero["brecha_utilidad_minima_cents"] == (
        enero["utilidad_operativa_real_cents"] - enero["utilidad_operativa_minima_cents"]
    )
    assert enero["semaforo_general"] == "rojo"              # 80% de cumplimiento


def test_resumen_mensual_no_cobra_un_gasto_fijo_antes_de_su_vigencia(repo, catalogo, codigo_unico):
    """El error de la hoja 09 del Excel: cargar los $150 de marketing a julio cuando el gasto
    arranca en agosto. El sistema respeta `mes_inicio`, así que la diferencia entre los dos
    meses es exactamente el gasto nuevo."""
    periodo, now = "2033", now_iso()
    repo.create_supuestos(periodo=periodo, costo_variable_pct=0.1, margen_operativo_meta_pct=0.2,
                          margen_seguridad_pct=0.15, created_at=now)
    repo.create_gasto_fijo(concepto=f"Marketing {codigo_unico}", tipo="Meta", monto_mensual_text="150",
                           mes_inicio=f"{periodo}-02", created_at=now)

    meses = repo.resumen_mensual(desde=f"{periodo}-01", hasta=f"{periodo}-02")["meses"]
    enero, febrero = meses[0], meses[1]

    assert febrero["gastos_fijos_cents"] - enero["gastos_fijos_cents"] == 15_000


def test_resumen_mensual_totaliza_el_rango(repo, catalogo):
    periodo, now = "2034", now_iso()
    repo.create_supuestos(periodo=periodo, costo_variable_pct=0.1, margen_operativo_meta_pct=0.2,
                          margen_seguridad_pct=0.15, created_at=now)
    familia_id = _familia(repo, catalogo)
    for mes in ("01", "02"):
        repo.create_forecast(family_id=familia_id, mes=f"{periodo}-{mes}", volumen_meta_text="2",
                             ticket_objetivo_text="500", margen_directo_objetivo_pct=0.5, created_at=now)

    resumen = repo.resumen_mensual(desde=f"{periodo}-01", hasta=f"{periodo}-02")

    assert len(resumen["meses"]) == 2
    assert resumen["totales"]["meta_ingresos_cents"] == 200_000  # $1,000 × 2 meses
    assert resumen["totales"]["mes"] == f"{periodo}-01 a {periodo}-02"


@pytest.mark.parametrize(
    "desde,hasta,mensaje",
    [
        ("2032-12", "2032-01", "no puede ser posterior"),
        ("julio", "2032-12", "formato AAAA-MM"),
        ("2000-01", "2032-12", "36 meses"),
    ],
)
def test_resumen_mensual_rechaza_rangos_invalidos(repo, desde, hasta, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        repo.resumen_mensual(desde=desde, hasta=hasta)


# ── KPI-009 · ticket promedio ────────────────────────────────────────────────

def test_ticket_promedio_divide_entre_expedientes_no_entre_cobros(repo, catalogo):
    """Dos cobros del mismo expediente son un solo caso: si se dividiera entre cobros, cobrar
    en cuotas haría parecer que el ticket cayó a la mitad."""
    periodo = "2035"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    _cobro(repo, catalogo, caso, "300", f"{periodo}-01-10")
    _cobro(repo, catalogo, caso, "500", f"{periodo}-01-20")

    resultado = repo.ticket_promedio(desde=f"{periodo}-01", hasta=f"{periodo}-01")

    assert resultado["ingresos_cents"] == 80_000
    assert resultado["casos_cobrados"] == 1
    assert resultado["ticket_promedio_cents"] == 80_000


def test_ticket_promedio_rechaza_agrupacion_desconocida(repo):
    with pytest.raises(ValueError, match="Agrupación inválida"):
        repo.ticket_promedio(desde="2035-01", hasta="2035-01", agrupar_por="cliente")


# ── KPI-015 · ingresos por origen ────────────────────────────────────────────

def test_ingresos_por_origen_reparte_segun_participacion(repo, catalogo, codigo_unico):
    """Con dos originadores al 50%, el ingreso del expediente se parte entre ambos y la suma
    de los orígenes sigue cuadrando con el total cobrado."""
    periodo, now = "2036", now_iso()
    segunda = repo.create_persona(persona=f"Persona B {codigo_unico}", mes_inicio=f"{periodo}-01", created_at=now)
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    repo.set_negocio_originadores(caso, created_at=now, originadores=[
        {"personal_id": catalogo["persona_id"], "porcentaje_participacion": 50, "tipo_origen": "Cliente nuevo"},
        {"personal_id": segunda, "porcentaje_participacion": 50, "tipo_origen": "Venta cruzada"},
    ])
    _cobro(repo, catalogo, caso, "1000", f"{periodo}-01-10")

    filas = repo.ingresos_por_origen(desde=f"{periodo}-01", hasta=f"{periodo}-01")

    assert len(filas) == 2
    assert sum(f["ingresos_cents"] for f in filas) == 100_000
    assert {f["tipo_origen"] for f in filas} == {"Cliente nuevo", "Venta cruzada"}
    assert all(f["ingresos_cents"] == 50_000 for f in filas)


def test_ingresos_por_origen_agrupa_los_expedientes_sin_originador(repo, catalogo):
    periodo = "2037"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    _cobro(repo, catalogo, caso, "400", f"{periodo}-01-10")

    filas = repo.ingresos_por_origen(desde=f"{periodo}-01", hasta=f"{periodo}-01")

    assert [f["origen"] for f in filas] == ["Sin originador"]
    assert filas[0]["ingresos_cents"] == 40_000


# ── KPI-016 · días de cobro ──────────────────────────────────────────────────

def test_dias_cobro_mide_desde_el_cierre_del_expediente(repo, catalogo):
    periodo, now = "2038", now_iso()
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    repo.update_case(caso, title="Caso resumen", status="Cerrado", priority="Media",
                     opened_at=f"{periodo}-01-01", closed_at=f"{periodo}-01-10", fecha_cierre_real=f"{periodo}-01-10",
                     service_id=catalogo["servicio_id"], honorarios_contratados_text="10000")
    _cobro(repo, catalogo, caso, "500", f"{periodo}-01-25")

    resultado = repo.dias_promedio_cobro(desde=f"{periodo}-01", hasta=f"{periodo}-01")

    assert resultado["cobros_medidos"] == 1
    assert resultado["promedio_dias"] == 15.0
    assert resultado["sin_referencia"] == 0


def test_dias_cobro_no_cuenta_los_anticipos_como_cero_dias(repo, catalogo):
    """Un cobro anterior a la fecha de referencia es un anticipo, no un cobro rápido: contarlo
    como 0 días bajaría artificialmente el promedio del despacho."""
    periodo = "2039"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01")
    repo.update_case(caso, title="Caso resumen", status="Cerrado", priority="Media",
                     opened_at=f"{periodo}-01-01", closed_at=f"{periodo}-01-28", fecha_cierre_real=f"{periodo}-01-28",
                     service_id=catalogo["servicio_id"], honorarios_contratados_text="10000")
    _cobro(repo, catalogo, caso, "200", f"{periodo}-01-05")

    resultado = repo.dias_promedio_cobro(desde=f"{periodo}-01", hasta=f"{periodo}-01")

    assert resultado["cobros_medidos"] == 0
    assert resultado["sin_referencia"] == 1
    assert resultado["promedio_dias"] is None


# ── Aging de cartera ─────────────────────────────────────────────────────────

def test_aging_clasifica_por_mes_de_cobro_esperado(repo, catalogo):
    """El saldo se envejece desde el último día del mes prometido al cliente."""
    periodo = "2040"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01", honorarios="1000",
                 mes_cobro_esperado=f"{periodo}-01")
    _cobro(repo, catalogo, caso, "400", f"{periodo}-01-10")

    # Corte a 45 días del 31 de enero -> tramo 31-60.
    aging = repo.aging_cartera(fecha_corte=f"{periodo}-03-16")
    caso_aging = next(c for c in aging["casos"] if c["case_id"] == caso)

    assert caso_aging["saldo_pendiente_cents"] == 60_000  # $1,000 − $400
    assert caso_aging["dias_atraso"] == 45
    assert caso_aging["tramo"] == "31-60"
    tramo = next(t for t in aging["tramos"] if t["tramo"] == "31-60")
    assert tramo["saldo_cents"] >= 60_000


def test_aging_marca_por_vencer_lo_que_aun_no_llega_al_mes_esperado(repo, catalogo):
    periodo = "2041"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01", honorarios="500",
                 mes_cobro_esperado=f"{periodo}-06")

    aging = repo.aging_cartera(fecha_corte=f"{periodo}-02-01")
    caso_aging = next(c for c in aging["casos"] if c["case_id"] == caso)

    assert caso_aging["tramo"] == "Por vencer"
    assert caso_aging["dias_atraso"] == 0


def test_aging_excluye_los_expedientes_ya_cobrados(repo, catalogo):
    periodo = "2042"
    caso = _caso(repo, catalogo, opened_at=f"{periodo}-01-01", honorarios="300",
                 mes_cobro_esperado=f"{periodo}-01", estado_cobro="Cobrado")
    # El estado manual no acredita dinero recibido: el saldo se cancela con un cobro.
    _cobro(repo, catalogo, caso, "300", f"{periodo}-01-15")

    aging = repo.aging_cartera(fecha_corte=f"{periodo}-06-01")

    assert all(c["case_id"] != caso for c in aging["casos"])

"""El dinero que sale del despacho tiene que llegar al resultado del mes.

Antes, el gasto que alguien registraba en Flujo de caja no movía ninguna cifra de
resultado: el resumen mensual y el punto de equilibrio trabajaban solo con el gasto
fijo presupuestado. Y una planilla se asentaba por el neto de la boleta, no por lo
que realmente le cuesta al despacho.

Cada prueba trabaja en su propio mes: el schema de pruebas es compartido y los
movimientos de una prueba se sumarían a los de otra dentro del mismo mes."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


def _supuestos(repo, periodo="2027"):
    """Los supuestos financieros son anuales y los comparten todas las pruebas."""
    try:
        repo.create_supuestos(periodo=periodo, costo_variable_pct=0.10,
                              margen_operativo_meta_pct=0.20, margen_seguridad_pct=0.15,
                              created_at=now_iso())
    except ValueError:
        pass


def _cuenta_egreso(repo, codigo_unico, *, sufijo="001", afecta_utilidad=True,
                   centro="Administración", nombre=None):
    return repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-{sufijo}", tipo="Egreso", grupo="Local",
        nombre=nombre or f"Cuenta {codigo_unico}-{sufijo}", naturaleza="Fijo",
        centro_costo=centro, afecta_utilidad=afecta_utilidad, created_at=now_iso(),
    )


def _gasto(repo, mes, cuenta, monto, *, dia=10, detalle="Gasto del mes", **kw):
    return repo.create_expense(
        detail=detalle, amount_text=str(monto), expense_date=f"{mes}-{dia:02d}",
        notes="", created_at=now_iso(), account_id=cuenta, **kw,
    )


def _presupuesto(repo, mes, monto):
    return repo.create_gasto_fijo(concepto=f"Alquiler {mes}", monto_mensual_text=str(monto),
                                  mes_inicio=mes, mes_fin=mes, created_at=now_iso())


def test_el_gasto_registrado_llega_al_resumen_del_mes(repo, catalogo, codigo_unico):
    mes = "2027-01"
    _supuestos(repo)
    _presupuesto(repo, mes, 400)
    _gasto(repo, mes, _cuenta_egreso(repo, codigo_unico), 475)  # se pagó más de lo presupuestado

    fila = repo.resumen_mensual(desde=mes, hasta=mes)["meses"][0]
    assert fila["gastos_fijos_cents"] == 40_000       # lo que se había presupuestado
    assert fila["gastos_reales_cents"] == 47_500      # lo que de verdad salió
    assert fila["brecha_gastos_cents"] == 7_500       # y la diferencia, visible
    # La utilidad de caja usa el gasto real; la del Archivo Maestro sigue con el presupuesto.
    assert fila["utilidad_operativa_caja_cents"] == -47_500
    assert fila["utilidad_operativa_real_cents"] == -40_000


def test_el_iva_y_lo_reembolsable_no_son_gasto_del_despacho(repo, catalogo, codigo_unico):
    mes = "2027-02"
    _supuestos(repo)
    cuenta = _cuenta_egreso(repo, codigo_unico)
    _gasto(repo, mes, cuenta, 113, monto_iva_text="13")
    _gasto(repo, mes, cuenta, 50, dia=11, detalle="Tasa que se le cobra al cliente",
           monto_reembolsable_text="50")
    fila = repo.resumen_mensual(desde=mes, hasta=mes)["meses"][0]
    assert fila["gastos_reales_cents"] == 10_000  # 113 - 13 de IVA; lo reembolsable no pesa


def test_una_inversion_sale_de_la_caja_pero_no_es_gasto_del_mes(repo, catalogo, codigo_unico):
    mes = "2027-03"
    _supuestos(repo)
    equipo = _cuenta_egreso(repo, codigo_unico, sufijo="009", afecta_utilidad=False,
                            nombre="Equipo y mobiliario")
    _gasto(repo, mes, equipo, 900, detalle="Escritorios")
    fila = repo.resumen_mensual(desde=mes, hasta=mes)["meses"][0]
    assert fila["gastos_reales_cents"] == 0


def test_el_punto_de_equilibrio_dice_cuanto_falta(repo, catalogo, codigo_unico):
    mes = "2027-04"
    _supuestos(repo)
    _presupuesto(repo, mes, 900)
    repo.create_income(amount_text="400", income_date=f"{mes}-15", created_at=now_iso(),
                       client_id=catalogo["cliente_id"], account_id=catalogo["cuenta_id"])

    pe = repo.calcular_punto_equilibrio(mes=mes)
    assert pe["punto_equilibrio_cents"] == 100_000  # 900 / (1 - 0.10)
    assert pe["ingresos_reales_cents"] == 40_000
    assert pe["avance_pct"] == 0.4
    assert pe["falta_para_equilibrio_cents"] == 60_000


def test_el_gasto_se_agrupa_por_centro_de_costo(repo, catalogo, codigo_unico):
    mes = "2027-05"
    admin = _cuenta_egreso(repo, codigo_unico, centro="Administración")
    juridica = _cuenta_egreso(repo, codigo_unico, sufijo="002", centro="Operación jurídica",
                              nombre="Transporte")
    _gasto(repo, mes, admin, 300, detalle="Alquiler")
    _gasto(repo, mes, juridica, 45, dia=12, detalle="Viáticos")
    caso = repo.create_case(client_id=catalogo["cliente_id"], title="Caso centro de costo",
                            status="Abierto", priority="Media", opened_at=f"{mes}-01",
                            created_at=now_iso(), honorarios_contratados_text="500")
    repo.create_cost(case_id=caso, detail="Edicto", amount_text="25", cost_date=f"{mes}-13",
                     notes="", created_at=now_iso(), account_id=juridica)

    d = repo.gastos_por_centro_costo(desde=mes, hasta=mes)
    por_centro = {c["centro_costo"]: c for c in d["centros"]}
    assert por_centro["Administración"]["total_cents"] == 30_000
    # El centro jurídico junta el gasto operativo y el costo directo del expediente.
    assert por_centro["Operación jurídica"]["gastos_operativos_cents"] == 4_500
    assert por_centro["Operación jurídica"]["costos_directos_cents"] == 2_500
    assert d["total_cents"] == 37_000
    assert por_centro["Administración"]["porcentaje"] == pytest.approx(0.8108, abs=1e-4)


def test_la_planilla_se_asienta_por_lo_que_le_cuesta_al_despacho(repo, catalogo, codigo_unico):
    mes = "2027-06"
    _supuestos(repo)
    cuenta = _cuenta_egreso(repo, codigo_unico, sufijo="003", nombre=f"Salario {codigo_unico}")
    persona = repo.create_persona(persona=f"Empleado {codigo_unico}", mes_inicio=mes,
                                  account_id=cuenta, created_at=now_iso())
    pid = repo.create_payroll(personal_id=persona, period=mes, payment_date=f"{mes}-30",
                              notes="", created_at=now_iso(), modo="calculado", salario_base_text="800")
    p = repo.get_payroll(pid)

    esperado = int(p["total_devengado_cents"]) + int(p["isss_patronal_cents"]) + int(p["afp_patronal_cents"])
    assert p["amount_cents"] == 68_353           # el neto de la boleta no cambia
    assert p["costo_empresa_cents"] == 93_000    # $800 devengado + $130 patronal
    assert esperado == 93_000
    gasto = next(e for e in repo.list_expenses() if e["id"] == p["expense_id"])
    assert gasto["amount_cents"] == 93_000

    fila = repo.resumen_mensual(desde=mes, hasta=mes)["meses"][0]
    assert fila["gastos_reales_cents"] == 93_000


def test_corregir_el_neto_mueve_el_costo_en_la_misma_cantidad(repo, catalogo, codigo_unico):
    mes = "2027-07"
    cuenta = _cuenta_egreso(repo, codigo_unico, sufijo="004", nombre=f"Salario {codigo_unico}")
    persona = repo.create_persona(persona=f"Empleado {codigo_unico}", mes_inicio=mes,
                                  account_id=cuenta, created_at=now_iso())
    pid = repo.create_payroll(personal_id=persona, period=mes, payment_date=f"{mes}-30", notes="",
                              created_at=now_iso(), modo="manual", amount_text="500")
    repo.update_payroll(pid, payment_date=f"{mes}-30", notes="Corrección", amount_text="560",
                        username="admin")
    p = repo.get_payroll(pid)
    assert p["amount_cents"] == 56_000 and p["costo_empresa_cents"] == 56_000
    gasto = next(e for e in repo.list_expenses() if e["id"] == p["expense_id"])
    assert gasto["amount_cents"] == 56_000


def test_un_cobro_sin_familia_no_desaparece_del_cumplimiento(repo, catalogo, codigo_unico):
    mes = "2027-08"
    otros = repo.create_cuenta(
        account_code=f"ING-{codigo_unico}-009", tipo="Ingreso", grupo="Otros ingresos",
        nombre="Otros ingresos operativos", naturaleza="Otros", centro_costo="Administración",
        created_at=now_iso(),
    )
    repo.create_income(amount_text="250", income_date=f"{mes}-09", created_at=now_iso(),
                       client_id=catalogo["cliente_id"], account_id=otros, detail="Contrato")

    filas = repo.cumplimiento_por_familia(mes=mes)
    sin_familia = next(f for f in filas if f["family_code"] == "(Sin familia)")
    assert sin_familia["ingresos_reales_cents"] >= 25_000
    assert sin_familia["family_id"] is None


def test_el_cobro_de_una_factura_muestra_su_numero(repo, catalogo, codigo_unico):
    mes = "2027-09"
    caso = repo.create_case(client_id=catalogo["cliente_id"], title="Caso facturado",
                            status="Abierto", priority="Media", opened_at=f"{mes}-01",
                            created_at=now_iso(), honorarios_contratados_text="600",
                            service_id=catalogo["servicio_id"])
    numero = f"FAC-{codigo_unico}-77"
    inv = repo.create_invoice(
        client_id=catalogo["cliente_id"], case_id=caso, invoice_number=numero,
        invoice_date=f"{mes}-15", due_date=None, notes="", firm_name=None, firm_phone=None,
        firm_email=None, firm_address=None, firm_tax_id=None, created_at=now_iso(),
        items=[{"description": "Honorarios", "quantity": 1, "unit_price": 600}],
    )
    repo.update_invoice_status(inv, "Pagada")
    repo.auto_income_from_invoice(inv)

    cobro = next(i for i in repo.list_incomes() if i["invoice_id"] == inv)
    assert cobro["invoice_number"] == numero


def test_la_factura_cobra_en_la_misma_cuenta_que_el_anticipo(repo, catalogo, codigo_unico):
    """Una compraventa es un servicio notarial pero se cobra en la cuenta de inmobiliario:
    si la factura elige cuenta por la categoría del servicio, el mismo expediente termina
    repartido en dos familias distintas."""
    mes = "2027-10"
    otra_familia = repo.create_cuenta(
        account_code=f"ING-{codigo_unico}-007", tipo="Ingreso", grupo="Servicios jurídicos",
        nombre="Ingresos inmobiliarios", naturaleza="Operativo", centro_costo="Operación jurídica",
        created_at=now_iso(),
    )
    caso = repo.create_case(client_id=catalogo["cliente_id"], title="Compraventa con dos cobros",
                            status="Abierto", priority="Media", opened_at=f"{mes}-01",
                            created_at=now_iso(), honorarios_contratados_text="1000",
                            service_id=catalogo["servicio_id"])
    # El abogado registra el anticipo eligiendo la cuenta a mano.
    repo.create_income(amount_text="400", income_date=f"{mes}-05", created_at=now_iso(),
                       client_id=catalogo["cliente_id"], case_id=caso, account_id=otra_familia)

    inv = repo.create_invoice(
        client_id=catalogo["cliente_id"], case_id=caso, invoice_number=f"FAC-{codigo_unico}-90",
        invoice_date=f"{mes}-15", due_date=None, notes="", firm_name=None, firm_phone=None,
        firm_email=None, firm_address=None, firm_tax_id=None, created_at=now_iso(),
        items=[{"description": "Saldo", "quantity": 1, "unit_price": 600}],
    )
    repo.update_invoice_status(inv, "Pagada")
    repo.auto_income_from_invoice(inv)

    cobro = next(i for i in repo.list_incomes() if i["invoice_id"] == inv)
    assert cobro["account_id"] == otra_familia  # sigue al expediente, no a la categoría

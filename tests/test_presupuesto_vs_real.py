"""Presupuestado contra pagado, concepto por concepto, y el aviso de la comisión que
nunca se va a calcular.

El total del mes ya se comparaba, pero dentro de esa suma "el alquiler subió $50" era
invisible. Y un expediente que cobra sin originadores configurados no genera comisión
sin que nadie se entere."""
from __future__ import annotations

from aglegal.db import now_iso

MES = "2027-11"  # mes propio: el schema de pruebas es compartido


def _cuenta(repo, codigo_unico, sufijo, nombre):
    return repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-{sufijo}", tipo="Egreso", grupo="Local", nombre=nombre,
        naturaleza="Fijo", centro_costo="Administración", created_at=now_iso(),
    )


def test_el_comparativo_casa_cada_concepto_con_su_cuenta(repo, catalogo, codigo_unico):
    alquiler = _cuenta(repo, codigo_unico, "011", "Alquiler de oficina")
    internet = _cuenta(repo, codigo_unico, "012", "Internet")
    papeleria = _cuenta(repo, codigo_unico, "013", "Papelería")

    repo.create_gasto_fijo(concepto="Alquiler", monto_mensual_text="400", mes_inicio=MES, mes_fin=MES,
                           account_id=alquiler, created_at=now_iso())
    repo.create_gasto_fijo(concepto="Internet", monto_mensual_text="30", mes_inicio=MES, mes_fin=MES,
                           account_id=internet, created_at=now_iso())
    # Presupuestado pero sin cuenta: no hay con qué compararlo.
    repo.create_gasto_fijo(concepto="Varios sin enlazar", monto_mensual_text="50", mes_inicio=MES,
                           mes_fin=MES, created_at=now_iso())

    for cuenta, monto, detalle in ((alquiler, "450", "Alquiler"), (internet, "30", "Internet"),
                                   (papeleria, "18", "Resmas de papel")):
        repo.create_expense(detail=detalle, amount_text=monto, expense_date=f"{MES}-05", notes="",
                            created_at=now_iso(), account_id=cuenta)

    comp = repo.comparativo_gastos_fijos(mes=MES)
    por_concepto = {c["concepto"]: c for c in comp["conceptos"]}

    # El alquiler se pasó $50 y ahora se ve en su propia línea.
    assert por_concepto["Alquiler"]["presupuestado_cents"] == 40_000
    assert por_concepto["Alquiler"]["pagado_cents"] == 45_000
    assert por_concepto["Alquiler"]["brecha_cents"] == 5_000
    # Internet pegó exacto.
    assert por_concepto["Internet"]["brecha_cents"] == 0
    # Lo que no tiene cuenta enlazada se muestra igual, sin inventarle un pagado.
    assert por_concepto["Varios sin enlazar"]["pagado_cents"] is None
    assert por_concepto["Varios sin enlazar"]["brecha_cents"] is None
    # Y lo pagado que nadie presupuestó no se pierde.
    assert [x["account_nombre"] for x in comp["no_presupuestado"]] == ["Papelería"]
    assert comp["no_presupuestado"][0]["pagado_cents"] == 1_800

    assert comp["total_presupuestado_cents"] == 48_000
    assert comp["total_pagado_cents"] == 49_800
    assert comp["brecha_cents"] == 1_800


def test_el_gasto_fijo_guarda_y_cambia_su_cuenta(repo, catalogo, codigo_unico):
    uno = _cuenta(repo, codigo_unico, "021", "Cuenta uno")
    dos = _cuenta(repo, codigo_unico, "022", "Cuenta dos")
    gid = repo.create_gasto_fijo(concepto="Servicio", monto_mensual_text="100", mes_inicio=MES,
                                 mes_fin=MES, account_id=uno, created_at=now_iso())
    assert repo.get_gasto_fijo(gid)["account_id"] == uno

    repo.update_gasto_fijo(gid, concepto="Servicio", monto_mensual_text="100", mes_inicio=MES,
                           mes_fin=MES, account_id=dos, estado="Activo")
    assert repo.get_gasto_fijo(gid)["account_code"] == f"EGR-{codigo_unico}-022"

    repo.update_gasto_fijo(gid, concepto="Servicio", monto_mensual_text="100", mes_inicio=MES,
                           mes_fin=MES, account_id=None, estado="Activo")
    assert repo.get_gasto_fijo(gid)["account_id"] is None


def test_un_gasto_fijo_no_acepta_una_cuenta_de_ingreso(repo, catalogo, codigo_unico):
    import pytest
    with pytest.raises(ValueError, match="ingreso"):
        repo.create_gasto_fijo(concepto="Mal enlazado", monto_mensual_text="10", mes_inicio=MES,
                               account_id=catalogo["cuenta_id"], created_at=now_iso())


def test_avisa_del_expediente_que_cobro_sin_originador(repo, catalogo, codigo_unico):
    caso = repo.create_case(client_id=catalogo["cliente_id"], title=f"Caso sin originador {codigo_unico}",
                            status="Abierto", priority="Media", opened_at=f"{MES}-01",
                            created_at=now_iso(), honorarios_contratados_text="900")
    repo.create_income(amount_text="300", income_date=f"{MES}-10", created_at=now_iso(),
                       client_id=catalogo["cliente_id"], case_id=caso, account_id=catalogo["cuenta_id"])

    alertas = repo.dashboard_alerts()
    aviso = next(a for a in alertas["casos_sin_originador"] if a["id"] == caso)
    assert aviso["cobrado_cents"] == 30_000

    # Al configurar el originador, el aviso desaparece.
    repo.set_negocio_originadores(caso, originadores=[
        {"personal_id": catalogo["persona_id"], "porcentaje_participacion": 100, "tipo_origen": "Cliente nuevo"},
    ], created_at=now_iso())
    alertas = repo.dashboard_alerts()
    assert not [a for a in alertas["casos_sin_originador"] if a["id"] == caso]


def test_un_expediente_sin_cobros_no_genera_aviso(repo, catalogo, codigo_unico):
    caso = repo.create_case(client_id=catalogo["cliente_id"], title=f"Caso sin cobros {codigo_unico}",
                            status="Abierto", priority="Media", opened_at=f"{MES}-01",
                            created_at=now_iso(), honorarios_contratados_text="500")
    alertas = repo.dashboard_alerts()
    assert not [a for a in alertas["casos_sin_originador"] if a["id"] == caso]

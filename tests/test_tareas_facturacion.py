"""La tarea como registro de lo que de más se hizo en un expediente y de lo que costó.
Separa tres cosas que antes vivían en un solo campo: lo que se le cobra al cliente, lo que
nos costó hacerla y lo que se le recupera por ser reembolsable."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso

HOY = now_iso()[:10]


def _caso(repo, catalogo, honorarios="1000"):
    return repo.create_case(
        client_id=catalogo["cliente_id"], title="Caso tareas", service_id=catalogo["servicio_id"],
        honorarios_contratados_text=honorarios, costos_directos_estimados_text="0",
        status="Abierto", priority="Media", opened_at=HOY, created_at=now_iso(),
    )


def _cuenta_egreso(repo, codigo_unico):
    return repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-001", tipo="Egreso", grupo="Transporte",
        nombre=f"Transporte {codigo_unico}", naturaleza="Variable",
        centro_costo="Operación jurídica", created_at=now_iso(),
    )


def _tarea(repo, case_id, **kw):
    datos = dict(case_id=case_id, title="Ir al CNR por la certificación", due_date=None,
                 created_at=now_iso(), username="gsanchez")
    datos.update(kw)
    return repo.create_case_task(**datos)


def test_cobro_extra_exige_autorizacion(repo, catalogo):
    cid = _caso(repo, catalogo)
    with pytest.raises(ValueError, match="quién lo autorizó"):
        _tarea(repo, cid, monto_adicional_text="100")

    tid = _tarea(repo, cid, monto_adicional_text="100", autorizado_por="Cliente (llamada del 20/09)")
    tarea = repo.list_case_tasks(cid)[0]
    assert tarea["id"] == tid
    assert tarea["autorizado_por"] == "Cliente (llamada del 20/09)" and tarea["fecha_autorizacion"] == HOY
    # El cobro sube los honorarios del expediente y queda en la bitácora.
    assert repo.get_case(cid)["honorarios_contratados_cents"] == 110_000
    assert repo.list_case_honorarios_log(cid)[0]["monto_cents"] == 10_000


def test_el_costo_de_la_diligencia_llega_a_flujo_de_caja(repo, catalogo, codigo_unico):
    cid = _caso(repo, catalogo)
    cuenta = _cuenta_egreso(repo, codigo_unico)
    tid = _tarea(repo, cid, costo_real_text="25", costo_account_id=cuenta)

    tarea = repo.list_case_tasks(cid)[0]
    costo = repo.get_cost(tarea["cost_id"])
    assert costo["case_id"] == cid and costo["amount_cents"] == 2_500
    assert costo["account_code"] == f"EGR-{codigo_unico}-001"
    assert "Ir al CNR" in costo["detail"]
    # Es costo, no cobro: no toca los honorarios, pero sí la utilidad del expediente.
    assert repo.get_case(cid)["honorarios_contratados_cents"] == 100_000
    caso = next(c for c in repo.list_cases() if c["id"] == cid)
    assert caso["costos_directos_reales_cents"] == 2_500
    assert repo.update_case_task(tid, title="Ir al CNR por la certificación", costo_real_text="25",
                                 costo_account_id=cuenta, username="gsanchez") is None


def test_un_costo_reembolsable_no_reduce_la_utilidad(repo, catalogo, codigo_unico):
    cid = _caso(repo, catalogo)
    cuenta = _cuenta_egreso(repo, codigo_unico)
    _tarea(repo, cid, title="Pagar edicto", costo_real_text="23.75", costo_account_id=cuenta,
           costo_es_reembolsable=True)
    caso = next(c for c in repo.list_cases() if c["id"] == cid)
    # El dinero se adelantó y se recupera del cliente: neto operativo cero.
    assert caso["costos_directos_reales_cents"] == 0


def test_el_costo_sin_cuenta_contable_se_rechaza(repo, catalogo):
    cid = _caso(repo, catalogo)
    with pytest.raises(ValueError, match="cuenta contable"):
        _tarea(repo, cid, costo_real_text="25")


def test_completar_la_tarea_guarda_fecha_real_y_quien_la_cerro(repo, catalogo):
    cid = _caso(repo, catalogo)
    tid = _tarea(repo, cid, due_date="2026-01-01")
    repo.set_case_task_done(tid, True, "Certificación obtenida y entregada", username="gsanchez")
    tarea = repo.list_case_tasks(cid)[0]
    assert tarea["done"] == 1 and tarea["completed_at"] == HOY and tarea["completed_by"] == "gsanchez"
    assert tarea["completed_notes"] == "Certificación obtenida y entregada"
    assert tarea["due_date"] == "2026-01-01"  # lo estimado no se pisa con lo real

    repo.set_case_task_done(tid, False)
    assert repo.list_case_tasks(cid)[0]["completed_at"] is None


def test_editar_la_tarea_ajusta_honorarios_y_costo_sin_duplicar(repo, catalogo, codigo_unico):
    cid = _caso(repo, catalogo)
    cuenta = _cuenta_egreso(repo, codigo_unico)
    tid = _tarea(repo, cid, monto_adicional_text="100", autorizado_por="Socio",
                 costo_real_text="25", costo_account_id=cuenta)

    repo.update_case_task(tid, title="Ir al CNR por la certificación", monto_adicional_text="180",
                          autorizado_por="Socio", costo_real_text="40", costo_account_id=cuenta,
                          username="gsanchez")

    assert repo.get_case(cid)["honorarios_contratados_cents"] == 118_000  # 1000 + 180
    ajuste = repo.list_case_honorarios_log(cid)[0]
    assert ajuste["monto_cents"] == 8_000 and "Ajuste" in ajuste["motivo"]
    costos = [c for c in repo.list_costs_range(start_date=None, end_date=None) if c["case_id"] == cid]
    assert len(costos) == 1 and costos[0]["amount_cents"] == 4_000  # se actualiza, no se duplica


def test_borrar_la_tarea_revierte_cobro_y_costo(repo, catalogo, codigo_unico):
    cid = _caso(repo, catalogo)
    cuenta = _cuenta_egreso(repo, codigo_unico)
    tid = _tarea(repo, cid, monto_adicional_text="100", autorizado_por="Socio",
                 costo_real_text="25", costo_account_id=cuenta)
    repo.delete_case_task(tid, username="gsanchez")

    assert repo.get_case(cid)["honorarios_contratados_cents"] == 100_000
    assert not [c for c in repo.list_costs_range(start_date=None, end_date=None) if c["case_id"] == cid]


def test_la_tarea_llega_a_la_factura_con_su_monto(repo, catalogo):
    cid = _caso(repo, catalogo)
    _tarea(repo, cid, title="Escrito adicional", monto_adicional_text="120", autorizado_por="Cliente", estado="Hecha")
    partidas = repo.get_unbilled_items(catalogo["cliente_id"], cid)
    tarea = next(t for t in partidas["tasks"] if t["title"] == "Escrito adicional")
    assert tarea["monto_adicional_cents"] == 12_000

"""Que nada quede cobrando aire.

Una factura y lo que factura tienen que decir lo mismo: si se borra la tarea, si se
cambia el monto, si se anula la factura ya cobrada. Antes cada una de estas cosas
dejaba un descuadre silencioso entre la factura, el expediente y la caja."""
from __future__ import annotations

import pytest
from datetime import date
import uuid

from aglegal.db import now_iso

MES = "2027-12"  # mes propio: el schema de pruebas es compartido


def _caso(repo, catalogo, honorarios="1000", titulo="Caso facturable"):
    return repo.create_case(
        client_id=catalogo["cliente_id"], title=titulo, service_id=catalogo["servicio_id"],
        honorarios_contratados_text=honorarios, status="Abierto", priority="Media",
        opened_at=f"{MES}-01", created_at=now_iso(),
    )


def _factura(repo, catalogo, caso, numero, items, fecha=f"{MES}-15"):
    return repo.create_invoice(
        client_id=catalogo["cliente_id"], case_id=caso, invoice_number=numero, invoice_date=fecha,
        due_date=None, notes="", firm_name=None, firm_phone=None, firm_email=None,
        firm_address=None, firm_tax_id=None, items=items, created_at=now_iso(),
    )


def _tarea(repo, caso, titulo, monto="0"):
    return repo.create_case_task(
        case_id=caso, title=titulo, due_date=None, created_at=now_iso(),
        monto_adicional_text=monto, autorizado_por="Cliente" if monto != "0" else "",
        username="admin", estado="Hecha",
    )


# ── Partidas amarradas a su factura ─────────────────────────────────────────

def test_no_se_borra_una_tarea_ya_facturada(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    tid = _tarea(repo, caso, "Diligencia cobrada", "120")
    _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-01",
             [{"description": "Diligencia", "quantity": 1, "unit_price": 120,
               "entity_type": "case_task", "entity_id": tid}])

    with pytest.raises(ValueError, match="ya está cobrada en la factura"):
        repo.delete_case_task(tid, username="admin")
    assert repo.list_case_tasks(caso)  # la tarea sigue ahí


def test_no_se_cambia_el_monto_de_una_tarea_facturada_pero_si_lo_demas(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    tid = _tarea(repo, caso, "Escrito adicional", "50")
    _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-02",
             [{"description": "Escrito", "quantity": 1, "unit_price": 50,
               "entity_type": "case_task", "entity_id": tid}])

    with pytest.raises(ValueError, match="ya está cobrada en la factura"):
        repo.update_case_task(tid, title="Escrito adicional", monto_adicional_text="250",
                              autorizado_por="Cliente", username="admin")
    # Corregir el texto o la fecha sí se puede: lo que no puede cambiar es lo que se cobra.
    repo.update_case_task(tid, title="Escrito adicional ampliado", monto_adicional_text="50",
                          autorizado_por="Cliente", username="admin")
    assert repo.list_case_tasks(caso)[0]["title"] == "Escrito adicional ampliado"


def test_no_se_borra_una_cita_ya_facturada(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    sid = repo.create_session(
        client_id=catalogo["cliente_id"], case_id=caso, session_date=f"{MES}-05",
        start_time="09:00", end_time="10:00", consult_type="Audiencia", notes="",
        status="Finalizada", created_at=now_iso(),
    )
    _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-03",
             [{"description": "Audiencia", "quantity": 1, "unit_price": 90,
               "entity_type": "session", "entity_id": sid}])
    with pytest.raises(ValueError, match="ya está cobrada en la factura"):
        repo.delete_session(sid, username="admin")


def test_la_misma_tarea_no_se_factura_dos_veces(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    tid = _tarea(repo, caso, "Tarea única", "70")
    item = [{"description": "Tarea", "quantity": 1, "unit_price": 70,
             "entity_type": "case_task", "entity_id": tid}]
    _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-04", item)
    with pytest.raises(ValueError, match="reservada o facturada"):
        _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-05", item)


def test_un_tipo_de_partida_desconocido_se_rechaza(repo, catalogo, codigo_unico):
    """El tipo mal escrito no marcaba la partida como facturada: se podía cobrar de nuevo."""
    caso = _caso(repo, catalogo)
    tid = _tarea(repo, caso, "Tarea con tipo raro", "30")
    with pytest.raises(ValueError, match="Tipo de partida desconocido"):
        _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-06",
                 [{"description": "X", "quantity": 1, "unit_price": 30,
                   "entity_type": "task", "entity_id": tid}])


def test_no_hay_dos_facturas_con_el_mismo_numero(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    numero = f"FAC-{codigo_unico}-07"
    _factura(repo, catalogo, caso, numero, [{"description": "A", "quantity": 1, "unit_price": 10}])
    with pytest.raises(ValueError, match="Ya existe una factura con el número"):
        _factura(repo, catalogo, caso, numero, [{"description": "B", "quantity": 1, "unit_price": 10}])


# ── Cambiar el documento conserva el dinero recibido ───────────────

def test_cancelar_una_factura_pagada_conserva_el_cobro(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, honorarios="400")
    inv = _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-08",
                   [{"description": "Honorarios", "quantity": 1, "unit_price": 400}])
    repo.update_invoice_status(inv, "Enviada")
    repo.register_invoice_payment(inv, amount=repo.get_invoice(inv)['total_cents']/100,
        income_date=date.today().isoformat(), account_id=catalogo['cuenta_id'],request_key=uuid.uuid4().hex)
    assert [i for i in repo.list_incomes() if i["invoice_id"] == inv]

    repo.update_invoice_status(inv, "Cancelada")
    assert [i for i in repo.list_incomes() if i["invoice_id"] == inv]
    assert repo.list_invoice_payments(inv)[0]["released_at"]
    assert repo.get_case(caso)["honorarios_contratados_cents"] == 40_000  # el acuerdo no cambia


def test_borrar_una_factura_pagada_no_deja_el_cobro_huerfano(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, honorarios="300")
    inv = _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-09",
                   [{"description": "Honorarios", "quantity": 1, "unit_price": 300}])
    repo.update_invoice_status(inv, "Enviada")
    repo.register_invoice_payment(inv, amount=repo.get_invoice(inv)['total_cents']/100,
        income_date=date.today().isoformat(), account_id=catalogo['cuenta_id'],request_key=uuid.uuid4().hex)
    with pytest.raises(ValueError, match="Solo se eliminan borradores"):
        repo.delete_invoice(inv)
    assert [i for i in repo.list_incomes() if i["case_id"] == caso]


def test_no_se_borra_un_cobro_aplicado_a_factura(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, honorarios="200")
    inv = _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-10",
                   [{"description": "Honorarios", "quantity": 1, "unit_price": 200}])
    repo.update_invoice_status(inv, "Enviada")
    repo.register_invoice_payment(inv, amount=repo.get_invoice(inv)['total_cents']/100,
        income_date=date.today().isoformat(), account_id=catalogo['cuenta_id'],request_key=uuid.uuid4().hex)
    cobro = next(i for i in repo.list_incomes() if i["invoice_id"] == inv)

    with pytest.raises(ValueError,match="historial"):
        repo.delete_income(cobro["id"])
    assert repo.get_invoice(inv)["status"] == "Pagada"


def test_un_estado_de_factura_inventado_se_rechaza(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    inv = _factura(repo, catalogo, caso, f"FAC-{codigo_unico}-11",
                   [{"description": "A", "quantity": 1, "unit_price": 10}])
    with pytest.raises(ValueError, match="Estado de factura inválido"):
        repo.update_invoice_status(inv, "Anulada")


# ── Expediente y agenda ─────────────────────────────────────────────────────

def test_los_honorarios_no_pueden_bajar_de_lo_ya_cobrado(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, honorarios="1000", titulo="Caso con cobro")
    repo.create_income(amount_text="600", income_date=f"{MES}-05", created_at=now_iso(),
                       client_id=catalogo["cliente_id"], case_id=caso, account_id=catalogo["cuenta_id"])
    with pytest.raises(ValueError, match="no pueden quedar por debajo de lo ya cobrado"):
        repo.update_case(caso, title="Caso con cobro", status="Abierto", priority="Media",
                         opened_at=f"{MES}-01", closed_at=None, honorarios_contratados_text="300")
    # Bajarlos hasta lo cobrado sí se puede (renegociación a la baja).
    repo.update_case(caso, title="Caso con cobro", status="Abierto", priority="Media",
                     opened_at=f"{MES}-01", closed_at=None, honorarios_contratados_text="600")
    assert repo.get_case(caso)["honorarios_contratados_cents"] == 60_000


def test_avisa_cuando_la_cita_choca_con_otra(repo, catalogo):
    base = dict(client_id=catalogo["cliente_id"], case_id=None, session_date=f"{MES}-18",
                notes="", status="Pendiente", created_at=now_iso())
    repo.create_session(consult_type="Reunión con cliente", start_time="09:00", end_time="10:00", **base)

    with pytest.raises(ValueError, match="Ya hay otra cita a esa hora"):
        repo.create_session(consult_type="Otra reunión", start_time="09:30", end_time="10:30", **base)

    # Confirmando el cruce sí se agenda: el despacho es más de una persona.
    sid = repo.create_session(consult_type="Otra reunión", start_time="09:30", end_time="10:30",
                              permitir_solape=True, **base)
    assert sid
    # Una cita pegada a la anterior, sin encimarse, no molesta.
    assert repo.create_session(consult_type="Tercera", start_time="10:30", end_time="11:00", **base)


def test_cerrar_o_suspender_no_elimina_deuda_de_la_cartera(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, honorarios="900", titulo=f"Caso que se cae {codigo_unico}")
    repo.conn.execute("UPDATE cases SET mes_cobro_esperado=%s WHERE id=%s", (MES, caso))
    repo.conn.commit()
    assert any(c["id"] == caso for c in repo.cartera_pendiente_ponderada(mes=MES)["casos"])

    repo.update_case(caso, title=f"Caso que se cae {codigo_unico}", status="Cerrado", priority="Media",
                     opened_at=f"{MES}-01", closed_at=None, honorarios_contratados_text="900",
                     mes_cobro_esperado=MES, estado_cobro="Suspendido")
    assert any(c["id"] == caso for c in repo.cartera_pendiente_ponderada(mes=MES)["casos"])

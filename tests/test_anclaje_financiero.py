"""Ancla lo financiero a lo operativo: plantillas de tareas por servicio, incremento
automático de honorarios al agregar tareas/sesiones fuera de plantilla (con bitácora
reversible), y que una factura ligada a un expediente no pueda mezclar trabajo de otro."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


@pytest.fixture()
def caso(repo, catalogo):
    now = now_iso()
    case_id = repo.create_case(
        client_id=catalogo["cliente_id"], title="Divorcio de prueba", status="Abierto", priority="Media",
        opened_at="2026-01-10", created_at=now, service_id=catalogo["servicio_id"],
        honorarios_contratados_text="500",
    )
    return case_id


def test_plantilla_de_tareas_crud(repo, catalogo):
    now = now_iso()
    p1 = repo.create_plantilla_tarea(service_id=catalogo["servicio_id"], titulo="Recibir documentos", orden=1, created_at=now)
    repo.create_plantilla_tarea(service_id=catalogo["servicio_id"], titulo="Presentar demanda", orden=2, es_critico_default=True, created_at=now)
    tareas = repo.list_plantilla_tareas(catalogo["servicio_id"])
    assert [t["titulo"] for t in tareas] == ["Recibir documentos", "Presentar demanda"]
    repo.update_plantilla_tarea(p1, titulo="Recibir documentos del cliente", orden=1)
    assert repo.list_plantilla_tareas(catalogo["servicio_id"])[0]["titulo"] == "Recibir documentos del cliente"
    repo.delete_plantilla_tarea(p1)
    assert len(repo.list_plantilla_tareas(catalogo["servicio_id"])) == 1


def test_crear_caso_con_tareas_iniciales_no_altera_honorarios(repo, catalogo):
    now = now_iso()
    case_id = repo.create_case(
        client_id=catalogo["cliente_id"], title="Caso con plantilla", status="Abierto", priority="Media",
        opened_at="2026-01-10", created_at=now, honorarios_contratados_text="800",
        tareas_iniciales=[{"titulo": "Recibir documentos"}, {"titulo": "Presentar demanda", "es_critico": True}],
    )
    tareas = repo.list_case_tasks(case_id)
    assert len(tareas) == 2
    assert all(t["origen"] == "plantilla" for t in tareas)
    assert all(t["monto_adicional_cents"] == 0 for t in tareas)
    row = repo.get_case(case_id)
    assert row["honorarios_contratados_cents"] == 80_000  # sin cambio


def test_tarea_manual_con_monto_sube_honorarios_y_queda_en_bitacora(repo, caso):
    task_id = repo.create_case_task(
        case_id=caso, title="Trámite adicional pedido por el cliente", due_date=None, created_at=now_iso(),
        monto_adicional_text="150", username="abogada1",
    )
    row = repo.get_case(caso)
    assert row["honorarios_contratados_cents"] == 65_000  # 500 + 150

    log = repo.list_case_honorarios_log(caso)
    assert len(log) == 1
    assert log[0]["monto_cents"] == 15_000
    assert log[0]["origen_tipo"] == "tarea"
    assert log[0]["username"] == "abogada1"

    repo.delete_case_task(task_id, username="abogada1")
    row = repo.get_case(caso)
    assert row["honorarios_contratados_cents"] == 50_000  # vuelve a lo pactado
    log = repo.list_case_honorarios_log(caso)
    assert len(log) == 2
    assert log[0]["monto_cents"] == -15_000  # la reversión, más reciente primero


def test_tarea_sin_monto_no_toca_honorarios_ni_bitacora(repo, caso):
    repo.create_case_task(case_id=caso, title="Nota interna", due_date=None, created_at=now_iso())
    row = repo.get_case(caso)
    assert row["honorarios_contratados_cents"] == 50_000
    assert repo.list_case_honorarios_log(caso) == []


def test_sesion_con_monto_requiere_case_id(repo):
    with pytest.raises(ValueError, match="expediente"):
        repo.create_session(
            client_id=None, case_id=None, session_date="2026-02-01", consult_type="Consulta",
            notes="", status="Pendiente", created_at=now_iso(), monto_adicional_text="50",
        )


def test_sesion_con_monto_sube_honorarios_y_se_revierte_al_borrar(repo, caso, catalogo):
    session_id = repo.create_session(
        client_id=catalogo["cliente_id"], case_id=caso, session_date="2026-02-01", consult_type="Audiencia extra",
        notes="", status="Pendiente", created_at=now_iso(), monto_adicional_text="75", username="abogada1",
    )
    assert repo.get_case(caso)["honorarios_contratados_cents"] == 57_500
    repo.delete_session(session_id, username="abogada1")
    assert repo.get_case(caso)["honorarios_contratados_cents"] == 50_000


def test_factura_ligada_a_expediente_no_puede_mezclar_otro_expediente(repo, caso, catalogo):
    now = now_iso()
    otro_caso = repo.create_case(
        client_id=catalogo["cliente_id"], title="Otro expediente del mismo cliente", status="Abierto",
        priority="Media", opened_at="2026-01-10", created_at=now,
    )
    tarea_de_otro_caso = repo.create_case_task(case_id=otro_caso, title="Tarea de otro expediente", due_date=None, created_at=now)

    with pytest.raises(ValueError, match="otro expediente"):
        repo.create_invoice(
            client_id=catalogo["cliente_id"], case_id=caso, invoice_number=f"F-{caso}", invoice_date="2026-02-01",
            due_date=None, notes=None, firm_name=None, firm_phone=None, firm_email=None, firm_address=None,
            firm_tax_id=None, created_at=now,
            items=[{"description": "Tarea de otro expediente", "quantity": 1, "unit_price": 100,
                    "entity_type": "case_task", "entity_id": tarea_de_otro_caso}],
        )


def test_get_unbilled_items_filtra_por_case_id(repo, caso, catalogo):
    now = now_iso()
    otro_caso = repo.create_case(
        client_id=catalogo["cliente_id"], title="Otro expediente", status="Abierto", priority="Media",
        opened_at="2026-01-10", created_at=now,
    )
    repo.create_case_task(case_id=caso, title="Tarea del caso principal", due_date=None, created_at=now)
    repo.create_case_task(case_id=otro_caso, title="Tarea del otro caso", due_date=None, created_at=now)

    items_filtrados = repo.get_unbilled_items(catalogo["cliente_id"], case_id=caso)
    titulos = [t["title"] for t in items_filtrados["tasks"]]
    assert "Tarea del caso principal" in titulos
    assert "Tarea del otro caso" not in titulos

    items_sin_filtro = repo.get_unbilled_items(catalogo["cliente_id"])
    titulos_todos = [t["title"] for t in items_sin_filtro["tasks"]]
    assert "Tarea del caso principal" in titulos_todos
    assert "Tarea del otro caso" in titulos_todos


def test_borrar_factura_libera_las_partidas_para_refacturar(repo, caso, catalogo):
    now = now_iso()
    task_id = repo.create_case_task(case_id=caso, title="Redacción de contrato", due_date=None, created_at=now)
    invoice_id = repo.create_invoice(
        client_id=catalogo["cliente_id"], case_id=caso, invoice_number=f"F-{task_id}", invoice_date="2026-02-01",
        due_date=None, notes=None, firm_name=None, firm_phone=None, firm_email=None, firm_address=None,
        firm_tax_id=None, created_at=now,
        items=[{"description": "Redacción de contrato", "quantity": 1, "unit_price": 200,
                "entity_type": "case_task", "entity_id": task_id}],
    )
    # Ya facturada: no debe aparecer como pendiente
    assert task_id not in [t["id"] for t in repo.get_unbilled_items(catalogo["cliente_id"], case_id=caso)["tasks"]]

    repo.delete_invoice(invoice_id)
    # Al borrar la factura, vuelve a estar disponible para facturar
    assert task_id in [t["id"] for t in repo.get_unbilled_items(catalogo["cliente_id"], case_id=caso)["tasks"]]

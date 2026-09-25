"""La tarea como tarjeta de trabajo, y la plantilla como el plan de un tipo de caso.

Antes una tarea era una línea de checklist: título, fecha y listo. Un expediente de
divorcio nacía vacío y el abogado tecleaba los mismos doce pasos cada vez."""
from __future__ import annotations
from datetime import date

import pytest

from aglegal.db import now_iso

MES = "2028-03"  # año propio: el schema de pruebas es compartido


def _caso(repo, catalogo, titulo="Caso del tablero"):
    return repo.create_case(
        client_id=catalogo["cliente_id"], title=titulo, service_id=catalogo["servicio_id"],
        honorarios_contratados_text="1000", status="Abierto", priority="Media",
        opened_at=f"{MES}-01", created_at=now_iso(),
    )


def _etiqueta(repo, codigo_unico, nombre="Urgente", color="red"):
    return repo.create_etiqueta_tarea(nombre=f"{nombre} {codigo_unico}", color=color, created_at=now_iso())


# ── El tablero ──────────────────────────────────────────────────────────────

def test_la_tarea_nace_por_hacer_y_se_mueve_de_columna(repo, catalogo):
    caso = _caso(repo, catalogo)
    tid = repo.create_case_task(case_id=caso, title="Estudio registral", due_date=None,
                                created_at=now_iso(), username="admin")
    assert repo.list_case_tasks(caso)[0]["estado"] == "Por hacer"

    repo.set_case_task_estado(tid, "En curso", username="admin")
    assert repo.list_case_tasks(caso)[0]["estado"] == "En curso"

    # "En espera" es lo que está detenido por un tercero, no lo que nadie empezó.
    repo.set_case_task_estado(tid, "En espera", username="admin")
    tarea = repo.list_case_tasks(caso)[0]
    assert tarea["estado"] == "En espera" and tarea["done"] == 0


def test_mover_a_hecha_cierra_la_tarea_y_sacarla_la_reabre(repo, catalogo):
    caso = _caso(repo, catalogo)
    tid = repo.create_case_task(case_id=caso, title="Presentar escrito", due_date=None,
                                created_at=now_iso(), username="admin")
    repo.set_case_task_estado(tid, "Hecha", username="gsanchez", completed_notes="Presentado y sellado")
    tarea = repo.list_case_tasks(caso)[0]
    assert tarea["done"] == 1 and tarea["completed_at"] and tarea["completed_by"] == "gsanchez"
    assert tarea["completed_notes"] == "Presentado y sellado"

    repo.set_case_task_estado(tid, "En curso", username="gsanchez")
    tarea = repo.list_case_tasks(caso)[0]
    assert tarea["done"] == 0 and tarea["completed_at"] is None


def test_marcar_hecha_por_el_check_tambien_mueve_la_tarjeta(repo, catalogo):
    """El check de la lista y la columna del tablero son la misma verdad."""
    caso = _caso(repo, catalogo)
    tid = repo.create_case_task(case_id=caso, title="Llamar al cliente", due_date=None,
                                created_at=now_iso(), username="admin")
    repo.set_case_task_done(tid, True, "Confirmó la cita", username="admin")
    assert repo.list_case_tasks(caso)[0]["estado"] == "Hecha"
    repo.set_case_task_done(tid, False)
    assert repo.list_case_tasks(caso)[0]["estado"] == "Por hacer"


def test_un_estado_inventado_se_rechaza(repo, catalogo):
    caso = _caso(repo, catalogo)
    tid = repo.create_case_task(case_id=caso, title="X", due_date=None, created_at=now_iso())
    with pytest.raises(ValueError, match="Estado de tarea inválido"):
        repo.set_case_task_estado(tid, "Archivada")


# ── Etiquetas y asignados ───────────────────────────────────────────────────

def test_la_tarea_lleva_etiquetas_y_varias_personas(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo)
    urgente = _etiqueta(repo, codigo_unico, "Urgente", "red")
    espera = _etiqueta(repo, codigo_unico, "Espera cliente", "amber")
    tid = repo.create_case_task(
        case_id=caso, title="Recolectar documentos", due_date=f"{MES}-10", created_at=now_iso(),
        responsible_username="agallegos", asignados=["agallegos", "gsanchez"],
        etiqueta_ids=[urgente, espera], costo_estimado_text="35", username="admin",
    )
    tarea = next(t for t in repo.list_case_tasks(caso) if t["id"] == tid)
    assert sorted(tarea["asignados"]) == ["agallegos", "gsanchez"]
    assert {e["nombre"] for e in tarea["etiquetas"]} == {f"Urgente {codigo_unico}", f"Espera cliente {codigo_unico}"}
    assert tarea["costo_estimado_cents"] == 3_500
    assert tarea["responsible_username"] == "agallegos"  # responde uno solo


def test_lo_mio_incluye_lo_que_trabajo_con_alguien_mas(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, titulo=f"Caso compartido {codigo_unico}")
    repo.create_case_task(case_id=caso, title=f"Apoyo {codigo_unico}", due_date=None, created_at=now_iso(),
                          responsible_username="agallegos", asignados=["gsanchez"], username="admin")
    mias = repo.list_all_case_tasks(asignado="gsanchez", case_id=caso)
    assert [t["title"] for t in mias] == [f"Apoyo {codigo_unico}"]
    # Y el responsable también la ve, claro.
    assert repo.list_all_case_tasks(asignado="agallegos", case_id=caso)


def test_el_tablero_filtra_por_etiqueta_y_columna(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, titulo=f"Caso filtros {codigo_unico}")
    plazo = _etiqueta(repo, codigo_unico, "Plazo legal", "rose")
    con = repo.create_case_task(case_id=caso, title="Con etiqueta", due_date=None, created_at=now_iso(),
                                etiqueta_ids=[plazo], username="admin")
    repo.create_case_task(case_id=caso, title="Sin etiqueta", due_date=None, created_at=now_iso(), username="admin")
    repo.set_case_task_estado(con, "En curso", username="admin")

    assert [t["id"] for t in repo.list_all_case_tasks(case_id=caso, etiqueta_id=plazo)] == [con]
    assert [t["id"] for t in repo.list_all_case_tasks(case_id=caso, estado="En curso")] == [con]
    assert len(repo.list_all_case_tasks(case_id=caso, estado="Por hacer")) == 1


def test_no_se_repiten_etiquetas_ni_colores_invalidos(repo, codigo_unico):
    repo.create_etiqueta_tarea(nombre=f"Tribunal {codigo_unico}", color="blue", created_at=now_iso())
    with pytest.raises(ValueError, match="Ya existe una etiqueta"):
        repo.create_etiqueta_tarea(nombre=f"tribunal {codigo_unico}", color="red", created_at=now_iso())
    with pytest.raises(ValueError, match="Color inválido"):
        repo.create_etiqueta_tarea(nombre=f"Otra {codigo_unico}", color="fucsia", created_at=now_iso())


def test_borrar_una_etiqueta_no_borra_las_tareas(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, titulo=f"Caso etiqueta borrada {codigo_unico}")
    eti = _etiqueta(repo, codigo_unico, "Temporal", "slate")
    tid = repo.create_case_task(case_id=caso, title="Sigue viva", due_date=None, created_at=now_iso(),
                                etiqueta_ids=[eti], username="admin")
    repo.delete_etiqueta_tarea(eti)
    tarea = next(t for t in repo.list_case_tasks(caso) if t["id"] == tid)
    assert tarea["title"] == "Sigue viva" and tarea["etiquetas"] == []


# ── Cierre con lo que se obtuvo ─────────────────────────────────────────────

def test_cerrar_la_tarea_guarda_fecha_real_costo_final_y_resultado(repo, catalogo, codigo_unico):
    caso = _caso(repo, catalogo, titulo=f"Caso cierre {codigo_unico}")
    cuenta = repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-031", tipo="Egreso", grupo="Transporte", nombre="Viáticos",
        naturaleza="Variable", centro_costo="Operación jurídica", created_at=now_iso(),
    )
    tid = repo.create_case_task(case_id=caso, title="Ir al CNR", due_date=date.today().isoformat(),
                                created_at=now_iso(), costo_estimado_text="20", username="admin")

    repo.cerrar_case_task(tid, completed_at=date.today().isoformat(), completed_notes="Certificación literal obtenida",
                          costo_real_text="28", costo_account_id=cuenta, username="gsanchez")

    tarea = next(t for t in repo.list_case_tasks(caso) if t["id"] == tid)
    assert tarea["done"] == 1 and tarea["estado"] == "Hecha"
    assert tarea["completed_at"] == date.today().isoformat() and tarea["completed_by"] == "gsanchez"
    assert tarea["completed_notes"] == "Certificación literal obtenida"
    assert tarea["costo_estimado_cents"] == 2_000 and tarea["costo_real_cents"] == 2_800
    # El costo real llega a Flujo de caja con su cuenta, como cualquier gasto del expediente.
    costo = repo.get_cost(tarea["cost_id"])
    assert costo["amount_cents"] == 2_800 and costo["account_code"] == f"EGR-{codigo_unico}-031"


def test_no_se_cierra_una_tarea_sin_decir_que_se_obtuvo(repo, catalogo):
    caso = _caso(repo, catalogo)
    tid = repo.create_case_task(case_id=caso, title="Sin resultado", due_date=None, created_at=now_iso())
    with pytest.raises(ValueError, match="qué se obtuvo"):
        repo.cerrar_case_task(tid, completed_notes="   ", username="admin")


# ── Plantillas: el plan de trabajo de un tipo de caso ───────────────────────

def test_la_plantilla_guarda_el_plan_completo_del_servicio(repo, catalogo, codigo_unico):
    eti = _etiqueta(repo, codigo_unico, "Plazo", "rose")
    pid = repo.create_plantilla_tarea(
        service_id=catalogo["servicio_id"], titulo="Solicitar partida de matrimonio", orden=0,
        dias_plazo_relativo=3, es_critico_default=True, costo_estimado_text="5",
        descripcion="Se pide en la alcaldía donde se celebró el matrimonio.",
        responsable_sugerido="gsanchez", etiqueta_ids=[eti], created_at=now_iso(),
    )
    p = next(x for x in repo.list_plantilla_tareas(catalogo["servicio_id"]) if x["id"] == pid)
    assert p["descripcion"].startswith("Se pide en la alcaldía")
    assert p["responsable_sugerido"] == "gsanchez"
    assert p["dias_plazo_relativo"] == 3 and p["es_critico_default"] == 1
    assert [e["nombre"] for e in p["etiquetas"]] == [f"Plazo {codigo_unico}"]

    repo.update_plantilla_tarea(pid, titulo="Solicitar partida de matrimonio (certificada)", orden=0,
                                dias_plazo_relativo=5, es_critico_default=False,
                                descripcion="", responsable_sugerido="", etiqueta_ids=[])
    p = next(x for x in repo.list_plantilla_tareas(catalogo["servicio_id"]) if x["id"] == pid)
    assert p["titulo"].endswith("(certificada)") and p["dias_plazo_relativo"] == 5
    assert p["etiquetas"] == [] and p["descripcion"] is None


def test_la_plantilla_se_reordena(repo, catalogo):
    ids = [
        repo.create_plantilla_tarea(service_id=catalogo["servicio_id"], titulo=f"Paso {i}", orden=i,
                                    created_at=now_iso())
        for i in range(3)
    ]
    repo.reordenar_plantilla_tareas(catalogo["servicio_id"], [ids[2], ids[0], ids[1]])
    orden = [p["id"] for p in repo.list_plantilla_tareas(catalogo["servicio_id"])]
    assert orden == [ids[2], ids[0], ids[1]]


def test_la_plantilla_se_copia_de_un_servicio_parecido(repo, catalogo, codigo_unico):
    """Divorcio por mutuo consentimiento y contencioso comparten casi todos los pasos."""
    otro = repo.create_servicio(subcategory_id=catalogo["subcategoria_id"],
                                nombre=f"Servicio hermano {codigo_unico}", created_at=now_iso())
    eti = _etiqueta(repo, codigo_unico, "Tribunal", "violet")
    for i, titulo in enumerate(("Demanda", "Audiencia", "Sentencia")):
        repo.create_plantilla_tarea(service_id=catalogo["servicio_id"], titulo=titulo, orden=i,
                                    dias_plazo_relativo=i * 5, etiqueta_ids=[eti], created_at=now_iso())

    copiadas = repo.copiar_plantilla_tareas(origen_service_id=catalogo["servicio_id"],
                                            destino_service_id=otro, created_at=now_iso())
    destino = repo.list_plantilla_tareas(otro)
    assert copiadas == len(destino) >= 3
    assert [p["titulo"] for p in destino][:3] == ["Demanda", "Audiencia", "Sentencia"]
    assert [e["nombre"] for e in destino[0]["etiquetas"]] == [f"Tribunal {codigo_unico}"]

    with pytest.raises(ValueError, match="el mismo"):
        repo.copiar_plantilla_tareas(origen_service_id=otro, destino_service_id=otro, created_at=now_iso())


def test_el_expediente_nace_con_el_plan_de_trabajo(repo, catalogo, codigo_unico):
    eti = _etiqueta(repo, codigo_unico, "Inicio", "green")
    caso = repo.create_case(
        client_id=catalogo["cliente_id"], title=f"Divorcio {codigo_unico}", service_id=catalogo["servicio_id"],
        honorarios_contratados_text="800", status="Abierto", priority="Alta", opened_at=f"{MES}-01",
        created_at=now_iso(),
        tareas_iniciales=[
            {"titulo": "Solicitar partida de matrimonio", "due_date": f"{MES}-04", "es_critico": True,
             "notes": "En la alcaldía donde se celebró", "responsible_username": "gsanchez",
             "costo_estimado": 5, "etiqueta_ids": [eti], "asignados": ["gsanchez", "agallegos"]},
            {"titulo": "Redactar la demanda", "due_date": f"{MES}-08"},
        ],
    )
    tareas = {t["title"]: t for t in repo.list_case_tasks(caso)}
    assert len(tareas) == 2
    primera = tareas["Solicitar partida de matrimonio"]
    assert primera["origen"] == "plantilla" and primera["estado"] == "Por hacer"
    assert primera["responsible_username"] == "gsanchez" and primera["costo_estimado_cents"] == 500
    assert sorted(primera["asignados"]) == ["agallegos", "gsanchez"]
    assert [e["nombre"] for e in primera["etiquetas"]] == [f"Inicio {codigo_unico}"]
    # Las tareas de plantilla no recargan honorarios: ya están en lo pactado.
    assert repo.get_case(caso)["honorarios_contratados_cents"] == 80_000


def test_cambiar_la_plantilla_no_toca_los_expedientes_ya_abiertos(repo, catalogo, codigo_unico):
    """La plantilla es la receta, no un vínculo vivo: un caso en marcha no cambia solo."""
    pid = repo.create_plantilla_tarea(service_id=catalogo["servicio_id"], titulo="Paso original",
                                      orden=0, created_at=now_iso())
    caso = repo.create_case(
        client_id=catalogo["cliente_id"], title=f"Caso con plan {codigo_unico}",
        service_id=catalogo["servicio_id"], honorarios_contratados_text="500", status="Abierto",
        priority="Media", opened_at=f"{MES}-01", created_at=now_iso(),
        tareas_iniciales=[{"titulo": "Paso original"}],
    )
    repo.update_plantilla_tarea(pid, titulo="Paso cambiado después", orden=0)
    repo.delete_plantilla_tarea(pid)
    assert [t["title"] for t in repo.list_case_tasks(caso)] == ["Paso original"]

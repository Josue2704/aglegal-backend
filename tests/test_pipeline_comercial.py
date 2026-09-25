"""Embudo comercial: el prospecto se vuelve cliente al ganar, el seguimiento se trabaja por
fechas y la pérdida se clasifica. Cubre la Fase 1 de la auditoría de la ruta Pipeline → Clientes."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from aglegal.db import now_iso

HOY = date.today()
AYER = (HOY - timedelta(days=1)).isoformat()


def _oportunidad_prospecto(repo, catalogo, **kw):
    datos = dict(
        prospecto_nombre="Rosa Melgar", prospecto_contacto="7777-1234",
        service_id=catalogo["servicio_id"], canal_captacion="Referido", origen_negocio="Andrea",
        honorarios_estimados_text="900", created_at=now_iso(),
    )
    datos.update(kw)
    return repo.create_oportunidad(**datos)


def test_ganar_un_prospecto_lo_registra_como_cliente_y_abre_el_expediente(repo, catalogo, apertura):
    op = _oportunidad_prospecto(repo, catalogo, responsable_username="gsanchez")

    # Sin pedirlo explícitamente no se crea a nadie: el alta de cliente es una decisión.
    with pytest.raises(ValueError, match="registrarlo como cliente"):
        repo.transition_oportunidad(op, nuevo_estado="Ganado")

    case_id = repo.transition_oportunidad(op, nuevo_estado="Ganado", crear_cliente=True, **apertura, cliente_documento="04567890-1")
    caso = repo.get_case(case_id)
    cliente = repo.conn.execute("SELECT * FROM clients WHERE id=%s", (caso["client_id"],)).fetchone()

    assert cliente["name"] == "Rosa Melgar"
    assert cliente["phone"] == "7777-1234"          # el contacto capturado al primer toque
    assert cliente["id_number"] == "04567890-1"
    assert caso["honorarios_contratados_cents"] == 90_000
    assert caso["responsible_username"] == "admin"
    # La oportunidad queda ligada al cliente recién creado, no huérfana como prospecto.
    assert repo.get_oportunidad(op)["client_id"] == cliente["id"]


def test_el_email_del_prospecto_no_se_guarda_como_telefono(repo, catalogo, apertura):
    op = _oportunidad_prospecto(repo, catalogo, prospecto_nombre="Luis Pineda", prospecto_contacto="luis@correo.sv")
    case_id = repo.transition_oportunidad(op, nuevo_estado="Ganado", crear_cliente=True, **apertura)
    cliente = repo.conn.execute(
        "SELECT * FROM clients WHERE id=(SELECT client_id FROM cases WHERE id=%s)", (case_id,)
    ).fetchone()
    assert cliente["email"] == "luis@correo.sv" and not cliente["phone"]


def test_perdida_se_clasifica_con_un_motivo_de_la_lista(repo, catalogo):
    op = _oportunidad_prospecto(repo, catalogo)
    with pytest.raises(ValueError, match="Motivo de pérdida inválido"):
        repo.transition_oportunidad(op, nuevo_estado="Perdido", motivo_perdida_tipo="porque sí")
    repo.transition_oportunidad(op, nuevo_estado="Perdido", motivo_perdida_tipo="Precio", motivo_perdida="Pedía 30% menos")
    fila = repo.get_oportunidad(op)
    assert fila["motivo_perdida_tipo"] == "Precio" and fila["estado"] == "Perdido"
    assert fila["fecha_proxima_accion"] is None  # una oportunidad cerrada no sigue pidiendo seguimiento


def test_seguimiento_vencido_aparece_en_las_alertas(repo, catalogo):
    op = _oportunidad_prospecto(repo, catalogo, prospecto_nombre="Seguimiento Vencido",
                                proxima_accion="Llamar para confirmar", fecha_proxima_accion=AYER)
    vencidos = repo.dashboard_alerts()["seguimiento_vencido"]
    assert any(v["id"] == op and v["proxima_accion"] == "Llamar para confirmar" for v in vencidos)

    # Al cerrarse deja de reclamar seguimiento.
    repo.transition_oportunidad(op, nuevo_estado="Perdido", motivo_perdida_tipo="No respondió")
    assert not any(v["id"] == op for v in repo.dashboard_alerts()["seguimiento_vencido"])


def test_la_tarjeta_sabe_cuantos_dias_lleva_en_la_etapa(repo, catalogo):
    op = _oportunidad_prospecto(repo, catalogo)
    fila = next(o for o in repo.list_oportunidades() if o["id"] == op)
    assert fila["dias_en_etapa"] == 0
    repo.transition_oportunidad(op, nuevo_estado="Cotizado")
    assert next(o for o in repo.list_oportunidades() if o["id"] == op)["dias_en_etapa"] == 0


def test_avisa_si_el_contacto_ya_existe_como_cliente_oportunidad_o_contraparte(repo, catalogo):
    repo.create_client(name="Marta Quintanilla Vega", phone="7000-9999", created_at=now_iso())
    op = _oportunidad_prospecto(repo, catalogo, prospecto_nombre="Marta Quintanilla Vega")
    repo.create_case(
        client_id=catalogo["cliente_id"], title="Litigio", service_id=catalogo["servicio_id"],
        status="Abierto", priority="Media", opened_at=HOY.isoformat(), created_at=now_iso(),
        opposing_party="Marta Quintanilla Vega",
    )

    hallazgos = repo.buscar_contactos_parecidos(nombre="Quintanilla")
    assert [c["name"] for c in hallazgos["clientes"]] == ["Marta Quintanilla Vega"]
    assert any(o["id"] == op for o in hallazgos["oportunidades"])
    assert hallazgos["contrapartes"] and hallazgos["contrapartes"][0]["opposing_party"] == "Marta Quintanilla Vega"

    # Un nombre demasiado corto no dispara búsquedas inútiles mientras se teclea.
    assert repo.buscar_contactos_parecidos(nombre="Qu") == {"clientes": [], "oportunidades": [], "contrapartes": []}


def test_tambien_encuentra_por_telefono_aunque_el_nombre_este_escrito_distinto(repo, catalogo):
    repo.create_client(name="José Antonio Ramos", phone="7555-0101", created_at=now_iso())
    hallazgos = repo.buscar_contactos_parecidos(nombre="Jose Ramos", contacto="7555-0101")
    assert [c["name"] for c in hallazgos["clientes"]] == ["José Antonio Ramos"]

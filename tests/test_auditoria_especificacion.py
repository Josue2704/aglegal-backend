"""Regresión de los hallazgos críticos de la auditoría contra el Archivo Maestro AG Legal
(00_PARA_DESARROLLADOR, 12_Reglas_Comision, 13_Especificacion_Sistema, 14_Dashboard_KPIs).
Cada prueba falla con el comportamiento anterior a la corrección."""
from __future__ import annotations

import pytest
from datetime import date
import uuid

from aglegal.db import now_iso

MES = now_iso()[:7]


def _caso(repo, catalogo, *, honorarios="1000", costos="0", client_id=None):
    return repo.create_case(
        client_id=client_id or catalogo["cliente_id"], title="Caso auditoría", service_id=catalogo["servicio_id"],
        honorarios_contratados_text=honorarios, costos_directos_estimados_text=costos,
        status="Abierto", priority="Media", opened_at=f"{MES}-01", created_at=now_iso(),
    )


def _cobro(repo, catalogo, case_id, monto, *, dia="10", account_id=None, **kw):
    return repo.create_income(
        amount_text=monto, income_date=f"{MES}-{dia}", created_at=now_iso(), client_id=catalogo["cliente_id"],
        case_id=case_id, account_id=account_id or catalogo["cuenta_id"], **kw,
    )


def _originadora(repo, catalogo, case_id, tipo_origen="Cliente nuevo"):
    repo.set_negocio_originadores(
        case_id,
        originadores=[{"personal_id": catalogo["persona_id"], "porcentaje_participacion": 100, "tipo_origen": tipo_origen}],
        created_at=now_iso(),
    )


def _neto_comisiones(repo, case_id) -> int:
    return sum(int(c["comision_cents"]) for c in repo.list_comisiones(case_id=case_id))


# ── Comisiones ────────────────────────────────────────────────────────────────

def test_editar_cobro_revierte_y_recalcula_la_comision(repo, catalogo):
    cid = _caso(repo, catalogo)
    _originadora(repo, catalogo, cid)
    iid = _cobro(repo, catalogo, cid, "1000")
    assert _neto_comisiones(repo, cid) == 10_000  # 10% de $1,000

    repo.update_income(iid, amount_text="100", income_date=f"{MES}-10", client_id=catalogo["cliente_id"],
                       case_id=cid, account_id=catalogo["cuenta_id"])
    comisiones = repo.list_comisiones(case_id=cid)
    assert _neto_comisiones(repo, cid) == 1_000  # $100 − $100 + $10
    ajuste = next(c for c in comisiones if c["ajusta_a_commission_id"] is not None)
    assert "Corrección" in ajuste["motivo"]


def test_editar_cobro_sin_cambio_de_monto_no_genera_ajustes(repo, catalogo):
    cid = _caso(repo, catalogo)
    _originadora(repo, catalogo, cid)
    iid = _cobro(repo, catalogo, cid, "500")
    repo.update_income(iid, amount_text="500", income_date=f"{MES}-11", client_id=catalogo["cliente_id"],
                       case_id=cid, account_id=catalogo["cuenta_id"], detail="solo cambia el detalle")
    assert len(repo.list_comisiones(case_id=cid)) == 1


def test_borrar_cobro_deja_la_comision_revertida_en_el_historial(repo, catalogo):
    cid = _caso(repo, catalogo)
    _originadora(repo, catalogo, cid)
    iid = _cobro(repo, catalogo, cid, "500")
    repo.delete_income(iid)
    comisiones = repo.list_comisiones(case_id=cid)
    assert len(comisiones) == 2  # original + ajuste negativo, ninguno borrado
    assert _neto_comisiones(repo, cid) == 0
    original = next(c for c in comisiones if c["ajusta_a_commission_id"] is None)
    assert original["income_id"] is None and original["income_date"] == f"{MES}-10"


def test_configurar_originadores_despues_del_cobro_reconoce_la_comision(repo, catalogo):
    cid = _caso(repo, catalogo)
    _cobro(repo, catalogo, cid, "500")
    assert repo.list_comisiones(case_id=cid) == []
    _originadora(repo, catalogo, cid)
    assert _neto_comisiones(repo, cid) == 5_000


def test_cambiar_originadores_recalcula_con_el_reparto_nuevo(repo, catalogo):
    cid = _caso(repo, catalogo)
    _originadora(repo, catalogo, cid, "Cliente nuevo")
    _cobro(repo, catalogo, cid, "1000")
    _originadora(repo, catalogo, cid, "Venta cruzada")
    assert _neto_comisiones(repo, cid) == 5_000  # 100 − 100 + 5% de 1,000
    # Guardar el mismo reparto otra vez no genera ajustes nuevos.
    antes = len(repo.list_comisiones(case_id=cid))
    _originadora(repo, catalogo, cid, "Venta cruzada")
    assert len(repo.list_comisiones(case_id=cid)) == antes


def test_comision_revertida_no_sube_el_tramo_de_la_siguiente(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="5000")
    _originadora(repo, catalogo, cid)
    i1 = _cobro(repo, catalogo, cid, "1000", dia="02")
    c1 = repo.list_comisiones(income_id=i1)[0]
    repo.revertir_comision(c1["id"], created_at=now_iso())
    i2 = _cobro(repo, catalogo, cid, "1000", dia="03")
    assert repo.list_comisiones(income_id=i2)[0]["comision_cents"] == 10_000  # 10%, no 12%


def test_oportunidad_ganada_por_andrea_nace_con_originadora_y_honorarios(repo, catalogo, codigo_unico, apertura):
    repo.create_persona(persona=f"Andrea Auditoria{codigo_unico}", mes_inicio="2026-01", created_at=now_iso())
    op = repo.create_oportunidad(client_id=catalogo["cliente_id"], service_id=catalogo["servicio_id"],
                                 canal_captacion="Referido", origen_negocio="Andrea", created_at=now_iso(),
                                 honorarios_estimados_text="1500")
    case_id = repo.transition_oportunidad(op, nuevo_estado="Ganado", **dict(apertura, honorarios_pactados=1500))
    originadores = repo.list_negocio_originadores(case_id)
    assert [o["persona_nombre"] for o in originadores] == [f"Andrea Auditoria{codigo_unico}"]
    assert originadores[0]["tipo_origen"] == "Cliente nuevo"
    assert repo.get_case(case_id)["honorarios_contratados_cents"] == 150_000


# ── Saldo del expediente ─────────────────────────────────────────────────────

def test_cobro_que_excede_el_saldo_se_rechaza_salvo_ajuste(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="1000")
    _cobro(repo, catalogo, cid, "800")
    with pytest.raises(ValueError, match="excede el saldo"):
        _cobro(repo, catalogo, cid, "300")
    iid = _cobro(repo, catalogo, cid, "300", es_ajuste=True)
    assert repo.get_income(iid)["es_ajuste"] is True


def test_editar_un_cobro_no_se_cuenta_a_si_mismo_en_el_saldo(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="1000")
    iid = _cobro(repo, catalogo, cid, "1000")
    repo.update_income(iid, amount_text="1000", income_date=f"{MES}-12", client_id=catalogo["cliente_id"],
                       case_id=cid, account_id=catalogo["cuenta_id"])


def test_cobro_a_expediente_sin_honorarios_exige_ajuste(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="0")
    with pytest.raises(ValueError, match="no tiene honorarios"):
        _cobro(repo, catalogo, cid, "50")


def test_el_iva_no_cuenta_contra_el_saldo(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="100")
    _cobro(repo, catalogo, cid, "113", monto_iva_text="13")  # neto $100 = saldo exacto


def test_cobro_completa_el_servicio_desde_el_expediente(repo, catalogo):
    cid = _caso(repo, catalogo)
    iid = _cobro(repo, catalogo, cid, "100")
    assert repo.get_income(iid)["service_id"] == catalogo["servicio_id"]


# ── Dashboard: ingresos netos (KPI-001 "Excluir IVA y reembolsos") ───────────

def test_ingresos_del_mes_excluyen_iva_y_fondos_de_terceros(repo, catalogo):
    antes = repo.dashboard_metrics_month()["incomes_cents"]
    repo.create_income(amount_text="150", income_date=now_iso()[:10], created_at=now_iso(),
                       account_id=catalogo["cuenta_id"], monto_iva_text="13", monto_fondos_terceros_text="37")
    assert repo.dashboard_metrics_month()["incomes_cents"] - antes == 10_000


# ── Familia por cuenta de ingreso (04_Plan_Cuentas, "Código familia relacionado") ──

def test_cumplimiento_por_familia_usa_la_cuenta_del_cobro(repo, catalogo, codigo_unico):
    now = now_iso()
    # El servicio del expediente es de la categoría A (familia A), pero se cobra con la cuenta
    # de la familia B — como una compraventa notarial cobrada con ING-RAI-001.
    fam_a = repo.create_familia(category_id=catalogo["categoria_id"], nombre=f"Familia A {codigo_unico}", created_at=now)
    cat_b = repo.create_categoria(category_code=codigo_unico[::-1] + "Q", nombre=f"Categoria B {codigo_unico}", created_at=now)
    fam_b = repo.create_familia(category_id=cat_b, nombre=f"Familia B {codigo_unico}", created_at=now)
    cuenta_b = repo.create_cuenta(account_code=f"ING-{codigo_unico[::-1]}-002", tipo="Ingreso", grupo="Honorarios",
                                  nombre=f"Ingresos B {codigo_unico}", naturaleza="Operativo", family_id=fam_b,
                                  centro_costo="Operación jurídica", created_at=now)
    for fam in (fam_a, fam_b):
        repo.create_forecast(family_id=fam, mes=MES, volumen_meta_text="1", ticket_objetivo_text="300",
                             margen_directo_objetivo_pct=0.8, created_at=now)
    cid = _caso(repo, catalogo)
    _cobro(repo, catalogo, cid, "300", account_id=cuenta_b)
    por_familia = {r["family_id"]: r for r in repo.cumplimiento_por_familia(mes=MES)}
    assert por_familia[fam_b]["ingresos_reales_cents"] == 30_000
    assert por_familia[fam_a]["ingresos_reales_cents"] == 0


# ── Histórico: no se purga lo que tiene movimientos ─────────────────────────

def test_no_se_purga_expediente_ni_cliente_con_cobros(repo, catalogo):
    cid = _caso(repo, catalogo)
    _cobro(repo, catalogo, cid, "100")
    repo.archive_case(cid, archived_at=now_iso())
    with pytest.raises(ValueError, match="no se puede eliminar"):
        repo.delete_case(cid)
    with pytest.raises(ValueError, match="no se puede eliminar"):
        repo.delete_client(catalogo["cliente_id"])


def test_expediente_sin_movimientos_si_se_puede_purgar(repo, catalogo):
    cid = _caso(repo, catalogo)
    repo.delete_case(cid)
    with pytest.raises(ValueError):
        repo.get_case(cid)


# ── Factura pagada → cobro ──────────────────────────────────────────────────

def test_registrar_pago_genera_cobro_con_cuenta_y_comision(repo, catalogo):
    cid = _caso(repo, catalogo, honorarios="1000")
    _originadora(repo, catalogo, cid)
    inv = repo.conn.execute(
        "INSERT INTO invoices(invoice_number, client_id, case_id, invoice_date, status, total_cents, created_at) "
        "VALUES(%s,%s,%s,%s,'Enviada',%s,%s) RETURNING id",
        (f"AUD-{catalogo['cliente_id']}", catalogo["cliente_id"], cid, f"{MES}-15", 40_000, now_iso()),
    ).fetchone()["id"]
    repo.conn.commit()
    repo.register_invoice_payment(inv,amount=400,income_date=date.today().isoformat(),account_id=catalogo['cuenta_id'],request_key=uuid.uuid4().hex)
    income = repo.conn.execute("SELECT * FROM incomes WHERE invoice_id=%s", (inv,)).fetchone()
    assert income["account_id"] is not None and income["case_id"] == cid
    assert _neto_comisiones(repo, cid) == 4_000


# ── Recorrido de abogada (ronda 2) ──────────────────────────────────────────

def test_documento_de_identidad_unico(repo, catalogo, codigo_unico):
    doc = f"0{abs(hash(codigo_unico)) % 10**7:07d}-9"
    repo.create_client(name="Cliente A", id_number=doc, created_at=now_iso())
    with pytest.raises(ValueError, match="documento de identidad"):
        repo.create_client(name="Cliente B", id_number=doc.replace("-", " "), created_at=now_iso())
    otro = repo.create_client(name="Cliente C", id_number="", created_at=now_iso())
    with pytest.raises(ValueError, match="documento de identidad"):
        repo.update_client(otro, name="Cliente C", id_number=doc.replace("-", ""))


def test_mes_de_cobro_anterior_a_la_apertura_tambien_al_editar(repo, catalogo):
    cid = _caso(repo, catalogo)
    with pytest.raises(ValueError, match="anterior a la fecha de apertura"):
        repo.update_case(cid, title="x", status="Abierto", priority="Media", opened_at=f"{MES}-01", closed_at=None,
                         service_id=catalogo["servicio_id"], mes_cobro_esperado="2020-01")


def test_aviso_de_cita_consulta_al_cliente_antes_de_cerrar_la_conexion(repo, catalogo, monkeypatch):
    """El correo de la cita se enviaba desde un hilo que consultaba la base con la conexión de
    la petición ya cerrada ("connection already closed") — el cliente nunca recibía el aviso."""
    from api.app.routers import sessions as ses

    enviados = []
    monkeypatch.setattr(ses, "send_session_email", lambda **kw: enviados.append(kw))
    monkeypatch.setattr(ses, "get_settings", lambda: type("S", (), {"resend_api_key": "x", "firm_name": "AG", "resend_from_email": "a@b"})())
    cliente = repo.create_client(name="Cliente Aviso", email="cliente@correo.sv", created_at=now_iso())
    sid = repo.create_session(client_id=cliente, case_id=None, session_date=f"{MES}-20", consult_type="Consulta",
                              notes="", status="Pendiente", created_at=now_iso())
    ses._email_notify(dict(repo.get_session(sid)), repo, False)
    ses._executor.shutdown(wait=True)
    ses._executor = type(ses._executor)(max_workers=2)
    assert [e["client_email"] for e in enviados] == ["cliente@correo.sv"]


# ── Consistencia de vistas (ronda 3) ────────────────────────────────────────

def test_expediente_individual_y_titulo_en_citas(repo, catalogo):
    """El panel del expediente se refresca con GET /cases/{id} (incluso en la papelera) y las
    citas traen el título del expediente en vez de solo su número."""
    from fastapi.testclient import TestClient
    from api.app.deps import get_current_user
    from api.app.main import app

    cid = _caso(repo, catalogo, honorarios="500")
    repo.create_session(client_id=catalogo["cliente_id"], case_id=cid, session_date=f"{MES}-21",
                        consult_type="Firma", notes="", status="Pendiente", created_at=now_iso())
    repo.archive_case(cid, archived_at=now_iso())
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "t", "role": "Administrador",
                                                          "role_id": None, "is_admin": True, "permissions": set()}
    try:
        with TestClient(app) as c:
            r = c.get(f"/cases/{cid}")
            assert r.status_code == 200 and r.json()["id"] == cid and r.json()["saldo_pendiente"] == 500
            assert c.get("/cases/999999").status_code == 404
            assert c.get("/cases/tasks").status_code == 200  # la ruta fija no la captura el comodín
            sesiones = c.get(f"/cases/{cid}/sessions").json()
            assert sesiones[0]["case_title"] == "Caso auditoría"
    finally:
        app.dependency_overrides.clear()

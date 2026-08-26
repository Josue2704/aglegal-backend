"""Comisión de Andrea (COM-001/002/003 + venta cruzada) — la fórmula donde un error es
directamente dinero mal pagado. Cubre: los umbrales exactos del Excel maestro, el cálculo
marginal por tramos acumulados, la tasa plana de venta cruzada, y que el desglose por tramo
expuesto a la UI (Fase 4) sume exactamente el total de la comisión."""
from __future__ import annotations

from aglegal.db import now_iso
from aglegal.repositories import (
    COMISION_TRAMO1_CENTS,
    COMISION_TRAMO2_CENTS,
    COMISION_TRAMO3_PCT,
    COMISION_VENTA_CRUZADA_PCT,
    Repository,
)


def test_umbrales_coinciden_con_el_archivo_maestro():
    """10% hasta $1,000, 12% de $1,000.01 a $2,500, 15% del excedente, 5% venta cruzada."""
    assert COMISION_TRAMO1_CENTS == 100_000
    assert COMISION_TRAMO2_CENTS == 250_000
    assert COMISION_TRAMO3_PCT == 0.15
    assert COMISION_VENTA_CRUZADA_PCT == 0.05


def test_formula_comision_tramos_puntos_de_quiebre():
    f = Repository._formula_comision_tramos
    assert f(0) == 0
    assert f(50_000) == 5_000  # $500 * 10% = $50
    assert f(COMISION_TRAMO1_CENTS) == 10_000  # $1,000 * 10% = $100
    # $100 (tramo 1) + $180 (tramo 2: $1,500*12%) = $280
    assert f(COMISION_TRAMO2_CENTS) == 28_000
    # + $150 (tramo 3: $1,000*15%) sobre una utilidad de $3,500
    assert f(350_000) == 43_000


def _crear_originador(repo, catalogo, tipo_origen: str):
    now = now_iso()
    caso_id = repo.create_case(
        client_id=catalogo["cliente_id"], title=f"Caso comisión {tipo_origen}", service_id=catalogo["servicio_id"],
        honorarios_contratados_text="5000", costos_directos_estimados_text="0",
        opened_at="2026-08-01", created_at=now, status="Abierto", priority="Media",
    )
    repo.set_negocio_originadores(
        caso_id, originadores=[{"personal_id": catalogo["persona_id"], "porcentaje_participacion": 100.0, "tipo_origen": tipo_origen}],
        created_at=now,
    )
    return caso_id


def test_comision_cruza_tramo1_a_tramo2(repo, catalogo):
    caso_id = _crear_originador(repo, catalogo, "Cliente nuevo")
    income_id = repo.create_income(
        amount_text="1500", income_date="2026-08-10", created_at=now_iso(),
        account_id=catalogo["cuenta_id"], case_id=caso_id,
    )
    comisiones = repo.reconocer_comision_income(income_id, created_at=now_iso())
    assert len(comisiones) == 1
    c = comisiones[0]
    # $1,000 al 10% + $500 al 12% = $100 + $60 = $160
    assert int(c["comision_cents"]) == 16_000
    assert int(c["base_acumulada_antes_cents"]) == 0
    assert int(c["base_acumulada_despues_cents"]) == 150_000


def test_comision_cruza_tramo2_a_tramo3_y_acumula_con_cobro_previo(repo, catalogo):
    caso_id = _crear_originador(repo, catalogo, "Cliente nuevo")
    now = now_iso()
    income1 = repo.create_income(amount_text="1500", income_date="2026-08-10", created_at=now, account_id=catalogo["cuenta_id"], case_id=caso_id)
    repo.reconocer_comision_income(income1, created_at=now)
    income2 = repo.create_income(amount_text="2000", income_date="2026-08-15", created_at=now, account_id=catalogo["cuenta_id"], case_id=caso_id)
    comisiones2 = repo.reconocer_comision_income(income2, created_at=now)
    c2 = comisiones2[0]
    # Acumulado pasa de $1,500 a $3,500 — cruza el límite de $2,500 (tramo2→tramo3)
    # $1,000 restante al 12% ($120) + $1,000 al 15% ($150) = $270
    assert int(c2["comision_cents"]) == 27_000
    assert int(c2["base_acumulada_antes_cents"]) == 150_000
    assert int(c2["base_acumulada_despues_cents"]) == 350_000


def test_venta_cruzada_es_tasa_plana_no_acumulada(repo, catalogo):
    caso_id = _crear_originador(repo, catalogo, "Venta cruzada")
    income_id = repo.create_income(amount_text="500", income_date="2026-08-10", created_at=now_iso(), account_id=catalogo["cuenta_id"], case_id=caso_id)
    comisiones = repo.reconocer_comision_income(income_id, created_at=now_iso())
    c = comisiones[0]
    assert int(c["comision_cents"]) == 2_500  # $500 * 5%


def test_reconocer_comision_es_idempotente(repo, catalogo):
    """Reconocer dos veces el mismo ingreso no debe duplicar la comisión — el punto de
    entrada es llamado automáticamente al registrar un ingreso ligado a un expediente."""
    caso_id = _crear_originador(repo, catalogo, "Cliente nuevo")
    income_id = repo.create_income(amount_text="500", income_date="2026-08-10", created_at=now_iso(), account_id=catalogo["cuenta_id"], case_id=caso_id)
    primera = repo.reconocer_comision_income(income_id, created_at=now_iso())
    segunda = repo.reconocer_comision_income(income_id, created_at=now_iso())
    assert len(primera) == 1
    assert [c["id"] for c in segunda] == [c["id"] for c in primera]


def test_desglose_tramos_suma_el_total_de_la_comision(repo, catalogo):
    caso_id = _crear_originador(repo, catalogo, "Cliente nuevo")
    income_id = repo.create_income(amount_text="2000", income_date="2026-08-10", created_at=now_iso(), account_id=catalogo["cuenta_id"], case_id=caso_id)
    c = repo.reconocer_comision_income(income_id, created_at=now_iso())[0]
    tramos = Repository.desglose_tramos_comision(c["tipo_origen"], c["base_acumulada_antes_cents"], c["base_acumulada_despues_cents"])
    assert sum(t["monto_cents"] for t in tramos) == int(c["comision_cents"])


def test_revertir_comision_no_representa_un_tramo_real(repo, catalogo):
    caso_id = _crear_originador(repo, catalogo, "Cliente nuevo")
    income_id = repo.create_income(amount_text="500", income_date="2026-08-10", created_at=now_iso(), account_id=catalogo["cuenta_id"], case_id=caso_id)
    c = repo.reconocer_comision_income(income_id, created_at=now_iso())[0]
    ajuste = repo.revertir_comision(c["id"], created_at=now_iso())
    assert int(ajuste["comision_cents"]) == -int(c["comision_cents"])
    assert Repository.desglose_tramos_comision(ajuste["tipo_origen"], ajuste["base_acumulada_antes_cents"], ajuste["base_acumulada_despues_cents"]) == []

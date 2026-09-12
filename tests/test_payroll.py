"""Repositorio de nómina: enlace Personal→cuenta contable, modo calculado vs manual,
unicidad de planilla mensual por persona, y edición con bitácora de auditoría."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


@pytest.fixture()
def cuenta_personal(repo, codigo_unico):
    now = now_iso()
    return repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-001", tipo="Egreso", grupo="Personal", nombre=f"Nómina {codigo_unico}",
        naturaleza="Fijo", centro_costo="Administración", created_at=now,
    )


@pytest.fixture()
def persona_con_cuenta(repo, codigo_unico, cuenta_personal):
    now = now_iso()
    return repo.create_persona(
        persona=f"Colaborador {codigo_unico}", cargo="Asistente", monto_mensual_text="800",
        mes_inicio="2026-01", account_id=cuenta_personal, created_at=now,
    )


@pytest.fixture()
def payroll_config_vigente(repo):
    """La config sembrada en la migración v35 ya cubre 'hoy' en la mayoría de entornos de
    prueba, pero la creamos explícita aquí para no depender de la fecha del seed."""
    try:
        return repo.get_payroll_config_vigente()
    except ValueError:
        config_id = repo.create_payroll_config(
            vigente_desde="2020-01-01",
            isss_tasa_empleado=0.03, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
            afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )
        return next(r for r in repo.list_payroll_config_historial() if r["id"] == config_id)


def test_planilla_calculada_requiere_persona_del_catalogo(repo, payroll_config_vigente):
    with pytest.raises(ValueError, match="catálogo"):
        repo.create_payroll(
            period="2026-08", payment_date="2026-08-31", notes="", created_at=now_iso(),
            modo="calculado", salario_base_text="800",
        )


def test_planilla_calculada_requiere_cuenta_contable_enlazada(repo, codigo_unico, payroll_config_vigente):
    now = now_iso()
    persona_id = repo.create_persona(persona=f"Sin cuenta {codigo_unico}", mes_inicio="2026-01", created_at=now)
    with pytest.raises(ValueError, match="cuenta contable enlazada"):
        repo.create_payroll(
            period="2026-08", payment_date="2026-08-31", notes="", created_at=now,
            personal_id=persona_id, modo="calculado", salario_base_text="800",
        )


def test_planilla_calculada_persiste_el_desglose_completo(repo, persona_con_cuenta, payroll_config_vigente):
    payroll_id = repo.create_payroll(
        period="2026-08", payment_date="2026-08-31", notes="Agosto", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
        horas_extra_cantidad=5, bonificaciones_text="50",
    )
    row = repo.get_payroll(payroll_id)
    assert row["modo"] == "calculado"
    assert row["salario_base_cents"] == 80_000
    assert row["bonificaciones_cents"] == 5_000
    assert row["horas_extra_monto_cents"] > 0
    assert row["isss_empleado_cents"] > 0
    assert row["afp_empleado_cents"] > 0
    # El neto persistido en amount_cents debe coincidir con devengado - deducciones
    assert row["amount_cents"] == row["total_devengado_cents"] - row["total_descuentos_cents"]
    # Y debe haber creado el gasto espejo enlazado a la cuenta explícita de la persona
    assert row["expense_id"] is not None


def test_no_se_puede_duplicar_la_planilla_calculada_del_mismo_mes(repo, persona_con_cuenta, payroll_config_vigente):
    repo.create_payroll(
        period="2026-09", payment_date="2026-09-30", notes="", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
    )
    with pytest.raises(ValueError, match="Ya existe una planilla"):
        repo.create_payroll(
            period="2026-09", payment_date="2026-09-30", notes="", created_at=now_iso(),
            personal_id=persona_con_cuenta, modo="calculado", salario_base_text="800",
        )


def test_pago_manual_no_bloquea_duplicados_del_mismo_mes(repo, persona_con_cuenta):
    """Un bono suelto sí puede repetirse en el mismo periodo — la unicidad solo aplica a
    la planilla mensual calculada."""
    repo.create_payroll(
        period="2026-10", payment_date="2026-10-15", notes="Bono 1", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="100",
    )
    payroll_id = repo.create_payroll(
        period="2026-10", payment_date="2026-10-20", notes="Bono 2", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="50",
    )
    assert repo.get_payroll(payroll_id)["amount_cents"] == 5_000


def test_editar_planilla_registra_bitacora_de_auditoria(repo, persona_con_cuenta):
    payroll_id = repo.create_payroll(
        period="2026-11", payment_date="2026-11-30", notes="Original", created_at=now_iso(),
        personal_id=persona_con_cuenta, modo="manual", amount_text="500",
    )
    repo.update_payroll(payroll_id, payment_date="2026-12-01", notes="Corregido", amount_text="550", username="tester")
    row = repo.get_payroll(payroll_id)
    assert row["amount_cents"] == 55_000
    assert row["payment_date"] == "2026-12-01"
    log = repo.list_payroll_audit_log(payroll_id)
    campos_cambiados = {entry["campo"] for entry in log}
    assert {"amount_cents", "payment_date", "notes"} <= campos_cambiados
    assert all(entry["username"] == "tester" for entry in log)


def test_config_de_nomina_es_versionada_y_no_se_edita(repo):
    config_id = repo.create_payroll_config(
        vigente_desde="2030-01-01",
        isss_tasa_empleado=0.03, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
        afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
        tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
        horas_jornada_mensual=240, created_at=now_iso(),
    )
    with pytest.raises(ValueError, match="Ya existe"):
        repo.create_payroll_config(
            vigente_desde="2030-01-01",
            isss_tasa_empleado=0.04, isss_tasa_patronal=0.08, isss_tope_cotizable_text="1200",
            afp_tasa_empleado=0.08, afp_tasa_patronal=0.09, afp_tope_cotizable_text="1200",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )
    vigente_futura = repo.get_payroll_config_vigente(fecha="2030-06-01")
    assert vigente_futura["id"] == config_id


def test_tasa_de_ley_fuera_de_rango_es_rechazada(repo):
    with pytest.raises(ValueError, match="tasa"):
        repo.create_payroll_config(
            vigente_desde="2031-01-01",
            isss_tasa_empleado=1.5, isss_tasa_patronal=0.075, isss_tope_cotizable_text="1000",
            afp_tasa_empleado=0.0725, afp_tasa_patronal=0.0875, afp_tope_cotizable_text="1000",
            tramos_renta=[], recargo_hora_extra_pct=0.5, recargo_nocturnidad_pct=0.25,
            horas_jornada_mensual=240, created_at=now_iso(),
        )

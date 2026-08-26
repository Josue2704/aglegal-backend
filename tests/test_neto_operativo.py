"""Monto neto operativo y las dos reglas de integridad de Fase 1 del Archivo Maestro:
todo movimiento debe llevar cuenta contable, y el neto operativo (base de la comisión y
del P&L) debe restar IVA, reembolsable Y fondos de terceros — no solo los dos primeros."""
from __future__ import annotations

import pytest

from aglegal.db import now_iso


def test_neto_operativo_resta_iva_reembolsable_y_fondos_terceros(repo, catalogo):
    income_id = repo.create_income(
        amount_text="500", income_date="2026-08-10", created_at=now_iso(),
        account_id=catalogo["cuenta_id"],
        monto_iva_text="65", monto_reembolsable_text="20", monto_fondos_terceros_text="50",
    )
    row = repo.get_income(income_id)
    # 500 - 65 - 20 - 50 = 365
    assert int(row["monto_neto_operativo_cents"]) == 36_500


def test_movimiento_sin_cuenta_contable_es_rechazado(repo):
    with pytest.raises(ValueError, match="cuenta contable"):
        repo.create_income(amount_text="100", income_date="2026-08-10", created_at=now_iso())


def test_iva_reembolsable_y_fondos_no_pueden_superar_el_bruto(repo, catalogo):
    with pytest.raises(ValueError):
        repo.create_income(
            amount_text="100", income_date="2026-08-10", created_at=now_iso(),
            account_id=catalogo["cuenta_id"],
            monto_iva_text="50", monto_reembolsable_text="30", monto_fondos_terceros_text="30",
        )


def test_cuenta_de_egreso_no_se_puede_usar_en_un_ingreso(repo, codigo_unico):
    now = now_iso()
    cuenta_egreso_id = repo.create_cuenta(
        account_code=f"EGR-{codigo_unico}-001", tipo="Egreso", grupo="Gastos", nombre=f"Gastos {codigo_unico}",
        naturaleza="Fijo", centro_costo="Administración", created_at=now,
    )
    with pytest.raises(ValueError):
        repo.create_income(amount_text="100", income_date="2026-08-10", created_at=now, account_id=cuenta_egreso_id)

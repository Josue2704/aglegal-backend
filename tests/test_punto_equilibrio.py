"""Punto de equilibrio — gastos_fijos / (1 - costo_variable_pct), más meta segura y ventas
para margen meta. Un error aquí hace que el Dashboard muestre una meta de ventas equivocada."""
from __future__ import annotations

from aglegal.db import now_iso


def test_calcular_punto_equilibrio_formula(repo, codigo_unico):
    now = now_iso()
    periodo = "2031"  # año fuera de rango de cualquier otra prueba/dato real, evita cruces
    mes = f"{periodo}-01"

    repo.create_gasto_fijo(concepto=f"Renta {codigo_unico}", monto_mensual_text="2000", mes_inicio=mes, created_at=now)
    repo.create_supuestos(periodo=periodo, costo_variable_pct=0.2, margen_operativo_meta_pct=0.1, margen_seguridad_pct=0.15, created_at=now)

    resultado = repo.calcular_punto_equilibrio(mes=mes)

    assert resultado["gastos_fijos_cents"] == 200_000
    # 2000 / (1 - 0.2) = 2500
    assert resultado["punto_equilibrio_cents"] == 250_000
    # 2500 * (1 + 0.15) = 2875
    assert resultado["meta_segura_cents"] == 287_500
    # 2000 / (1 - 0.2 - 0.1) = 2857.14... -> redondeado
    assert resultado["ventas_margen_meta_cents"] == round(200_000 / 0.7)

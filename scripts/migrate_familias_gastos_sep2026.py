"""Migración puntual: lleva al servidor los cambios hechos localmente el
2026-09-24 vía Gobierno del Catálogo / Finanzas que nunca se propagaron
(familias FAM-14/15/16, sus cuentas de ingreso, gastos fijos GF-006..009,
y los account_id de gastos_fijos/personal).

Todo se resuelve por código (family_code/account_code/category_code/
person_code/expense_code), nunca por id crudo, para no depender de que los
ids locales coincidan con los del servidor. Idempotente: si una fila con
ese código ya existe, no la vuelve a insertar.

Uso (en el servidor, dentro de /opt/aglegal, con el venv activo):
    python scripts/migrate_familias_gastos_sep2026.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aglegal import db
from aglegal.db import now_iso

FAMILIAS = [
    # family_code, nombre, category_code
    ("FAM-14", "Contratos y obligaciones", "CTR"),
    ("FAM-15", "Derecho de familia", "FAM"),
    ("FAM-16", "Relocalizacion", "REL"),
]

PLAN_CUENTAS = [
    # account_code, tipo, grupo, subgrupo, nombre, naturaleza, family_code,
    # category_code, centro_costo, afecta_utilidad, estado, regla_de_uso
    (
        "ING-CTR-001", "Ingreso", "Servicios juridicos", "Contratos y obligaciones",
        "Ingresos por contratos y obligaciones", "Operativo", "FAM-14", "CTR",
        "Operación jurídica", True, "Activo",
        "Usar para redaccion, revision y negociacion de contratos.",
    ),
    (
        "ING-FAM-001", "Ingreso", "Servicios juridicos", "Derecho de familia",
        "Ingresos por derecho de familia", "Operativo", "FAM-15", "FAM",
        "Operación jurídica", True, "Activo",
        "Usar para procesos familiares, filiacion, alimentos y divorcios.",
    ),
    (
        "ING-REL-001", "Ingreso", "Servicios juridicos", "Relocalizacion",
        "Ingresos por relocalizacion", "Operativo", "FAM-16", "REL",
        "Operación jurídica", True, "Activo",
        "Usar para acompanamiento integral de relocalizacion.",
    ),
]

GASTOS_FIJOS = [
    # expense_code, concepto, tipo, monto_mensual_cents, mes_inicio, mes_fin, estado, account_code
    ("GF-006", "Energia electrica", "Fijo", 10500, "2026-09", "2026-12", "Inactivo", "EGR-SER-002"),
    ("GF-007", "Salario Guadalupe Sánchez", "Fijo", 55000, "2026-07", "2026-12", "Activo", "EGR-PER-001"),
    ("GF-008", "Salario Alfredo Gallegos", "Fijo", 55000, "2026-07", "2026-12", "Activo", "EGR-PER-002"),
    ("GF-009", "Salario Andrea Escobar", "Fijo", 25000, "2026-07", "2026-12", "Activo", "EGR-PER-003"),
]

# expense_code -> account_code (to link existing GF-002..005)
GASTOS_ACCOUNT_LINKS = {
    "GF-002": "EGR-LOC-001",
    "GF-003": "EGR-SER-001",
    "GF-004": "EGR-ADM-001",
    "GF-005": "EGR-MKT-001",
}

# person_code -> account_code
PERSONAL_ACCOUNT_LINKS = {
    "PER-001": "EGR-PER-001",
    "PER-002": "EGR-PER-002",
    "PER-003": "EGR-PER-003",
}


def _account_id(conn, code: str):
    row = conn.execute("SELECT id FROM plan_cuentas WHERE account_code = %s", (code,)).fetchone()
    if not row:
        raise RuntimeError(f"plan_cuentas no tiene account_code={code!r}")
    return row["id"]


def _category_id(conn, code: str):
    row = conn.execute("SELECT id FROM categorias WHERE category_code = %s", (code,)).fetchone()
    if not row:
        raise RuntimeError(f"categorias no tiene category_code={code!r}")
    return row["id"]


def _family_id(conn, code: str):
    row = conn.execute("SELECT id FROM familias WHERE family_code = %s", (code,)).fetchone()
    if not row:
        raise RuntimeError(f"familias no tiene family_code={code!r}")
    return row["id"]


def main() -> int:
    conn = db.connect()
    ts = now_iso()

    for family_code, nombre, category_code in FAMILIAS:
        exists = conn.execute("SELECT 1 FROM familias WHERE family_code = %s", (family_code,)).fetchone()
        if exists:
            print(f"familias: {family_code} ya existe, se omite")
            continue
        category_id = _category_id(conn, category_code)
        conn.execute(
            "INSERT INTO familias (family_code, nombre, category_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s)",
            (family_code, nombre, category_id, ts, ts),
        )
        print(f"familias: {family_code} insertada")

    for (account_code, tipo, grupo, subgrupo, nombre, naturaleza, family_code,
         category_code, centro_costo, afecta_utilidad, estado, regla_de_uso) in PLAN_CUENTAS:
        exists = conn.execute("SELECT 1 FROM plan_cuentas WHERE account_code = %s", (account_code,)).fetchone()
        if exists:
            print(f"plan_cuentas: {account_code} ya existe, se omite")
            continue
        family_id = _family_id(conn, family_code)
        category_id = _category_id(conn, category_code)
        conn.execute(
            "INSERT INTO plan_cuentas (account_code, tipo, grupo, subgrupo, nombre, naturaleza, "
            "family_id, category_id, centro_costo, afecta_utilidad, estado, regla_de_uso, "
            "created_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (account_code, tipo, grupo, subgrupo, nombre, naturaleza, family_id, category_id,
             centro_costo, afecta_utilidad, estado, regla_de_uso, ts, ts),
        )
        print(f"plan_cuentas: {account_code} insertada")

    conn.commit()
    print("OK — familias y plan_cuentas confirmadas (commit parcial).")

    has_account_id = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'gastos_fijos' AND column_name = 'account_id'"
    ).fetchone()
    if not has_account_id:
        print("gastos_fijos.account_id no existe todavía en este esquema — se omite el resto "
              "(gastos_fijos nuevos y vínculos de cuenta) hasta que se aplique esa migración.")
        return 0

    for (expense_code, concepto, tipo, monto_cents, mes_inicio, mes_fin, estado, account_code) in GASTOS_FIJOS:
        exists = conn.execute("SELECT 1 FROM gastos_fijos WHERE expense_code = %s", (expense_code,)).fetchone()
        if exists:
            print(f"gastos_fijos: {expense_code} ya existe, se omite")
            continue
        account_id = _account_id(conn, account_code)
        conn.execute(
            "INSERT INTO gastos_fijos (expense_code, concepto, tipo, monto_mensual_cents, "
            "mes_inicio, mes_fin, estado, account_id, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (expense_code, concepto, tipo, monto_cents, mes_inicio, mes_fin, estado, account_id, ts, ts),
        )
        print(f"gastos_fijos: {expense_code} insertado")

    gf001 = conn.execute("SELECT id, estado FROM gastos_fijos WHERE expense_code = 'GF-001'").fetchone()
    if gf001 and gf001["estado"] != "Inactivo":
        conn.execute(
            "UPDATE gastos_fijos SET estado = 'Inactivo', updated_at = %s WHERE id = %s",
            (ts, gf001["id"]),
        )
        print("gastos_fijos: GF-001 marcado Inactivo")
    elif gf001:
        print("gastos_fijos: GF-001 ya estaba Inactivo")

    for expense_code, account_code in GASTOS_ACCOUNT_LINKS.items():
        row = conn.execute(
            "SELECT id, account_id FROM gastos_fijos WHERE expense_code = %s", (expense_code,)
        ).fetchone()
        if not row:
            print(f"gastos_fijos: {expense_code} no existe, se omite link de cuenta")
            continue
        account_id = _account_id(conn, account_code)
        if row["account_id"] == account_id:
            print(f"gastos_fijos: {expense_code} ya vinculado a {account_code}")
            continue
        conn.execute(
            "UPDATE gastos_fijos SET account_id = %s, updated_at = %s WHERE id = %s",
            (account_id, ts, row["id"]),
        )
        print(f"gastos_fijos: {expense_code} vinculado a {account_code}")

    for person_code, account_code in PERSONAL_ACCOUNT_LINKS.items():
        row = conn.execute(
            "SELECT id, account_id FROM personal WHERE person_code = %s", (person_code,)
        ).fetchone()
        if not row:
            print(f"personal: {person_code} no existe, se omite link de cuenta")
            continue
        account_id = _account_id(conn, account_code)
        if row["account_id"] == account_id:
            print(f"personal: {person_code} ya vinculado a {account_code}")
            continue
        conn.execute(
            "UPDATE personal SET account_id = %s, updated_at = %s WHERE id = %s",
            (account_id, ts, row["id"]),
        )
        print(f"personal: {person_code} vinculado a {account_code}")

    conn.commit()
    print("OK — migración aplicada y confirmada (commit).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

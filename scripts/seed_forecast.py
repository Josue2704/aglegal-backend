"""Seed de presupuesto por familia (forecast) leyendo directamente el Archivo
Maestro de Excel (hoja 08_Presupuesto_Jul_Dic). Requiere que
scripts/seed_catalogo.py ya se haya corrido antes (necesita familias existentes).

Uso:
    python scripts/seed_forecast.py ["ruta/al/Archivo Maestro.xlsx"]

Es idempotente: si ya fue sembrado (marca en meta), no hace nada.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openpyxl

from aglegal import db
from aglegal.db import now_iso
from aglegal.repositories import Repository

SEED_KEY = "forecast_seed_v1"
DEFAULT_XLSX = ROOT / "AG Legal Archivo Maestro2026.xlsx"
YEAR = "2026"  # el archivo maestro solo cubre julio-diciembre 2026

# Columna "Cant." de cada mes en la hoja 08_Presupuesto_Jul_Dic
MES_COLUMNAS = [
    ("07", "I"),  # Julio
    ("08", "K"),  # Agosto
    ("09", "M"),  # Septiembre
    ("10", "O"),  # Octubre
    ("11", "Q"),  # Noviembre
    ("12", "S"),  # Diciembre
]


def _cell(ws, row: int, col: str):
    return ws[f"{col}{row}"].value


def _seed_forecast(repo: Repository, wb, family_codes_to_id: dict[str, int]) -> int:
    ws = wb["08_Presupuesto_Jul_Dic"]
    count = 0
    row = 5
    while _cell(ws, row, "A"):
        fam_code = str(_cell(ws, row, "A")).strip()
        family_id = family_codes_to_id.get(fam_code)
        if family_id is None:
            row += 1
            continue

        ticket_objetivo = _cell(ws, row, "G")
        margen_directo_pct = _cell(ws, row, "H")

        for mes_num, col in MES_COLUMNAS:
            volumen = _cell(ws, row, col)
            if volumen is None:
                continue
            repo.create_forecast(
                family_id=family_id,
                mes=f"{YEAR}-{mes_num}",
                volumen_meta_text=str(volumen),
                ticket_objetivo_text=str(ticket_objetivo),
                margen_directo_objetivo_pct=float(margen_directo_pct),
                created_at=now_iso(),
            )
            count += 1
        row += 1
    return count


def main() -> int:
    xlsx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    if not xlsx_path.exists():
        print(f"No se encontró el archivo: {xlsx_path}")
        return 1

    conn = db.connect()
    try:
        db.init_db(conn)
        existing = conn.execute("SELECT value FROM meta WHERE key=%s", (SEED_KEY,)).fetchone()
        if existing:
            print("El presupuesto por familia ya fue sembrado — no se hace nada.")
            return 0

        catalogo_seeded = conn.execute("SELECT value FROM meta WHERE key='catalogo_seed_v1'").fetchone()
        if not catalogo_seeded:
            print("Corre primero scripts/seed_catalogo.py — este script necesita familias existentes.")
            return 1

        repo = Repository(conn)
        family_codes_to_id = {r["family_code"]: r["id"] for r in repo.list_familias()}

        wb = openpyxl.load_workbook(str(xlsx_path), data_only=True)

        count = _seed_forecast(repo, wb, family_codes_to_id)
        print(f"Presupuesto (forecast): {count} filas (familia × mes)")

        conn.execute(
            "INSERT INTO meta(key, value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SEED_KEY, now_iso()),
        )
        conn.commit()
        print("Presupuesto por familia sembrado desde el Archivo Maestro.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

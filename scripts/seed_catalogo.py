"""Seed del catálogo maestro (categorías, subcategorías, familias, servicios)
leyendo directamente el Archivo Maestro de Excel — nunca se transcriben los
datos a mano, para no arrastrar errores de dedo al sistema.

Uso:
    python scripts/seed_catalogo.py ["ruta/al/Archivo Maestro.xlsx"]

Es idempotente: si el catálogo ya fue sembrado (marca en meta), no hace nada.
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

SEED_KEY = "catalogo_seed_v1"
DEFAULT_XLSX = ROOT / "AG Legal Archivo Maestro2026.xlsx"


def _cell(ws, row: int, col: str) -> str:
    v = ws[f"{col}{row}"].value
    return str(v).strip() if v is not None else ""


def _seed_categorias(repo: Repository, wb) -> dict[str, int]:
    ws = wb["01_Categorias"]
    code_to_id: dict[str, int] = {}
    row = 5
    while _cell(ws, row, "A"):
        code = _cell(ws, row, "A")
        nombre = _cell(ws, row, "B")
        cat_id = repo.create_categoria(category_code=code, nombre=nombre, created_at=now_iso())
        code_to_id[code] = cat_id
        row += 1
    return code_to_id


def _seed_subcategorias(repo: Repository, wb, category_ids: dict[str, int]) -> dict[str, int]:
    ws = wb["02_Subcategorias"]
    composite_to_id: dict[str, int] = {}
    row = 5
    while _cell(ws, row, "A"):
        cat_code = _cell(ws, row, "A")
        sub_code = _cell(ws, row, "C")
        nombre = _cell(ws, row, "D")
        cat_id = category_ids[cat_code]
        sub_id = repo.create_subcategoria(category_id=cat_id, subcategory_code=sub_code, nombre=nombre, created_at=now_iso())
        composite_to_id[f"{cat_code}-{sub_code}"] = sub_id
        row += 1
    return composite_to_id


def _seed_servicios(repo: Repository, wb, subcategory_ids: dict[str, int]) -> int:
    ws = wb["03_Catalogo_Servicios"]
    count = 0
    row = 5
    while _cell(ws, row, "A"):
        cat_code = _cell(ws, row, "B")
        sub_code = _cell(ws, row, "D")
        nombre = _cell(ws, row, "F")
        etiquetas = _cell(ws, row, "G")
        estado = _cell(ws, row, "H") or "Activo"
        unidad_cobro = _cell(ws, row, "I") or "Por definir"
        responsable = _cell(ws, row, "J") or "Por definir"
        tarifa = _cell(ws, row, "K") or "0"
        costo = _cell(ws, row, "L") or "0"
        horas = _cell(ws, row, "M") or "0"

        sub_id = subcategory_ids[f"{cat_code}-{sub_code}"]
        repo.create_servicio(
            subcategory_id=sub_id,
            nombre=nombre,
            etiquetas=etiquetas,
            unidad_cobro=unidad_cobro,
            responsable_sugerido=responsable,
            tarifa_referencia_text=tarifa,
            costo_referencia_text=costo,
            horas_estandar=float(horas or 0),
            estado=estado,
            created_at=now_iso(),
        )
        count += 1
        row += 1
    return count


def _seed_familias(repo: Repository, wb, category_ids: dict[str, int]) -> int:
    ws = wb["04_Plan_Cuentas"]
    count = 0
    row = 5
    while _cell(ws, row, "A"):
        tipo = _cell(ws, row, "B")
        cat_code = _cell(ws, row, "G")
        family_code_hint = _cell(ws, row, "H")
        subgrupo = _cell(ws, row, "D")
        if tipo == "Ingreso" and family_code_hint.startswith("FAM-") and cat_code in category_ids:
            repo.create_familia(category_id=category_ids[cat_code], nombre=subgrupo, created_at=now_iso())
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
            print("El catálogo maestro ya fue sembrado — no se hace nada.")
            return 0

        wb = openpyxl.load_workbook(str(xlsx_path), data_only=True)
        repo = Repository(conn)

        category_ids = _seed_categorias(repo, wb)
        print(f"Categorías: {len(category_ids)}")

        subcategory_ids = _seed_subcategorias(repo, wb, category_ids)
        print(f"Subcategorías: {len(subcategory_ids)}")

        familias_count = _seed_familias(repo, wb, category_ids)
        print(f"Familias: {familias_count}")

        servicios_count = _seed_servicios(repo, wb, subcategory_ids)
        print(f"Servicios: {servicios_count}")

        conn.execute(
            "INSERT INTO meta(key, value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SEED_KEY, now_iso()),
        )
        conn.commit()
        print("Catálogo maestro sembrado desde el Archivo Maestro.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

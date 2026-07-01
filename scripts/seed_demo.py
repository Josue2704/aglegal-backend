from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aglegal import db
from aglegal.db import now_iso
from aglegal.repositories import Repository


SEED_KEY = "demo_seed_v1"


def main() -> int:
    conn = db.connect()
    try:
        db.init_db(conn)
        existing = conn.execute("SELECT value FROM meta WHERE key=?", (SEED_KEY,)).fetchone()
        if existing:
            print("Demo seed already applied.")
            return 0

        repo = Repository(conn)
        today = date.today()
        clients = _seed_clients(repo)
        categories = _category_ids(repo)
        products = _product_ids(repo)
        cases = _seed_cases(repo, clients, products, today)
        _seed_tasks(repo, cases, today)
        _seed_sessions(repo, clients, cases, today)
        _seed_money(repo, clients, cases, categories, today)
        _seed_payroll(repo, today)

        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
            (SEED_KEY, now_iso()),
        )
        conn.commit()
        print("Demo data inserted.")
        print(f"Clients: {len(clients)} | Cases: {len(cases)}")
        return 0
    finally:
        conn.close()


def _seed_clients(repo: Repository) -> dict[str, int]:
    data = [
        ("Josué Martínez", "7000-1122", "josue@example.com", "San Salvador", "Cliente recurrente de servicios notariales."),
        ("Inversiones La Ceiba", "2222-3030", "legal@laceiba.com", "Santa Tecla", "Empresa con trámites corporativos."),
        ("María Fernanda López", "7777-8899", "maria.lopez@example.com", "Antiguo Cuscatlán", "Caso familiar sensible."),
        ("Agroexportadora del Valle", "2266-7788", "admin@agrovalle.com", "La Libertad", "Contratos y permisos administrativos."),
        ("Carlos Hernández", "7012-3434", "carlos.h@example.com", "San Miguel", "Migratorio y residencia."),
        ("Grupo Nova S.A. de C.V.", "2525-9090", "finanzas@gruponova.com", "San Salvador", "Cliente empresarial de alto valor."),
    ]
    out: dict[str, int] = {}
    for name, phone, email, address, notes in data:
        row = repo.conn.execute("SELECT id FROM clients WHERE name=?", (name,)).fetchone()
        if row:
            out[name] = int(row["id"])
            continue
        out[name] = repo.create_client(
            name=name,
            phone=phone,
            email=email,
            address=address,
            notes=notes,
            created_at=now_iso(),
        )
    return out


def _category_ids(repo: Repository) -> dict[tuple[str, str], int]:
    required = {
        "income": ["Honorarios", "Servicios", "Anticipo"],
        "expense": ["Alquiler", "Internet", "Oficina", "Transporte", "Impuestos", "Nóminas"],
        "cost": ["Trámite", "Subcontratación", "Materiales", "Comisión", "Compra directa"],
    }
    for kind, names in required.items():
        for name in names:
            row = repo.conn.execute("SELECT id FROM categories WHERE kind=? AND name=?", (kind, name)).fetchone()
            if not row:
                repo.create_category(kind=kind, name=name, created_at=now_iso())
    rows = repo.conn.execute("SELECT id, kind, name FROM categories").fetchall()
    return {(str(row["kind"]), str(row["name"])): int(row["id"]) for row in rows}


def _product_ids(repo: Repository) -> dict[str, int]:
    rows = repo.conn.execute("SELECT id, name FROM service_products WHERE active=1").fetchall()
    return {str(row["name"]): int(row["id"]) for row in rows}


def _seed_cases(repo: Repository, clients: dict[str, int], products: dict[str, int], today: date) -> dict[str, int]:
    rows = [
        ("Escritura compraventa Escalón", "Josué Martínez", "Servicios Notariales", "Escritura pública", "Abierto", "Media", -38),
        ("Constitución sociedad tecnológica", "Grupo Nova S.A. de C.V.", "Derecho Corporativo y Empresarial", "Constitución de sociedad", "Abierto", "Alta", -72),
        ("Divorcio por mutuo consentimiento", "María Fernanda López", "Derecho de Familia", "Divorcio", "En trámite", "Alta", -45),
        ("Contrato de arrendamiento bodegas", "Inversiones La Ceiba", "Bienes Raíces e Inversiones", "Arrendamiento", "Abierto", "Media", -22),
        ("Permiso administrativo MAG", "Agroexportadora del Valle", "Derecho Administrativo", "Permiso institucional", "En pausa", "Media", -95),
        ("Residencia temporal", "Carlos Hernández", "Migratorio", "Residencia", "Abierto", "Baja", -18),
        ("Modificación de pacto social", "Grupo Nova S.A. de C.V.", "Derecho Corporativo y Empresarial", "Modificación de sociedad", "Cerrado", "Media", -130),
    ]
    out: dict[str, int] = {}
    for title, client, area, product, status, priority, offset in rows:
        existing = repo.conn.execute("SELECT id FROM cases WHERE title=?", (title,)).fetchone()
        if existing:
            out[title] = int(existing["id"])
            continue
        out[title] = repo.create_case(
            client_id=clients[client],
            service_area=area,
            service_product_id=products.get(product),
            title=title,
            status=status,
            priority=priority,
            opened_at=(today + timedelta(days=offset)).isoformat(),
            notes=f"Demo: expediente de {area}.",
            created_at=now_iso(),
        )
    return out


def _seed_tasks(repo: Repository, cases: dict[str, int], today: date) -> None:
    tasks = [
        ("Escritura compraventa Escalón", "Solicitar solvencia municipal", 2),
        ("Constitución sociedad tecnológica", "Preparar estatutos finales", 4),
        ("Divorcio por mutuo consentimiento", "Confirmar audiencia con cliente", -1),
        ("Permiso administrativo MAG", "Revisar observaciones de institución", 7),
        ("Residencia temporal", "Completar formulario migratorio", 3),
    ]
    for case_title, title, due_offset in tasks:
        case_id = cases[case_title]
        exists = repo.conn.execute(
            "SELECT 1 FROM case_tasks WHERE case_id=? AND title=?",
            (case_id, title),
        ).fetchone()
        if exists:
            continue
        repo.create_case_task(
            case_id=case_id,
            title=title,
            due_date=(today + timedelta(days=due_offset)).isoformat(),
            created_at=now_iso(),
        )


def _seed_sessions(repo: Repository, clients: dict[str, int], cases: dict[str, int], today: date) -> None:
    rows = [
        ("Josué Martínez", "Escritura compraventa Escalón", -7, "Firma de escritura", "Finalizada"),
        ("Grupo Nova S.A. de C.V.", "Constitución sociedad tecnológica", -3, "Revisión documental", "En proceso"),
        ("María Fernanda López", "Divorcio por mutuo consentimiento", 1, "Seguimiento de acuerdo", "Pendiente"),
        ("Inversiones La Ceiba", "Contrato de arrendamiento bodegas", 4, "Revisión de contrato", "Pendiente"),
        ("Agroexportadora del Valle", "Permiso administrativo MAG", 6, "Consulta administrativa", "Pendiente"),
        ("Carlos Hernández", "Residencia temporal", 8, "Entrega de documentos", "Pendiente"),
    ]
    for client, case_title, offset, consult_type, status in rows:
        session_date = (today + timedelta(days=offset)).isoformat()
        exists = repo.conn.execute(
            "SELECT 1 FROM sessions WHERE client_id=? AND case_id=? AND session_date=? AND consult_type=?",
            (clients[client], cases[case_title], session_date, consult_type),
        ).fetchone()
        if exists:
            continue
        repo.create_session(
            client_id=clients[client],
            case_id=cases[case_title],
            session_date=session_date,
            consult_type=consult_type,
            notes="Sesión demo para poblar agenda y métricas.",
            status=status,
            created_at=now_iso(),
        )


def _seed_money(repo: Repository, clients: dict[str, int], cases: dict[str, int], categories: dict[tuple[str, str], int], today: date) -> None:
    income_rows = [
        ("Josué Martínez", "Escritura compraventa Escalón", "Honorarios", "Honorarios escritura pública", 850.00, -6),
        ("Grupo Nova S.A. de C.V.", "Constitución sociedad tecnológica", "Honorarios", "Anticipo constitución de sociedad", 1800.00, -20),
        ("María Fernanda López", "Divorcio por mutuo consentimiento", "Servicios", "Pago inicial divorcio", 950.00, -12),
        ("Inversiones La Ceiba", "Contrato de arrendamiento bodegas", "Honorarios", "Contrato arrendamiento", 700.00, -8),
        ("Agroexportadora del Valle", "Permiso administrativo MAG", "Servicios", "Gestión permiso administrativo", 1200.00, -34),
        ("Carlos Hernández", "Residencia temporal", "Servicios", "Trámite residencia", 650.00, -2),
        ("Grupo Nova S.A. de C.V.", "Modificación de pacto social", "Honorarios", "Cierre modificación pacto social", 1450.00, -50),
    ]
    for client, case_title, category, detail, amount, offset in income_rows:
        income_date = (today + timedelta(days=offset)).isoformat()
        if _money_exists(repo, "incomes", detail, income_date):
            continue
        repo.create_income(
            client_id=clients[client],
            case_id=cases[case_title],
            category_id=categories.get(("income", category)),
            detail=detail,
            amount_text=f"{amount:.2f}",
            income_date=income_date,
            created_at=now_iso(),
        )

    cost_rows = [
        ("Josué Martínez", "Escritura compraventa Escalón", "Trámite", "Derechos registrales y copias", 135.00, -5),
        ("Grupo Nova S.A. de C.V.", "Constitución sociedad tecnológica", "Materiales", "Publicaciones y formularios", 260.00, -18),
        ("María Fernanda López", "Divorcio por mutuo consentimiento", "Subcontratación", "Procurador externo audiencia", 220.00, -10),
        ("Inversiones La Ceiba", "Contrato de arrendamiento bodegas", "Comisión", "Comisión revisión inmueble", 110.00, -7),
        ("Agroexportadora del Valle", "Permiso administrativo MAG", "Trámite", "Tasas y certificaciones", 310.00, -30),
        ("Carlos Hernández", "Residencia temporal", "Trámite", "Pago formulario migratorio", 180.00, -1),
        ("Grupo Nova S.A. de C.V.", "Modificación de pacto social", "Materiales", "Inscripciones y publicaciones", 240.00, -48),
    ]
    for client, case_title, category, detail, amount, offset in cost_rows:
        cost_date = (today + timedelta(days=offset)).isoformat()
        if _money_exists(repo, "costs", detail, cost_date, date_column="cost_date"):
            continue
        repo.create_cost(
            client_id=clients[client],
            case_id=cases[case_title],
            category_id=categories.get(("cost", category)),
            detail=detail,
            amount_text=f"{amount:.2f}",
            cost_date=cost_date,
            notes="Costo demo directo del servicio.",
            created_at=now_iso(),
        )

    expense_rows = [
        ("Alquiler", "Alquiler oficina", 900.00, -5),
        ("Internet", "Internet y telefonía", 125.00, -4),
        ("Oficina", "Papelería y tóner", 180.00, -3),
        ("Transporte", "Combustible y parqueos", 210.00, -9),
        ("Impuestos", "Pago municipal", 160.00, -11),
    ]
    for category, detail, amount, offset in expense_rows:
        expense_date = (today + timedelta(days=offset)).isoformat()
        if _money_exists(repo, "expenses", detail, expense_date, date_column="expense_date"):
            continue
        repo.create_expense(
            category_id=categories.get(("expense", category)),
            detail=detail,
            amount_text=f"{amount:.2f}",
            expense_date=expense_date,
            notes="Gasto operativo demo.",
            created_at=now_iso(),
        )


def _seed_payroll(repo: Repository, today: date) -> None:
    period = today.strftime("%Y-%m")
    rows = [
        ("Ana Rodríguez", "Asistente legal", period, 650.00, -2),
        ("Luis Méndez", "Paralegal", period, 720.00, -2),
    ]
    for employee, role, period_text, amount, offset in rows:
        exists = repo.conn.execute(
            "SELECT 1 FROM payrolls WHERE employee_name=? AND period=?",
            (employee, period_text),
        ).fetchone()
        if exists:
            continue
        repo.create_payroll(
            employee_name=employee,
            role=role,
            period=period_text,
            amount_text=f"{amount:.2f}",
            payment_date=(today + timedelta(days=offset)).isoformat(),
            notes="Nómina demo mensual.",
            created_at=now_iso(),
        )


def _money_exists(repo: Repository, table: str, detail: str, value_date: str, *, date_column: str = "income_date") -> bool:
    row = repo.conn.execute(
        f"SELECT 1 FROM {table} WHERE detail=? AND {date_column}=? LIMIT 1",
        (detail, value_date),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    raise SystemExit(main())

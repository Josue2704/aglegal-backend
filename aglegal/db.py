from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .security import hash_password


@dataclass(frozen=True)
class DbConfig:
    path: Path


def _default_db_path() -> Path:
    return Path(os.environ.get("AGLEGAL_DB_PATH", "data/aglegal.db"))


def get_config() -> DbConfig:
    return DbConfig(path=_default_db_path())


def connect() -> sqlite3.Connection:
    cfg = get_config()
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  address TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER NOT NULL,
  session_date TEXT NOT NULL,
  consult_type TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS incomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id INTEGER,
  concept TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  income_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  expense_date TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL, -- 'income' | 'expense'
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS attachments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL, -- 'session' | 'income' | 'expense'
  entity_id INTEGER NOT NULL,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_client_date ON sessions(client_id, session_date);
CREATE INDEX IF NOT EXISTS idx_incomes_date ON incomes(income_date);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_categories_kind_name ON categories(kind, name);
CREATE INDEX IF NOT EXISTS idx_attachments_entity ON attachments(entity_type, entity_id);
"""


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def date_iso(d: date) -> str:
    return d.isoformat()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1')")
    _migrate(conn)
    _seed_admin(conn)
    conn.commit()


def _seed_admin(conn: sqlite3.Connection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM users WHERE username = ? LIMIT 1", ("admin",)
    ).fetchone()
    if existing:
        return

    conn.execute(
        "INSERT INTO users(username, password_hash, created_at) VALUES(?,?,?)",
        ("admin", hash_password("admin"), now_iso()),
    )


def _schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    try:
        return int(row["value"]) if row else 1
    except Exception:
        return 1


def _set_schema_version(conn: sqlite3.Connection, v: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(int(v)),),
    )


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(c["name"]) == column for c in cols)


def _migrate(conn: sqlite3.Connection) -> None:
    v = _schema_version(conn)

    # v2: add categories + link to incomes/expenses with optional category_id and free-text detail
    if v < 2:
        if not _column_exists(conn, "incomes", "category_id"):
            conn.execute("ALTER TABLE incomes ADD COLUMN category_id INTEGER")
        if not _column_exists(conn, "incomes", "detail"):
            conn.execute("ALTER TABLE incomes ADD COLUMN detail TEXT")

        if not _column_exists(conn, "expenses", "category_id"):
            conn.execute("ALTER TABLE expenses ADD COLUMN category_id INTEGER")
        if not _column_exists(conn, "expenses", "detail"):
            conn.execute("ALTER TABLE expenses ADD COLUMN detail TEXT")

        _seed_default_categories(conn)
        _set_schema_version(conn, 2)

    # v3: cases (expedientes) + tasks + link sessions to case + allow case attachments
    if v < 3:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER NOT NULL,
              service_area TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL, -- 'Abierto' | 'En trámite' | 'En pausa' | 'Cerrado'
              priority TEXT NOT NULL, -- 'Baja' | 'Media' | 'Alta'
              opened_at TEXT NOT NULL,
              closed_at TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_cases_client_status ON cases(client_id, status);

            CREATE TABLE IF NOT EXISTS case_tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id INTEGER NOT NULL,
              title TEXT NOT NULL,
              done INTEGER NOT NULL DEFAULT 0,
              due_date TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_case_tasks_case_done ON case_tasks(case_id, done);
            """
        )

        if not _column_exists(conn, "sessions", "case_id"):
            conn.execute("ALTER TABLE sessions ADD COLUMN case_id INTEGER")

        _set_schema_version(conn, 3)

    # v4: service catalog (service categories + products offered)
    if v < 4:
        _seed_service_categories(conn)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS service_products (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              category_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              description TEXT,
              base_price_cents INTEGER,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
              UNIQUE(category_id, name)
            );

            CREATE INDEX IF NOT EXISTS idx_service_products_category ON service_products(category_id, active);
            """
        )
        if not _column_exists(conn, "cases", "service_product_id"):
            conn.execute("ALTER TABLE cases ADD COLUMN service_product_id INTEGER")
        _seed_default_service_products(conn)
        _set_schema_version(conn, 4)


    # v5: user access management
    if v < 5:
        if not _column_exists(conn, "users", "full_name"):
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        if not _column_exists(conn, "users", "role"):
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'Administrador'")
        if not _column_exists(conn, "users", "active"):
            conn.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        _set_schema_version(conn, 5)

    # v6: payroll / nominas
    if v < 6:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS payrolls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              employee_name TEXT NOT NULL,
              role TEXT,
              period TEXT NOT NULL,
              amount_cents INTEGER NOT NULL,
              payment_date TEXT NOT NULL,
              notes TEXT,
              expense_id INTEGER,
              created_at TEXT NOT NULL,
              FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_payrolls_payment_date ON payrolls(payment_date);
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO categories(kind, name, created_at) VALUES(?,?,?)",
            ("expense", "Nóminas", now_iso()),
        )
        _set_schema_version(conn, 6)

    # v7: link incomes to cases/services for profitability analytics
    if v < 7:
        if not _column_exists(conn, "incomes", "case_id"):
            conn.execute("ALTER TABLE incomes ADD COLUMN case_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incomes_case ON incomes(case_id)")
        _set_schema_version(conn, 7)

    # v8: direct costs separated from operating expenses
    if v < 8:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS costs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              client_id INTEGER,
              case_id INTEGER,
              category_id INTEGER,
              concept TEXT NOT NULL,
              detail TEXT,
              amount_cents INTEGER NOT NULL,
              cost_date TEXT NOT NULL,
              notes TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL,
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL,
              FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_costs_date ON costs(cost_date);
            CREATE INDEX IF NOT EXISTS idx_costs_case ON costs(case_id);
            """
        )
        for name in ["Compra directa", "Trámite", "Subcontratación", "Materiales", "Comisión", "Otro"]:
            conn.execute(
                "INSERT OR IGNORE INTO categories(kind, name, created_at) VALUES(?,?,?)",
                ("cost", name, now_iso()),
            )
        _set_schema_version(conn, 8)

    # v9: Google Calendar integration — token storage + event_id on sessions
    if v < 9:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS google_tokens (
              username TEXT PRIMARY KEY,
              access_token TEXT NOT NULL,
              refresh_token TEXT NOT NULL,
              expiry_at TEXT NOT NULL
            );
            """
        )
        if not _column_exists(conn, "sessions", "gcal_event_id"):
            conn.execute("ALTER TABLE sessions ADD COLUMN gcal_event_id TEXT")
        _set_schema_version(conn, 9)

    # v10: exact session time ranges for Google Calendar sync
    if v < 10:
        if not _column_exists(conn, "sessions", "start_time"):
            conn.execute("ALTER TABLE sessions ADD COLUMN start_time TEXT")
        if not _column_exists(conn, "sessions", "end_time"):
            conn.execute("ALTER TABLE sessions ADD COLUMN end_time TEXT")
        _set_schema_version(conn, 10)


def _seed_default_categories(conn: sqlite3.Connection) -> None:
    defaults_income = ["Honorarios", "Servicios", "Otro"]
    defaults_expense = ["Alimentos", "Transporte", "Servicios", "Oficina", "Impuestos", "Otro"]
    for name in defaults_income:
        conn.execute(
            "INSERT OR IGNORE INTO categories(kind, name, created_at) VALUES(?,?,?)",
            ("income", name, now_iso()),
        )
    for name in defaults_expense:
        conn.execute(
            "INSERT OR IGNORE INTO categories(kind, name, created_at) VALUES(?,?,?)",
            ("expense", name, now_iso()),
        )


def with_db(fn):
    def wrapper(*args, **kwargs):
        conn = connect()
        try:
            init_db(conn)
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()

    return wrapper



def _seed_service_categories(conn: sqlite3.Connection) -> None:
    defaults = [
        "Servicios Notariales",
        "Bienes Raíces e Inversiones",
        "Derecho Corporativo y Empresarial",
        "Derecho de Familia",
        "Representación en Juicios",
        "Derecho Administrativo",
        "Migratorio",
        "Otro",
    ]
    for name in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO categories(kind, name, created_at) VALUES(?,?,?)",
            ("service", name, now_iso()),
        )


def _seed_default_service_products(conn: sqlite3.Connection) -> None:
    defaults = {
        "Servicios Notariales": ["Escritura pública", "Poder", "Auténtica", "Acta notarial"],
        "Bienes Raíces e Inversiones": ["Compraventa", "Arrendamiento", "Estudio registral"],
        "Derecho Corporativo y Empresarial": ["Constitución de sociedad", "Modificación de sociedad", "Contrato mercantil"],
        "Derecho de Familia": ["Divorcio", "Alimentos", "Cuidado personal"],
        "Representación en Juicios": ["Demanda civil", "Defensa judicial", "Conciliación"],
        "Derecho Administrativo": ["Trámite municipal", "Recurso administrativo", "Permiso institucional"],
        "Migratorio": ["Residencia", "Permiso de trabajo", "Regularización migratoria"],
        "Otro": ["Consulta general"],
    }
    rows = conn.execute("SELECT id, name FROM categories WHERE kind='service'").fetchall()
    by_name = {str(row["name"]): int(row["id"]) for row in rows}
    for category_name, products in defaults.items():
        category_id = by_name.get(category_name)
        if not category_id:
            continue
        for product in products:
            conn.execute(
                "INSERT OR IGNORE INTO service_products(category_id, name, description, base_price_cents, active, created_at) VALUES(?,?,?,?,?,?)",
                (category_id, product, "", None, 1, now_iso()),
            )

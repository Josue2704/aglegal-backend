from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json, RealDictCursor

from .security import hash_password

_RE_INSERT_TABLE = re.compile(r'\bINSERT\b.*?\bINTO\b\s+(\w+)', re.IGNORECASE)

# ── Connection ────────────────────────────────────────────────────────────────

def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://aglegal:aglegal@localhost:5432/aglegal",
    )


# ── psycopg2 ↔ sqlite3 compatibility wrapper ─────────────────────────────────
# Gives psycopg2 connections the same .execute() / .commit() / .close() surface
# that the rest of the codebase expects from sqlite3, including .lastrowid.

_TABLES_WITHOUT_ID = {"meta", "role_permissions", "google_tokens", "outlook_tokens"}


class _Cursor:
    """Wraps a psycopg2 RealDictCursor to look like a sqlite3 cursor."""

    def __init__(self, pg_cursor: Any) -> None:
        self._c = pg_cursor
        self.lastrowid: int | None = None

    def execute(self, sql: str, params: Any = ()) -> "_Cursor":
        stripped = sql.strip().upper()
        is_insert = stripped.startswith("INSERT") and "RETURNING" not in stripped
        wants_returning = False
        if is_insert:
            m = _RE_INSERT_TABLE.search(sql)
            table = m.group(1).lower() if m else ""
            if table not in _TABLES_WITHOUT_ID:
                sql = sql.rstrip().rstrip(";") + " RETURNING id"
                wants_returning = True
        self._c.execute(sql, params if params else None)
        if wants_returning:
            row = self._c.fetchone()
            self.lastrowid = int(row["id"]) if row and row.get("id") is not None else None
        return self

    def fetchone(self) -> Any:
        return self._c.fetchone()

    def fetchall(self) -> list[Any]:
        return self._c.fetchall()

    @property
    def rowcount(self) -> int:
        return self._c.rowcount


class PgConnection:
    """Wraps a psycopg2 connection to look like a sqlite3.Connection."""

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn

    def execute(self, sql: str, params: Any = ()) -> _Cursor:
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        wrapper = _Cursor(cur)
        return wrapper.execute(sql, params)

    def executescript(self, sql: str) -> None:
        """Run multiple ';'-separated DDL statements (migration helper)."""
        cur = self._conn.cursor()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            # skip empty chunks and pure-comment lines
            if stmt and not all(ln.strip().startswith("--") for ln in stmt.splitlines() if ln.strip()):
                cur.execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def rollback(self) -> None:
        self._conn.rollback()


def connect() -> PgConnection:
    pg = psycopg2.connect(_database_url())
    pg.autocommit = False
    return PgConnection(pg)


# ── Schema (PostgreSQL DDL) ───────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  phone TEXT,
  email TEXT,
  address TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id SERIAL PRIMARY KEY,
  client_id INTEGER NOT NULL,
  session_date TEXT NOT NULL,
  consult_type TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS incomes (
  id SERIAL PRIMARY KEY,
  client_id INTEGER,
  concept TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  income_date TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS expenses (
  id SERIAL PRIMARY KEY,
  concept TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  expense_date TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
  id SERIAL PRIMARY KEY,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(kind, name)
);

CREATE TABLE IF NOT EXISTS attachments (
  id SERIAL PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  original_name TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_client_date ON sessions(client_id, session_date);
CREATE INDEX IF NOT EXISTS idx_incomes_date ON incomes(income_date);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_categories_kind_name ON categories(kind, name);
CREATE INDEX IF NOT EXISTS idx_attachments_entity ON attachments(entity_type, entity_id)
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def date_iso(d: date) -> str:
    return d.isoformat()


def _column_exists(conn: PgConnection, table: str, column: str) -> bool:
    # information_schema.columns no filtra por schema, así que en una base con más de un
    # schema (p. ej. un schema de pruebas aislado junto al de producción) reportaba una
    # columna como existente porque la vio en OTRO schema, y la migración se saltaba el
    # ALTER TABLE que sí hacía falta en el schema actual. to_regclass() resuelve el nombre
    # de tabla exactamente igual que lo hace el propio ALTER/CREATE INDEX: vía search_path.
    row = conn.execute(
        "SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(%s) AND attname = %s AND NOT attisdropped",
        (table, column),
    ).fetchone()
    return row is not None


def _schema_version(conn: PgConnection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    try:
        return int(row["value"]) if row else 1
    except Exception:
        return 1


def _set_schema_version(conn: PgConnection, v: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', %s) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(int(v)),),
    )


# ── Init ──────────────────────────────────────────────────────────────────────

def init_db(conn: PgConnection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', '1') ON CONFLICT(key) DO NOTHING"
    )
    _migrate(conn)
    _seed_admin(conn)
    conn.commit()


def _seed_admin(conn: PgConnection) -> None:
    existing = conn.execute(
        "SELECT 1 FROM users WHERE username = %s LIMIT 1", ("admin",)
    ).fetchone()
    if existing:
        return

    initial_password = secrets.token_urlsafe(12)
    conn.execute(
        "INSERT INTO users(username, password_hash, created_at) VALUES(%s,%s,%s)",
        ("admin", hash_password(initial_password), now_iso()),
    )
    sep = "=" * 52
    print(f"\n{sep}")
    print("  AGLegal — primer inicio de sesión")
    print(f"  Usuario:    admin")
    print(f"  Contraseña: {initial_password}")
    print("  Cámbiala desde Usuarios una vez que ingreses.")
    print(f"{sep}\n")


# ── Migrations ────────────────────────────────────────────────────────────────

def _migrate(conn: PgConnection) -> None:
    v = _schema_version(conn)

    # v2: categories + link to incomes/expenses
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

    # v3: cases + tasks + link sessions to case
    if v < 3:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
              id SERIAL PRIMARY KEY,
              client_id INTEGER NOT NULL,
              service_area TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL,
              priority TEXT NOT NULL,
              opened_at TEXT NOT NULL,
              closed_at TEXT,
              notes TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_cases_client_status ON cases(client_id, status);
            CREATE TABLE IF NOT EXISTS case_tasks (
              id SERIAL PRIMARY KEY,
              case_id INTEGER NOT NULL,
              title TEXT NOT NULL,
              done INTEGER NOT NULL DEFAULT 0,
              due_date TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_case_tasks_case_done ON case_tasks(case_id, done)
        """)
        if not _column_exists(conn, "sessions", "case_id"):
            conn.execute("ALTER TABLE sessions ADD COLUMN case_id INTEGER")
        _set_schema_version(conn, 3)

    # v4: service catalog
    if v < 4:
        _seed_service_categories(conn)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS service_products (
              id SERIAL PRIMARY KEY,
              category_id INTEGER NOT NULL,
              name TEXT NOT NULL,
              description TEXT,
              base_price_cents INTEGER,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
              UNIQUE(category_id, name)
            );
            CREATE INDEX IF NOT EXISTS idx_service_products_category ON service_products(category_id, active)
        """)
        if not _column_exists(conn, "cases", "service_product_id"):
            conn.execute("ALTER TABLE cases ADD COLUMN service_product_id INTEGER")
        _seed_default_service_products(conn)
        _set_schema_version(conn, 4)

    # v5: user roles
    if v < 5:
        if not _column_exists(conn, "users", "full_name"):
            conn.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
        if not _column_exists(conn, "users", "role"):
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'Administrador'")
        if not _column_exists(conn, "users", "active"):
            conn.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        _set_schema_version(conn, 5)

    # v6: payroll
    if v < 6:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS payrolls (
              id SERIAL PRIMARY KEY,
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
            CREATE INDEX IF NOT EXISTS idx_payrolls_payment_date ON payrolls(payment_date)
        """)
        conn.execute(
            "INSERT INTO categories(kind, name, created_at) VALUES(%s,%s,%s) ON CONFLICT(kind, name) DO NOTHING",
            ("expense", "Nóminas", now_iso()),
        )
        _set_schema_version(conn, 6)

    # v7: link incomes to cases
    if v < 7:
        if not _column_exists(conn, "incomes", "case_id"):
            conn.execute("ALTER TABLE incomes ADD COLUMN case_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incomes_case ON incomes(case_id)")
        _set_schema_version(conn, 7)

    # v8: direct costs
    if v < 8:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS costs (
              id SERIAL PRIMARY KEY,
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
            CREATE INDEX IF NOT EXISTS idx_costs_case ON costs(cost_date)
        """)
        for name in ["Compra directa", "Trámite", "Subcontratación", "Materiales", "Comisión", "Otro"]:
            conn.execute(
                "INSERT INTO categories(kind, name, created_at) VALUES(%s,%s,%s) ON CONFLICT(kind, name) DO NOTHING",
                ("cost", name, now_iso()),
            )
        _set_schema_version(conn, 8)

    # v9: Google Calendar
    if v < 9:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS google_tokens (
              username TEXT PRIMARY KEY,
              access_token TEXT NOT NULL,
              refresh_token TEXT NOT NULL,
              expiry_at TEXT NOT NULL
            )
        """)
        if not _column_exists(conn, "sessions", "gcal_event_id"):
            conn.execute("ALTER TABLE sessions ADD COLUMN gcal_event_id TEXT")
        _set_schema_version(conn, 9)

    # v10: session time ranges
    if v < 10:
        if not _column_exists(conn, "sessions", "start_time"):
            conn.execute("ALTER TABLE sessions ADD COLUMN start_time TEXT")
        if not _column_exists(conn, "sessions", "end_time"):
            conn.execute("ALTER TABLE sessions ADD COLUMN end_time TEXT")
        _set_schema_version(conn, 10)

    # v11: task notes
    if v < 11:
        if not _column_exists(conn, "case_tasks", "notes"):
            conn.execute("ALTER TABLE case_tasks ADD COLUMN notes TEXT")
        if not _column_exists(conn, "case_tasks", "completed_notes"):
            conn.execute("ALTER TABLE case_tasks ADD COLUMN completed_notes TEXT")
        _set_schema_version(conn, 11)

    # v12: invoices
    if v < 12:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS invoices (
              id SERIAL PRIMARY KEY,
              invoice_number TEXT NOT NULL,
              client_id INTEGER NOT NULL,
              case_id INTEGER,
              invoice_date TEXT NOT NULL,
              due_date TEXT,
              status TEXT NOT NULL DEFAULT 'Borrador',
              notes TEXT,
              firm_name TEXT,
              firm_phone TEXT,
              firm_email TEXT,
              firm_address TEXT,
              firm_tax_id TEXT,
              total_cents INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE,
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS invoice_items (
              id SERIAL PRIMARY KEY,
              invoice_id INTEGER NOT NULL,
              description TEXT NOT NULL,
              quantity REAL NOT NULL DEFAULT 1,
              unit_price_cents INTEGER NOT NULL DEFAULT 0,
              entity_type TEXT,
              entity_id INTEGER,
              created_at TEXT NOT NULL,
              FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_invoices_client ON invoices(client_id);
            CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id)
        """)
        if not _column_exists(conn, "sessions", "invoice_id"):
            conn.execute("ALTER TABLE sessions ADD COLUMN invoice_id INTEGER")
        if not _column_exists(conn, "case_tasks", "invoice_id"):
            conn.execute("ALTER TABLE case_tasks ADD COLUMN invoice_id INTEGER")
        _set_schema_version(conn, 12)

    # v13: link incomes to invoices
    if v < 13:
        if not _column_exists(conn, "incomes", "invoice_id"):
            conn.execute("ALTER TABLE incomes ADD COLUMN invoice_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incomes_invoice ON incomes(invoice_id)")
        _set_schema_version(conn, 13)

    # v14: extended client profile
    if v < 14:
        if not _column_exists(conn, "clients", "client_type"):
            conn.execute("ALTER TABLE clients ADD COLUMN client_type TEXT NOT NULL DEFAULT 'Física'")
        else:
            conn.execute("UPDATE clients SET client_type='Física' WHERE client_type='Persona física'")
            conn.execute("UPDATE clients SET client_type='Jurídica' WHERE client_type='Persona jurídica'")
        if not _column_exists(conn, "clients", "id_number"):
            conn.execute("ALTER TABLE clients ADD COLUMN id_number TEXT")
        if not _column_exists(conn, "clients", "phone2"):
            conn.execute("ALTER TABLE clients ADD COLUMN phone2 TEXT")
        _set_schema_version(conn, 14)

    # v15: extended case profile
    if v < 15:
        for col in ("internal_ref", "official_ref", "opposing_party", "court_entity", "responsible_username"):
            if not _column_exists(conn, "cases", col):
                conn.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
        _set_schema_version(conn, 15)

    # v16: task responsible + attachment doc_role
    if v < 16:
        if not _column_exists(conn, "case_tasks", "responsible_username"):
            conn.execute("ALTER TABLE case_tasks ADD COLUMN responsible_username TEXT")
        if not _column_exists(conn, "attachments", "doc_role"):
            conn.execute("ALTER TABLE attachments ADD COLUMN doc_role TEXT")
        _set_schema_version(conn, 16)

    if v < 17:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS roles (
              id SERIAL PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              description TEXT,
              is_system INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS permissions (
              id SERIAL PRIMARY KEY,
              module TEXT NOT NULL,
              action TEXT NOT NULL,
              label TEXT NOT NULL,
              UNIQUE(module, action)
            );
            CREATE TABLE IF NOT EXISTS role_permissions (
              role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
              permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
              PRIMARY KEY (role_id, permission_id)
            )
        """)
        if not _column_exists(conn, "users", "role_id"):
            conn.execute("ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL")
        _seed_rbac(conn)
        _set_schema_version(conn, 17)

    if v < 18:
        # Make sessions.client_id nullable so imported calendar events don't need a fake client
        conn.execute("""
            ALTER TABLE sessions
            DROP CONSTRAINT IF EXISTS sessions_client_id_fkey
        """)
        conn.execute("ALTER TABLE sessions ALTER COLUMN client_id DROP NOT NULL")
        conn.execute("""
            ALTER TABLE sessions
            ADD CONSTRAINT sessions_client_id_fkey
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
        """)
        # Remove the placeholder Google Calendar client if it exists (no real data)
        conn.execute(
            "DELETE FROM clients WHERE name = 'Google Calendar' AND phone IS NULL AND email IS NULL"
        )
        conn.commit()
        _set_schema_version(conn, 18)

    # v19: Outlook Calendar tokens (table was referenced by repositories.py but never created)
    if v < 19:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS outlook_tokens (
              username TEXT PRIMARY KEY,
              access_token TEXT NOT NULL,
              refresh_token TEXT NOT NULL,
              expiry_at TEXT NOT NULL
            )
        """)
        _set_schema_version(conn, 19)

    # v20: catálogo maestro — categorías, subcategorías, servicios, familias, historial
    if v < 20:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS categorias (
              id SERIAL PRIMARY KEY,
              category_code TEXT NOT NULL UNIQUE,
              nombre TEXT NOT NULL UNIQUE,
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_categorias_estado ON categorias(estado);

            CREATE TABLE IF NOT EXISTS subcategorias (
              id SERIAL PRIMARY KEY,
              subcategory_code TEXT NOT NULL,
              category_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE RESTRICT,
              nombre TEXT NOT NULL,
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(category_id, subcategory_code)
            );
            CREATE INDEX IF NOT EXISTS idx_subcategorias_category ON subcategorias(category_id, estado);

            CREATE TABLE IF NOT EXISTS familias (
              id SERIAL PRIMARY KEY,
              family_code TEXT NOT NULL UNIQUE,
              nombre TEXT NOT NULL,
              category_id INTEGER NOT NULL UNIQUE REFERENCES categorias(id) ON DELETE RESTRICT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS servicios (
              id SERIAL PRIMARY KEY,
              service_code TEXT NOT NULL UNIQUE,
              subcategory_id INTEGER NOT NULL REFERENCES subcategorias(id) ON DELETE RESTRICT,
              nombre TEXT NOT NULL,
              etiquetas TEXT,
              unidad_cobro TEXT NOT NULL DEFAULT 'Por definir'
                CHECK (unidad_cobro IN ('Precio fijo','Por hora','Por etapa','Mensual','Porcentaje','Por definir')),
              responsable_sugerido TEXT NOT NULL DEFAULT 'Por definir'
                CHECK (responsable_sugerido IN ('Socio / Notario','Abogada asociada','Manager','Asistente legal','Equipo mixto','Por definir')),
              tarifa_referencia_cents INTEGER NOT NULL DEFAULT 0 CHECK (tarifa_referencia_cents >= 0),
              costo_referencia_cents INTEGER NOT NULL DEFAULT 0 CHECK (costo_referencia_cents >= 0),
              margen_referencia_cents INTEGER GENERATED ALWAYS AS (tarifa_referencia_cents - costo_referencia_cents) STORED,
              horas_estandar NUMERIC(6,2) NOT NULL DEFAULT 0 CHECK (horas_estandar >= 0),
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo','En diseño')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(subcategory_id, nombre)
            );
            CREATE INDEX IF NOT EXISTS idx_servicios_subcategory ON servicios(subcategory_id, estado);
            CREATE INDEX IF NOT EXISTS idx_servicios_nombre ON servicios(lower(nombre));

            CREATE TABLE IF NOT EXISTS historial_catalogo (
              id SERIAL PRIMARY KEY,
              tipo_registro TEXT NOT NULL CHECK (tipo_registro IN ('Categoria','Subcategoria','Servicio')),
              entity_id INTEGER NOT NULL,
              version_anterior JSONB NOT NULL,
              usuario_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
              fecha_cambio TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_historial_catalogo_entity ON historial_catalogo(tipo_registro, entity_id)
        """)
        _set_schema_version(conn, 20)

    # v21: plan de cuentas, personal, gastos fijos, supuestos financieros
    if v < 21:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plan_cuentas (
              id SERIAL PRIMARY KEY,
              account_code TEXT NOT NULL UNIQUE,
              tipo TEXT NOT NULL CHECK (tipo IN ('Ingreso','Egreso')),
              grupo TEXT NOT NULL,
              subgrupo TEXT,
              nombre TEXT NOT NULL,
              naturaleza TEXT NOT NULL
                CHECK (naturaleza IN ('Operativo','Fijo','Variable','Directo','Inversión','Otros','Fijo/Variable')),
              family_id INTEGER REFERENCES familias(id) ON DELETE SET NULL,
              category_id INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
              centro_costo TEXT NOT NULL
                CHECK (centro_costo IN ('Operación jurídica','Administración','Comercial','Tecnología','Comercial y administración')),
              afecta_utilidad BOOLEAN NOT NULL DEFAULT TRUE,
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo')),
              regla_de_uso TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plan_cuentas_tipo ON plan_cuentas(tipo, estado);

            CREATE TABLE IF NOT EXISTS personal (
              id SERIAL PRIMARY KEY,
              person_code TEXT NOT NULL UNIQUE,
              persona TEXT NOT NULL,
              cargo TEXT,
              monto_mensual_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_mensual_cents >= 0),
              mes_inicio TEXT NOT NULL,
              mes_fin TEXT,
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS gastos_fijos (
              id SERIAL PRIMARY KEY,
              expense_code TEXT NOT NULL UNIQUE,
              concepto TEXT NOT NULL,
              tipo TEXT NOT NULL CHECK (tipo IN ('Fijo','Estimado','Meta')),
              monto_mensual_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_mensual_cents >= 0),
              mes_inicio TEXT NOT NULL,
              mes_fin TEXT,
              estado TEXT NOT NULL DEFAULT 'Activo' CHECK (estado IN ('Activo','Inactivo')),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS supuestos_financieros (
              id SERIAL PRIMARY KEY,
              periodo TEXT NOT NULL UNIQUE,
              costo_variable_pct NUMERIC(6,4) NOT NULL CHECK (costo_variable_pct >= 0 AND costo_variable_pct < 1),
              margen_operativo_meta_pct NUMERIC(6,4) NOT NULL CHECK (margen_operativo_meta_pct >= 0 AND margen_operativo_meta_pct < 1),
              margen_seguridad_pct NUMERIC(6,4) NOT NULL CHECK (margen_seguridad_pct >= 0),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        _set_schema_version(conn, 21)

    # v22: pipeline comercial (oportunidades) — previo al expediente
    if v < 22:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oportunidades (
              id SERIAL PRIMARY KEY,
              client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
              prospecto_nombre TEXT,
              prospecto_contacto TEXT,
              service_id INTEGER REFERENCES servicios(id) ON DELETE SET NULL,
              canal_captacion TEXT NOT NULL CHECK (canal_captacion IN ('Instagram','Google','LinkedIn','Referido','Otro')),
              origen_negocio TEXT NOT NULL CHECK (origen_negocio IN ('Andrea','Alfredo','Guadalupe','Referido','Orgánico','Otro')),
              estado TEXT NOT NULL DEFAULT 'Prospecto' CHECK (estado IN ('Prospecto','Cotizado','Ganado','Perdido')),
              motivo_perdida TEXT,
              case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
              fecha_prospecto TEXT NOT NULL,
              fecha_cotizado TEXT,
              fecha_cierre TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              CONSTRAINT chk_oportunidad_cliente_o_prospecto CHECK (client_id IS NOT NULL OR prospecto_nombre IS NOT NULL)
            );
            CREATE INDEX IF NOT EXISTS idx_oportunidades_estado ON oportunidades(estado);
        """)
        if not _column_exists(conn, "cases", "opportunity_id"):
            conn.execute("ALTER TABLE cases ADD COLUMN opportunity_id INTEGER REFERENCES oportunidades(id) ON DELETE SET NULL")
        _set_schema_version(conn, 22)

    # v23: expedientes — clasificación por servicio, campos financieros y gestión de tiempos
    if v < 23:
        if not _column_exists(conn, "cases", "service_id"):
            conn.execute("ALTER TABLE cases ADD COLUMN service_id INTEGER REFERENCES servicios(id) ON DELETE SET NULL")
        if not _column_exists(conn, "cases", "honorarios_contratados_cents"):
            conn.execute(
                "ALTER TABLE cases ADD COLUMN honorarios_contratados_cents INTEGER NOT NULL DEFAULT 0 "
                "CHECK (honorarios_contratados_cents >= 0)"
            )
        if not _column_exists(conn, "cases", "costos_directos_estimados_cents"):
            conn.execute(
                "ALTER TABLE cases ADD COLUMN costos_directos_estimados_cents INTEGER NOT NULL DEFAULT 0 "
                "CHECK (costos_directos_estimados_cents >= 0)"
            )
        if not _column_exists(conn, "cases", "mes_cobro_esperado"):
            conn.execute("ALTER TABLE cases ADD COLUMN mes_cobro_esperado TEXT")
        if not _column_exists(conn, "cases", "estado_cobro"):
            # Campo NUEVO e independiente de `status` (progreso legal). Este trackea el ciclo de
            # facturación/cobro que pide el Archivo Maestro, sin tocar el status ya usado por
            # alertas y badges existentes.
            conn.execute(
                "ALTER TABLE cases ADD COLUMN estado_cobro TEXT NOT NULL DEFAULT 'En ejecución' "
                "CHECK (estado_cobro IN ('En ejecución','Finalizado pendiente de facturar','Facturado pendiente de cobro','Cobrado','Suspendido'))"
            )
        if not _column_exists(conn, "cases", "fecha_cierre_estimada"):
            conn.execute("ALTER TABLE cases ADD COLUMN fecha_cierre_estimada TEXT")
        if not _column_exists(conn, "cases", "fecha_cierre_real"):
            conn.execute("ALTER TABLE cases ADD COLUMN fecha_cierre_real TEXT")
        if not _column_exists(conn, "cases", "proxima_accion"):
            conn.execute("ALTER TABLE cases ADD COLUMN proxima_accion TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cases_service ON cases(service_id)")
        _set_schema_version(conn, 23)

    # v24: movimientos financieros — código de cuenta, código de servicio y desglose
    # bruto/IVA/reembolsable/neto operativo en incomes/expenses/costs. `amount_cents`
    # (ya existente) se conserva como el monto bruto — no se renombra para no romper
    # facturas, dashboard ni el resto del código que ya lo usa.
    if v < 24:
        for table in ("incomes", "expenses", "costs"):
            if not _column_exists(conn, table, "account_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN account_id INTEGER REFERENCES plan_cuentas(id) ON DELETE SET NULL")
            if not _column_exists(conn, table, "service_id"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN service_id INTEGER REFERENCES servicios(id) ON DELETE SET NULL")
            if not _column_exists(conn, table, "monto_iva_cents"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN monto_iva_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_iva_cents >= 0)")
            if not _column_exists(conn, table, "monto_reembolsable_cents"):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN monto_reembolsable_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_reembolsable_cents >= 0)")
            if not _column_exists(conn, table, "monto_neto_operativo_cents"):
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN monto_neto_operativo_cents INTEGER "
                    "GENERATED ALWAYS AS (amount_cents - monto_iva_cents - monto_reembolsable_cents) STORED"
                )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_account ON {table}(account_id)")
        _set_schema_version(conn, 24)

    # v25: presupuesto por familia (meta mensual) para proyección de cierre de mes
    if v < 25:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS forecast (
              id SERIAL PRIMARY KEY,
              family_id INTEGER NOT NULL REFERENCES familias(id) ON DELETE CASCADE,
              mes TEXT NOT NULL,
              volumen_meta INTEGER NOT NULL DEFAULT 0 CHECK (volumen_meta >= 0),
              ticket_objetivo_cents INTEGER NOT NULL DEFAULT 0 CHECK (ticket_objetivo_cents >= 0),
              ingreso_proyectado_cents INTEGER GENERATED ALWAYS AS (volumen_meta * ticket_objetivo_cents) STORED,
              margen_directo_objetivo_pct NUMERIC(6,4) NOT NULL DEFAULT 0 CHECK (margen_directo_objetivo_pct >= 0 AND margen_directo_objetivo_pct < 1),
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(family_id, mes)
            );
            CREATE INDEX IF NOT EXISTS idx_forecast_mes ON forecast(mes);
        """)
        _set_schema_version(conn, 25)

    # v26: comisión multi-originador — reparto por expediente + registros de comisión
    # calculados por cobro individual, acumulados por persona y mes.
    if v < 26:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS negocio_originadores (
              id SERIAL PRIMARY KEY,
              case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
              personal_id INTEGER NOT NULL REFERENCES personal(id) ON DELETE RESTRICT,
              porcentaje_participacion NUMERIC(5,2) NOT NULL CHECK (porcentaje_participacion > 0 AND porcentaje_participacion <= 100),
              tipo_origen TEXT NOT NULL CHECK (tipo_origen IN ('Cliente nuevo','Venta cruzada')),
              created_at TEXT NOT NULL,
              UNIQUE(case_id, personal_id)
            );
            CREATE INDEX IF NOT EXISTS idx_negocio_originadores_case ON negocio_originadores(case_id);

            CREATE TABLE IF NOT EXISTS comisiones (
              id SERIAL PRIMARY KEY,
              income_id INTEGER NOT NULL REFERENCES incomes(id) ON DELETE CASCADE,
              case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
              personal_id INTEGER NOT NULL REFERENCES personal(id) ON DELETE RESTRICT,
              tipo_origen TEXT NOT NULL CHECK (tipo_origen IN ('Cliente nuevo','Venta cruzada')),
              porcentaje_participacion NUMERIC(5,2) NOT NULL,
              base_utilidad_directa_cents INTEGER NOT NULL CHECK (base_utilidad_directa_cents >= 0),
              comision_cents INTEGER NOT NULL,
              mes_reconocimiento TEXT NOT NULL,
              ajusta_a_commission_id INTEGER REFERENCES comisiones(id) ON DELETE SET NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comisiones_persona_mes ON comisiones(personal_id, mes_reconocimiento);
            CREATE INDEX IF NOT EXISTS idx_comisiones_income ON comisiones(income_id);
        """)
        _set_schema_version(conn, 26)

    # v27: gobierno del catálogo — solicitudes de alta/cambio con código propuesto
    # (tentativo, editable) separado del código definitivo (solo se asigna al aprobar).
    if v < 27:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS solicitudes_catalogo (
              id SERIAL PRIMARY KEY,
              solicitud_code TEXT NOT NULL UNIQUE,
              fecha_solicitud TEXT NOT NULL,
              tipo_solicitud TEXT NOT NULL CHECK (tipo_solicitud IN ('Alta','Cambio','Baja')),
              tipo_registro TEXT NOT NULL CHECK (tipo_registro IN ('Categoria','Subcategoria','Servicio','Familia')),
              nombre_propuesto TEXT NOT NULL,
              categoria_padre TEXT,
              subcategoria_padre TEXT,
              codigo_propuesto TEXT NOT NULL,
              codigo_definitivo TEXT,
              descripcion TEXT,
              motivo TEXT,
              etiquetas TEXT,
              solicitante TEXT NOT NULL,
              resultado_revision_duplicidad TEXT,
              aprobador TEXT,
              fecha_aprobacion TEXT,
              estado TEXT NOT NULL DEFAULT 'Solicitado'
                CHECK (estado IN ('Solicitado','En revisión','Aprobado','Rechazado','Activo','Inactivo')),
              observaciones TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_solicitudes_estado ON solicitudes_catalogo(estado);
        """)
        _set_schema_version(conn, 27)

    # v28: los módulos nuevos de las Fases 1-10 (Catálogo Maestro, Finanzas, Pipeline,
    # Comisiones, Gobierno del Catálogo) viajaban sin permisos propios — reutilizaban
    # "categorias.*" o "expedientes.editar" sin relación real con esos módulos, y todos
    # sus endpoints de lectura no exigían ningún permiso más allá de estar autenticado.
    # Se retira el permiso genérico "categorias" (ya sin uso tras el retiro del sistema
    # legado de categorías/productos) y se crean permisos dedicados por módulo.
    if v < 28:
        conn.execute("DELETE FROM permissions WHERE module = 'categorias'")
        _seed_rbac(conn)
        _set_schema_version(conn, 28)

    # v29: las solicitudes de catálogo ganan referencia a un registro existente
    # (entity_id, igual de polimórfico que historial_catalogo.entity_id — sin FK porque
    # apunta a 4 tablas distintas según tipo_registro) más los campos propuestos que le
    # faltaban a "Cambio" para un Servicio (unidad de cobro, responsable, tarifa, costo,
    # horas, estado) — sin esto, aprobar un Cambio solo podía renombrar/retaguetear.
    # Motivo: se retira la creación/edición directa del Catálogo Maestro (Fase 10.2) —
    # toda alta, cambio o baja pasa ahora por una solicitud, así que el Cambio tiene que
    # poder editar cualquier campo que antes se editaba directo ahí.
    if v < 29:
        conn.executescript("""
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS entity_id INTEGER;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS unidad_cobro_propuesta TEXT;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS responsable_sugerido_propuesto TEXT;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS tarifa_referencia_propuesta_cents INTEGER;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS costo_referencia_propuesta_cents INTEGER;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS horas_estandar_propuesta NUMERIC;
            ALTER TABLE solicitudes_catalogo ADD COLUMN IF NOT EXISTS estado_propuesto TEXT;
            CREATE INDEX IF NOT EXISTS idx_solicitudes_entity ON solicitudes_catalogo(tipo_registro, entity_id);
        """)
        conn.execute("DELETE FROM permissions WHERE module = 'catalogo' AND action IN ('crear', 'editar')")
        _seed_rbac(conn)
        _set_schema_version(conn, 29)

    # v30: cases.service_area (texto libre, lista fija de 8 valores, previa al Catálogo
    # Maestro) se retira — quedaba desincronizado del service_id real elegido, sin nada
    # que los mantuviera de acuerdo. La categoría del servicio del catálogo (ya
    # disponible vía service_id → categoria) pasa a ser la única fuente de "área". Se
    # quita el NOT NULL para no romper los INSERT que ya no la envían — la columna y
    # los datos históricos se quedan intactos, solo deja de ser obligatoria y de usarse.
    if v < 30:
        conn.execute("ALTER TABLE cases ALTER COLUMN service_area DROP NOT NULL")
        _set_schema_version(conn, 30)

    # v31: hallazgos de la auditoría "rol de abogado" (AUDITORIA_USO_ABOGADO.md) —
    # papelera para clientes/expedientes (borrado real era irreversible), plazos
    # legales críticos distinguibles de un pendiente cualquiera, registro de horas
    # trabajadas para servicios cobrados "Por hora", valor monetario del pipeline
    # comercial, y enlace de Nóminas al catálogo de Personal ya existente.
    if v < 31:
        conn.executescript("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT;
            ALTER TABLE clients ADD COLUMN IF NOT EXISTS archived_at TEXT;
            ALTER TABLE cases ADD COLUMN IF NOT EXISTS archived_at TEXT;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS es_critico INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS honorarios_estimados_cents INTEGER;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS personal_id INTEGER;
            CREATE TABLE IF NOT EXISTS case_time_entries (
              id SERIAL PRIMARY KEY,
              case_id INTEGER NOT NULL,
              username TEXT NOT NULL,
              work_date TEXT NOT NULL,
              hours NUMERIC(6,2) NOT NULL,
              description TEXT,
              billable INTEGER NOT NULL DEFAULT 1,
              invoice_id INTEGER,
              created_at TEXT NOT NULL,
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_case_time_entries_case ON case_time_entries(case_id);
            CREATE INDEX IF NOT EXISTS idx_clients_archived ON clients(archived_at);
            CREATE INDEX IF NOT EXISTS idx_cases_archived ON cases(archived_at);
        """)
        _set_schema_version(conn, 31)

    # v32: fondos de terceros como cuarta categoría de movimiento (junto a honorarios/IVA
    # 13% El Salvador/reembolsable) y código de cuenta contable obligatorio en todo
    # movimiento — ambos exigidos por el Archivo Maestro AG Legal. Los movimientos
    # existentes son datos de prueba: se eliminan los que no tienen cuenta asignada en
    # vez de forzar una reclasificación manual (comisiones cae en cascada con ellos).
    if v < 32:
        for table in ("incomes", "expenses", "costs"):
            if not _column_exists(conn, table, "monto_fondos_terceros_cents"):
                conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN monto_fondos_terceros_cents "
                    "INTEGER NOT NULL DEFAULT 0 CHECK (monto_fondos_terceros_cents >= 0)"
                )
            # GENERATED ALWAYS AS no admite ALTER; se recrea con la fórmula ampliada.
            conn.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS monto_neto_operativo_cents")
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN monto_neto_operativo_cents INTEGER "
                "GENERATED ALWAYS AS (amount_cents - monto_iva_cents - monto_reembolsable_cents "
                "- monto_fondos_terceros_cents) STORED"
            )
            conn.execute(f"DELETE FROM {table} WHERE account_id IS NULL")
            conn.execute(f"ALTER TABLE {table} ALTER COLUMN account_id SET NOT NULL")
        _set_schema_version(conn, 32)

    # v33: desglose de tramos de comisión — guarda el punto de la curva acumulada antes y
    # después de cada cobro para que la UI pueda mostrar "10% x $1,000 + 12% x $600" sin
    # duplicar los umbrales COM-001/002/003 como números mágicos en el frontend. Nulo en
    # las filas de ajuste/reversión (no representan un tramo real).
    if v < 33:
        if not _column_exists(conn, "comisiones", "base_acumulada_antes_cents"):
            conn.execute("ALTER TABLE comisiones ADD COLUMN base_acumulada_antes_cents INTEGER")
        if not _column_exists(conn, "comisiones", "base_acumulada_despues_cents"):
            conn.execute("ALTER TABLE comisiones ADD COLUMN base_acumulada_despues_cents INTEGER")
        _set_schema_version(conn, 33)

    # v34: revisión de duplicidad asistida en el gobierno del catálogo — pg_trgm permite
    # comparar el nombre propuesto contra el catálogo existente por similitud, en vez de que
    # el aprobador tenga que recordar de memoria si algo parecido ya existe.
    if v < 34:
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        _set_schema_version(conn, 34)

    # v35: motor de cálculo de nómina real. Hasta ahora "Nóminas" solo guardaba un monto
    # único que el usuario ya calculaba a mano fuera del sistema (ISSS, AFP, renta, horas
    # extra, etc. vivían en un Excel aparte). Esta migración:
    #  1. Crea `payroll_config`, una tabla de configuración VERSIONADA (nunca se edita una
    #     fila existente, se inserta una nueva vigente_desde) porque las tasas de ley
    #     cambian con el tiempo y necesitamos poder recalcular planillas pasadas con la
    #     tasa que estaba vigente en ese momento, no con la de hoy.
    #  2. Agrega `personal.account_id`: enlace EXPLÍCITO a la cuenta contable de cada
    #     persona. Antes, create_payroll() buscaba la cuenta por "ILIKE %nombre%" sobre
    #     plan_cuentas — frágil (coincidencias parciales, o ninguna coincidencia hace que
    #     _validate_movement_account() truene con account_id=None) y ahora innecesario.
    #  3. Amplía `payrolls` con el desglose completo (devengos, deducciones, cálculo) y un
    #     campo `modo` para distinguir una planilla calculada por el motor de un pago
    #     manual (bono suelto, ajuste) que sigue sin desglose. `amount_cents` se mantiene
    #     como el neto a pagar final en ambos casos — no se toca su significado.
    #  4. Evita el doble pago accidental de la planilla mensual de una misma persona con un
    #     índice único parcial (solo aplica a modo='calculado', un bono sí puede repetirse).
    #  5. `payroll_audit_log` registra cada corrección de una planilla ya creada — antes la
    #     única forma de corregir era borrar y recrear, perdiendo el porqué del cambio.
    if v < 35:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS payroll_config (
              id SERIAL PRIMARY KEY,
              vigente_desde TEXT NOT NULL UNIQUE,
              isss_tasa_empleado NUMERIC(6,4) NOT NULL,
              isss_tasa_patronal NUMERIC(6,4) NOT NULL,
              isss_tope_cotizable_cents INTEGER NOT NULL,
              afp_tasa_empleado NUMERIC(6,4) NOT NULL,
              afp_tasa_patronal NUMERIC(6,4) NOT NULL,
              afp_tope_cotizable_cents INTEGER NOT NULL,
              tramos_renta JSONB NOT NULL DEFAULT '[]'::jsonb,
              recargo_hora_extra_pct NUMERIC(6,4) NOT NULL DEFAULT 0.5,
              recargo_nocturnidad_pct NUMERIC(6,4) NOT NULL DEFAULT 0.25,
              horas_jornada_mensual NUMERIC(6,2) NOT NULL DEFAULT 240,
              notas TEXT,
              created_at TEXT NOT NULL
            );

            ALTER TABLE personal ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES plan_cuentas(id);

            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'manual' CHECK (modo IN ('calculado','manual'));
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS salario_base_cents INTEGER;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS horas_extra_cantidad NUMERIC(6,2) NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS horas_extra_monto_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS nocturnidad_horas NUMERIC(6,2) NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS nocturnidad_monto_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS bonificaciones_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS otros_ingresos_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS descuento_faltas_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS descuento_prestamos_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS otros_descuentos_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS isss_empleado_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS afp_empleado_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS renta_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS isss_patronal_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS afp_patronal_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS total_devengado_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS total_descuentos_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS payroll_config_id INTEGER REFERENCES payroll_config(id);

            CREATE UNIQUE INDEX IF NOT EXISTS uq_payrolls_personal_period_calculado
              ON payrolls(personal_id, period) WHERE modo = 'calculado' AND personal_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS payroll_audit_log (
              id SERIAL PRIMARY KEY,
              payroll_id INTEGER NOT NULL REFERENCES payrolls(id) ON DELETE CASCADE,
              campo TEXT NOT NULL,
              valor_anterior TEXT,
              valor_nuevo TEXT,
              username TEXT NOT NULL,
              changed_at TEXT NOT NULL
            );
        """)
        # Config inicial con las tasas de ISSS/AFP y el tope de cotización vigentes según la
        # reforma de 2023 (Decreto 843) — verificar con tu contador antes de depender de
        # estos números en producción, y actualizarlos aquí (Configuración → Nómina) el día
        # que cambien por ley. La tabla de tramos de renta se deja VACÍA a propósito: son
        # los más propensos a quedar desactualizados y un valor inventado aquí podría causar
        # una retención de ISR incorrecta — el motor avisa explícitamente si intentas
        # calcular una planilla sin la tabla de renta configurada.
        conn.execute(
            "INSERT INTO payroll_config(vigente_desde, isss_tasa_empleado, isss_tasa_patronal, "
            "isss_tope_cotizable_cents, afp_tasa_empleado, afp_tasa_patronal, afp_tope_cotizable_cents, "
            "tramos_renta, recargo_hora_extra_pct, recargo_nocturnidad_pct, horas_jornada_mensual, notas, created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vigente_desde) DO NOTHING",
            ("2023-05-01", 0.03, 0.075, 100000, 0.0725, 0.0875, 100000, "[]",
             0.5, 0.25, 240, "Config inicial migrada automáticamente — VERIFICAR tasas y completar tramos_renta.", now_iso()),
        )
        _set_schema_version(conn, 35)

    # v36: dos correcciones verificadas contra fuente oficial (Ministerio de Hacienda,
    # Decreto Ejecutivo No. 10 del 30/abr/2025, vigente desde mayo 2025) más el soporte
    # para las prestaciones de ley que la v35 no cubría:
    #  1. AFP NO tiene tope de cotización desde la Ley Integral del Sistema de Pensiones
    #     ("No se establece un monto máximo de salario a utilizar como base para cálculo
    #     de las cotizaciones") — la v35 le puso por error el mismo tope de $1,000 de
    #     ISSS. Se permite NULL en ambos topes para representar "sin tope" (ISSS sí
    #     conserva el suyo de $1,000 hoy, pero la ley puede volver a cambiarlo).
    #  2. Se agrega la tabla real de retención de renta mensual del decreto vigente.
    #  3. `tope_salario_indemnizacion_cents`: el salario base para la indemnización por
    #     despido (Art. 58 Código de Trabajo) está limitado a un múltiplo del salario
    #     mínimo vigente, que cambia por decreto ejecutivo — se deja NULL (sin tope) hasta
    #     que se configure explícitamente, en vez de asumir un multiplicador no verificado.
    # Se inserta una nueva versión vigente_desde 2025-05-01 en vez de tocar la fila de la
    # v35 — esa fila queda como registro histórico de lo que estaba configurado antes de
    # esta corrección, consistente con que payroll_config nunca se edita en el sitio.
    if v < 36:
        conn.executescript("""
            ALTER TABLE payroll_config ALTER COLUMN afp_tope_cotizable_cents DROP NOT NULL;
            ALTER TABLE payroll_config ALTER COLUMN isss_tope_cotizable_cents DROP NOT NULL;
            ALTER TABLE payroll_config ADD COLUMN IF NOT EXISTS tope_salario_indemnizacion_cents INTEGER;
        """)
        tramos_renta_2025 = [
            {"sobre_exceso_de_cents": 0, "hasta_cents": 55000, "cuota_fija_cents": 0, "porcentaje_exceso": 0},
            {"sobre_exceso_de_cents": 55000, "hasta_cents": 89524, "cuota_fija_cents": 1767, "porcentaje_exceso": 0.10},
            {"sobre_exceso_de_cents": 89524, "hasta_cents": 203810, "cuota_fija_cents": 6000, "porcentaje_exceso": 0.20},
            {"sobre_exceso_de_cents": 203810, "hasta_cents": None, "cuota_fija_cents": 28857, "porcentaje_exceso": 0.30},
        ]
        conn.execute(
            "INSERT INTO payroll_config(vigente_desde, isss_tasa_empleado, isss_tasa_patronal, "
            "isss_tope_cotizable_cents, afp_tasa_empleado, afp_tasa_patronal, afp_tope_cotizable_cents, "
            "tope_salario_indemnizacion_cents, tramos_renta, recargo_hora_extra_pct, recargo_nocturnidad_pct, "
            "horas_jornada_mensual, notas, created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (vigente_desde) DO NOTHING",
            (
                "2025-05-01", 0.03, 0.075, 100000, 0.0725, 0.0875, None, None,
                Json(tramos_renta_2025), 0.5, 0.25, 240,
                "Corrige el tope de AFP (no tiene, según Ley Integral del Sistema de Pensiones) y agrega "
                "la tabla real de retención de renta mensual (Decreto Ejecutivo No. 10, vigente desde "
                "mayo 2025, fuente: Ministerio de Hacienda). Falta configurar el tope de salario para "
                "indemnización (ligado al salario mínimo vigente) antes de usar esa prestación.",
                now_iso(),
            ),
        )
        _set_schema_version(conn, 36)

    # v37: ancla lo financiero a lo operativo — hasta ahora un expediente tenía un costo
    # pactado fijo (`honorarios_contratados_cents`) que nada tocaba, aunque se agregaran
    # tareas o sesiones de más; y una factura con `case_id` podía jalar partidas de
    # CUALQUIER expediente del mismo cliente (el `case_id` era solo metadata, no filtro).
    # Tres piezas:
    #  1. `plantillas_tareas`: catálogo de tareas típicas por servicio. Al crear un
    #     expediente con ese servicio, se sugieren (editable) — no obligan a nada.
    #  2. `case_tasks`/`sessions` ganan `origen` ('plantilla' = ya incluida en lo
    #     pactado, 'manual' = agregada aparte) y `monto_adicional_cents`. Cada vez que se
    #     crea una tarea/sesión manual con monto > 0, ese monto se SUMA a
    #     `cases.honorarios_contratados_cents` automáticamente (y se resta si se borra) —
    #     `case_honorarios_log` deja registro de cada movimiento para que nunca sea un
    #     cambio invisible al monto pactado con el cliente.
    #  3. `costs` no tenía `invoice_id` — un costo facturado nunca se marcaba como tal y
    #     podía reaparecer en el selector de "no facturado" y cobrarse dos veces. Se
    #     agrega la columna, igual que ya la tienen `sessions`/`case_tasks`/`case_time_entries`.
    if v < 37:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS plantillas_tareas (
              id SERIAL PRIMARY KEY,
              service_id INTEGER NOT NULL REFERENCES servicios(id) ON DELETE CASCADE,
              titulo TEXT NOT NULL,
              orden INTEGER NOT NULL DEFAULT 0,
              dias_plazo_relativo INTEGER,
              es_critico_default INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plantillas_tareas_service ON plantillas_tareas(service_id, orden);

            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('plantilla','manual'));
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS monto_adicional_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_adicional_cents >= 0);
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS origen TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('plantilla','manual'));
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS monto_adicional_cents INTEGER NOT NULL DEFAULT 0 CHECK (monto_adicional_cents >= 0);
            ALTER TABLE costs ADD COLUMN IF NOT EXISTS invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL;

            CREATE TABLE IF NOT EXISTS case_honorarios_log (
              id SERIAL PRIMARY KEY,
              case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
              origen_tipo TEXT NOT NULL CHECK (origen_tipo IN ('tarea','sesion')),
              origen_id INTEGER NOT NULL,
              monto_cents INTEGER NOT NULL,
              motivo TEXT NOT NULL,
              username TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_case_honorarios_log_case ON case_honorarios_log(case_id);
        """)
        _set_schema_version(conn, 37)

    # v38: hallazgos críticos de la auditoría contra el Archivo Maestro.
    #  1. El historial de comisiones ya no se borra en cascada: borrar un cobro dejaba
    #     desaparecer su comisión sin ajuste trazable ("Reversión: se corrige en el
    #     siguiente período"). income_id pasa a SET NULL y case_id a RESTRICT; se guarda
    #     una copia de la fecha del cobro y de la referencia del expediente para que la
    #     fila siga siendo legible aunque el cobro ya no exista, más el motivo del ajuste.
    #  2. `incomes.es_ajuste`: un cobro que excede el saldo del expediente solo se acepta
    #     marcado explícitamente como ajuste ("No exceder saldo salvo ajuste").
    if v < 38:
        conn.executescript("""
            ALTER TABLE comisiones ALTER COLUMN income_id DROP NOT NULL;
            ALTER TABLE comisiones DROP CONSTRAINT IF EXISTS comisiones_income_id_fkey;
            ALTER TABLE comisiones ADD CONSTRAINT comisiones_income_id_fkey
              FOREIGN KEY (income_id) REFERENCES incomes(id) ON DELETE SET NULL;
            ALTER TABLE comisiones DROP CONSTRAINT IF EXISTS comisiones_case_id_fkey;
            ALTER TABLE comisiones ADD CONSTRAINT comisiones_case_id_fkey
              FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE RESTRICT;
            ALTER TABLE comisiones ADD COLUMN IF NOT EXISTS fecha_cobro TEXT;
            ALTER TABLE comisiones ADD COLUMN IF NOT EXISTS case_label TEXT;
            ALTER TABLE comisiones ADD COLUMN IF NOT EXISTS motivo TEXT;
            UPDATE comisiones c SET fecha_cobro = i.income_date FROM incomes i WHERE i.id = c.income_id AND c.fecha_cobro IS NULL;
            UPDATE comisiones c SET case_label = COALESCE(cs.internal_ref || ' — ', '') || cs.title
              FROM cases cs WHERE cs.id = c.case_id AND c.case_label IS NULL;
            ALTER TABLE incomes ADD COLUMN IF NOT EXISTS es_ajuste BOOLEAN NOT NULL DEFAULT FALSE;
        """)
        _set_schema_version(conn, 38)

    # v39: el embudo comercial se trabaja por fechas, no de memoria. Una oportunidad
    # abierta necesita saber quién le da seguimiento, cuál es el próximo paso y cuándo;
    # y al perderse, por qué (de una lista corta, para poder medir el canal después).
    if v < 39:
        conn.executescript("""
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS responsable_username TEXT;
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS proxima_accion TEXT;
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS fecha_proxima_accion TEXT;
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS motivo_perdida_tipo TEXT;
            ALTER TABLE oportunidades ADD COLUMN IF NOT EXISTS fecha_ultimo_estado TEXT;
            CREATE INDEX IF NOT EXISTS idx_oportunidades_proxima ON oportunidades(fecha_proxima_accion);
            UPDATE oportunidades SET fecha_ultimo_estado = COALESCE(fecha_cotizado, fecha_prospecto)
              WHERE fecha_ultimo_estado IS NULL;
        """)
        _set_schema_version(conn, 39)

    # v40: la tarea pasa a ser el registro de lo que de más se hizo en un expediente y de
    # lo que costó. Hasta ahora solo tenía un monto, que se interpretaba como cobro al
    # cliente: anotar ahí el transporte de una diligencia subía la factura y además inflaba
    # la utilidad. Se separan los tres conceptos del Archivo Maestro:
    #   · monto_adicional_cents  → honorario extra que se le cobra al cliente (ya existía)
    #   · costo_real_cents       → lo que nos costó hacerla; genera el costo directo del
    #                              expediente (cost_id) con su cuenta contable
    #   · costo_es_reembolsable  → ese costo se recupera del cliente y no es utilidad
    # Más el cierre real (cuándo y quién) y la autorización del cobro extra, para que un
    # aumento de honorarios nunca sea un cambio sin respaldo.
    if v < 40:
        conn.executescript("""
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS completed_at TEXT;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS completed_by TEXT;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS costo_real_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS costo_account_id INTEGER REFERENCES plan_cuentas(id);
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS costo_es_reembolsable BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS cost_id INTEGER REFERENCES costs(id) ON DELETE SET NULL;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS autorizado_por TEXT;
            ALTER TABLE case_tasks ADD COLUMN IF NOT EXISTS fecha_autorizacion TEXT;
            ALTER TABLE plantillas_tareas ADD COLUMN IF NOT EXISTS costo_estimado_cents INTEGER NOT NULL DEFAULT 0;
            ALTER TABLE plantillas_tareas ADD COLUMN IF NOT EXISTS honorario_sugerido_cents INTEGER NOT NULL DEFAULT 0;
            CREATE INDEX IF NOT EXISTS idx_case_tasks_cost ON case_tasks(cost_id);
            UPDATE case_tasks SET completed_at = created_at WHERE done = 1 AND completed_at IS NULL;
        """)
        _set_schema_version(conn, 40)

    # v41: lo que una planilla le cuesta de verdad al despacho. `amount_cents` es el neto
    # que recibe la persona, pero la salida real de caja incluye lo retenido (ISSS/AFP/renta
    # que el despacho remite) y el aporte patronal. El gasto que llega a Flujo de caja pasa
    # a ser ese costo completo; el neto sigue siendo el de la boleta.
    if v < 41:
        conn.executescript("""
            ALTER TABLE payrolls ADD COLUMN IF NOT EXISTS costo_empresa_cents INTEGER NOT NULL DEFAULT 0;
            UPDATE payrolls SET costo_empresa_cents =
                COALESCE(total_devengado_cents, amount_cents)
                + COALESCE(isss_patronal_cents, 0) + COALESCE(afp_patronal_cents, 0)
            WHERE costo_empresa_cents = 0;
            UPDATE expenses e SET amount_cents = p.costo_empresa_cents
            FROM payrolls p WHERE p.expense_id = e.id AND p.costo_empresa_cents > 0;
        """)
        _set_schema_version(conn, 41)

    # v42: cada gasto fijo apunta a la cuenta contable por la que se paga. Sin esto, lo
    # presupuestado y lo pagado solo se podían comparar como un total del mes: "el alquiler
    # subió $50" era invisible dentro de la suma.
    if v < 42:
        conn.executescript("""
            ALTER TABLE gastos_fijos ADD COLUMN IF NOT EXISTS account_id INTEGER REFERENCES plan_cuentas(id);
            CREATE INDEX IF NOT EXISTS idx_gastos_fijos_account ON gastos_fijos(account_id);
        """)
        _set_schema_version(conn, 42)

    # v43: el número de factura es único. La validación vive en el repositorio, pero dos
    # usuarios facturando al mismo tiempo pueden pasarla: el índice lo cierra de verdad.
    # Si ya hay repetidos de antes, se renumeran con sufijo para poder crear el índice.
    if v < 43:
        conn.executescript("""
            UPDATE invoices i SET invoice_number = i.invoice_number || '-DUP' || i.id
            WHERE EXISTS (
                SELECT 1 FROM invoices j
                WHERE j.invoice_number = i.invoice_number AND j.id < i.id
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_invoices_numero ON invoices(invoice_number);
        """)
        _set_schema_version(conn, 43)


# ── Seeds ─────────────────────────────────────────────────────────────────────

# All permissions in the system — (module, action, label)
ALL_PERMISSIONS: list[tuple[str, str, str]] = [
    ("dashboard",     "ver",      "Ver dashboard"),
    ("clientes",      "ver",      "Ver clientes"),
    ("clientes",      "crear",    "Crear clientes"),
    ("clientes",      "editar",   "Editar clientes"),
    ("clientes",      "eliminar", "Eliminar clientes"),
    ("expedientes",   "ver",      "Ver expedientes"),
    ("expedientes",   "crear",    "Crear expedientes"),
    ("expedientes",   "editar",   "Editar expedientes"),
    ("expedientes",   "eliminar", "Eliminar expedientes"),
    ("tareas",        "ver",      "Ver tareas"),
    ("tareas",        "crear",    "Crear tareas"),
    ("tareas",        "editar",   "Editar tareas"),
    ("tareas",        "eliminar", "Eliminar tareas"),
    ("agenda",        "ver",      "Ver agenda"),
    ("agenda",        "crear",    "Crear sesiones"),
    ("agenda",        "editar",   "Editar sesiones"),
    ("agenda",        "eliminar", "Eliminar sesiones"),
    ("flujo_caja",    "ver",      "Ver flujo de caja"),
    ("flujo_caja",    "crear",    "Registrar ingresos y gastos"),
    ("flujo_caja",    "editar",   "Editar ingresos y gastos"),
    ("flujo_caja",    "eliminar", "Eliminar ingresos y gastos"),
    ("facturas",      "ver",      "Ver facturas"),
    ("facturas",      "crear",    "Crear facturas"),
    ("facturas",      "editar",   "Editar facturas"),
    ("facturas",      "eliminar", "Eliminar facturas"),
    ("nominas",       "ver",      "Ver nóminas"),
    ("nominas",       "crear",    "Crear nóminas"),
    ("nominas",       "editar",   "Editar nóminas"),
    ("nominas",       "eliminar", "Eliminar nóminas"),
    ("catalogo",      "ver",      "Ver catálogo maestro"),
    ("finanzas",      "ver",      "Ver plan de cuentas, personal, gastos fijos y presupuesto"),
    ("finanzas",      "crear",    "Crear cuentas, personal, gastos fijos y metas de presupuesto"),
    ("finanzas",      "editar",   "Editar cuentas, personal, gastos fijos y metas de presupuesto"),
    ("finanzas",      "eliminar", "Eliminar metas de presupuesto"),
    ("pipeline",      "ver",      "Ver pipeline comercial"),
    ("pipeline",      "crear",    "Crear oportunidades"),
    ("pipeline",      "editar",   "Editar y transicionar oportunidades"),
    ("comisiones",    "ver",      "Ver comisiones"),
    ("comisiones",    "editar",   "Configurar originadores, reconocer y revertir comisiones"),
    ("gobierno_catalogo", "ver",      "Ver solicitudes de catálogo"),
    ("gobierno_catalogo", "crear",    "Crear solicitudes de catálogo"),
    ("gobierno_catalogo", "editar",   "Editar solicitudes de catálogo"),
    ("gobierno_catalogo", "aprobar",  "Aprobar, rechazar y activar solicitudes de catálogo"),
    ("usuarios",      "ver",      "Ver usuarios"),
    ("usuarios",      "crear",    "Crear usuarios"),
    ("usuarios",      "editar",   "Editar usuarios"),
    ("usuarios",      "eliminar", "Eliminar usuarios"),
    ("roles",         "ver",      "Ver roles y permisos"),
    ("roles",         "crear",    "Crear roles"),
    ("roles",         "editar",   "Editar roles y permisos"),
    ("roles",         "eliminar", "Eliminar roles"),
    ("configuracion", "ver",      "Ver configuración"),
    ("configuracion", "editar",   "Editar configuración"),
]

_ABOGADO_PERMS = {
    "dashboard.ver",
    "clientes.ver", "clientes.crear", "clientes.editar",
    "expedientes.ver", "expedientes.crear", "expedientes.editar",
    "tareas.ver", "tareas.crear", "tareas.editar",
    "agenda.ver", "agenda.crear", "agenda.editar",
    "flujo_caja.ver", "flujo_caja.crear", "flujo_caja.editar",
    "facturas.ver", "facturas.crear", "facturas.editar",
    "nominas.ver", "nominas.crear", "nominas.editar",
    "catalogo.ver",
    "finanzas.ver", "finanzas.crear", "finanzas.editar",
    "pipeline.ver", "pipeline.crear", "pipeline.editar",
    "comisiones.ver", "comisiones.editar",
    "gobierno_catalogo.ver", "gobierno_catalogo.crear", "gobierno_catalogo.editar",
    "usuarios.ver",
    "configuracion.ver",
}

_ASISTENTE_PERMS = {
    "dashboard.ver",
    "clientes.ver", "clientes.crear", "clientes.editar",
    "expedientes.ver", "expedientes.crear", "expedientes.editar",
    "tareas.ver", "tareas.crear", "tareas.editar",
    "agenda.ver", "agenda.crear", "agenda.editar",
    "facturas.ver",
    "catalogo.ver",
}

_VISUALIZADOR_PERMS = {
    "dashboard.ver",
    "clientes.ver",
    "expedientes.ver",
    "tareas.ver",
    "agenda.ver",
}


def _seed_rbac(conn: PgConnection) -> None:
    ts = now_iso()

    # 1. Upsert all permissions
    for module, action, label in ALL_PERMISSIONS:
        conn.execute(
            "INSERT INTO permissions(module, action, label) VALUES(%s,%s,%s) ON CONFLICT(module, action) DO NOTHING",
            (module, action, label),
        )

    # Fetch permission id map
    perm_rows = conn.execute("SELECT id, module || '.' || action AS key FROM permissions").fetchall()
    perm_id: dict[str, int] = {str(r["key"]): int(r["id"]) for r in perm_rows}

    # 2. Default roles
    default_roles = [
        ("Administrador", "Acceso total al sistema", 1),
        ("Abogado",       "Acceso completo excepto gestión de usuarios y roles", 0),
        ("Asistente",     "Acceso operativo limitado — sin finanzas ni administración", 0),
        ("Visualizador",  "Solo lectura de expedientes y agenda", 0),
    ]
    role_id: dict[str, int] = {}
    for name, desc, is_sys in default_roles:
        existing = conn.execute("SELECT id FROM roles WHERE name=%s", (name,)).fetchone()
        if existing:
            role_id[name] = int(existing["id"])
        else:
            cur = conn.execute(
                "INSERT INTO roles(name, description, is_system, created_at) VALUES(%s,%s,%s,%s)",
                (name, desc, is_sys, ts),
            )
            role_id[name] = cur.lastrowid  # type: ignore[assignment]

    # 3. Assign permissions to roles
    all_perm_keys = {f"{m}.{a}" for m, a, _ in ALL_PERMISSIONS}
    role_perms: dict[str, set[str]] = {
        "Administrador": all_perm_keys,
        "Abogado":       _ABOGADO_PERMS,
        "Asistente":     _ASISTENTE_PERMS,
        "Visualizador":  _VISUALIZADOR_PERMS,
    }
    for rname, perms in role_perms.items():
        rid = role_id[rname]
        for pkey in perms:
            pid = perm_id.get(pkey)
            if pid:
                conn.execute(
                    "INSERT INTO role_permissions(role_id, permission_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (rid, pid),
                )

    # 4. Assign Administrador role to admin user (only if role_id is NULL)
    admin_role_id = role_id["Administrador"]
    conn.execute(
        "UPDATE users SET role_id=%s WHERE username='admin' AND (role_id IS NULL OR role_id != %s)",
        (admin_role_id, admin_role_id),
    )

def _seed_default_categories(conn: PgConnection) -> None:
    for name in ["Honorarios", "Servicios", "Otro"]:
        conn.execute(
            "INSERT INTO categories(kind, name, created_at) VALUES(%s,%s,%s) ON CONFLICT(kind, name) DO NOTHING",
            ("income", name, now_iso()),
        )
    for name in ["Alimentos", "Transporte", "Servicios", "Oficina", "Impuestos", "Otro"]:
        conn.execute(
            "INSERT INTO categories(kind, name, created_at) VALUES(%s,%s,%s) ON CONFLICT(kind, name) DO NOTHING",
            ("expense", name, now_iso()),
        )


def _seed_service_categories(conn: PgConnection) -> None:
    for name in [
        "Servicios Notariales", "Bienes Raíces e Inversiones",
        "Derecho Corporativo y Empresarial", "Derecho de Familia",
        "Representación en Juicios", "Derecho Administrativo",
        "Migratorio", "Otro",
    ]:
        conn.execute(
            "INSERT INTO categories(kind, name, created_at) VALUES(%s,%s,%s) ON CONFLICT(kind, name) DO NOTHING",
            ("service", name, now_iso()),
        )


def _seed_default_service_products(conn: PgConnection) -> None:
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
                "INSERT INTO service_products(category_id, name, description, base_price_cents, active, created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(category_id, name) DO NOTHING",
                (category_id, product, "", None, 1, now_iso()),
            )


# ── Backwards-compat alias ────────────────────────────────────────────────────

def with_db(fn):
    def wrapper(*args, **kwargs):
        conn = connect()
        try:
            init_db(conn)
            return fn(conn, *args, **kwargs)
        finally:
            conn.close()
    return wrapper

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable
from pathlib import Path
import os
import re
import shutil
import uuid

from psycopg2.extras import Json

from .db import now_iso
from .security import hash_password, verify_password


SESSION_STATUSES = ["Pendiente", "En proceso", "Finalizada"]
ATTACH_ENTITY_TYPES = ["session", "income", "expense", "case", "client", "cost", "user"]
CASE_STATUSES = ["Abierto", "En trámite", "En pausa", "Cerrado"]
CASE_PRIORITIES = ["Baja", "Media", "Alta"]
# Ciclo de facturación/cobro del expediente — independiente de `status` (progreso legal).
ESTADOS_COBRO = ["En ejecución", "Finalizado pendiente de facturar", "Facturado pendiente de cobro", "Cobrado", "Suspendido"]
# Probabilidad de cobro por estado [por defecto — el Excel no la define explícitamente],
# usada para ponderar la cartera pendiente en la proyección de cierre de mes (Fase 7).
PROBABILIDAD_COBRO_POR_ESTADO: dict[str, float] = {
    "En ejecución": 0.40,
    "Finalizado pendiente de facturar": 0.70,
    "Facturado pendiente de cobro": 0.90,
    "Cobrado": 1.0,
    "Suspendido": 0.05,
}

# --- Catálogo maestro (categorías / subcategorías / servicios / familias)
CATALOGO_ESTADOS = ["Activo", "Inactivo"]
SERVICIO_ESTADOS = ["Activo", "Inactivo", "En diseño"]
UNIDADES_COBRO = ["Precio fijo", "Por hora", "Por etapa", "Mensual", "Porcentaje", "Por definir"]
RESPONSABLES_SUGERIDOS = ["Socio / Notario", "Abogada asociada", "Manager", "Asistente legal", "Equipo mixto", "Por definir"]
_CATEGORY_CODE_RE = re.compile(r"^[A-Z]{2,4}$")
_SUBCATEGORY_CODE_RE = re.compile(r"^[A-Z]{2,4}$")

# --- Plan de cuentas / personal / gastos fijos / supuestos financieros
PLAN_CUENTAS_TIPOS = ["Ingreso", "Egreso"]
NATURALEZAS_CUENTA = ["Operativo", "Fijo", "Variable", "Directo", "Inversión", "Otros", "Fijo/Variable"]
CENTROS_COSTO = ["Operación jurídica", "Administración", "Comercial", "Tecnología", "Comercial y administración"]
GASTOS_FIJOS_TIPOS = ["Fijo", "Estimado", "Meta"]
_ACCOUNT_CODE_RE = re.compile(r"^(ING|EGR)-[A-Z]{2,4}-\d{3}$")
_MES_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# --- Pipeline comercial (oportunidades, previo al expediente)
OPORTUNIDAD_ESTADOS = ["Prospecto", "Cotizado", "Ganado", "Perdido"]
CANALES_CAPTACION = ["Instagram", "Google", "LinkedIn", "Referido", "Otro"]
ORIGENES_NEGOCIO = ["Andrea", "Alfredo", "Guadalupe", "Referido", "Orgánico", "Otro"]
_OPORTUNIDAD_TRANSICIONES: dict[str, set[str]] = {
    "Prospecto": {"Cotizado", "Ganado", "Perdido"},
    "Cotizado": {"Ganado", "Perdido"},
    "Ganado": set(),
    "Perdido": set(),
}

# --- Comisión multi-originador (Fase 8) — reglas reales de 12_Reglas_Comision
TIPO_ORIGEN_VALUES = ["Cliente nuevo", "Venta cruzada"]
# Tramos mensuales acumulados por persona (solo tipo "Cliente nuevo"; "Venta cruzada" es plano 5%).
COMISION_TRAMO1_CENTS = 100_000   # $1,000.00 — 10%
COMISION_TRAMO2_CENTS = 250_000   # $2,500.00 — 12% entre tramo1 y tramo2
COMISION_TRAMO3_PCT = 0.15        # 15% en adelante
COMISION_VENTA_CRUZADA_PCT = 0.05

# --- Gobierno del catálogo (Fase 10) — reglas reales de 18_Procedimiento_Catalogo
TIPO_SOLICITUD_VALUES = ["Alta", "Cambio", "Baja"]
TIPO_REGISTRO_VALUES = ["Categoria", "Subcategoria", "Servicio", "Familia"]
SOLICITUD_ESTADOS = ["Solicitado", "En revisión", "Aprobado", "Rechazado", "Activo", "Inactivo"]
# GOB-001: el código definitivo es permanente y solo se asigna al aprobar. Antes de eso el código
# propuesto puede editarse libremente (incluso tras un rechazo) sin dejar histórico.
_SOLICITUD_TRANSICIONES: dict[str, set[str]] = {
    "Solicitado": {"En revisión", "Rechazado"},
    "En revisión": {"Aprobado", "Rechazado", "Solicitado"},
    "Rechazado": {"Solicitado"},
    "Aprobado": {"Activo"},
    "Activo": {"Inactivo"},
    "Inactivo": set(),
}
_SOLICITUD_EDITABLE_ESTADOS = {"Solicitado", "En revisión", "Rechazado"}


def _iso_today() -> str:
    return date.today().isoformat()


def _to_cents(amount_text: str) -> int:
    cleaned = (amount_text or "").strip().replace(",", "")
    if not cleaned:
        raise ValueError("Monto requerido")
    value = float(cleaned)
    return int(round(value * 100))


def _from_cents(cents: int) -> str:
    return f"{(cents or 0) / 100:.2f}"


@dataclass
class DashboardSummary:
    total_clients: int
    total_incomes_cents: int
    total_expenses_cents: int
    sessions_this_month: int

    @property
    def balance_cents(self) -> int:
        return self.total_incomes_cents - self.total_expenses_cents


class Repository:
    def __init__(self, conn: Any):
        self.conn = conn

    @staticmethod
    def _normalize_date_range(start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
        s = (start_date or "").strip() or None
        e = (end_date or "").strip() or None
        return s, e

    @staticmethod
    def _date_where(column: str, start_date: str | None, end_date: str | None) -> tuple[str, tuple]:
        s, e = Repository._normalize_date_range(start_date, end_date)
        if s and e:
            return f" WHERE {column} >= %s AND {column} <= %s", (s, e)
        if s:
            return f" WHERE {column} >= %s", (s,)
        if e:
            return f" WHERE {column} <= %s", (e,)
        return "", ()

    # --- Auth
    def authenticate(self, username: str, password: str) -> bool:
        row = self.conn.execute(
            "SELECT password_hash FROM users WHERE username = %s AND COALESCE(active, 1) = 1",
            (username.strip(),),
        ).fetchone()
        if not row:
            return False
        return verify_password(password, row["password_hash"])


    # --- Users / access
    def list_users(self) -> list[Any]:
        return list(
            self.conn.execute(
                "SELECT id, username, full_name, role, active, created_at FROM users ORDER BY username ASC"
            ).fetchall()
        )

    def create_user(
        self,
        *,
        username: str,
        password: str,
        full_name: str = "",
        role: str = "Usuario",
        active: bool = True,
        created_at: str,
    ) -> int:
        username_clean = (username or "").strip()
        if not username_clean:
            raise ValueError("Usuario requerido")
        if not password:
            raise ValueError("Contraseña requerida")
        cur = self.conn.execute(
            "INSERT INTO users(username, password_hash, full_name, role, active, created_at) VALUES(%s,%s,%s,%s,%s,%s)",
            (username_clean, hash_password(password), (full_name or "").strip(), role, 1 if active else 0, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_user(self, user_id: int, *, full_name: str, role: str, active: bool) -> None:
        self.conn.execute(
            "UPDATE users SET full_name=%s, role=%s, active=%s WHERE id=%s",
            ((full_name or "").strip(), role, 1 if active else 0, int(user_id)),
        )
        self.conn.commit()

    def update_user_password(self, user_id: int, password: str) -> None:
        if not password:
            raise ValueError("Contraseña requerida")
        self.conn.execute(
            "UPDATE users SET password_hash=%s WHERE id=%s",
            (hash_password(password), int(user_id)),
        )
        self.conn.commit()

    def delete_user(self, user_id: int) -> None:
        active_count = int(self.conn.execute("SELECT COUNT(1) AS n FROM users WHERE COALESCE(active, 1)=1").fetchone()["n"])
        row = self.conn.execute("SELECT active FROM users WHERE id=%s", (int(user_id),)).fetchone()
        if row and int(row["active"] or 0) == 1 and active_count <= 1:
            raise ValueError("Debe quedar al menos un usuario activo")
        self.conn.execute("DELETE FROM users WHERE id=%s", (int(user_id),))
        self.conn.commit()

    # --- Clients
    def list_clients(self, search: str | None = None) -> list[Any]:
        base = (
            "SELECT c.*, "
            "COUNT(DISTINCT s.id) AS session_count, "
            "COUNT(DISTINCT cs.id) AS case_count "
            "FROM clients c "
            "LEFT JOIN sessions s ON s.client_id = c.id "
            "LEFT JOIN cases cs ON cs.client_id = c.id "
        )
        if search:
            like = f"%{search.strip()}%"
            return list(self.conn.execute(
                base + "WHERE c.name ILIKE %s OR c.phone ILIKE %s OR c.email ILIKE %s "
                "GROUP BY c.id ORDER BY c.id DESC",
                (like, like, like),
            ).fetchall())
        return list(self.conn.execute(base + "GROUP BY c.id ORDER BY c.id DESC").fetchall())

    def list_case_all_attachments(self, case_id: int) -> list[Any]:
        """Return attachments for the case itself plus attachments from its sessions."""
        return list(self.conn.execute(
            "SELECT a.*, "
            "CASE WHEN a.entity_type='session' THEN s.session_date ELSE NULL END AS session_date, "
            "CASE WHEN a.entity_type='session' THEN s.consult_type ELSE NULL END AS session_type "
            "FROM attachments a "
            "LEFT JOIN sessions s ON (a.entity_type='session' AND a.entity_id = s.id) "
            "WHERE (a.entity_type='case' AND a.entity_id=%s) "
            "   OR (a.entity_type='session' AND s.case_id=%s) "
            "ORDER BY a.created_at DESC",
            (int(case_id), int(case_id)),
        ).fetchall())

    def create_client(
        self,
        *,
        name: str,
        client_type: str = "Física",
        id_number: str = "",
        phone: str = "",
        phone2: str = "",
        email: str = "",
        address: str = "",
        notes: str = "",
        created_at: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO clients(name, client_type, id_number, phone, phone2, email, address, notes, created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (name.strip(), client_type, (id_number or "").strip(), (phone or "").strip(), (phone2 or "").strip(),
             (email or "").strip(), (address or "").strip(), (notes or "").strip(), created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_client(
        self,
        client_id: int,
        *,
        name: str,
        client_type: str = "Física",
        id_number: str = "",
        phone: str = "",
        phone2: str = "",
        email: str = "",
        address: str = "",
        notes: str = "",
    ) -> None:
        self.conn.execute(
            "UPDATE clients SET name=%s, client_type=%s, id_number=%s, phone=%s, phone2=%s, "
            "email=%s, address=%s, notes=%s WHERE id=%s",
            (name.strip(), client_type, (id_number or "").strip(), (phone or "").strip(), (phone2 or "").strip(),
             (email or "").strip(), (address or "").strip(), (notes or "").strip(), int(client_id)),
        )
        self.conn.commit()


    def client_history(self, client_id: int) -> list[dict[str, Any]]:
        cid = int(client_id)
        items: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "SELECT id, title, status, opened_at FROM cases WHERE client_id=%s ORDER BY opened_at DESC, id DESC",
            (cid,),
        ).fetchall():
            items.append({"date": row["opened_at"], "type": "Caso", "detail": row["title"], "status": row["status"]})
        for row in self.conn.execute(
            "SELECT id, session_date, consult_type, status FROM sessions WHERE client_id=%s ORDER BY session_date DESC, id DESC",
            (cid,),
        ).fetchall():
            items.append({"date": row["session_date"], "type": "Sesión", "detail": row["consult_type"], "status": row["status"]})
        for row in self.conn.execute(
            "SELECT id, income_date, detail, concept, amount_cents FROM incomes WHERE client_id=%s ORDER BY income_date DESC, id DESC",
            (cid,),
        ).fetchall():
            amount = self.cents_to_text(int(row["amount_cents"] or 0))
            items.append({"date": row["income_date"], "type": "Ingreso", "detail": row["detail"] or row["concept"], "status": f"$ {amount}"})
        return sorted(items, key=lambda item: item["date"] or "", reverse=True)

    def delete_client(self, client_id: int) -> None:
        self.conn.execute("DELETE FROM clients WHERE id = %s", (int(client_id),))
        self.conn.commit()

    # --- Sessions
    def list_sessions(
        self,
        client_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        conditions: list[str] = []
        params: list = []
        if client_id:
            conditions.append("s.client_id=%s")
            params.append(int(client_id))
        if start_date:
            conditions.append("s.session_date>=%s")
            params.append(start_date)
        if end_date:
            conditions.append("s.session_date<=%s")
            params.append(end_date)
        if status:
            conditions.append("s.status=%s")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return list(
            self.conn.execute(
                f"SELECT s.*, c.name AS client_name FROM sessions s "
                f"LEFT JOIN clients c ON c.id=s.client_id {where} "
                f"ORDER BY s.session_date DESC, COALESCE(s.start_time, '99:99') ASC, s.id DESC",
                params,
            ).fetchall()
        )

    def list_sessions_by_case(self, case_id: int) -> list[Any]:
        return list(
            self.conn.execute(
                "SELECT s.*, c.name AS client_name FROM sessions s "
                "LEFT JOIN clients c ON c.id=s.client_id "
                "WHERE s.case_id=%s ORDER BY s.session_date DESC, COALESCE(s.start_time, '99:99') ASC, s.id DESC",
                (int(case_id),),
            ).fetchall()
        )

    def create_session(
        self,
        *,
        client_id: int | None,
        case_id: int | None,
        session_date: str,
        consult_type: str,
        notes: str,
        status: str,
        created_at: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> int:
        if status not in SESSION_STATUSES:
            raise ValueError("Estado inválido")
        if start_time and end_time and end_time <= start_time:
            raise ValueError("La hora de fin debe ser posterior a la hora de inicio")
        cur = self.conn.execute(
            "INSERT INTO sessions(client_id, case_id, session_date, start_time, end_time, consult_type, notes, status, created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                session_date,
                (start_time or "").strip() or None,
                (end_time or "").strip() or None,
                consult_type.strip(),
                notes.strip(),
                status,
                created_at,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_session(
        self,
        session_id: int,
        *,
        case_id: int | None,
        session_date: str,
        consult_type: str,
        notes: str,
        status: str,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> None:
        if status not in SESSION_STATUSES:
            raise ValueError("Estado inválido")
        self.conn.execute(
            "UPDATE sessions SET case_id=%s, session_date=%s, start_time=%s, end_time=%s, consult_type=%s, notes=%s, status=%s WHERE id=%s",
            (
                int(case_id) if case_id else None,
                session_date,
                (start_time or "").strip() or None,
                (end_time or "").strip() or None,
                consult_type.strip(),
                notes.strip(),
                status,
                int(session_id),
            ),
        )
        self.conn.commit()

    def delete_session(self, session_id: int) -> None:
        self.conn.execute("DELETE FROM sessions WHERE id = %s", (int(session_id),))
        self.conn.commit()

    def get_session(self, session_id: int) -> Any | None:
        return self.conn.execute(
            "SELECT s.*, c.name AS client_name "
            "FROM sessions s LEFT JOIN clients c ON c.id=s.client_id "
            "WHERE s.id=%s",
            (int(session_id),),
        ).fetchone()

    def set_session_gcal_event_id(self, session_id: int, event_id: str | None) -> None:
        self.conn.execute(
            "UPDATE sessions SET gcal_event_id=%s WHERE id=%s", (event_id, int(session_id))
        )
        self.conn.commit()

    # --- Google tokens
    def get_google_tokens(self, username: str) -> Any | None:
        return self.conn.execute(
            "SELECT * FROM google_tokens WHERE username=%s", (username,)
        ).fetchone()

    def save_google_tokens(self, username: str, access_token: str, refresh_token: str, expiry_at: str) -> None:
        self.conn.execute(
            "INSERT INTO google_tokens(username, access_token, refresh_token, expiry_at) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(username) DO UPDATE SET access_token=excluded.access_token, "
            "refresh_token=excluded.refresh_token, expiry_at=excluded.expiry_at",
            (username, access_token, refresh_token, expiry_at),
        )
        self.conn.commit()

    def delete_google_tokens(self, username: str) -> None:
        self.conn.execute("DELETE FROM google_tokens WHERE username=%s", (username,))
        self.conn.commit()

    # --- Outlook tokens
    def get_outlook_tokens(self, username: str) -> Any | None:
        return self.conn.execute(
            "SELECT * FROM outlook_tokens WHERE username=%s", (username,)
        ).fetchone()

    def save_outlook_tokens(self, username: str, access_token: str, refresh_token: str, expiry_at: str) -> None:
        self.conn.execute(
            "INSERT INTO outlook_tokens(username, access_token, refresh_token, expiry_at) VALUES(%s,%s,%s,%s) "
            "ON CONFLICT(username) DO UPDATE SET access_token=excluded.access_token, "
            "refresh_token=excluded.refresh_token, expiry_at=excluded.expiry_at",
            (username, access_token, refresh_token, expiry_at),
        )
        self.conn.commit()

    def delete_outlook_tokens(self, username: str) -> None:
        self.conn.execute("DELETE FROM outlook_tokens WHERE username=%s", (username,))
        self.conn.commit()

    def set_session_outlook_event_id(self, session_id: int, event_id: str | None) -> None:
        self.conn.execute(
            "UPDATE sessions SET outlook_event_id=%s WHERE id=%s", (event_id, int(session_id))
        )
        self.conn.commit()

    # --- Incomes
    _INCOME_SELECT = (
        "SELECT i.*, c.name AS client_name, "
        "cs.title AS case_title, "
        "ac.account_code, ac.nombre AS account_nombre, sv.service_code, sv.nombre AS service_nombre "
        "FROM incomes i "
        "LEFT JOIN clients c ON c.id=i.client_id "
        "LEFT JOIN cases cs ON cs.id=i.case_id "
        "LEFT JOIN plan_cuentas ac ON ac.id=i.account_id "
        "LEFT JOIN servicios sv ON sv.id=i.service_id "
    )

    def list_incomes(self) -> list[Any]:
        return list(self.conn.execute(f"{self._INCOME_SELECT} ORDER BY income_date DESC, i.id DESC").fetchall())

    def list_incomes_range(self, *, start_date: str | None, end_date: str | None) -> list[Any]:
        where, params = self._date_where("i.income_date", start_date, end_date)
        sql = f"{self._INCOME_SELECT} {where} ORDER BY i.income_date DESC, i.id DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def create_income(
        self,
        *,
        amount_text: str,
        income_date: str,
        created_at: str,
        client_id: int | None = None,
        case_id: int | None = None,
        detail: str = "",
        concept: str | None = None,
        invoice_id: int | None = None,
        account_id: int | None = None,
        service_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> int:
        amount_cents = _to_cents(amount_text)
        resolved_detail = (detail or concept or "").strip()
        resolved_concept = resolved_detail or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Ingreso")
        if service_id is not None:
            self.get_servicio(service_id)
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        cur = self.conn.execute(
            "INSERT INTO incomes(client_id, case_id, concept, amount_cents, income_date, created_at, detail, "
            "invoice_id, account_id, service_id, monto_iva_cents, monto_reembolsable_cents) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                resolved_concept,
                amount_cents,
                income_date,
                created_at,
                resolved_detail,
                int(invoice_id) if invoice_id else None,
                int(account_id) if account_id else None,
                int(service_id) if service_id else None,
                iva_cents,
                reembolsable_cents,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_income(self, income_id: int) -> Any | None:
        return self.conn.execute(f"{self._INCOME_SELECT} WHERE i.id=%s", (int(income_id),)).fetchone()

    def update_income(
        self,
        income_id: int,
        *,
        amount_text: str,
        income_date: str,
        client_id: int | None = None,
        case_id: int | None = None,
        detail: str = "",
        account_id: int | None = None,
        service_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> None:
        amount_cents = _to_cents(amount_text)
        resolved_detail = (detail or "").strip()
        resolved_concept = resolved_detail or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Ingreso")
        if service_id is not None:
            self.get_servicio(service_id)
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        self.conn.execute(
            "UPDATE incomes SET amount_cents=%s, income_date=%s, client_id=%s, "
            "case_id=%s, detail=%s, concept=%s, account_id=%s, service_id=%s, monto_iva_cents=%s, monto_reembolsable_cents=%s "
            "WHERE id=%s",
            (
                amount_cents,
                income_date,
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                resolved_detail,
                resolved_concept,
                int(account_id) if account_id else None,
                int(service_id) if service_id else None,
                iva_cents,
                reembolsable_cents,
                int(income_id),
            ),
        )
        self.conn.commit()

    def delete_income(self, income_id: int) -> None:
        self.conn.execute("DELETE FROM incomes WHERE id = %s", (int(income_id),))
        self.conn.commit()

    # --- Expenses
    _EXPENSE_SELECT = (
        "SELECT e.*, ac.account_code, ac.nombre AS account_nombre "
        "FROM expenses e "
        "LEFT JOIN plan_cuentas ac ON ac.id=e.account_id "
    )

    def list_expenses(self) -> list[Any]:
        return list(self.conn.execute(f"{self._EXPENSE_SELECT} ORDER BY expense_date DESC, e.id DESC").fetchall())

    def list_expenses_range(self, *, start_date: str | None, end_date: str | None) -> list[Any]:
        where, params = self._date_where("e.expense_date", start_date, end_date)
        sql = f"{self._EXPENSE_SELECT} {where} ORDER BY e.expense_date DESC, e.id DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def create_expense(
        self,
        *,
        detail: str,
        amount_text: str,
        expense_date: str,
        notes: str,
        created_at: str,
        account_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> int:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Egreso")
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        cur = self.conn.execute(
            "INSERT INTO expenses(concept, amount_cents, expense_date, notes, created_at, detail, "
            "account_id, monto_iva_cents, monto_reembolsable_cents) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                concept,
                amount_cents,
                expense_date,
                notes.strip(),
                created_at,
                (detail or "").strip(),
                int(account_id) if account_id else None,
                iva_cents,
                reembolsable_cents,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_expense(self, expense_id: int) -> Any | None:
        return self.conn.execute(f"{self._EXPENSE_SELECT} WHERE e.id=%s", (int(expense_id),)).fetchone()

    def update_expense(
        self,
        expense_id: int,
        *,
        detail: str,
        amount_text: str,
        expense_date: str,
        notes: str,
        account_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> None:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Egreso")
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        self.conn.execute(
            "UPDATE expenses SET detail=%s, concept=%s, amount_cents=%s, expense_date=%s, notes=%s, "
            "account_id=%s, monto_iva_cents=%s, monto_reembolsable_cents=%s WHERE id=%s",
            (
                (detail or "").strip(),
                concept,
                amount_cents,
                expense_date,
                (notes or "").strip(),
                int(account_id) if account_id else None,
                iva_cents,
                reembolsable_cents,
                int(expense_id),
            ),
        )
        self.conn.commit()

    def delete_expense(self, expense_id: int) -> None:
        self.conn.execute("DELETE FROM expenses WHERE id = %s", (int(expense_id),))
        self.conn.commit()

    # --- Costs (direct costs tied to what is sold)
    _COST_SELECT = (
        "SELECT co.*, c.name AS client_name, cs.title AS case_title, "
        "ac.account_code, ac.nombre AS account_nombre, sv.service_code, sv.nombre AS service_nombre "
        "FROM costs co "
        "LEFT JOIN clients c ON c.id=co.client_id "
        "LEFT JOIN cases cs ON cs.id=co.case_id "
        "LEFT JOIN plan_cuentas ac ON ac.id=co.account_id "
        "LEFT JOIN servicios sv ON sv.id=co.service_id "
    )

    def list_costs_range(self, *, start_date: str | None, end_date: str | None) -> list[Any]:
        where, params = self._date_where("co.cost_date", start_date, end_date)
        sql = f"{self._COST_SELECT} {where} ORDER BY co.cost_date DESC, co.id DESC"
        return list(self.conn.execute(sql, params).fetchall())

    def create_cost(
        self,
        *,
        client_id: int | None = None,
        case_id: int | None = None,
        detail: str,
        amount_text: str,
        cost_date: str,
        notes: str,
        created_at: str,
        account_id: int | None = None,
        service_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> int:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Egreso")
        if service_id is not None:
            self.get_servicio(service_id)
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        cur = self.conn.execute(
            "INSERT INTO costs(client_id, case_id, concept, detail, amount_cents, cost_date, notes, created_at, "
            "account_id, service_id, monto_iva_cents, monto_reembolsable_cents) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                concept,
                (detail or "").strip(),
                amount_cents,
                cost_date,
                (notes or "").strip(),
                created_at,
                int(account_id) if account_id else None,
                int(service_id) if service_id else None,
                iva_cents,
                reembolsable_cents,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_cost(self, cost_id: int) -> Any | None:
        return self.conn.execute(f"{self._COST_SELECT} WHERE co.id=%s", (int(cost_id),)).fetchone()

    def update_cost(
        self,
        cost_id: int,
        *,
        client_id: int | None = None,
        case_id: int | None = None,
        detail: str,
        amount_text: str,
        cost_date: str,
        notes: str,
        account_id: int | None = None,
        service_id: int | None = None,
        monto_iva_text: str = "",
        monto_reembolsable_text: str = "",
    ) -> None:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self._validate_movement_account(account_id, expected_tipo="Egreso")
        if service_id is not None:
            self.get_servicio(service_id)
        iva_cents = self._to_cents_or_zero(monto_iva_text)
        reembolsable_cents = self._to_cents_or_zero(monto_reembolsable_text)
        if iva_cents + reembolsable_cents > amount_cents:
            raise ValueError("IVA + reembolsable no puede superar el monto bruto")
        self.conn.execute(
            "UPDATE costs SET client_id=%s, case_id=%s, concept=%s, detail=%s, "
            "amount_cents=%s, cost_date=%s, notes=%s, account_id=%s, service_id=%s, monto_iva_cents=%s, monto_reembolsable_cents=%s "
            "WHERE id=%s",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                concept,
                (detail or "").strip(),
                amount_cents,
                cost_date,
                (notes or "").strip(),
                int(account_id) if account_id else None,
                int(service_id) if service_id else None,
                iva_cents,
                reembolsable_cents,
                int(cost_id),
            ),
        )
        self.conn.commit()

    def delete_cost(self, cost_id: int) -> None:
        self.conn.execute("DELETE FROM costs WHERE id=%s", (int(cost_id),))
        self.conn.commit()

    def cost_totals(self, *, start_date: str | None, end_date: str | None) -> int:
        where, params = self._date_where("cost_date", start_date, end_date)
        return int(
            self.conn.execute(
                f"SELECT COALESCE(SUM(amount_cents), 0) AS total FROM costs{where}",
                params,
            ).fetchone()["total"]
        )


    # --- Payroll / nominas
    def list_payrolls(self) -> list[Any]:
        return list(self.conn.execute("SELECT * FROM payrolls ORDER BY payment_date DESC, id DESC").fetchall())

    def create_payroll(
        self,
        *,
        employee_name: str,
        role: str,
        period: str,
        amount_text: str,
        payment_date: str,
        notes: str,
        created_at: str,
    ) -> int:
        employee = (employee_name or "").strip()
        if not employee:
            raise ValueError("Empleado requerido")
        if not period.strip() or not payment_date.strip():
            raise ValueError("Periodo y fecha de pago requeridos")
        # Plan de cuentas tiene una cuenta EGR-PER-XXX por persona (grupo 'Personal'); se busca la
        # que coincide con el nombre del empleado. Si no hay una cuenta que calce, queda sin asignar
        # — no es obligatorio y se puede corregir luego desde Flujo de Caja.
        account = self.conn.execute(
            "SELECT id FROM plan_cuentas WHERE tipo='Egreso' AND grupo='Personal' AND nombre ILIKE %s LIMIT 1",
            (f"%{employee}%",),
        ).fetchone()
        account_id = int(account["id"]) if account else None
        detail = f"Nómina - {employee} - {period.strip()}"
        expense_id = self.create_expense(
            detail=detail,
            amount_text=amount_text,
            expense_date=payment_date,
            notes=notes,
            created_at=created_at,
            account_id=account_id,
        )
        amount_cents = _to_cents(amount_text)
        cur = self.conn.execute(
            "INSERT INTO payrolls(employee_name, role, period, amount_cents, payment_date, notes, expense_id, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (employee, (role or "").strip(), period.strip(), amount_cents, payment_date.strip(), (notes or "").strip(), expense_id, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_payroll(self, payroll_id: int) -> None:
        row = self.conn.execute("SELECT expense_id FROM payrolls WHERE id=%s", (int(payroll_id),)).fetchone()
        self.conn.execute("DELETE FROM payrolls WHERE id=%s", (int(payroll_id),))
        if row and row["expense_id"]:
            self.conn.execute("DELETE FROM expenses WHERE id=%s", (int(row["expense_id"]),))
        self.conn.commit()

    # --- Attachments (stored on disk + metadata in SQLite)
    def list_attachments(self, *, entity_type: str, entity_id: int) -> list[Any]:
        if entity_type not in ATTACH_ENTITY_TYPES:
            raise ValueError("Tipo de adjunto inválido")
        return list(
            self.conn.execute(
                "SELECT * FROM attachments WHERE entity_type=%s AND entity_id=%s ORDER BY id DESC",
                (entity_type, int(entity_id)),
            ).fetchall()
        )

    def add_attachment(
        self,
        *,
        entity_type: str,
        entity_id: int,
        source_path: str,
        stored_path: str,
        original_name: str,
        created_at: str,
    ) -> int:
        if entity_type not in ATTACH_ENTITY_TYPES:
            raise ValueError("Tipo de adjunto inválido")
        if not source_path:
            raise ValueError("Archivo requerido")

        src = Path(source_path)
        if not src.exists():
            raise ValueError("Archivo no existe")

        dst = Path(stored_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        cur = self.conn.execute(
            "INSERT INTO attachments(entity_type, entity_id, original_name, stored_path, created_at) VALUES(%s,%s,%s,%s,%s)",
            (
                entity_type,
                int(entity_id),
                (original_name or src.name),
                str(dst.as_posix()),
                created_at,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_attachment(self, attachment_id: int) -> None:
        row = self.conn.execute(
            "SELECT stored_path FROM attachments WHERE id=%s", (int(attachment_id),)
        ).fetchone()
        self.conn.execute("DELETE FROM attachments WHERE id=%s", (int(attachment_id),))
        self.conn.commit()
        if row and row["stored_path"]:
            try:
                p = Path(str(row["stored_path"]))
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    @staticmethod
    def suggest_attachment_path(entity_type: str, entity_id: int, original_name: str) -> str:
        safe_name = Path(original_name).name
        suffix = Path(safe_name).suffix
        token = uuid.uuid4().hex[:10]
        out = Path("data") / "attachments" / entity_type / str(int(entity_id)) / f"{token}{suffix}"
        return str(out)

    # --- Cases (Expedientes) + Tasks
    def list_cases(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        estado_cobro: str | None = None,
        client_id: int | None = None,
        category_id: int | None = None,
        subcategory_id: int | None = None,
        service_id: int | None = None,
    ) -> list[Any]:
        where = []
        params: list[Any] = []
        if search:
            where.append("(cs.title ILIKE %s OR cs.service_area ILIKE %s OR cl.name ILIKE %s OR sp.name ILIKE %s OR sv.service_code ILIKE %s)")
            like = f"%{search.strip()}%"
            params.extend([like, like, like, like, like])
        if status and status != "Todos":
            where.append("cs.status = %s")
            params.append(status)
        if estado_cobro:
            where.append("cs.estado_cobro = %s")
            params.append(estado_cobro)
        if client_id:
            where.append("cs.client_id = %s")
            params.append(int(client_id))
        if category_id:
            where.append("ct.id = %s")
            params.append(int(category_id))
        if subcategory_id:
            where.append("sc.id = %s")
            params.append(int(subcategory_id))
        if service_id:
            where.append("cs.service_id = %s")
            params.append(int(service_id))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        sql = (
            "SELECT cs.*, cl.name AS client_name, "
            "sv.service_code, sv.nombre AS service_nombre, "
            "sc.id AS subcategory_id, sc.subcategory_code, sc.nombre AS subcategory_nombre, "
            "ct.id AS category_id, ct.category_code, ct.nombre AS category_nombre, "
            "fa.id AS family_id, fa.family_code, fa.nombre AS family_nombre, "
            "(cs.honorarios_contratados_cents - COALESCE("
            "  (SELECT SUM(monto_neto_operativo_cents) FROM incomes WHERE case_id = cs.id), 0"
            ")) AS saldo_pendiente_cents, "
            "COALESCE((SELECT SUM(monto_neto_operativo_cents) FROM costs WHERE case_id = cs.id), 0) AS costos_directos_reales_cents, "
            "(COALESCE(cs.fecha_cierre_real, CURRENT_DATE::text)::date - cs.opened_at::date) AS dias_duracion "
            "FROM cases cs JOIN clients cl ON cl.id=cs.client_id "
            "LEFT JOIN servicios sv ON sv.id = cs.service_id "
            "LEFT JOIN subcategorias sc ON sc.id = sv.subcategory_id "
            "LEFT JOIN categorias ct ON ct.id = sc.category_id "
            "LEFT JOIN familias fa ON fa.category_id = ct.id "
            f"{w} "
            "ORDER BY cs.id DESC"
        )
        return list(self.conn.execute(sql, tuple(params)).fetchall())

    def tiempos_atencion(self, *, category_id: int | None = None, subcategory_id: int | None = None, service_id: int | None = None) -> list[Any]:
        """Días promedio de atención (apertura → cierre real, o a hoy si sigue abierto), por servicio."""
        where, params = [], []
        if category_id:
            where.append("ct.id=%s")
            params.append(int(category_id))
        if subcategory_id:
            where.append("sc.id=%s")
            params.append(int(subcategory_id))
        if service_id:
            where.append("sv.id=%s")
            params.append(int(service_id))
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                f"""SELECT sv.service_code, sv.nombre AS service_nombre, ct.category_code, ct.nombre AS category_nombre,
                           COUNT(*) AS total_casos,
                           COUNT(*) FILTER (WHERE cs.fecha_cierre_real IS NOT NULL) AS casos_cerrados,
                           ROUND(AVG(COALESCE(cs.fecha_cierre_real, CURRENT_DATE::text)::date - cs.opened_at::date), 1) AS dias_promedio
                    FROM cases cs
                    LEFT JOIN servicios sv ON sv.id = cs.service_id
                    LEFT JOIN subcategorias sc ON sc.id = sv.subcategory_id
                    LEFT JOIN categorias ct ON ct.id = sc.category_id
                    {clause}
                    GROUP BY sv.service_code, sv.nombre, ct.category_code, ct.nombre
                    ORDER BY dias_promedio DESC NULLS LAST""",
                tuple(params),
            ).fetchall()
        )

    def _generate_case_ref(self, opened_at: str) -> str:
        parts = opened_at.split("-")
        year, month = parts[0], parts[1]
        prefix = f"EXP-{month}-{year}-"
        row = self.conn.execute(
            "SELECT internal_ref FROM cases WHERE internal_ref LIKE %s ORDER BY internal_ref DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
        if row and row["internal_ref"]:
            try:
                last_num = int(row["internal_ref"].rsplit("-", 1)[-1])
                next_num = last_num + 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1
        return f"{prefix}{next_num:04d}"

    def create_case(
        self,
        *,
        client_id: int,
        service_area: str,
        title: str,
        status: str,
        priority: str,
        opened_at: str,
        notes: str | None = None,
        created_at: str,
        internal_ref: str | None = None,
        official_ref: str | None = None,
        opposing_party: str | None = None,
        court_entity: str | None = None,
        responsible_username: str | None = None,
        service_id: int | None = None,
        honorarios_contratados_text: str = "",
        costos_directos_estimados_text: str = "",
        mes_cobro_esperado: str | None = None,
        estado_cobro: str = "En ejecución",
        fecha_cierre_estimada: str | None = None,
        proxima_accion: str | None = None,
    ) -> int:
        if status not in CASE_STATUSES:
            raise ValueError("Estado de caso inválido")
        if priority not in CASE_PRIORITIES:
            raise ValueError("Prioridad inválida")
        if estado_cobro not in ESTADOS_COBRO:
            raise ValueError("Estado de cobro inválido")
        if service_id is not None:
            self.get_servicio(service_id)
        if mes_cobro_esperado:
            mes_cobro_esperado = self._clean_mes(mes_cobro_esperado, "Mes de cobro esperado")
            if mes_cobro_esperado < opened_at[:7]:
                raise ValueError("El mes de cobro esperado no puede ser anterior a la fecha de apertura")
        if not (internal_ref or "").strip():
            internal_ref = self._generate_case_ref(opened_at)
        honorarios_cents = self._to_cents_or_zero(honorarios_contratados_text)
        costos_cents = self._to_cents_or_zero(costos_directos_estimados_text)
        cur = self.conn.execute(
            "INSERT INTO cases(client_id, service_area, title, status, priority, opened_at, closed_at, notes, created_at, "
            "internal_ref, official_ref, opposing_party, court_entity, responsible_username, "
            "service_id, honorarios_contratados_cents, costos_directos_estimados_cents, mes_cobro_esperado, "
            "estado_cobro, fecha_cierre_estimada, proxima_accion) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                int(client_id),
                service_area.strip(),
                title.strip(),
                status,
                priority,
                opened_at,
                None,
                (notes or "").strip(),
                created_at,
                (internal_ref or "").strip() or None,
                (official_ref or "").strip() or None,
                (opposing_party or "").strip() or None,
                (court_entity or "").strip() or None,
                (responsible_username or "").strip() or None,
                int(service_id) if service_id else None,
                honorarios_cents,
                costos_cents,
                mes_cobro_esperado or None,
                estado_cobro,
                (fecha_cierre_estimada or "").strip() or None,
                (proxima_accion or "").strip() or None,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_case(
        self,
        case_id: int,
        *,
        service_area: str,
        title: str,
        status: str,
        priority: str,
        opened_at: str,
        closed_at: str | None,
        notes: str | None = None,
        internal_ref: str | None = None,
        official_ref: str | None = None,
        opposing_party: str | None = None,
        court_entity: str | None = None,
        responsible_username: str | None = None,
        service_id: int | None = None,
        honorarios_contratados_text: str = "",
        costos_directos_estimados_text: str = "",
        mes_cobro_esperado: str | None = None,
        estado_cobro: str = "En ejecución",
        fecha_cierre_estimada: str | None = None,
        fecha_cierre_real: str | None = None,
        proxima_accion: str | None = None,
    ) -> None:
        if status not in CASE_STATUSES:
            raise ValueError("Estado de caso inválido")
        if priority not in CASE_PRIORITIES:
            raise ValueError("Prioridad inválida")
        if estado_cobro not in ESTADOS_COBRO:
            raise ValueError("Estado de cobro inválido")
        if service_id is not None:
            self.get_servicio(service_id)
        if mes_cobro_esperado:
            mes_cobro_esperado = self._clean_mes(mes_cobro_esperado, "Mes de cobro esperado")

        # Al cerrar el expediente (status='Cerrado') se captura la fecha real de cierre sin
        # intervención manual, si todavía no se había registrado — de ahí sale días de duración.
        fecha_real = (fecha_cierre_real or "").strip() or None
        if status == "Cerrado" and not fecha_real:
            existing = self.conn.execute("SELECT fecha_cierre_real FROM cases WHERE id=%s", (int(case_id),)).fetchone()
            fecha_real = (existing["fecha_cierre_real"] if existing else None) or date.today().isoformat()

        honorarios_cents = self._to_cents_or_zero(honorarios_contratados_text)
        costos_cents = self._to_cents_or_zero(costos_directos_estimados_text)
        self.conn.execute(
            "UPDATE cases SET service_area=%s, title=%s, status=%s, priority=%s, opened_at=%s, closed_at=%s, notes=%s, "
            "internal_ref=%s, official_ref=%s, opposing_party=%s, court_entity=%s, responsible_username=%s, "
            "service_id=%s, honorarios_contratados_cents=%s, costos_directos_estimados_cents=%s, mes_cobro_esperado=%s, "
            "estado_cobro=%s, fecha_cierre_estimada=%s, fecha_cierre_real=%s, proxima_accion=%s "
            "WHERE id=%s",
            (
                service_area.strip(),
                title.strip(),
                status,
                priority,
                opened_at,
                (closed_at or "").strip() or None,
                (notes or "").strip(),
                (internal_ref or "").strip() or None,
                (official_ref or "").strip() or None,
                (opposing_party or "").strip() or None,
                (court_entity or "").strip() or None,
                (responsible_username or "").strip() or None,
                int(service_id) if service_id else None,
                honorarios_cents,
                costos_cents,
                mes_cobro_esperado or None,
                estado_cobro,
                (fecha_cierre_estimada or "").strip() or None,
                fecha_real,
                (proxima_accion or "").strip() or None,
                int(case_id),
            ),
        )
        self.conn.commit()

    def delete_case(self, case_id: int) -> None:
        self.conn.execute("DELETE FROM cases WHERE id=%s", (int(case_id),))
        self.conn.commit()

    def case_choices(self, *, client_id: int | None = None) -> list[tuple[int, str]]:
        if client_id:
            rows = self.conn.execute(
                "SELECT id, title FROM cases WHERE client_id=%s ORDER BY id DESC",
                (int(client_id),),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT id, title FROM cases ORDER BY id DESC").fetchall()
        return [(int(r["id"]), str(r["title"])) for r in rows]

    def list_case_tasks(self, case_id: int) -> list[Any]:
        return list(
            self.conn.execute(
                "SELECT * FROM case_tasks WHERE case_id=%s ORDER BY done ASC, id DESC",
                (int(case_id),),
            ).fetchall()
        )

    def list_all_case_tasks(
        self,
        done: bool | None = None,
        search: str | None = None,
        case_id: int | None = None,
    ) -> list[Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if done is not None:
            conditions.append("ct.done = %s")
            params.append(1 if done else 0)
        if case_id is not None:
            conditions.append("ct.case_id = %s")
            params.append(int(case_id))
        if search:
            conditions.append("(ct.title ILIKE %s OR cs.title ILIKE %s OR cl.name ILIKE %s)")
            like = f"%{search.strip()}%"
            params.extend([like, like, like])
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return list(
            self.conn.execute(
                f"SELECT ct.*, cs.title AS case_title, cs.status AS case_status, "
                f"cs.client_id, cl.name AS client_name "
                f"FROM case_tasks ct "
                f"JOIN cases cs ON cs.id = ct.case_id "
                f"LEFT JOIN clients cl ON cl.id = cs.client_id "
                f"{where} "
                f"ORDER BY ct.done ASC, ct.due_date ASC NULLS LAST, ct.id DESC",
                params,
            ).fetchall()
        )

    def create_case_task(
        self,
        *,
        case_id: int,
        title: str,
        due_date: str | None,
        created_at: str,
        notes: str | None = None,
        responsible_username: str | None = None,
    ) -> int:
        t = (title or "").strip()
        if not t:
            raise ValueError("Título requerido")
        cur = self.conn.execute(
            "INSERT INTO case_tasks(case_id, title, done, due_date, notes, responsible_username, created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                int(case_id), t, 0,
                (due_date or "").strip() or None,
                (notes or "").strip() or None,
                (responsible_username or "").strip() or None,
                created_at,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_case_task_done(self, task_id: int, done: bool, completed_notes: str | None = None) -> None:
        self.conn.execute(
            "UPDATE case_tasks SET done=%s, completed_notes=%s WHERE id=%s",
            (1 if done else 0, (completed_notes or "").strip() or None, int(task_id)),
        )
        self.conn.commit()

    def update_case_task_notes(self, task_id: int, notes: str | None, completed_notes: str | None = None) -> None:
        self.conn.execute(
            "UPDATE case_tasks SET notes=%s, completed_notes=%s WHERE id=%s",
            ((notes or "").strip() or None, (completed_notes or "").strip() or None, int(task_id)),
        )
        self.conn.commit()

    def delete_case_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM case_tasks WHERE id=%s", (int(task_id),))
        self.conn.commit()

    # --- Dashboard helpers

    def upcoming_sessions(self, *, days: int = 7) -> list:
        today = date.today().isoformat()
        until = (date.today() + __import__('datetime').timedelta(days=days)).isoformat()
        return self.conn.execute(
            """SELECT s.id, s.session_date, s.start_time, s.end_time,
                      s.consult_type, s.status, s.notes,
                      cl.name AS client_name, ca.title AS case_title
               FROM sessions s
               LEFT JOIN clients cl ON cl.id = s.client_id
               LEFT JOIN cases ca ON ca.id = s.case_id
               WHERE s.session_date >= %s AND s.session_date <= %s
                 AND s.status != 'Realizada'
               ORDER BY s.session_date, s.start_time NULLS LAST""",
            (today, until),
        ).fetchall()

    def dashboard_alerts(self, *, stale_days: int = 15) -> dict:
        today = date.today().isoformat()
        overdue_rows = self.conn.execute(
            """SELECT ct.id, ct.title, ct.due_date, ct.case_id,
                      ca.title AS case_title, cl.name AS client_name
               FROM case_tasks ct
               JOIN cases ca ON ca.id = ct.case_id
               LEFT JOIN clients cl ON cl.id = ca.client_id
               WHERE ct.done = 0 AND ct.due_date IS NOT NULL AND ct.due_date < %s
               ORDER BY ct.due_date ASC
               LIMIT 20""",
            (today,),
        ).fetchall()
        stale_rows = self.conn.execute(
            """SELECT ca.id, ca.title, ca.status, cl.name AS client_name,
                      MAX(s.session_date) AS last_session
               FROM cases ca
               LEFT JOIN clients cl ON cl.id = ca.client_id
               LEFT JOIN sessions s ON s.case_id = ca.id
               WHERE ca.status NOT IN ('Cerrado')
               GROUP BY ca.id, ca.title, ca.status, cl.name
               HAVING MAX(s.session_date::date) < (CURRENT_DATE - (%s * INTERVAL '1 day'))
                   OR MAX(s.session_date) IS NULL
               ORDER BY last_session ASC NULLS FIRST
               LIMIT 10""",
            (int(stale_days),),
        ).fetchall()

        mes_actual = today[:7]
        overdue_billing_rows = self.conn.execute(
            """
            WITH saldos AS (
                SELECT cs.id, cs.title, cl.name AS client_name, cs.mes_cobro_esperado, cs.estado_cobro,
                       (cs.honorarios_contratados_cents - COALESCE(
                           (SELECT SUM(monto_neto_operativo_cents) FROM incomes WHERE case_id = cs.id), 0
                       )) AS saldo_pendiente_cents
                FROM cases cs LEFT JOIN clients cl ON cl.id = cs.client_id
                WHERE cs.mes_cobro_esperado IS NOT NULL AND cs.mes_cobro_esperado < %s AND cs.estado_cobro <> 'Cobrado'
            )
            SELECT * FROM saldos WHERE saldo_pendiente_cents > 0 ORDER BY mes_cobro_esperado ASC LIMIT 20
            """,
            (mes_actual,),
        ).fetchall()

        desviacion_presupuesto: list[dict] = []
        try:
            proyeccion = self.proyeccion_cierre_mes(mes=mes_actual)
            if proyeccion["meta_ingresos_cents"] > 0 and (proyeccion["cumplimiento_proyectado_pct"] or 0) < 0.85:
                desviacion_presupuesto.append(proyeccion)
        except ValueError:
            pass  # sin metas de presupuesto configuradas para el mes — no hay nada que evaluar

        return {
            "overdue_tasks": [dict(r) for r in overdue_rows],
            "stale_cases": [dict(r) for r in stale_rows],
            "overdue_billing": [dict(r) for r in overdue_billing_rows],
            "budget_deviation": desviacion_presupuesto,
        }

    def global_search(self, q: str, *, limit: int = 8) -> dict:
        like = f"%{q}%"
        clients = self.conn.execute(
            "SELECT id, name, client_type FROM clients WHERE name ILIKE %s ORDER BY name LIMIT %s",
            (like, limit),
        ).fetchall()
        cases = self.conn.execute(
            """SELECT ca.id, ca.title, ca.status, cl.name AS client_name
               FROM cases ca LEFT JOIN clients cl ON cl.id = ca.client_id
               WHERE ca.title ILIKE %s OR ca.internal_ref ILIKE %s OR ca.official_ref ILIKE %s
               ORDER BY ca.id DESC LIMIT %s""",
            (like, like, like, limit),
        ).fetchall()
        sessions = self.conn.execute(
            """SELECT s.id, s.session_date, s.consult_type, s.status, cl.name AS client_name
               FROM sessions s LEFT JOIN clients cl ON cl.id = s.client_id
               WHERE s.consult_type ILIKE %s OR s.notes ILIKE %s OR cl.name ILIKE %s
               ORDER BY s.session_date DESC LIMIT %s""",
            (like, like, like, limit),
        ).fetchall()
        return {
            "clients": [dict(r) for r in clients],
            "cases": [dict(r) for r in cases],
            "sessions": [dict(r) for r in sessions],
        }

    # --- Dashboard
    def dashboard_summary(self) -> DashboardSummary:
        total_clients = int(self.conn.execute("SELECT COUNT(1) AS n FROM clients").fetchone()["n"])
        incomes = int(self.conn.execute("SELECT COALESCE(SUM(amount_cents), 0) AS s FROM incomes").fetchone()["s"])
        expenses = int(self.conn.execute("SELECT COALESCE(SUM(amount_cents), 0) AS s FROM expenses").fetchone()["s"])

        month_prefix = date.today().strftime("%Y-%m-")
        sessions_this_month = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE %s",
                (f"{month_prefix}%",),
            ).fetchone()["n"]
        )
        return DashboardSummary(
            total_clients=total_clients,
            total_incomes_cents=incomes,
            total_expenses_cents=expenses,
            sessions_this_month=sessions_this_month,
        )

    def dashboard_metrics_month(self) -> dict[str, int]:
        """
        Month-to-date metrics using session_date/income_date/expense_date (YYYY-MM-DD text).
        Returns cents for money values.
        """
        month_prefix = date.today().strftime("%Y-%m-")

        clients_attended = int(
            self.conn.execute(
                "SELECT COUNT(DISTINCT client_id) AS n FROM sessions WHERE session_date LIKE %s",
                (f"{month_prefix}%",),
            ).fetchone()["n"]
        )
        sessions_total = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE %s",
                (f"{month_prefix}%",),
            ).fetchone()["n"]
        )
        sessions_finalized = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE %s AND status = %s",
                (f"{month_prefix}%", "Finalizada"),
            ).fetchone()["n"]
        )
        incomes_cents = int(
            self.conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM incomes WHERE income_date LIKE %s",
                (f"{month_prefix}%",),
            ).fetchone()["s"]
        )
        expenses_cents = int(
            self.conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM expenses WHERE expense_date LIKE %s",
                (f"{month_prefix}%",),
            ).fetchone()["s"]
        )
        return {
            "clients_attended": clients_attended,
            "sessions_total": sessions_total,
            "sessions_finalized": sessions_finalized,
            "incomes_cents": incomes_cents,
            "expenses_cents": expenses_cents,
        }

    def cashflow_totals(self, *, start_date: str | None, end_date: str | None) -> tuple[int, int]:
        w_in, p_in = self._date_where("income_date", start_date, end_date)
        incomes = int(
            self.conn.execute(
                f"SELECT COALESCE(SUM(amount_cents), 0) AS s FROM incomes{w_in}", p_in
            ).fetchone()["s"]
        )
        w_ex, p_ex = self._date_where("expense_date", start_date, end_date)
        expenses = int(
            self.conn.execute(
                f"SELECT COALESCE(SUM(amount_cents), 0) AS s FROM expenses{w_ex}", p_ex
            ).fetchone()["s"]
        )
        return incomes, expenses

    def cashflow_monthly(self, *, start_date: str | None, end_date: str | None) -> list[tuple[str, int, int]]:
        """
        Returns list of (YYYY-MM, incomes_cents, expenses_cents) for the range.
        SQLite text dates assumed as YYYY-MM-DD.
        """
        start_iso, end_iso = self._normalize_date_range(start_date, end_date)

        w_in, p_in = self._date_where("income_date", start_iso, end_iso)
        income_rows = self.conn.execute(
            f"""
            SELECT substr(income_date, 1, 7) AS ym, COALESCE(SUM(amount_cents), 0) AS total
            FROM incomes
            {w_in}
            GROUP BY ym
            ORDER BY ym ASC
            """,
            p_in,
        ).fetchall()
        incomes = {str(r["ym"]): int(r["total"] or 0) for r in income_rows}

        w_ex, p_ex = self._date_where("expense_date", start_iso, end_iso)
        expense_rows = self.conn.execute(
            f"""
            SELECT substr(expense_date, 1, 7) AS ym, COALESCE(SUM(amount_cents), 0) AS total
            FROM expenses
            {w_ex}
            GROUP BY ym
            ORDER BY ym ASC
            """,
            p_ex,
        ).fetchall()
        expenses = {str(r["ym"]): int(r["total"] or 0) for r in expense_rows}

        all_months = sorted(set(incomes.keys()) | set(expenses.keys()))
        return [(m, incomes.get(m, 0), expenses.get(m, 0)) for m in all_months]

    def account_totals(self, *, movimiento: str, start_date: str | None, end_date: str | None) -> list[tuple[str, int]]:
        """Totales agrupados por cuenta contable (plan_cuentas) — reemplaza las categorías planas
        heredadas del sistema anterior a la Fase 1, que ya no se alimentan."""
        table_by_movimiento = {"income": ("incomes", "i", "income_date"), "expense": ("expenses", "e", "expense_date"), "cost": ("costs", "co", "cost_date")}
        if movimiento not in table_by_movimiento:
            raise ValueError("Tipo de movimiento inválido")
        table, alias, date_col = table_by_movimiento[movimiento]
        where, params = self._date_where(f"{alias}.{date_col}", start_date, end_date)
        rows = self.conn.execute(
            f"""
            SELECT COALESCE(pc.nombre, '(Sin cuenta)') AS name,
                   COALESCE(SUM({alias}.amount_cents), 0) AS total
            FROM {table} {alias}
            LEFT JOIN plan_cuentas pc ON pc.id={alias}.account_id
            {where}
            GROUP BY name
            ORDER BY total DESC
            """,
            params,
        ).fetchall()
        return [(str(r["name"]), int(r["total"] or 0)) for r in rows]

    def top_clients_by_revenue(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        where, params = self._date_where("i.income_date", start_date, end_date)
        rows = self.conn.execute(
            f"""
            SELECT COALESCE(c.name, '(Sin cliente)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN clients c ON c.id=i.client_id
            {where}
            GROUP BY c.name
            HAVING COALESCE(SUM(i.amount_cents), 0) > 0
            ORDER BY total DESC
            LIMIT %s
            """,
            (*params, int(limit)),
        ).fetchall()
        return [(str(row["name"]), int(row["total"] or 0)) for row in rows]

    def top_services_by_revenue(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        where, params = self._date_where("i.income_date", start_date, end_date)
        service_filter = " AND i.case_id IS NOT NULL" if where else " WHERE i.case_id IS NOT NULL"
        rows = self.conn.execute(
            f"""
            SELECT COALESCE(sv.nombre, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN cases cs ON cs.id=i.case_id
            LEFT JOIN servicios sv ON sv.id=cs.service_id
            {where}{service_filter}
            GROUP BY COALESCE(sv.nombre, cs.service_area, '(Sin servicio)')
            HAVING COALESCE(SUM(i.amount_cents), 0) > 0
            ORDER BY total DESC
            LIMIT %s
            """,
            (*params, int(limit)),
        ).fetchall()
        return [(str(row["name"]), int(row["total"] or 0)) for row in rows]

    def top_expenses_by_account(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        return self.account_totals(movimiento="expense", start_date=start_date, end_date=end_date)[: int(limit)]

    def top_costs_by_account(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        return self.account_totals(movimiento="cost", start_date=start_date, end_date=end_date)[: int(limit)]

    def top_services_by_gross_profit(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int, int, int]]:
        income_where, income_params = self._date_where("i.income_date", start_date, end_date)
        cost_where, cost_params = self._date_where("co.cost_date", start_date, end_date)
        income_rows = self.conn.execute(
            f"""
            SELECT COALESCE(sv.nombre, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN cases cs ON cs.id=i.case_id
            LEFT JOIN servicios sv ON sv.id=cs.service_id
            {income_where}{' AND i.case_id IS NOT NULL' if income_where else ' WHERE i.case_id IS NOT NULL'}
            GROUP BY COALESCE(sv.nombre, cs.service_area, '(Sin servicio)')
            """,
            income_params,
        ).fetchall()
        cost_rows = self.conn.execute(
            f"""
            SELECT COALESCE(sv.nombre, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(co.amount_cents), 0) AS total
            FROM costs co
            LEFT JOIN cases cs ON cs.id=co.case_id
            LEFT JOIN servicios sv ON sv.id=cs.service_id
            {cost_where}{' AND co.case_id IS NOT NULL' if cost_where else ' WHERE co.case_id IS NOT NULL'}
            GROUP BY COALESCE(sv.nombre, cs.service_area, '(Sin servicio)')
            """,
            cost_params,
        ).fetchall()
        incomes = {str(row["name"]): int(row["total"] or 0) for row in income_rows}
        costs = {str(row["name"]): int(row["total"] or 0) for row in cost_rows}
        names = set(incomes) | set(costs)
        rows = [(name, incomes.get(name, 0), costs.get(name, 0), incomes.get(name, 0) - costs.get(name, 0)) for name in names]
        return sorted(rows, key=lambda item: item[3], reverse=True)[: int(limit)]

    def top_clients_by_gross_profit(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int, int, int]]:
        income_where, income_params = self._date_where("i.income_date", start_date, end_date)
        cost_where, cost_params = self._date_where("co.cost_date", start_date, end_date)
        income_rows = self.conn.execute(
            f"""
            SELECT COALESCE(c.name, '(Sin cliente)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN clients c ON c.id=i.client_id
            {income_where}
            GROUP BY name
            """,
            income_params,
        ).fetchall()
        cost_rows = self.conn.execute(
            f"""
            SELECT COALESCE(c.name, '(Sin cliente)') AS name,
                   COALESCE(SUM(co.amount_cents), 0) AS total
            FROM costs co
            LEFT JOIN clients c ON c.id=co.client_id
            {cost_where}
            GROUP BY name
            """,
            cost_params,
        ).fetchall()
        incomes = {str(row["name"]): int(row["total"] or 0) for row in income_rows}
        costs = {str(row["name"]): int(row["total"] or 0) for row in cost_rows}
        names = set(incomes) | set(costs)
        rows = [(name, incomes.get(name, 0), costs.get(name, 0), incomes.get(name, 0) - costs.get(name, 0)) for name in names]
        return sorted(rows, key=lambda item: item[3], reverse=True)[: int(limit)]

    def cashflow_by_client(
        self, *, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        """Aggregate incomes and costs grouped by client, including unassigned rows."""
        income_where, income_params = self._date_where("i.income_date", start_date, end_date)
        cost_where, cost_params = self._date_where("co.cost_date", start_date, end_date)

        income_rows = self.conn.execute(
            f"""
            SELECT i.client_id,
                   COALESCE(c.name, '(Sin cliente)') AS client_name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN clients c ON c.id = i.client_id
            {income_where}
            GROUP BY i.client_id, client_name
            """,
            income_params,
        ).fetchall()
        cost_rows = self.conn.execute(
            f"""
            SELECT co.client_id,
                   COALESCE(c.name, '(Sin cliente)') AS client_name,
                   COALESCE(SUM(co.amount_cents), 0) AS total
            FROM costs co
            LEFT JOIN clients c ON c.id = co.client_id
            {cost_where}
            GROUP BY co.client_id, client_name
            """,
            cost_params,
        ).fetchall()

        # key = (client_id, client_name)
        incomes: dict[tuple, int] = {(r["client_id"], str(r["client_name"])): int(r["total"] or 0) for r in income_rows}
        costs: dict[tuple, int] = {(r["client_id"], str(r["client_name"])): int(r["total"] or 0) for r in cost_rows}
        keys = set(incomes) | set(costs)

        result = []
        for key in keys:
            cid, cname = key
            inc = incomes.get(key, 0)
            cost = costs.get(key, 0)
            balance = inc - cost
            margin_pct = round((balance / inc) * 100, 1) if inc > 0 else 0.0
            result.append({
                "client_id": cid,
                "client_name": cname,
                "income": inc / 100,
                "cost": cost / 100,
                "balance": balance / 100,
                "margin_pct": margin_pct,
            })

        return sorted(result, key=lambda x: x["income"], reverse=True)

    # --- Roles & Permissions

    def list_roles(self) -> list:
        return self.conn.execute(
            """SELECT r.id, r.name, r.description, r.is_system, r.created_at,
                      COUNT(rp.permission_id) AS permission_count
               FROM roles r
               LEFT JOIN role_permissions rp ON rp.role_id = r.id
               GROUP BY r.id ORDER BY r.is_system DESC, r.name"""
        ).fetchall()

    def get_role(self, role_id: int):
        return self.conn.execute(
            "SELECT id, name, description, is_system, created_at FROM roles WHERE id=%s",
            (role_id,),
        ).fetchone()

    def get_role_permissions(self, role_id: int) -> list:
        return self.conn.execute(
            """SELECT p.id, p.module, p.action, p.label
               FROM role_permissions rp
               JOIN permissions p ON p.id = rp.permission_id
               WHERE rp.role_id = %s
               ORDER BY p.module, p.action""",
            (role_id,),
        ).fetchall()

    def list_all_permissions(self) -> list:
        return self.conn.execute(
            "SELECT id, module, action, label FROM permissions ORDER BY module, action"
        ).fetchall()

    def create_role(self, name: str, description: str | None, created_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO roles(name, description, is_system, created_at) VALUES(%s,%s,0,%s)",
            (name, description, created_at),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_role(self, role_id: int, name: str, description: str | None) -> None:
        self.conn.execute(
            "UPDATE roles SET name=%s, description=%s WHERE id=%s AND is_system=0",
            (name, description, role_id),
        )
        self.conn.commit()

    def set_role_permissions(self, role_id: int, permission_ids: list[int]) -> None:
        self.conn.execute("DELETE FROM role_permissions WHERE role_id=%s", (role_id,))
        for pid in permission_ids:
            self.conn.execute(
                "INSERT INTO role_permissions(role_id, permission_id) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (role_id, pid),
            )
        self.conn.commit()

    def delete_role(self, role_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET role_id=NULL WHERE role_id=%s", (role_id,)
        )
        self.conn.execute("DELETE FROM roles WHERE id=%s AND is_system=0", (role_id,))
        self.conn.commit()

    def get_user_permissions(self, username: str) -> set[str]:
        rows = self.conn.execute(
            """SELECT p.module || '.' || p.action AS perm
               FROM users u
               JOIN role_permissions rp ON rp.role_id = u.role_id
               JOIN permissions p ON p.id = rp.permission_id
               WHERE u.username = %s""",
            (username,),
        ).fetchall()
        return {str(r["perm"]) for r in rows}

    def assign_user_role(self, user_id: int, role_id: int | None) -> None:
        self.conn.execute(
            "UPDATE users SET role_id=%s WHERE id=%s", (role_id, user_id)
        )
        self.conn.commit()

    # --- Invoices

    def list_invoices(self, client_id: int | None = None) -> list:
        if client_id is not None:
            return self.conn.execute(
                """SELECT i.*, cl.name AS client_name, ca.title AS case_title,
                          EXISTS(SELECT 1 FROM incomes WHERE invoice_id = i.id) AS has_income
                   FROM invoices i
                   LEFT JOIN clients cl ON cl.id = i.client_id
                   LEFT JOIN cases ca ON ca.id = i.case_id
                   WHERE i.client_id = %s
                   ORDER BY i.id DESC""",
                (client_id,),
            ).fetchall()
        return self.conn.execute(
            """SELECT i.*, cl.name AS client_name, ca.title AS case_title,
                      EXISTS(SELECT 1 FROM incomes WHERE invoice_id = i.id) AS has_income
               FROM invoices i
               LEFT JOIN clients cl ON cl.id = i.client_id
               LEFT JOIN cases ca ON ca.id = i.case_id
               ORDER BY i.id DESC"""
        ).fetchall()

    def get_invoice(self, invoice_id: int):
        return self.conn.execute(
            """SELECT i.*, cl.name AS client_name, ca.title AS case_title,
                      EXISTS(SELECT 1 FROM incomes WHERE invoice_id = i.id) AS has_income
               FROM invoices i
               LEFT JOIN clients cl ON cl.id = i.client_id
               LEFT JOIN cases ca ON ca.id = i.case_id
               WHERE i.id = %s""",
            (invoice_id,),
        ).fetchone()

    def get_invoice_items(self, invoice_id: int) -> list:
        return self.conn.execute(
            "SELECT * FROM invoice_items WHERE invoice_id = %s ORDER BY id",
            (invoice_id,),
        ).fetchall()

    def next_invoice_number(self) -> str:
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM invoices").fetchone()
        n = int(row["cnt"]) + 1
        return f"FAC-{n:04d}"

    def create_invoice(
        self,
        client_id: int,
        case_id: int | None,
        invoice_number: str,
        invoice_date: str,
        due_date: str | None,
        notes: str | None,
        firm_name: str | None,
        firm_phone: str | None,
        firm_email: str | None,
        firm_address: str | None,
        firm_tax_id: str | None,
        items: list[dict],
        created_at: str,
    ) -> int:
        total_cents = sum(
            round(float(it.get("unit_price", 0)) * float(it.get("quantity", 1)) * 100)
            for it in items
        )
        cur = self.conn.execute(
            """INSERT INTO invoices(client_id, case_id, invoice_number, invoice_date, due_date,
               status, notes, firm_name, firm_phone, firm_email, firm_address, firm_tax_id,
               total_cents, created_at)
               VALUES(%s,%s,%s,%s,%s,'Borrador',%s,%s,%s,%s,%s,%s,%s,%s)""",
            (client_id, case_id, invoice_number, invoice_date, due_date, notes,
             firm_name, firm_phone, firm_email, firm_address, firm_tax_id,
             total_cents, created_at),
        )
        invoice_id = cur.lastrowid
        for it in items:
            price_cents = round(float(it.get("unit_price", 0)) * 100)
            self.conn.execute(
                """INSERT INTO invoice_items(invoice_id, description, quantity, unit_price_cents,
                   entity_type, entity_id, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (invoice_id, it["description"], float(it.get("quantity", 1)),
                 price_cents, it.get("entity_type"), it.get("entity_id"), created_at),
            )
        self.conn.commit()
        return invoice_id

    def update_invoice(
        self,
        invoice_id: int,
        invoice_number: str,
        invoice_date: str,
        due_date: str | None,
        status: str,
        notes: str | None,
        firm_name: str | None,
        firm_phone: str | None,
        firm_email: str | None,
        firm_address: str | None,
        firm_tax_id: str | None,
        items: list[dict],
        created_at: str,
    ) -> None:
        total_cents = sum(
            round(float(it.get("unit_price", 0)) * float(it.get("quantity", 1)) * 100)
            for it in items
        )
        self.conn.execute(
            """UPDATE invoices SET invoice_number=%s, invoice_date=%s, due_date=%s, status=%s,
               notes=%s, firm_name=%s, firm_phone=%s, firm_email=%s, firm_address=%s,
               firm_tax_id=%s, total_cents=%s WHERE id=%s""",
            (invoice_number, invoice_date, due_date, status, notes,
             firm_name, firm_phone, firm_email, firm_address, firm_tax_id,
             total_cents, invoice_id),
        )
        self.conn.execute("DELETE FROM invoice_items WHERE invoice_id=%s", (invoice_id,))
        for it in items:
            price_cents = round(float(it.get("unit_price", 0)) * 100)
            self.conn.execute(
                """INSERT INTO invoice_items(invoice_id, description, quantity, unit_price_cents,
                   entity_type, entity_id, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (invoice_id, it["description"], float(it.get("quantity", 1)),
                 price_cents, it.get("entity_type"), it.get("entity_id"), created_at),
            )
        self.conn.commit()

    def update_invoice_status(self, invoice_id: int, status: str) -> None:
        self.conn.execute(
            "UPDATE invoices SET status=%s WHERE id=%s", (status, invoice_id)
        )
        self.conn.commit()

    def auto_income_from_invoice(self, invoice_id: int) -> None:
        existing = self.conn.execute(
            "SELECT id FROM incomes WHERE invoice_id=%s LIMIT 1", (invoice_id,)
        ).fetchone()
        if existing:
            return
        inv = self.get_invoice(invoice_id)
        if not inv or not inv["total_cents"]:
            return
        from aglegal.db import now_iso
        self.conn.execute(
            """INSERT INTO incomes(client_id, concept, amount_cents, income_date, case_id, invoice_id, detail, created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                inv["client_id"],
                f"Factura {inv['invoice_number']}",
                inv["total_cents"],
                inv["invoice_date"],
                inv.get("case_id"),
                invoice_id,
                "Ingreso generado automáticamente desde facturación",
                now_iso(),
            ),
        )
        self.conn.commit()

    def delete_invoice(self, invoice_id: int) -> None:
        self.conn.execute("DELETE FROM invoices WHERE id=%s", (invoice_id,))
        self.conn.commit()

    def get_unbilled_items(self, client_id: int) -> dict:
        sessions = self.conn.execute(
            """SELECT id, session_date, consult_type, notes FROM sessions
               WHERE client_id=%s AND (invoice_id IS NULL)
               ORDER BY session_date DESC""",
            (client_id,),
        ).fetchall()
        tasks = self.conn.execute(
            """SELECT ct.id, ct.title, ct.due_date, ca.title AS case_title, ca.id AS case_id
               FROM case_tasks ct
               JOIN cases ca ON ca.id = ct.case_id
               WHERE ca.client_id=%s AND (ct.invoice_id IS NULL)
               ORDER BY ct.due_date DESC NULLS LAST""",
            (client_id,),
        ).fetchall()
        costs = self.conn.execute(
            """SELECT id, concept, detail, amount_cents, cost_date FROM costs
               WHERE client_id=%s ORDER BY cost_date DESC""",
            (client_id,),
        ).fetchall()
        return {"sessions": sessions, "tasks": tasks, "costs": costs}

    # --- Helpers for UI
    def client_choices(self) -> list[tuple[int, str]]:
        rows = self.conn.execute("SELECT id, name FROM clients ORDER BY name ASC").fetchall()
        return [(int(r["id"]), str(r["name"])) for r in rows]

    @staticmethod
    def cents_to_text(cents: int) -> str:
        return _from_cents(cents)

    # ── Catálogo maestro ─────────────────────────────────────────────────────
    # Categorías → subcategorías → servicios, con códigos permanentes e
    # historial de cambios. Los códigos nunca se exponen para edición: una vez
    # creado un registro, su *_code no vuelve a aparecer en ningún método de
    # actualización — es la única garantía real de inmutabilidad en esta fase.

    @staticmethod
    def _clean_code(code: str, pattern: re.Pattern, label: str) -> str:
        c = (code or "").strip().upper()
        if not pattern.match(c):
            raise ValueError(f"{label} inválido: use 2 a 4 letras mayúsculas, sin espacios ni números")
        return c

    @staticmethod
    def _to_cents_or_zero(amount_text: Any) -> int:
        text = str(amount_text).strip() if amount_text not in (None, "") else ""
        return _to_cents(text) if text else 0

    def _snapshot_history(self, table: str, tipo_registro: str, entity_id: int, usuario_id: int | None, fecha: str) -> None:
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id=%s", (entity_id,)).fetchone()
        if not row:
            return
        # Json() shells out to json.dumps with no Decimal support — columns like
        # servicios.horas_estandar (NUMERIC) come back from psycopg2 as Decimal, which
        # json.dumps can't serialize on its own.
        snapshot = {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dict(row).items()}
        self.conn.execute(
            "INSERT INTO historial_catalogo(tipo_registro, entity_id, version_anterior, usuario_id, fecha_cambio) "
            "VALUES(%s,%s,%s,%s,%s)",
            (tipo_registro, int(entity_id), Json(snapshot), usuario_id, fecha),
        )

    def historial_catalogo(self, *, tipo_registro: str, entity_id: int) -> list[Any]:
        return list(
            self.conn.execute(
                "SELECT * FROM historial_catalogo WHERE tipo_registro=%s AND entity_id=%s ORDER BY fecha_cambio DESC",
                (tipo_registro, int(entity_id)),
            ).fetchall()
        )

    # --- Categorías

    def list_categorias(self, *, estado: str | None = None) -> list[Any]:
        where, params = ("", ())
        if estado:
            where, params = " WHERE estado=%s", (estado,)
        return list(self.conn.execute(f"SELECT * FROM categorias{where} ORDER BY category_code ASC", params).fetchall())

    def get_categoria(self, categoria_id: int) -> Any:
        row = self.conn.execute("SELECT * FROM categorias WHERE id=%s", (int(categoria_id),)).fetchone()
        if not row:
            raise ValueError("Categoría no encontrada")
        return row

    def create_categoria(self, *, category_code: str, nombre: str, created_at: str, usuario_id: int | None = None) -> int:
        code = self._clean_code(category_code, _CATEGORY_CODE_RE, "Código de categoría")
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de categoría requerido")
        if self.conn.execute("SELECT 1 FROM categorias WHERE category_code=%s", (code,)).fetchone():
            raise ValueError(f"El código {code} ya existe y los códigos activos nunca se reutilizan")
        if self.conn.execute("SELECT 1 FROM categorias WHERE lower(nombre)=lower(%s)", (n,)).fetchone():
            raise ValueError("Ya existe una categoría con ese nombre")
        try:
            cur = self.conn.execute(
                "INSERT INTO categorias(category_code, nombre, estado, created_at, updated_at) VALUES(%s,%s,'Activo',%s,%s)",
                (code, n, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"El código {code} ya existe") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_categoria(self, categoria_id: int, *, nombre: str, estado: str, usuario_id: int | None = None) -> None:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de categoría requerido")
        if estado not in CATALOGO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_categoria(categoria_id)  # 404 if missing
        if self.conn.execute(
            "SELECT 1 FROM categorias WHERE lower(nombre)=lower(%s) AND id != %s", (n, int(categoria_id))
        ).fetchone():
            raise ValueError("Ya existe otra categoría con ese nombre")
        fecha = now_iso()
        self._snapshot_history("categorias", "Categoria", categoria_id, usuario_id, fecha)
        self.conn.execute(
            "UPDATE categorias SET nombre=%s, estado=%s, updated_at=%s WHERE id=%s",
            (n, estado, fecha, int(categoria_id)),
        )
        self.conn.commit()

    def categoria_choices(self, *, estado: str | None = "Activo") -> list[tuple[int, str, str]]:
        return [
            (int(r["id"]), str(r["category_code"]), str(r["nombre"]))
            for r in self.list_categorias(estado=estado)
        ]

    # --- Subcategorías

    def list_subcategorias(self, *, category_id: int | None = None, estado: str | None = None) -> list[Any]:
        where, params = [], []
        if category_id:
            where.append("sc.category_id=%s")
            params.append(int(category_id))
        if estado:
            where.append("sc.estado=%s")
            params.append(estado)
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                f"""SELECT sc.*, ct.category_code, ct.nombre AS category_nombre
                    FROM subcategorias sc JOIN categorias ct ON ct.id = sc.category_id
                    {clause} ORDER BY ct.category_code ASC, sc.subcategory_code ASC""",
                tuple(params),
            ).fetchall()
        )

    def get_subcategoria(self, subcategoria_id: int) -> Any:
        row = self.conn.execute(
            """SELECT sc.*, ct.category_code, ct.nombre AS category_nombre
               FROM subcategorias sc JOIN categorias ct ON ct.id = sc.category_id
               WHERE sc.id=%s""",
            (int(subcategoria_id),),
        ).fetchone()
        if not row:
            raise ValueError("Subcategoría no encontrada")
        return row

    def create_subcategoria(self, *, category_id: int, subcategory_code: str, nombre: str, created_at: str, usuario_id: int | None = None) -> int:
        code = self._clean_code(subcategory_code, _SUBCATEGORY_CODE_RE, "Código de subcategoría")
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de subcategoría requerido")
        categoria = self.get_categoria(category_id)
        if categoria["estado"] != "Activo":
            raise ValueError("No se puede agregar una subcategoría a una categoría inactiva")
        if self.conn.execute(
            "SELECT 1 FROM subcategorias WHERE category_id=%s AND subcategory_code=%s", (int(category_id), code)
        ).fetchone():
            raise ValueError(f"El código {code} ya existe dentro de esta categoría")
        try:
            cur = self.conn.execute(
                "INSERT INTO subcategorias(subcategory_code, category_id, nombre, estado, created_at, updated_at) "
                "VALUES(%s,%s,%s,'Activo',%s,%s)",
                (code, int(category_id), n, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"El código {code} ya existe dentro de esta categoría") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_subcategoria(self, subcategoria_id: int, *, nombre: str, estado: str, usuario_id: int | None = None) -> None:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de subcategoría requerido")
        if estado not in CATALOGO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_subcategoria(subcategoria_id)  # 404 if missing
        fecha = now_iso()
        self._snapshot_history("subcategorias", "Subcategoria", subcategoria_id, usuario_id, fecha)
        self.conn.execute(
            "UPDATE subcategorias SET nombre=%s, estado=%s, updated_at=%s WHERE id=%s",
            (n, estado, fecha, int(subcategoria_id)),
        )
        self.conn.commit()

    def subcategoria_choices(self, *, category_id: int | None = None, estado: str | None = "Activo") -> list[tuple[int, str, str]]:
        return [
            (int(r["id"]), str(r["subcategory_code"]), str(r["nombre"]))
            for r in self.list_subcategorias(category_id=category_id, estado=estado)
        ]

    # --- Familias (agrupación comercial — no confundir con subcategoría)

    def list_familias(self) -> list[Any]:
        return list(
            self.conn.execute(
                """SELECT f.*, ct.category_code, ct.nombre AS category_nombre
                   FROM familias f JOIN categorias ct ON ct.id = f.category_id
                   ORDER BY f.family_code ASC"""
            ).fetchall()
        )

    def get_familia(self, familia_id: int) -> Any:
        row = self.conn.execute(
            """SELECT f.*, ct.category_code, ct.nombre AS category_nombre
               FROM familias f JOIN categorias ct ON ct.id = f.category_id
               WHERE f.id=%s""",
            (int(familia_id),),
        ).fetchone()
        if not row:
            raise ValueError("Familia no encontrada")
        return row

    def _next_family_code(self) -> str:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(CAST(substring(family_code FROM '[0-9]+$') AS INTEGER)), 0) AS max_seq "
            "FROM familias WHERE family_code ~ '^FAM-[0-9]+$'"
        ).fetchone()
        return f"FAM-{int(row['max_seq']) + 1:02d}"

    def create_familia(self, *, category_id: int, nombre: str, created_at: str, usuario_id: int | None = None) -> int:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de familia requerido")
        self.get_categoria(category_id)  # 404 if missing
        if self.conn.execute("SELECT 1 FROM familias WHERE category_id=%s", (int(category_id),)).fetchone():
            raise ValueError("Esta categoría ya tiene una familia asignada")
        code = self._next_family_code()
        try:
            cur = self.conn.execute(
                "INSERT INTO familias(family_code, nombre, category_id, created_at, updated_at) VALUES(%s,%s,%s,%s,%s)",
                (code, n, int(category_id), created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError("No se pudo crear la familia — intenta de nuevo") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_familia(self, familia_id: int, *, nombre: str, usuario_id: int | None = None) -> None:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de familia requerido")
        self.get_familia(familia_id)  # 404 if missing
        fecha = now_iso()
        self.conn.execute(
            "UPDATE familias SET nombre=%s, updated_at=%s WHERE id=%s",
            (n, fecha, int(familia_id)),
        )
        self.conn.commit()

    def familia_choices(self) -> list[tuple[int, str, str]]:
        return [(int(r["id"]), str(r["family_code"]), str(r["nombre"])) for r in self.list_familias()]

    # --- Servicios

    def list_servicios(
        self,
        *,
        subcategory_id: int | None = None,
        category_id: int | None = None,
        estado: str | None = None,
        q: str | None = None,
    ) -> list[Any]:
        where, params = [], []
        if subcategory_id:
            where.append("sv.subcategory_id=%s")
            params.append(int(subcategory_id))
        if category_id:
            where.append("sc.category_id=%s")
            params.append(int(category_id))
        if estado:
            where.append("sv.estado=%s")
            params.append(estado)
        if q:
            where.append("(sv.service_code ILIKE %s OR sv.nombre ILIKE %s)")
            like = f"%{q.strip()}%"
            params.extend([like, like])
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                f"""SELECT sv.*, sc.subcategory_code, sc.nombre AS subcategory_nombre, sc.category_id,
                           ct.category_code, ct.nombre AS category_nombre
                    FROM servicios sv
                    JOIN subcategorias sc ON sc.id = sv.subcategory_id
                    JOIN categorias ct ON ct.id = sc.category_id
                    {clause}
                    ORDER BY sv.service_code ASC""",
                tuple(params),
            ).fetchall()
        )

    def get_servicio(self, servicio_id: int) -> Any:
        rows = self.list_servicios()
        row = next((r for r in rows if int(r["id"]) == int(servicio_id)), None)
        if not row:
            raise ValueError("Servicio no encontrado")
        return row

    def _next_service_code(self, subcategory_id: int) -> tuple[str, str, str]:
        """Returns (service_code, category_code, subcategory_code) for a new service in this subcategory."""
        sub = self.get_subcategoria(subcategory_id)
        prefix = f"AGL-{sub['category_code']}-{sub['subcategory_code']}-"
        row = self.conn.execute(
            "SELECT COALESCE(MAX(CAST(substring(service_code FROM '[0-9]+$') AS INTEGER)), 0) AS max_seq "
            "FROM servicios WHERE service_code LIKE %s",
            (prefix + "%",),
        ).fetchone()
        seq = int(row["max_seq"]) + 1
        return f"{prefix}{seq:03d}", sub["category_code"], sub["subcategory_code"]

    def create_servicio(
        self,
        *,
        subcategory_id: int,
        nombre: str,
        etiquetas: str = "",
        unidad_cobro: str = "Por definir",
        responsable_sugerido: str = "Por definir",
        tarifa_referencia_text: str = "",
        costo_referencia_text: str = "",
        horas_estandar: float = 0,
        estado: str = "Activo",
        created_at: str,
        usuario_id: int | None = None,
    ) -> int:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de servicio requerido")
        if unidad_cobro not in UNIDADES_COBRO:
            raise ValueError("Unidad de cobro inválida")
        if responsable_sugerido not in RESPONSABLES_SUGERIDOS:
            raise ValueError("Responsable sugerido inválido")
        if estado not in SERVICIO_ESTADOS:
            raise ValueError("Estado inválido")
        sub = self.get_subcategoria(subcategory_id)
        if sub["estado"] != "Activo":
            raise ValueError("No se puede agregar un servicio a una subcategoría inactiva")
        if self.conn.execute(
            "SELECT 1 FROM servicios WHERE subcategory_id=%s AND lower(nombre)=lower(%s)", (int(subcategory_id), n)
        ).fetchone():
            raise ValueError("Ya existe un servicio con ese nombre en esta subcategoría — no duplicar prestaciones idénticas")

        tarifa_cents = self._to_cents_or_zero(tarifa_referencia_text)
        costo_cents = self._to_cents_or_zero(costo_referencia_text)
        code, _, _ = self._next_service_code(subcategory_id)
        try:
            cur = self.conn.execute(
                """INSERT INTO servicios(
                     service_code, subcategory_id, nombre, etiquetas, unidad_cobro, responsable_sugerido,
                     tarifa_referencia_cents, costo_referencia_cents, horas_estandar, estado, created_at, updated_at
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    code, int(subcategory_id), n, (etiquetas or "").strip(), unidad_cobro, responsable_sugerido,
                    tarifa_cents, costo_cents, float(horas_estandar or 0), estado, created_at, created_at,
                ),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"El código {code} ya existe — intenta de nuevo") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_servicio(
        self,
        servicio_id: int,
        *,
        nombre: str,
        etiquetas: str = "",
        unidad_cobro: str = "Por definir",
        responsable_sugerido: str = "Por definir",
        tarifa_referencia_text: str = "",
        costo_referencia_text: str = "",
        horas_estandar: float = 0,
        estado: str = "Activo",
        usuario_id: int | None = None,
    ) -> None:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de servicio requerido")
        if unidad_cobro not in UNIDADES_COBRO:
            raise ValueError("Unidad de cobro inválida")
        if responsable_sugerido not in RESPONSABLES_SUGERIDOS:
            raise ValueError("Responsable sugerido inválido")
        if estado not in SERVICIO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_servicio(servicio_id)  # 404 if missing

        tarifa_cents = self._to_cents_or_zero(tarifa_referencia_text)
        costo_cents = self._to_cents_or_zero(costo_referencia_text)
        fecha = now_iso()
        self._snapshot_history("servicios", "Servicio", servicio_id, usuario_id, fecha)
        self.conn.execute(
            """UPDATE servicios SET nombre=%s, etiquetas=%s, unidad_cobro=%s, responsable_sugerido=%s,
                 tarifa_referencia_cents=%s, costo_referencia_cents=%s, horas_estandar=%s, estado=%s, updated_at=%s
               WHERE id=%s""",
            (
                n, (etiquetas or "").strip(), unidad_cobro, responsable_sugerido,
                tarifa_cents, costo_cents, float(horas_estandar or 0), estado, fecha, int(servicio_id),
            ),
        )
        self.conn.commit()

    def servicio_choices(self, *, q: str | None = None, estado: str = "Activo", limit: int = 25) -> list[Any]:
        """Typeahead search by código o nombre — usado para seleccionar servicio en expedientes (Fase 4)."""
        where, params = ["sv.estado=%s"], [estado]
        if q:
            where.append("(sv.service_code ILIKE %s OR sv.nombre ILIKE %s)")
            like = f"%{q.strip()}%"
            params.extend([like, like])
        clause = " WHERE " + " AND ".join(where)
        rows = self.conn.execute(
            f"""SELECT sv.id, sv.service_code, sv.nombre, sc.category_id, sv.subcategory_id,
                       ct.category_code, sc.subcategory_code
                FROM servicios sv
                JOIN subcategorias sc ON sc.id = sv.subcategory_id
                JOIN categorias ct ON ct.id = sc.category_id
                {clause}
                ORDER BY sv.service_code ASC LIMIT %s""",
            tuple(params) + (int(limit),),
        ).fetchall()
        return list(rows)

    # ── Plan de cuentas ──────────────────────────────────────────────────────

    @staticmethod
    def _clean_mes(mes: str, label: str = "Mes") -> str:
        m = (mes or "").strip()
        if not _MES_RE.match(m):
            raise ValueError(f"{label} inválido: use formato AAAA-MM (ej. 2026-07)")
        return m

    def list_plan_cuentas(self, *, tipo: str | None = None, estado: str | None = None, naturaleza: str | None = None) -> list[Any]:
        where, params = [], []
        if tipo:
            where.append("pc.tipo=%s")
            params.append(tipo)
        if estado:
            where.append("pc.estado=%s")
            params.append(estado)
        if naturaleza:
            where.append("pc.naturaleza=%s")
            params.append(naturaleza)
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                f"""SELECT pc.*, ct.category_code, ct.nombre AS category_nombre,
                           fa.family_code, fa.nombre AS family_nombre
                    FROM plan_cuentas pc
                    LEFT JOIN categorias ct ON ct.id = pc.category_id
                    LEFT JOIN familias fa ON fa.id = pc.family_id
                    {clause}
                    ORDER BY pc.account_code ASC""",
                tuple(params),
            ).fetchall()
        )

    def get_cuenta(self, cuenta_id: int) -> Any:
        rows = self.list_plan_cuentas()
        row = next((r for r in rows if int(r["id"]) == int(cuenta_id)), None)
        if not row:
            raise ValueError("Cuenta no encontrada")
        return row

    def create_cuenta(
        self,
        *,
        account_code: str,
        tipo: str,
        grupo: str,
        subgrupo: str = "",
        nombre: str,
        naturaleza: str,
        category_id: int | None = None,
        family_id: int | None = None,
        centro_costo: str,
        afecta_utilidad: bool = True,
        regla_de_uso: str = "",
        created_at: str,
    ) -> int:
        code = (account_code or "").strip().upper()
        if not _ACCOUNT_CODE_RE.match(code):
            raise ValueError("Código de cuenta inválido: use ING-XXX-000 o EGR-XXX-000")
        if tipo not in PLAN_CUENTAS_TIPOS:
            raise ValueError("Tipo inválido")
        prefix = "ING" if tipo == "Ingreso" else "EGR"
        if not code.startswith(f"{prefix}-"):
            raise ValueError(f"El código debe empezar con {prefix}- para una cuenta de {tipo.lower()}")
        if naturaleza not in NATURALEZAS_CUENTA:
            raise ValueError("Naturaleza inválida")
        if centro_costo not in CENTROS_COSTO:
            raise ValueError("Centro de costo inválido")
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de cuenta requerido")
        if category_id is not None:
            self.get_categoria(category_id)
        if family_id is not None:
            self.get_familia(family_id)
        if self.conn.execute("SELECT 1 FROM plan_cuentas WHERE account_code=%s", (code,)).fetchone():
            raise ValueError(f"El código {code} ya existe")
        try:
            cur = self.conn.execute(
                """INSERT INTO plan_cuentas(
                     account_code, tipo, grupo, subgrupo, nombre, naturaleza, category_id, family_id,
                     centro_costo, afecta_utilidad, regla_de_uso, created_at, updated_at
                   ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    code, tipo, grupo.strip(), (subgrupo or "").strip(), n, naturaleza,
                    category_id, family_id, centro_costo, bool(afecta_utilidad), (regla_de_uso or "").strip(),
                    created_at, created_at,
                ),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"El código {code} ya existe") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_cuenta(
        self,
        cuenta_id: int,
        *,
        grupo: str,
        subgrupo: str = "",
        nombre: str,
        naturaleza: str,
        category_id: int | None = None,
        family_id: int | None = None,
        centro_costo: str,
        afecta_utilidad: bool = True,
        regla_de_uso: str = "",
        estado: str,
    ) -> None:
        n = (nombre or "").strip()
        if not n:
            raise ValueError("Nombre de cuenta requerido")
        if naturaleza not in NATURALEZAS_CUENTA:
            raise ValueError("Naturaleza inválida")
        if centro_costo not in CENTROS_COSTO:
            raise ValueError("Centro de costo inválido")
        if estado not in CATALOGO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_cuenta(cuenta_id)  # 404 if missing
        if category_id is not None:
            self.get_categoria(category_id)
        if family_id is not None:
            self.get_familia(family_id)
        fecha = now_iso()
        self.conn.execute(
            """UPDATE plan_cuentas SET grupo=%s, subgrupo=%s, nombre=%s, naturaleza=%s, category_id=%s, family_id=%s,
                 centro_costo=%s, afecta_utilidad=%s, regla_de_uso=%s, estado=%s, updated_at=%s
               WHERE id=%s""",
            (
                grupo.strip(), (subgrupo or "").strip(), n, naturaleza, category_id, family_id,
                centro_costo, bool(afecta_utilidad), (regla_de_uso or "").strip(), estado, fecha, int(cuenta_id),
            ),
        )
        self.conn.commit()

    def cuenta_choices(self, *, tipo: str | None = None, estado: str = "Activo") -> list[tuple[int, str, str]]:
        return [(int(r["id"]), str(r["account_code"]), str(r["nombre"])) for r in self.list_plan_cuentas(tipo=tipo, estado=estado)]

    def _validate_movement_account(self, account_id: int | None, *, expected_tipo: str) -> None:
        """Un movimiento con cuenta ING-* debe ser un ingreso; EGR-* debe ser un egreso."""
        if account_id is None:
            return
        cuenta = self.get_cuenta(account_id)
        if cuenta["tipo"] != expected_tipo:
            raise ValueError(f"La cuenta {cuenta['account_code']} es de {cuenta['tipo'].lower()} y no puede usarse en un movimiento de {expected_tipo.lower()}")
        if cuenta["estado"] != "Activo":
            raise ValueError(f"La cuenta {cuenta['account_code']} está inactiva")

    # ── Personal (catálogo de costo de nómina) ──────────────────────────────

    def list_personal(self, *, estado: str | None = None) -> list[Any]:
        where, params = ("", ())
        if estado:
            where, params = " WHERE estado=%s", (estado,)
        return list(self.conn.execute(f"SELECT * FROM personal{where} ORDER BY person_code ASC", params).fetchall())

    def get_persona(self, persona_id: int) -> Any:
        row = self.conn.execute("SELECT * FROM personal WHERE id=%s", (int(persona_id),)).fetchone()
        if not row:
            raise ValueError("Registro de personal no encontrado")
        return row

    def _next_person_code(self) -> str:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(CAST(substring(person_code FROM '[0-9]+$') AS INTEGER)), 0) AS max_seq "
            "FROM personal WHERE person_code ~ '^PER-[0-9]+$'"
        ).fetchone()
        return f"PER-{int(row['max_seq']) + 1:03d}"

    def create_persona(
        self, *, persona: str, cargo: str = "", monto_mensual_text: str = "", mes_inicio: str, mes_fin: str | None = None, created_at: str,
    ) -> int:
        p = (persona or "").strip()
        if not p:
            raise ValueError("Nombre de la persona requerido")
        inicio = self._clean_mes(mes_inicio, "Mes de inicio")
        fin = self._clean_mes(mes_fin, "Mes de fin") if mes_fin else None
        if fin and fin < inicio:
            raise ValueError("El mes de fin no puede ser anterior al mes de inicio")
        monto_cents = self._to_cents_or_zero(monto_mensual_text)
        code = self._next_person_code()
        try:
            cur = self.conn.execute(
                """INSERT INTO personal(person_code, persona, cargo, monto_mensual_cents, mes_inicio, mes_fin, created_at, updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (code, p, (cargo or "").strip(), monto_cents, inicio, fin, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError("No se pudo crear el registro — intenta de nuevo") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_persona(
        self, persona_id: int, *, persona: str, cargo: str = "", monto_mensual_text: str = "", mes_inicio: str, mes_fin: str | None = None, estado: str,
    ) -> None:
        p = (persona or "").strip()
        if not p:
            raise ValueError("Nombre de la persona requerido")
        inicio = self._clean_mes(mes_inicio, "Mes de inicio")
        fin = self._clean_mes(mes_fin, "Mes de fin") if mes_fin else None
        if fin and fin < inicio:
            raise ValueError("El mes de fin no puede ser anterior al mes de inicio")
        if estado not in CATALOGO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_persona(persona_id)  # 404 if missing
        monto_cents = self._to_cents_or_zero(monto_mensual_text)
        fecha = now_iso()
        self.conn.execute(
            """UPDATE personal SET persona=%s, cargo=%s, monto_mensual_cents=%s, mes_inicio=%s, mes_fin=%s, estado=%s, updated_at=%s
               WHERE id=%s""",
            (p, (cargo or "").strip(), monto_cents, inicio, fin, estado, fecha, int(persona_id)),
        )
        self.conn.commit()

    # ── Gastos fijos ─────────────────────────────────────────────────────────

    def list_gastos_fijos(self, *, estado: str | None = None, tipo: str | None = None) -> list[Any]:
        where, params = [], []
        if estado:
            where.append("estado=%s")
            params.append(estado)
        if tipo:
            where.append("tipo=%s")
            params.append(tipo)
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(self.conn.execute(f"SELECT * FROM gastos_fijos{clause} ORDER BY expense_code ASC", tuple(params)).fetchall())

    def get_gasto_fijo(self, gasto_id: int) -> Any:
        row = self.conn.execute("SELECT * FROM gastos_fijos WHERE id=%s", (int(gasto_id),)).fetchone()
        if not row:
            raise ValueError("Gasto fijo no encontrado")
        return row

    def _next_expense_code(self) -> str:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(CAST(substring(expense_code FROM '[0-9]+$') AS INTEGER)), 0) AS max_seq "
            "FROM gastos_fijos WHERE expense_code ~ '^GF-[0-9]+$'"
        ).fetchone()
        return f"GF-{int(row['max_seq']) + 1:03d}"

    def create_gasto_fijo(
        self, *, concepto: str, tipo: str = "Fijo", monto_mensual_text: str = "", mes_inicio: str, mes_fin: str | None = None, created_at: str,
    ) -> int:
        c = (concepto or "").strip()
        if not c:
            raise ValueError("Concepto requerido")
        if tipo not in GASTOS_FIJOS_TIPOS:
            raise ValueError("Tipo de gasto inválido")
        inicio = self._clean_mes(mes_inicio, "Mes de inicio")
        fin = self._clean_mes(mes_fin, "Mes de fin") if mes_fin else None
        if fin and fin < inicio:
            raise ValueError("El mes de fin no puede ser anterior al mes de inicio")
        monto_cents = self._to_cents_or_zero(monto_mensual_text)
        code = self._next_expense_code()
        try:
            cur = self.conn.execute(
                """INSERT INTO gastos_fijos(expense_code, concepto, tipo, monto_mensual_cents, mes_inicio, mes_fin, created_at, updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (code, c, tipo, monto_cents, inicio, fin, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError("No se pudo crear el gasto fijo — intenta de nuevo") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_gasto_fijo(
        self, gasto_id: int, *, concepto: str, tipo: str = "Fijo", monto_mensual_text: str = "", mes_inicio: str, mes_fin: str | None = None, estado: str,
    ) -> None:
        c = (concepto or "").strip()
        if not c:
            raise ValueError("Concepto requerido")
        if tipo not in GASTOS_FIJOS_TIPOS:
            raise ValueError("Tipo de gasto inválido")
        inicio = self._clean_mes(mes_inicio, "Mes de inicio")
        fin = self._clean_mes(mes_fin, "Mes de fin") if mes_fin else None
        if fin and fin < inicio:
            raise ValueError("El mes de fin no puede ser anterior al mes de inicio")
        if estado not in CATALOGO_ESTADOS:
            raise ValueError("Estado inválido")
        self.get_gasto_fijo(gasto_id)  # 404 if missing
        monto_cents = self._to_cents_or_zero(monto_mensual_text)
        fecha = now_iso()
        self.conn.execute(
            """UPDATE gastos_fijos SET concepto=%s, tipo=%s, monto_mensual_cents=%s, mes_inicio=%s, mes_fin=%s, estado=%s, updated_at=%s
               WHERE id=%s""",
            (c, tipo, monto_cents, inicio, fin, estado, fecha, int(gasto_id)),
        )
        self.conn.commit()

    # ── Supuestos financieros ────────────────────────────────────────────────

    def list_supuestos(self) -> list[Any]:
        return list(self.conn.execute("SELECT * FROM supuestos_financieros ORDER BY periodo DESC").fetchall())

    def get_supuestos_activos(self) -> Any | None:
        return self.conn.execute("SELECT * FROM supuestos_financieros ORDER BY periodo DESC LIMIT 1").fetchone()

    @staticmethod
    def _clean_pct(value: float, label: str) -> float:
        v = float(value)
        if v < 0 or v >= 1:
            raise ValueError(f"{label} debe expresarse como fracción entre 0 y 1 (ej. 0.10 para 10%)")
        return v

    def create_supuestos(
        self, *, periodo: str, costo_variable_pct: float, margen_operativo_meta_pct: float, margen_seguridad_pct: float, created_at: str,
    ) -> int:
        p = (periodo or "").strip()
        if not p:
            raise ValueError("Periodo requerido")
        cv = self._clean_pct(costo_variable_pct, "Costo variable")
        mo = self._clean_pct(margen_operativo_meta_pct, "Margen operativo meta")
        ms = float(margen_seguridad_pct)
        if ms < 0:
            raise ValueError("Margen de seguridad no puede ser negativo")
        if self.conn.execute("SELECT 1 FROM supuestos_financieros WHERE periodo=%s", (p,)).fetchone():
            raise ValueError(f"Ya existen supuestos para el periodo {p}")
        try:
            cur = self.conn.execute(
                """INSERT INTO supuestos_financieros(periodo, costo_variable_pct, margen_operativo_meta_pct, margen_seguridad_pct, created_at, updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s)""",
                (p, cv, mo, ms, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"Ya existen supuestos para el periodo {p}") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_supuestos(
        self, supuestos_id: int, *, costo_variable_pct: float, margen_operativo_meta_pct: float, margen_seguridad_pct: float,
    ) -> None:
        cv = self._clean_pct(costo_variable_pct, "Costo variable")
        mo = self._clean_pct(margen_operativo_meta_pct, "Margen operativo meta")
        ms = float(margen_seguridad_pct)
        if ms < 0:
            raise ValueError("Margen de seguridad no puede ser negativo")
        if not self.conn.execute("SELECT 1 FROM supuestos_financieros WHERE id=%s", (int(supuestos_id),)).fetchone():
            raise ValueError("Supuestos no encontrados")
        fecha = now_iso()
        self.conn.execute(
            "UPDATE supuestos_financieros SET costo_variable_pct=%s, margen_operativo_meta_pct=%s, margen_seguridad_pct=%s, updated_at=%s WHERE id=%s",
            (cv, mo, ms, fecha, int(supuestos_id)),
        )
        self.conn.commit()

    # ── Punto de equilibrio (Fase 2 — insumo para el dashboard de la Fase 9) ──

    def calcular_punto_equilibrio(self, *, mes: str) -> dict:
        m = self._clean_mes(mes, "Mes")
        row = self.conn.execute(
            "SELECT COALESCE(SUM(monto_mensual_cents), 0) AS total FROM gastos_fijos "
            "WHERE estado='Activo' AND mes_inicio <= %s AND (mes_fin IS NULL OR mes_fin >= %s)",
            (m, m),
        ).fetchone()
        gastos_fijos_cents = int(row["total"])

        supuestos = self.get_supuestos_activos()
        if not supuestos:
            raise ValueError("No hay supuestos financieros configurados todavía")
        cv = float(supuestos["costo_variable_pct"])
        mo = float(supuestos["margen_operativo_meta_pct"])
        ms = float(supuestos["margen_seguridad_pct"])

        if cv >= 1:
            raise ValueError("Costo variable inválido para el cálculo")
        punto_equilibrio_cents = round(gastos_fijos_cents / (1 - cv))
        meta_segura_cents = round(punto_equilibrio_cents * (1 + ms))
        denom = 1 - cv - mo
        ventas_margen_meta_cents = round(gastos_fijos_cents / denom) if denom > 0 else None

        return {
            "mes": m,
            "gastos_fijos_cents": gastos_fijos_cents,
            "costo_variable_pct": cv,
            "margen_operativo_meta_pct": mo,
            "margen_seguridad_pct": ms,
            "punto_equilibrio_cents": punto_equilibrio_cents,
            "meta_segura_cents": meta_segura_cents,
            "ventas_margen_meta_cents": ventas_margen_meta_cents,
        }

    # ── Presupuesto por familia y proyección de cierre de mes (Fase 7) ──────

    def list_forecast(self, *, mes: str | None = None, family_id: int | None = None) -> list[Any]:
        where, params = [], []
        if mes:
            where.append("f.mes = %s")
            params.append(self._clean_mes(mes, "Mes"))
        if family_id:
            where.append("f.family_id = %s")
            params.append(int(family_id))
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(self.conn.execute(
            f"""SELECT f.*, fa.family_code, fa.nombre AS family_nombre
                FROM forecast f JOIN familias fa ON fa.id = f.family_id
                {clause}
                ORDER BY f.mes ASC, fa.family_code ASC""",
            tuple(params),
        ).fetchall())

    def get_forecast(self, forecast_id: int) -> Any:
        row = self.conn.execute(
            """SELECT f.*, fa.family_code, fa.nombre AS family_nombre
               FROM forecast f JOIN familias fa ON fa.id = f.family_id WHERE f.id=%s""",
            (int(forecast_id),),
        ).fetchone()
        if not row:
            raise ValueError("Meta de presupuesto no encontrada")
        return row

    def create_forecast(
        self, *, family_id: int, mes: str, volumen_meta_text: str, ticket_objetivo_text: str,
        margen_directo_objetivo_pct: float, created_at: str,
    ) -> int:
        m = self._clean_mes(mes, "Mes")
        if not self.conn.execute("SELECT 1 FROM familias WHERE id=%s", (int(family_id),)).fetchone():
            raise ValueError("Familia no encontrada")
        try:
            volumen = int(float(volumen_meta_text or 0))
        except ValueError:
            raise ValueError("Volumen meta inválido") from None
        if volumen < 0:
            raise ValueError("El volumen meta no puede ser negativo")
        ticket_cents = self._to_cents_or_zero(ticket_objetivo_text)
        margen = self._clean_pct(margen_directo_objetivo_pct, "Margen directo objetivo")
        if self.conn.execute("SELECT 1 FROM forecast WHERE family_id=%s AND mes=%s", (int(family_id), m)).fetchone():
            raise ValueError(f"Ya existe una meta para esta familia en {m}")
        try:
            cur = self.conn.execute(
                """INSERT INTO forecast(family_id, mes, volumen_meta, ticket_objetivo_cents, margen_directo_objetivo_pct, created_at, updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                (int(family_id), m, volumen, ticket_cents, margen, created_at, created_at),
            )
        except Exception:
            self.conn.rollback()
            raise ValueError(f"Ya existe una meta para esta familia en {m}") from None
        self.conn.commit()
        return int(cur.lastrowid)

    def update_forecast(
        self, forecast_id: int, *, volumen_meta_text: str, ticket_objetivo_text: str, margen_directo_objetivo_pct: float,
    ) -> None:
        self.get_forecast(forecast_id)
        try:
            volumen = int(float(volumen_meta_text or 0))
        except ValueError:
            raise ValueError("Volumen meta inválido") from None
        if volumen < 0:
            raise ValueError("El volumen meta no puede ser negativo")
        ticket_cents = self._to_cents_or_zero(ticket_objetivo_text)
        margen = self._clean_pct(margen_directo_objetivo_pct, "Margen directo objetivo")
        fecha = now_iso()
        self.conn.execute(
            "UPDATE forecast SET volumen_meta=%s, ticket_objetivo_cents=%s, margen_directo_objetivo_pct=%s, updated_at=%s WHERE id=%s",
            (volumen, ticket_cents, margen, fecha, int(forecast_id)),
        )
        self.conn.commit()

    def delete_forecast(self, forecast_id: int) -> None:
        self.conn.execute("DELETE FROM forecast WHERE id=%s", (int(forecast_id),))
        self.conn.commit()

    def cartera_pendiente_ponderada(self, *, mes: str | None = None) -> dict:
        """Saldo pendiente de cobro por expediente, ponderado por probabilidad de cobro según estado_cobro."""
        m = self._clean_mes(mes, "Mes") if mes else None
        mes_filter = "AND cs.mes_cobro_esperado = %s" if m else ""
        params: list[Any] = [m] if m else []
        rows = self.conn.execute(
            f"""
            WITH saldos AS (
                SELECT cs.id, cs.title, cs.estado_cobro, cs.mes_cobro_esperado,
                       (cs.honorarios_contratados_cents - COALESCE(
                           (SELECT SUM(monto_neto_operativo_cents) FROM incomes WHERE case_id = cs.id), 0
                       )) AS saldo_pendiente_cents
                FROM cases cs
                WHERE 1=1 {mes_filter}
            )
            SELECT * FROM saldos WHERE saldo_pendiente_cents > 0 ORDER BY saldo_pendiente_cents DESC
            """,
            tuple(params),
        ).fetchall()
        total_cents = 0
        ponderado_cents = 0
        detalle = []
        for r in rows:
            prob = PROBABILIDAD_COBRO_POR_ESTADO.get(r["estado_cobro"], 0.5)
            saldo = int(r["saldo_pendiente_cents"])
            pond = round(saldo * prob)
            total_cents += saldo
            ponderado_cents += pond
            detalle.append({**dict(r), "probabilidad_cobro": prob, "saldo_ponderado_cents": pond})
        return {
            "mes": m,
            "total_pendiente_cents": total_cents,
            "total_ponderado_cents": ponderado_cents,
            "casos": detalle,
        }

    def proyeccion_cierre_mes(self, *, mes: str) -> dict:
        """Ingresos ya cobrados en el mes + cartera ponderada con mes_cobro_esperado = mes, vs. meta de presupuesto."""
        m = self._clean_mes(mes, "Mes")
        cobrado_row = self.conn.execute(
            "SELECT COALESCE(SUM(monto_neto_operativo_cents), 0) AS total FROM incomes WHERE income_date LIKE %s",
            (m + "-%",),
        ).fetchone()
        cobrado_cents = int(cobrado_row["total"])

        cartera = self.cartera_pendiente_ponderada(mes=m)
        ponderado_cents = int(cartera["total_ponderado_cents"])

        meta_row = self.conn.execute(
            "SELECT COALESCE(SUM(ingreso_proyectado_cents), 0) AS total FROM forecast WHERE mes=%s",
            (m,),
        ).fetchone()
        meta_cents = int(meta_row["total"])

        proyeccion_cents = cobrado_cents + ponderado_cents
        cumplimiento_pct = (proyeccion_cents / meta_cents) if meta_cents > 0 else None

        return {
            "mes": m,
            "cobrado_mes_cents": cobrado_cents,
            "cartera_ponderada_mes_cents": ponderado_cents,
            "proyeccion_cierre_cents": proyeccion_cents,
            "meta_ingresos_cents": meta_cents,
            "cumplimiento_proyectado_pct": cumplimiento_pct,
        }

    # ── Pipeline comercial (oportunidades) ──────────────────────────────────

    def list_oportunidades(self, *, estado: str | None = None, q: str | None = None) -> list[Any]:
        where, params = [], []
        if estado:
            where.append("op.estado=%s")
            params.append(estado)
        if q:
            where.append("(cl.name ILIKE %s OR op.prospecto_nombre ILIKE %s OR sv.service_code ILIKE %s OR sv.nombre ILIKE %s)")
            like = f"%{q.strip()}%"
            params.extend([like, like, like, like])
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                f"""SELECT op.*, cl.name AS client_name,
                           sv.service_code, sv.nombre AS service_nombre,
                           ca.internal_ref AS case_internal_ref
                    FROM oportunidades op
                    LEFT JOIN clients cl ON cl.id = op.client_id
                    LEFT JOIN servicios sv ON sv.id = op.service_id
                    LEFT JOIN cases ca ON ca.id = op.case_id
                    {clause}
                    ORDER BY op.id DESC""",
                tuple(params),
            ).fetchall()
        )

    def get_oportunidad(self, oportunidad_id: int) -> Any:
        rows = self.list_oportunidades()
        row = next((r for r in rows if int(r["id"]) == int(oportunidad_id)), None)
        if not row:
            raise ValueError("Oportunidad no encontrada")
        return row

    def create_oportunidad(
        self, *, client_id: int | None = None, prospecto_nombre: str = "", prospecto_contacto: str = "",
        service_id: int | None = None, canal_captacion: str, origen_negocio: str, created_at: str,
    ) -> int:
        nombre = (prospecto_nombre or "").strip()
        if not client_id and not nombre:
            raise ValueError("Indica un cliente existente o el nombre del prospecto")
        if canal_captacion not in CANALES_CAPTACION:
            raise ValueError("Canal de captación inválido")
        if origen_negocio not in ORIGENES_NEGOCIO:
            raise ValueError("Origen de negocio inválido")
        if client_id is not None and not self.conn.execute("SELECT 1 FROM clients WHERE id=%s", (int(client_id),)).fetchone():
            raise ValueError("Cliente no encontrado")
        if service_id is not None:
            self.get_servicio(service_id)
        fecha = created_at[:10]
        cur = self.conn.execute(
            """INSERT INTO oportunidades(client_id, prospecto_nombre, prospecto_contacto, service_id, canal_captacion,
                 origen_negocio, estado, fecha_prospecto, created_at, updated_at)
               VALUES(%s,%s,%s,%s,%s,%s,'Prospecto',%s,%s,%s)""",
            (client_id, nombre or None, (prospecto_contacto or "").strip() or None, service_id, canal_captacion, origen_negocio, fecha, created_at, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_oportunidad(
        self, oportunidad_id: int, *, client_id: int | None = None, prospecto_nombre: str = "", prospecto_contacto: str = "",
        service_id: int | None = None, canal_captacion: str, origen_negocio: str,
    ) -> None:
        current = self.get_oportunidad(oportunidad_id)
        if current["estado"] in ("Ganado", "Perdido"):
            raise ValueError("No se puede editar una oportunidad ya cerrada")
        nombre = (prospecto_nombre or "").strip()
        if not client_id and not nombre:
            raise ValueError("Indica un cliente existente o el nombre del prospecto")
        if canal_captacion not in CANALES_CAPTACION:
            raise ValueError("Canal de captación inválido")
        if origen_negocio not in ORIGENES_NEGOCIO:
            raise ValueError("Origen de negocio inválido")
        if client_id is not None and not self.conn.execute("SELECT 1 FROM clients WHERE id=%s", (int(client_id),)).fetchone():
            raise ValueError("Cliente no encontrado")
        if service_id is not None:
            self.get_servicio(service_id)
        fecha = now_iso()
        self.conn.execute(
            """UPDATE oportunidades SET client_id=%s, prospecto_nombre=%s, prospecto_contacto=%s, service_id=%s,
                 canal_captacion=%s, origen_negocio=%s, updated_at=%s WHERE id=%s""",
            (client_id, nombre or None, (prospecto_contacto or "").strip() or None, service_id, canal_captacion, origen_negocio, fecha, int(oportunidad_id)),
        )
        self.conn.commit()

    def transition_oportunidad(
        self, oportunidad_id: int, *, nuevo_estado: str, motivo_perdida: str | None = None, usuario_id: int | None = None,
    ) -> int | None:
        """Avanza el estado de una oportunidad. Si nuevo_estado='Ganado', crea el expediente
        automáticamente (heredando cliente, servicio y origen) y devuelve su id."""
        if nuevo_estado not in OPORTUNIDAD_ESTADOS:
            raise ValueError("Estado inválido")
        current = self.get_oportunidad(oportunidad_id)
        permitidos = _OPORTUNIDAD_TRANSICIONES.get(current["estado"], set())
        if nuevo_estado not in permitidos:
            raise ValueError(f"No se puede pasar de {current['estado']} a {nuevo_estado}")

        fecha = now_iso()
        hoy = fecha[:10]

        if nuevo_estado == "Perdido":
            if not (motivo_perdida or "").strip():
                raise ValueError("El motivo de pérdida es obligatorio")
            self.conn.execute(
                "UPDATE oportunidades SET estado='Perdido', motivo_perdida=%s, fecha_cierre=%s, updated_at=%s WHERE id=%s",
                (motivo_perdida.strip(), hoy, fecha, int(oportunidad_id)),
            )
            self.conn.commit()
            return None

        if nuevo_estado == "Cotizado":
            self.conn.execute(
                "UPDATE oportunidades SET estado='Cotizado', fecha_cotizado=%s, updated_at=%s WHERE id=%s",
                (hoy, fecha, int(oportunidad_id)),
            )
            self.conn.commit()
            return None

        # nuevo_estado == "Ganado" -> crea el expediente automáticamente, sin recapturar datos
        if not current["client_id"]:
            raise ValueError("Para marcar Ganado, la oportunidad debe estar ligada a un cliente registrado (no solo un prospecto)")
        if not current["service_id"]:
            raise ValueError("Para marcar Ganado, selecciona primero el servicio que se va a contratar")

        servicio = self.get_servicio(current["service_id"])
        client_row = self.conn.execute("SELECT name FROM clients WHERE id=%s", (int(current["client_id"]),)).fetchone()
        client_name = client_row["name"] if client_row else "Cliente"

        case_id = self.create_case(
            client_id=int(current["client_id"]),
            service_area=servicio["category_nombre"],
            title=f"{servicio['nombre']} — {client_name}",
            status="Abierto",
            priority="Media",
            opened_at=hoy,
            notes=f"Generado automáticamente desde la oportunidad #{oportunidad_id} (origen: {current['origen_negocio']}, canal: {current['canal_captacion']}).",
            created_at=fecha,
            service_id=int(current["service_id"]),
        )
        self.conn.execute("UPDATE cases SET opportunity_id=%s WHERE id=%s", (int(oportunidad_id), case_id))
        self.conn.execute(
            "UPDATE oportunidades SET estado='Ganado', case_id=%s, fecha_cierre=%s, updated_at=%s WHERE id=%s",
            (case_id, hoy, fecha, int(oportunidad_id)),
        )
        self.conn.commit()
        return case_id

    def conversion_comercial(self) -> dict:
        """Ganados / Cotizados — KPI de conversión comercial (solo cuenta lo que de verdad pasó por Cotizado)."""
        row = self.conn.execute(
            """SELECT
                 COUNT(*) FILTER (WHERE fecha_cotizado IS NOT NULL) AS cotizados,
                 COUNT(*) FILTER (WHERE estado = 'Ganado') AS ganados,
                 COUNT(*) FILTER (WHERE estado = 'Perdido') AS perdidos,
                 COUNT(*) FILTER (WHERE estado = 'Prospecto') AS prospectos
               FROM oportunidades"""
        ).fetchone()
        cotizados = int(row["cotizados"])
        ganados = int(row["ganados"])
        return {
            "prospectos": int(row["prospectos"]),
            "cotizados": cotizados,
            "ganados": ganados,
            "perdidos": int(row["perdidos"]),
            "conversion_pct": round(ganados / cotizados, 4) if cotizados else None,
        }

    # ── Comisión multi-originador (Fase 8) ───────────────────────────────────

    def list_negocio_originadores(self, case_id: int) -> list[Any]:
        return list(self.conn.execute(
            """SELECT no.*, p.person_code, p.persona AS persona_nombre
               FROM negocio_originadores no JOIN personal p ON p.id = no.personal_id
               WHERE no.case_id=%s ORDER BY no.porcentaje_participacion DESC""",
            (int(case_id),),
        ).fetchall())

    def set_negocio_originadores(self, case_id: int, *, originadores: list[dict], created_at: str) -> None:
        """Reemplaza por completo la lista de originadores de un expediente. Vacía = sin comisión configurada."""
        if not self.conn.execute("SELECT 1 FROM cases WHERE id=%s", (int(case_id),)).fetchone():
            raise ValueError("Expediente no encontrado")
        if not originadores:
            self.conn.execute("DELETE FROM negocio_originadores WHERE case_id=%s", (int(case_id),))
            self.conn.commit()
            return
        total = sum(float(o["porcentaje_participacion"]) for o in originadores)
        if abs(total - 100) > 0.01:
            raise ValueError(f"Los porcentajes de participación deben sumar 100% (suman {total:.2f}%)")
        seen: set[int] = set()
        for o in originadores:
            pid = int(o["personal_id"])
            if pid in seen:
                raise ValueError("No se puede repetir la misma persona como originador de un mismo expediente")
            seen.add(pid)
            if o["tipo_origen"] not in TIPO_ORIGEN_VALUES:
                raise ValueError("Tipo de origen inválido")
            if not self.conn.execute("SELECT 1 FROM personal WHERE id=%s", (pid,)).fetchone():
                raise ValueError("Persona no encontrada en el catálogo de personal")
        self.conn.execute("DELETE FROM negocio_originadores WHERE case_id=%s", (int(case_id),))
        for o in originadores:
            self.conn.execute(
                """INSERT INTO negocio_originadores(case_id, personal_id, porcentaje_participacion, tipo_origen, created_at)
                   VALUES(%s,%s,%s,%s,%s)""",
                (int(case_id), int(o["personal_id"]), float(o["porcentaje_participacion"]), o["tipo_origen"], created_at),
            )
        self.conn.commit()

    @staticmethod
    def _formula_comision_tramos(utilidad_cents: int) -> int:
        """Comisión TOTAL acumulada para una utilidad directa mensual dada (tipo 'Cliente nuevo').
        MIN(U,1000)*10% + MAX(MIN(U-1000,1500),0)*12% + MAX(U-2500,0)*15% — regla COM-001/002/003."""
        u = max(0, int(utilidad_cents))
        t1 = min(u, COMISION_TRAMO1_CENTS)
        t2 = max(min(u - COMISION_TRAMO1_CENTS, COMISION_TRAMO2_CENTS - COMISION_TRAMO1_CENTS), 0)
        t3 = max(u - COMISION_TRAMO2_CENTS, 0)
        return round(t1 * 0.10 + t2 * 0.12 + t3 * COMISION_TRAMO3_PCT)

    def _comision_marginal(self, *, personal_id: int, mes: str, tipo_origen: str, utilidad_incremento_cents: int) -> int:
        """Comisión de ESTE cobro = fórmula(acumulado_después) − fórmula(acumulado_antes), acumulado por persona y mes."""
        if tipo_origen == "Venta cruzada":
            return round(utilidad_incremento_cents * COMISION_VENTA_CRUZADA_PCT)
        row = self.conn.execute(
            """SELECT COALESCE(SUM(base_utilidad_directa_cents), 0) AS total FROM comisiones
               WHERE personal_id=%s AND mes_reconocimiento=%s AND tipo_origen='Cliente nuevo' AND ajusta_a_commission_id IS NULL""",
            (int(personal_id), mes),
        ).fetchone()
        u_antes = int(row["total"])
        u_despues = u_antes + utilidad_incremento_cents
        return self._formula_comision_tramos(u_despues) - self._formula_comision_tramos(u_antes)

    def reconocer_comision_income(self, income_id: int, *, created_at: str) -> list[Any]:
        """Punto de entrada: al cobrarse efectivamente un honorario, reconoce la comisión de cada originador
        del expediente. Idempotente — si ya se reconoció para este income_id, devuelve lo existente sin duplicar."""
        income = self.conn.execute("SELECT * FROM incomes WHERE id=%s", (int(income_id),)).fetchone()
        if not income:
            raise ValueError("Ingreso no encontrado")
        existentes = self.list_comisiones(income_id=int(income_id))
        if existentes:
            return existentes
        if not income["case_id"]:
            return []  # solo los cobros ligados a un expediente pueden generar comisión

        originadores = self.list_negocio_originadores(income["case_id"])
        if not originadores:
            return []  # expediente sin originadores configurados — nada que reconocer todavía

        caso = self.conn.execute(
            """SELECT cs.honorarios_contratados_cents,
                      COALESCE((SELECT SUM(monto_neto_operativo_cents) FROM costs WHERE case_id = cs.id), 0) AS costos_directos_reales_cents
               FROM cases cs WHERE cs.id=%s""",
            (income["case_id"],),
        ).fetchone()
        honorarios = int(caso["honorarios_contratados_cents"] or 0)
        costos = int(caso["costos_directos_reales_cents"] or 0)
        # [por defecto] ratio de margen directo del expediente completo, aplicado proporcionalmente a cada cobro
        # — evita depender del orden de llegada de los cobros para atribuir costos directos.
        ratio = 1.0 if honorarios <= 0 else max(0.0, min(1.0, 1 - (costos / honorarios)))
        utilidad_directa_total_cents = round(int(income["monto_neto_operativo_cents"]) * ratio)
        mes = str(income["income_date"])[:7]

        ids: list[int] = []
        for orig in originadores:
            share_cents = round(utilidad_directa_total_cents * float(orig["porcentaje_participacion"]) / 100)
            comision_cents = self._comision_marginal(
                personal_id=orig["personal_id"], mes=mes, tipo_origen=orig["tipo_origen"], utilidad_incremento_cents=share_cents,
            )
            cur = self.conn.execute(
                """INSERT INTO comisiones(income_id, case_id, personal_id, tipo_origen, porcentaje_participacion,
                       base_utilidad_directa_cents, comision_cents, mes_reconocimiento, created_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (int(income_id), income["case_id"], orig["personal_id"], orig["tipo_origen"], orig["porcentaje_participacion"],
                 share_cents, comision_cents, mes, created_at),
            )
            ids.append(int(cur.lastrowid))
        self.conn.commit()
        return [self.get_comision(cid) for cid in ids]

    def get_comision(self, commission_id: int) -> Any:
        row = self.conn.execute(
            """SELECT c.*, p.person_code, p.persona AS persona_nombre, cs.title AS case_title, i.income_date
               FROM comisiones c
               JOIN personal p ON p.id = c.personal_id
               JOIN cases cs ON cs.id = c.case_id
               JOIN incomes i ON i.id = c.income_id
               WHERE c.id=%s""",
            (int(commission_id),),
        ).fetchone()
        if not row:
            raise ValueError("Comisión no encontrada")
        return row

    def list_comisiones(self, *, personal_id: int | None = None, mes: str | None = None, case_id: int | None = None, income_id: int | None = None) -> list[Any]:
        where, params = [], []
        if personal_id:
            where.append("c.personal_id=%s")
            params.append(int(personal_id))
        if mes:
            where.append("c.mes_reconocimiento=%s")
            params.append(self._clean_mes(mes, "Mes"))
        if case_id:
            where.append("c.case_id=%s")
            params.append(int(case_id))
        if income_id:
            where.append("c.income_id=%s")
            params.append(int(income_id))
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(self.conn.execute(
            f"""SELECT c.*, p.person_code, p.persona AS persona_nombre, cs.title AS case_title, i.income_date
                FROM comisiones c
                JOIN personal p ON p.id = c.personal_id
                JOIN cases cs ON cs.id = c.case_id
                JOIN incomes i ON i.id = c.income_id
                {clause}
                ORDER BY c.created_at DESC""",
            tuple(params),
        ).fetchall())

    def revertir_comision(self, commission_id: int, *, created_at: str) -> Any:
        """Reversión trazable: crea un movimiento nuevo negativo referenciando el original — nunca edita el histórico.
        Se reconoce en el mes en curso, no en el mes original (regla del Excel: 'se corrige en el siguiente período')."""
        original = self.get_comision(commission_id)
        if original["ajusta_a_commission_id"] is not None:
            raise ValueError("No se puede revertir un ajuste — revierte la comisión original")
        if self.conn.execute("SELECT 1 FROM comisiones WHERE ajusta_a_commission_id=%s", (int(commission_id),)).fetchone():
            raise ValueError("Esta comisión ya fue revertida")
        mes_ajuste = _iso_today()[:7]
        cur = self.conn.execute(
            """INSERT INTO comisiones(income_id, case_id, personal_id, tipo_origen, porcentaje_participacion,
                   base_utilidad_directa_cents, comision_cents, mes_reconocimiento, ajusta_a_commission_id, created_at)
               VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (original["income_id"], original["case_id"], original["personal_id"], original["tipo_origen"],
             original["porcentaje_participacion"], 0, -int(original["comision_cents"]), mes_ajuste, int(commission_id), created_at),
        )
        self.conn.commit()
        return self.get_comision(int(cur.lastrowid))

    def resumen_comisiones_mes(self, mes: str) -> list[Any]:
        m = self._clean_mes(mes, "Mes")
        return list(self.conn.execute(
            """SELECT p.id AS personal_id, p.person_code, p.persona AS persona_nombre,
                      COALESCE(SUM(c.comision_cents), 0) AS total_comision_cents,
                      COALESCE(SUM(c.base_utilidad_directa_cents) FILTER (WHERE c.ajusta_a_commission_id IS NULL), 0) AS total_utilidad_directa_cents,
                      COUNT(*) FILTER (WHERE c.ajusta_a_commission_id IS NULL) AS movimientos,
                      COUNT(*) FILTER (WHERE c.ajusta_a_commission_id IS NOT NULL) AS ajustes
               FROM personal p
               JOIN comisiones c ON c.personal_id = p.id AND c.mes_reconocimiento = %s
               GROUP BY p.id, p.person_code, p.persona
               ORDER BY total_comision_cents DESC""",
            (m,),
        ).fetchall())

    # ── Rentabilidad por abogado (Fase 9 — dashboard operativo/financiero) ──

    def rentabilidad_por_abogado(self, *, start_date: str | None = None, end_date: str | None = None) -> list[dict]:
        """Utilidad directa (neto operativo cobrado − costo directo neto) agrupada por abogado responsable
        del expediente. Solo cuenta movimientos ligados a un expediente (join interno con cases)."""
        income_where, income_params = self._date_where("i.income_date", start_date, end_date)
        cost_where, cost_params = self._date_where("co.cost_date", start_date, end_date)
        income_rows = self.conn.execute(
            f"""SELECT COALESCE(cs.responsible_username, '(Sin asignar)') AS responsable,
                       COALESCE(SUM(i.monto_neto_operativo_cents), 0) AS total
                FROM incomes i JOIN cases cs ON cs.id = i.case_id
                {income_where}
                GROUP BY responsable""",
            income_params,
        ).fetchall()
        cost_rows = self.conn.execute(
            f"""SELECT COALESCE(cs.responsible_username, '(Sin asignar)') AS responsable,
                       COALESCE(SUM(co.monto_neto_operativo_cents), 0) AS total
                FROM costs co JOIN cases cs ON cs.id = co.case_id
                {cost_where}
                GROUP BY responsable""",
            cost_params,
        ).fetchall()
        ingresos = {str(r["responsable"]): int(r["total"] or 0) for r in income_rows}
        costos = {str(r["responsable"]): int(r["total"] or 0) for r in cost_rows}
        nombres = set(ingresos) | set(costos)
        resultado = []
        for nombre in nombres:
            ing = ingresos.get(nombre, 0)
            cost = costos.get(nombre, 0)
            utilidad = ing - cost
            resultado.append({
                "responsable": nombre,
                "ingresos_cents": ing,
                "costos_cents": cost,
                "utilidad_directa_cents": utilidad,
                "margen_pct": round(utilidad / ing, 4) if ing > 0 else None,
            })
        return sorted(resultado, key=lambda r: r["utilidad_directa_cents"], reverse=True)

    def cumplimiento_por_familia(self, *, mes: str) -> list[dict]:
        """Compara la meta de presupuesto (Fase 7) contra lo realmente cobrado ese mes, por familia —
        mismo espíritu que la hoja 15_Cumplimiento_Metas del Excel."""
        m = self._clean_mes(mes, "Mes")
        metas = self.list_forecast(mes=m)
        reales = self.conn.execute(
            """SELECT fa.id AS family_id,
                      COUNT(DISTINCT i.case_id) AS casos_reales,
                      COALESCE(SUM(i.monto_neto_operativo_cents), 0) AS ingresos_reales_cents
               FROM incomes i
               JOIN cases cs ON cs.id = i.case_id
               JOIN servicios sv ON sv.id = cs.service_id
               JOIN subcategorias sc ON sc.id = sv.subcategory_id
               JOIN categorias ct ON ct.id = sc.category_id
               JOIN familias fa ON fa.category_id = ct.id
               WHERE i.income_date LIKE %s
               GROUP BY fa.id""",
            (m + "-%",),
        ).fetchall()
        reales_map = {int(r["family_id"]): r for r in reales}
        resultado = []
        for meta in metas:
            real = reales_map.get(int(meta["family_id"]))
            casos_reales = int(real["casos_reales"]) if real else 0
            ingresos_reales_cents = int(real["ingresos_reales_cents"]) if real else 0
            volumen_meta = int(meta["volumen_meta"])
            ingreso_proyectado_cents = int(meta["ingreso_proyectado_cents"])
            resultado.append({
                "family_id": meta["family_id"], "family_code": meta["family_code"], "family_nombre": meta["family_nombre"],
                "meta_casos": volumen_meta, "casos_reales": casos_reales,
                "cumplimiento_casos_pct": round(casos_reales / volumen_meta, 4) if volumen_meta else None,
                "meta_ingresos_cents": ingreso_proyectado_cents, "ingresos_reales_cents": ingresos_reales_cents,
                "cumplimiento_ingresos_pct": round(ingresos_reales_cents / ingreso_proyectado_cents, 4) if ingreso_proyectado_cents else None,
            })
        return sorted(resultado, key=lambda r: (r["cumplimiento_ingresos_pct"] if r["cumplimiento_ingresos_pct"] is not None else -1))

    # ── Gobierno del catálogo — solicitudes de alta/cambio (Fase 10) ────────

    def _next_solicitud_code(self, year: str) -> str:
        row = self.conn.execute(
            "SELECT COALESCE(MAX(CAST(substring(solicitud_code FROM '[0-9]+$') AS INTEGER)), 0) AS max_seq "
            "FROM solicitudes_catalogo WHERE solicitud_code ~ %s",
            (f"^SOL-{year}-[0-9]+$",),
        ).fetchone()
        return f"SOL-{year}-{int(row['max_seq']) + 1:03d}"

    def list_solicitudes(self, *, estado: str | None = None, tipo_registro: str | None = None, q: str | None = None) -> list[Any]:
        where, params = [], []
        if estado:
            where.append("estado = %s")
            params.append(estado)
        if tipo_registro:
            where.append("tipo_registro = %s")
            params.append(tipo_registro)
        if q:
            where.append("(nombre_propuesto ILIKE %s OR codigo_propuesto ILIKE %s OR solicitud_code ILIKE %s)")
            like = f"%{q.strip()}%"
            params.extend([like, like, like])
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(self.conn.execute(
            f"SELECT * FROM solicitudes_catalogo{clause} ORDER BY id DESC", tuple(params),
        ).fetchall())

    def get_solicitud(self, solicitud_id: int) -> Any:
        row = self.conn.execute("SELECT * FROM solicitudes_catalogo WHERE id=%s", (int(solicitud_id),)).fetchone()
        if not row:
            raise ValueError("Solicitud no encontrada")
        return row

    def _resolver_entidad_por_tipo(self, tipo_registro: str, entity_id: int) -> Any:
        table = {"Categoria": "categorias", "Subcategoria": "subcategorias", "Servicio": "servicios", "Familia": "familias"}[tipo_registro]
        row = self.conn.execute(f"SELECT * FROM {table} WHERE id=%s", (int(entity_id),)).fetchone()
        if not row:
            raise ValueError(f"El registro #{entity_id} de tipo {tipo_registro} no existe")
        return row

    def create_solicitud(
        self, *, tipo_solicitud: str, tipo_registro: str, nombre_propuesto: str,
        categoria_padre: str | None, subcategoria_padre: str | None, codigo_propuesto: str = "",
        descripcion: str = "", motivo: str = "", etiquetas: str = "", solicitante: str, created_at: str,
        entity_id: int | None = None,
        unidad_cobro_propuesta: str | None = None, responsable_sugerido_propuesto: str | None = None,
        tarifa_referencia_propuesta_text: str = "", costo_referencia_propuesta_text: str = "",
        horas_estandar_propuesta: float | None = None, estado_propuesto: str | None = None,
    ) -> int:
        if tipo_solicitud not in TIPO_SOLICITUD_VALUES:
            raise ValueError("Tipo de solicitud inválido")
        if tipo_registro not in TIPO_REGISTRO_VALUES:
            raise ValueError("Tipo de registro inválido")
        nombre = (nombre_propuesto or "").strip()
        if not nombre:
            raise ValueError("Nombre propuesto requerido")

        if tipo_solicitud == "Alta":
            entity_id = None
            codigo = (codigo_propuesto or "").strip().upper()
            if not codigo:
                raise ValueError("Código propuesto requerido")
            if tipo_registro in ("Subcategoria", "Servicio", "Familia") and not (categoria_padre or "").strip():
                raise ValueError("Categoría padre requerida para este tipo de registro")
            if tipo_registro == "Servicio" and not (subcategoria_padre or "").strip():
                raise ValueError("Subcategoría padre requerida para un servicio")
        else:
            # Cambio / Baja: la solicitud apunta a un registro que ya existe — el código
            # no se reasigna, se toma directo del registro real (nunca del formulario).
            if tipo_solicitud == "Baja" and tipo_registro == "Familia":
                raise ValueError("Las familias no tienen estado activo/inactivo — no se puede dar de baja una familia")
            if entity_id is None:
                raise ValueError("Selecciona el registro existente al que aplica este Cambio/Baja")
            entidad = self._resolver_entidad_por_tipo(tipo_registro, entity_id)
            codigo_col = {"Categoria": "category_code", "Subcategoria": "subcategory_code", "Servicio": "service_code", "Familia": "family_code"}[tipo_registro]
            codigo = str(entidad[codigo_col])

        year = created_at[:4]
        code = self._next_solicitud_code(year)
        tarifa_cents = self._to_cents_or_zero(tarifa_referencia_propuesta_text) if tarifa_referencia_propuesta_text else None
        costo_cents = self._to_cents_or_zero(costo_referencia_propuesta_text) if costo_referencia_propuesta_text else None
        cur = self.conn.execute(
            """INSERT INTO solicitudes_catalogo(
                   solicitud_code, fecha_solicitud, tipo_solicitud, tipo_registro, nombre_propuesto,
                   categoria_padre, subcategoria_padre, codigo_propuesto, descripcion, motivo, etiquetas,
                   solicitante, estado, created_at, updated_at, entity_id,
                   unidad_cobro_propuesta, responsable_sugerido_propuesto,
                   tarifa_referencia_propuesta_cents, costo_referencia_propuesta_cents,
                   horas_estandar_propuesta, estado_propuesto
               ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Solicitado',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (code, created_at[:10], tipo_solicitud, tipo_registro, nombre,
             (categoria_padre or "").strip() or None, (subcategoria_padre or "").strip() or None, codigo,
             (descripcion or "").strip(), (motivo or "").strip(), (etiquetas or "").strip(),
             solicitante, created_at, created_at, entity_id,
             (unidad_cobro_propuesta or "").strip() or None, (responsable_sugerido_propuesto or "").strip() or None,
             tarifa_cents, costo_cents, horas_estandar_propuesta, (estado_propuesto or "").strip() or None),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_solicitud(
        self, solicitud_id: int, *, nombre_propuesto: str, categoria_padre: str | None,
        subcategoria_padre: str | None, codigo_propuesto: str = "", descripcion: str = "", motivo: str = "", etiquetas: str = "",
        unidad_cobro_propuesta: str | None = None, responsable_sugerido_propuesto: str | None = None,
        tarifa_referencia_propuesta_text: str = "", costo_referencia_propuesta_text: str = "",
        horas_estandar_propuesta: float | None = None, estado_propuesto: str | None = None,
    ) -> None:
        current = self.get_solicitud(solicitud_id)
        if current["estado"] not in _SOLICITUD_EDITABLE_ESTADOS:
            raise ValueError("Solo se puede editar una solicitud en estado Solicitado, En revisión o Rechazado")
        nombre = (nombre_propuesto or "").strip()
        if not nombre:
            raise ValueError("Nombre propuesto requerido")
        if current["tipo_solicitud"] == "Alta":
            codigo = (codigo_propuesto or "").strip().upper()
            if not codigo:
                raise ValueError("Código propuesto requerido")
        else:
            codigo = current["codigo_propuesto"]
        tarifa_cents = self._to_cents_or_zero(tarifa_referencia_propuesta_text) if tarifa_referencia_propuesta_text else None
        costo_cents = self._to_cents_or_zero(costo_referencia_propuesta_text) if costo_referencia_propuesta_text else None
        self.conn.execute(
            """UPDATE solicitudes_catalogo SET nombre_propuesto=%s, categoria_padre=%s, subcategoria_padre=%s,
                   codigo_propuesto=%s, descripcion=%s, motivo=%s, etiquetas=%s, updated_at=%s,
                   unidad_cobro_propuesta=%s, responsable_sugerido_propuesto=%s,
                   tarifa_referencia_propuesta_cents=%s, costo_referencia_propuesta_cents=%s,
                   horas_estandar_propuesta=%s, estado_propuesto=%s
               WHERE id=%s""",
            (nombre, (categoria_padre or "").strip() or None, (subcategoria_padre or "").strip() or None,
             codigo, (descripcion or "").strip(), (motivo or "").strip(), (etiquetas or "").strip(),
             now_iso(), (unidad_cobro_propuesta or "").strip() or None, (responsable_sugerido_propuesto or "").strip() or None,
             tarifa_cents, costo_cents, horas_estandar_propuesta, (estado_propuesto or "").strip() or None,
             int(solicitud_id)),
        )
        self.conn.commit()

    def _resolver_categoria_padre(self, codigo: str | None) -> Any:
        code = (codigo or "").strip()
        if not code:
            raise ValueError("Falta la categoría padre de la solicitud")
        row = self.conn.execute("SELECT * FROM categorias WHERE category_code=%s", (code,)).fetchone()
        if not row:
            raise ValueError(f"La categoría padre '{code}' no existe en el Catálogo Maestro — créala primero o corrige el código")
        return row

    def _resolver_subcategoria_padre(self, category_id: int, codigo: str | None) -> Any:
        code = (codigo or "").strip()
        if not code:
            raise ValueError("Falta la subcategoría padre de la solicitud")
        row = self.conn.execute(
            "SELECT * FROM subcategorias WHERE category_id=%s AND subcategory_code=%s", (int(category_id), code)
        ).fetchone()
        if not row:
            raise ValueError(f"La subcategoría padre '{code}' no existe dentro de esa categoría — créala primero o corrige el código")
        return row

    def _activar_alta_en_catalogo(self, solicitud: Any, *, created_at: str) -> tuple[str, str]:
        """Crea el registro real en el Catálogo Maestro a partir de una solicitud de Alta aprobada.
        Devuelve (nota_de_trazabilidad, codigo_definitivo_real) — para Servicio/Familia el código
        real lo asigna el sistema y puede diferir del código propuesto por quien solicitó."""
        tipo = solicitud["tipo_registro"]
        nombre = solicitud["nombre_propuesto"]

        if tipo == "Categoria":
            cat_id = self.create_categoria(category_code=solicitud["codigo_definitivo"], nombre=nombre, created_at=created_at)
            return f"Activada en Catálogo Maestro — Categoría #{cat_id} ({solicitud['codigo_definitivo']})", solicitud["codigo_definitivo"]

        if tipo == "Subcategoria":
            categoria = self._resolver_categoria_padre(solicitud["categoria_padre"])
            sub_id = self.create_subcategoria(
                category_id=int(categoria["id"]), subcategory_code=solicitud["codigo_definitivo"], nombre=nombre, created_at=created_at,
            )
            return f"Activada en Catálogo Maestro — Subcategoría #{sub_id} ({solicitud['codigo_definitivo']})", solicitud["codigo_definitivo"]

        if tipo == "Servicio":
            categoria = self._resolver_categoria_padre(solicitud["categoria_padre"])
            subcategoria = self._resolver_subcategoria_padre(int(categoria["id"]), solicitud["subcategoria_padre"])
            serv_id = self.create_servicio(
                subcategory_id=int(subcategoria["id"]), nombre=nombre, etiquetas=solicitud["etiquetas"] or "",
                estado="En diseño", created_at=created_at,
            )
            servicio = self.conn.execute("SELECT service_code FROM servicios WHERE id=%s", (serv_id,)).fetchone()
            code_real = str(servicio["service_code"])
            return (
                f"Activado en Catálogo Maestro — Servicio #{serv_id} ({code_real}), en estado 'En diseño'. "
                "Envía una solicitud de Cambio para completar tarifa, unidad de cobro y responsable antes de pasarlo a Activo."
            ), code_real

        if tipo == "Familia":
            categoria = self._resolver_categoria_padre(solicitud["categoria_padre"])
            fam_id = self.create_familia(category_id=int(categoria["id"]), nombre=nombre, created_at=created_at)
            familia = self.conn.execute("SELECT family_code FROM familias WHERE id=%s", (fam_id,)).fetchone()
            code_real = str(familia["family_code"])
            return f"Activada en Catálogo Maestro — Familia #{fam_id} ({code_real})", code_real

        raise ValueError(f"Tipo de registro no soportado para activación automática: {tipo}")

    def _activar_cambio_en_catalogo(self, solicitud: Any, *, usuario_id: int | None) -> tuple[str, str]:
        """Aplica una solicitud de Cambio aprobada al registro existente que referencia
        (solicitud['entity_id']) — nunca crea un registro nuevo. Cualquier campo propuesto
        que venga vacío conserva el valor que el registro ya tenía."""
        tipo = solicitud["tipo_registro"]
        entity_id = int(solicitud["entity_id"])
        nombre = solicitud["nombre_propuesto"]
        entidad = self._resolver_entidad_por_tipo(tipo, entity_id)

        if tipo == "Categoria":
            estado = solicitud["estado_propuesto"] or entidad["estado"]
            self.update_categoria(entity_id, nombre=nombre, estado=estado, usuario_id=usuario_id)
            return f"Cambio aplicado — Categoría #{entity_id} ({entidad['category_code']})", str(entidad["category_code"])

        if tipo == "Subcategoria":
            estado = solicitud["estado_propuesto"] or entidad["estado"]
            self.update_subcategoria(entity_id, nombre=nombre, estado=estado, usuario_id=usuario_id)
            return f"Cambio aplicado — Subcategoría #{entity_id} ({entidad['subcategory_code']})", str(entidad["subcategory_code"])

        if tipo == "Servicio":
            self.update_servicio(
                entity_id,
                nombre=nombre,
                etiquetas=solicitud["etiquetas"] or entidad["etiquetas"] or "",
                unidad_cobro=solicitud["unidad_cobro_propuesta"] or entidad["unidad_cobro"],
                responsable_sugerido=solicitud["responsable_sugerido_propuesto"] or entidad["responsable_sugerido"],
                tarifa_referencia_text=(
                    str(solicitud["tarifa_referencia_propuesta_cents"] / 100)
                    if solicitud["tarifa_referencia_propuesta_cents"] is not None
                    else str((entidad["tarifa_referencia_cents"] or 0) / 100)
                ),
                costo_referencia_text=(
                    str(solicitud["costo_referencia_propuesta_cents"] / 100)
                    if solicitud["costo_referencia_propuesta_cents"] is not None
                    else str((entidad["costo_referencia_cents"] or 0) / 100)
                ),
                horas_estandar=(
                    float(solicitud["horas_estandar_propuesta"])
                    if solicitud["horas_estandar_propuesta"] is not None
                    else float(entidad["horas_estandar"] or 0)
                ),
                estado=solicitud["estado_propuesto"] or entidad["estado"],
                usuario_id=usuario_id,
            )
            return f"Cambio aplicado — Servicio #{entity_id} ({entidad['service_code']})", str(entidad["service_code"])

        if tipo == "Familia":
            self.update_familia(entity_id, nombre=nombre, usuario_id=usuario_id)
            return f"Cambio aplicado — Familia #{entity_id} ({entidad['family_code']})", str(entidad["family_code"])

        raise ValueError(f"Tipo de registro no soportado para Cambio: {tipo}")

    def _activar_baja_en_catalogo(self, solicitud: Any, *, usuario_id: int | None) -> tuple[str, str]:
        """Inactiva el registro existente que la solicitud de Baja referencia. Las familias
        no tienen estado, así que este tipo de solicitud nunca se acepta para ellas
        (validado antes, en create_solicitud)."""
        tipo = solicitud["tipo_registro"]
        entity_id = int(solicitud["entity_id"])
        entidad = self._resolver_entidad_por_tipo(tipo, entity_id)

        if tipo == "Categoria":
            self.update_categoria(entity_id, nombre=str(entidad["nombre"]), estado="Inactivo", usuario_id=usuario_id)
            return f"Baja aplicada — Categoría #{entity_id} ({entidad['category_code']}) pasó a Inactivo", str(entidad["category_code"])

        if tipo == "Subcategoria":
            self.update_subcategoria(entity_id, nombre=str(entidad["nombre"]), estado="Inactivo", usuario_id=usuario_id)
            return f"Baja aplicada — Subcategoría #{entity_id} ({entidad['subcategory_code']}) pasó a Inactivo", str(entidad["subcategory_code"])

        if tipo == "Servicio":
            self.update_servicio(
                entity_id, nombre=str(entidad["nombre"]), etiquetas=entidad["etiquetas"] or "",
                unidad_cobro=entidad["unidad_cobro"], responsable_sugerido=entidad["responsable_sugerido"],
                tarifa_referencia_text=str((entidad["tarifa_referencia_cents"] or 0) / 100),
                costo_referencia_text=str((entidad["costo_referencia_cents"] or 0) / 100),
                horas_estandar=float(entidad["horas_estandar"] or 0), estado="Inactivo", usuario_id=usuario_id,
            )
            return f"Baja aplicada — Servicio #{entity_id} ({entidad['service_code']}) pasó a Inactivo", str(entidad["service_code"])

        raise ValueError(f"Tipo de registro no soportado para Baja: {tipo}")

    def transition_solicitud(
        self, solicitud_id: int, *, estado: str, resultado_revision_duplicidad: str | None = None,
        aprobador: str | None = None, observaciones: str | None = None, created_at: str, usuario_id: int | None = None,
    ) -> Any:
        current = self.get_solicitud(solicitud_id)
        if estado not in _SOLICITUD_TRANSICIONES.get(current["estado"], set()):
            raise ValueError(f"No se puede pasar de '{current['estado']}' a '{estado}'")

        fields: dict[str, Any] = {"updated_at": created_at}
        if resultado_revision_duplicidad is not None:
            fields["resultado_revision_duplicidad"] = resultado_revision_duplicidad.strip()
        obs = observaciones.strip() if observaciones is not None else None

        if estado == "Aprobado":
            if not (aprobador or "").strip():
                raise ValueError("Se requiere indicar el aprobador para aprobar una solicitud")
            codigo_definitivo = current["codigo_propuesto"]
            # El código propuesto solo se vuelve el código real, sujeto a validación de unicidad,
            # para un Alta de Categoría/Subcategoría — es la única combinación donde se está
            # asignando un código nuevo de verdad. Para Servicio/Familia el sistema genera su
            # propio código al crear, y para Cambio/Baja el código ya pertenece al registro
            # existente desde antes (por eso ya pasó esta misma validación en su propia Alta).
            if current["tipo_solicitud"] == "Alta" and current["tipo_registro"] in ("Categoria", "Subcategoria") and self.conn.execute(
                "SELECT 1 FROM solicitudes_catalogo WHERE codigo_definitivo = %s AND id <> %s",
                (codigo_definitivo, int(solicitud_id)),
            ).fetchone():
                raise ValueError(f"El código '{codigo_definitivo}' ya fue asignado como definitivo en otra solicitud")
            fields["codigo_definitivo"] = codigo_definitivo
            fields["aprobador"] = aprobador.strip()
            fields["fecha_aprobacion"] = created_at[:10]

            # Activación automática: al aprobar, se aplica de una vez el efecto real en el
            # Catálogo Maestro (crear / editar / inactivar según el tipo) y la solicitud pasa
            # directo a Activo — sin paso manual aparte.
            if current["tipo_solicitud"] == "Alta":
                pseudo = dict(current)
                pseudo["codigo_definitivo"] = codigo_definitivo
                nota, codigo_real = self._activar_alta_en_catalogo(pseudo, created_at=created_at)
            elif current["tipo_solicitud"] == "Cambio":
                nota, codigo_real = self._activar_cambio_en_catalogo(current, usuario_id=usuario_id)
            elif current["tipo_solicitud"] == "Baja":
                nota, codigo_real = self._activar_baja_en_catalogo(current, usuario_id=usuario_id)
            else:
                raise ValueError(f"Tipo de solicitud no soportado: {current['tipo_solicitud']}")
            fields["estado"] = "Activo"
            fields["codigo_definitivo"] = codigo_real
            obs = f"{obs}\n{nota}" if obs else nota
        else:
            fields["estado"] = estado

        if obs is not None:
            fields["observaciones"] = obs

        set_clause = ", ".join(f"{k}=%s" for k in fields)
        self.conn.execute(
            f"UPDATE solicitudes_catalogo SET {set_clause} WHERE id=%s",
            (*fields.values(), int(solicitud_id)),
        )
        self.conn.commit()
        return self.get_solicitud(solicitud_id)

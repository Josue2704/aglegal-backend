from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from pathlib import Path
import os
import shutil
import uuid

from .security import hash_password, verify_password


SESSION_STATUSES = ["Pendiente", "En proceso", "Finalizada"]
ATTACH_ENTITY_TYPES = ["session", "income", "expense", "case"]
CATEGORY_KINDS = ["income", "expense", "cost", "service"]
CASE_STATUSES = ["Abierto", "En trámite", "En pausa", "Cerrado"]
CASE_PRIORITIES = ["Baja", "Media", "Alta"]


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
    def __init__(self, conn: sqlite3.Connection):
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
            return f" WHERE {column} >= ? AND {column} <= ?", (s, e)
        if s:
            return f" WHERE {column} >= ?", (s,)
        if e:
            return f" WHERE {column} <= ?", (e,)
        return "", ()

    # --- Auth
    def authenticate(self, username: str, password: str) -> bool:
        row = self.conn.execute(
            "SELECT password_hash FROM users WHERE username = ? AND COALESCE(active, 1) = 1",
            (username.strip(),),
        ).fetchone()
        if not row:
            return False
        return verify_password(password, row["password_hash"])


    # --- Users / access
    def list_users(self) -> list[sqlite3.Row]:
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
            "INSERT INTO users(username, password_hash, full_name, role, active, created_at) VALUES(?,?,?,?,?,?)",
            (username_clean, hash_password(password), (full_name or "").strip(), role, 1 if active else 0, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_user(self, user_id: int, *, full_name: str, role: str, active: bool) -> None:
        self.conn.execute(
            "UPDATE users SET full_name=?, role=?, active=? WHERE id=?",
            ((full_name or "").strip(), role, 1 if active else 0, int(user_id)),
        )
        self.conn.commit()

    def update_user_password(self, user_id: int, password: str) -> None:
        if not password:
            raise ValueError("Contraseña requerida")
        self.conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(password), int(user_id)),
        )
        self.conn.commit()

    def delete_user(self, user_id: int) -> None:
        active_count = int(self.conn.execute("SELECT COUNT(1) AS n FROM users WHERE COALESCE(active, 1)=1").fetchone()["n"])
        row = self.conn.execute("SELECT active FROM users WHERE id=?", (int(user_id),)).fetchone()
        if row and int(row["active"] or 0) == 1 and active_count <= 1:
            raise ValueError("Debe quedar al menos un usuario activo")
        self.conn.execute("DELETE FROM users WHERE id=?", (int(user_id),))
        self.conn.commit()

    # --- Clients
    def list_clients(self, search: str | None = None) -> list[sqlite3.Row]:
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
                base + "WHERE c.name LIKE ? OR c.phone LIKE ? OR c.email LIKE ? "
                "GROUP BY c.id ORDER BY c.id DESC",
                (like, like, like),
            ).fetchall())
        return list(self.conn.execute(base + "GROUP BY c.id ORDER BY c.id DESC").fetchall())

    def list_case_all_attachments(self, case_id: int) -> list[sqlite3.Row]:
        """Return attachments for the case itself plus attachments from its sessions."""
        return list(self.conn.execute(
            "SELECT a.*, "
            "CASE WHEN a.entity_type='session' THEN s.session_date ELSE NULL END AS session_date, "
            "CASE WHEN a.entity_type='session' THEN s.consult_type ELSE NULL END AS session_type "
            "FROM attachments a "
            "LEFT JOIN sessions s ON (a.entity_type='session' AND a.entity_id = s.id) "
            "WHERE (a.entity_type='case' AND a.entity_id=?) "
            "   OR (a.entity_type='session' AND s.case_id=?) "
            "ORDER BY a.created_at DESC",
            (int(case_id), int(case_id)),
        ).fetchall())

    def create_client(
        self,
        *,
        name: str,
        phone: str = "",
        email: str = "",
        address: str = "",
        notes: str = "",
        created_at: str,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO clients(name, phone, email, address, notes, created_at) VALUES(?,?,?,?,?,?)",
            (name.strip(), phone.strip(), email.strip(), address.strip(), notes.strip(), created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_client(
        self,
        client_id: int,
        *,
        name: str,
        phone: str = "",
        email: str = "",
        address: str = "",
        notes: str = "",
    ) -> None:
        self.conn.execute(
            "UPDATE clients SET name=?, phone=?, email=?, address=?, notes=? WHERE id=?",
            (name.strip(), phone.strip(), email.strip(), address.strip(), notes.strip(), int(client_id)),
        )
        self.conn.commit()


    def client_history(self, client_id: int) -> list[dict[str, Any]]:
        cid = int(client_id)
        items: list[dict[str, Any]] = []
        for row in self.conn.execute(
            "SELECT id, title, status, opened_at FROM cases WHERE client_id=? ORDER BY opened_at DESC, id DESC",
            (cid,),
        ).fetchall():
            items.append({"date": row["opened_at"], "type": "Caso", "detail": row["title"], "status": row["status"]})
        for row in self.conn.execute(
            "SELECT id, session_date, consult_type, status FROM sessions WHERE client_id=? ORDER BY session_date DESC, id DESC",
            (cid,),
        ).fetchall():
            items.append({"date": row["session_date"], "type": "Sesión", "detail": row["consult_type"], "status": row["status"]})
        for row in self.conn.execute(
            "SELECT id, income_date, detail, concept, amount_cents FROM incomes WHERE client_id=? ORDER BY income_date DESC, id DESC",
            (cid,),
        ).fetchall():
            amount = self.cents_to_text(int(row["amount_cents"] or 0))
            items.append({"date": row["income_date"], "type": "Ingreso", "detail": row["detail"] or row["concept"], "status": f"$ {amount}"})
        return sorted(items, key=lambda item: item["date"] or "", reverse=True)

    def delete_client(self, client_id: int) -> None:
        self.conn.execute("DELETE FROM clients WHERE id = ?", (int(client_id),))
        self.conn.commit()

    # --- Sessions
    def list_sessions(
        self,
        client_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str | None = None,
    ) -> list[sqlite3.Row]:
        conditions: list[str] = []
        params: list = []
        if client_id:
            conditions.append("s.client_id=?")
            params.append(int(client_id))
        if start_date:
            conditions.append("s.session_date>=?")
            params.append(start_date)
        if end_date:
            conditions.append("s.session_date<=?")
            params.append(end_date)
        if status:
            conditions.append("s.status=?")
            params.append(status)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        return list(
            self.conn.execute(
                f"SELECT s.*, c.name AS client_name FROM sessions s "
                f"JOIN clients c ON c.id=s.client_id {where} "
                f"ORDER BY s.session_date DESC, COALESCE(s.start_time, '99:99') ASC, s.id DESC",
                params,
            ).fetchall()
        )

    def list_sessions_by_case(self, case_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT s.*, c.name AS client_name FROM sessions s "
                "JOIN clients c ON c.id=s.client_id "
                "WHERE s.case_id=? ORDER BY s.session_date DESC, COALESCE(s.start_time, '99:99') ASC, s.id DESC",
                (int(case_id),),
            ).fetchall()
        )

    def create_session(
        self,
        *,
        client_id: int,
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
        cur = self.conn.execute(
            "INSERT INTO sessions(client_id, case_id, session_date, start_time, end_time, consult_type, notes, status, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                int(client_id),
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
            "UPDATE sessions SET case_id=?, session_date=?, start_time=?, end_time=?, consult_type=?, notes=?, status=? WHERE id=?",
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
        self.conn.execute("DELETE FROM sessions WHERE id = ?", (int(session_id),))
        self.conn.commit()

    def get_session(self, session_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT s.*, c.name AS client_name "
            "FROM sessions s LEFT JOIN clients c ON c.id=s.client_id "
            "WHERE s.id=?",
            (int(session_id),),
        ).fetchone()

    def set_session_gcal_event_id(self, session_id: int, event_id: str | None) -> None:
        self.conn.execute(
            "UPDATE sessions SET gcal_event_id=? WHERE id=?", (event_id, int(session_id))
        )
        self.conn.commit()

    # --- Google tokens
    def get_google_tokens(self, username: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM google_tokens WHERE username=?", (username,)
        ).fetchone()

    def save_google_tokens(self, username: str, access_token: str, refresh_token: str, expiry_at: str) -> None:
        self.conn.execute(
            "INSERT INTO google_tokens(username, access_token, refresh_token, expiry_at) VALUES(?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET access_token=excluded.access_token, "
            "refresh_token=excluded.refresh_token, expiry_at=excluded.expiry_at",
            (username, access_token, refresh_token, expiry_at),
        )
        self.conn.commit()

    def delete_google_tokens(self, username: str) -> None:
        self.conn.execute("DELETE FROM google_tokens WHERE username=?", (username,))
        self.conn.commit()

    # --- Incomes
    def list_incomes(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT i.*, c.name AS client_name, cat.name AS category_name, "
                "cs.title AS case_title, sp.name AS product_name "
                "FROM incomes i "
                "LEFT JOIN clients c ON c.id=i.client_id "
                "LEFT JOIN categories cat ON cat.id=i.category_id "
                "LEFT JOIN cases cs ON cs.id=i.case_id "
                "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
                "ORDER BY income_date DESC, id DESC"
            ).fetchall()
        )

    def list_incomes_range(self, *, start_date: str | None, end_date: str | None) -> list[sqlite3.Row]:
        where, params = self._date_where("i.income_date", start_date, end_date)
        sql = (
            "SELECT i.*, c.name AS client_name, cat.name AS category_name, "
            "cs.title AS case_title, sp.name AS product_name "
            "FROM incomes i "
            "LEFT JOIN clients c ON c.id=i.client_id "
            "LEFT JOIN categories cat ON cat.id=i.category_id "
            "LEFT JOIN cases cs ON cs.id=i.case_id "
            "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
            f"{where} "
            "ORDER BY i.income_date DESC, i.id DESC"
        )
        return list(self.conn.execute(sql, params).fetchall())

    def create_income(
        self,
        *,
        amount_text: str,
        income_date: str,
        created_at: str,
        client_id: int | None = None,
        category_id: int | None = None,
        case_id: int | None = None,
        detail: str = "",
        concept: str | None = None,
    ) -> int:
        amount_cents = _to_cents(amount_text)
        resolved_detail = (detail or concept or "").strip()
        resolved_concept = resolved_detail or "(Sin detalle)"
        cur = self.conn.execute(
            "INSERT INTO incomes(client_id, case_id, concept, amount_cents, income_date, created_at, category_id, detail) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                resolved_concept,
                amount_cents,
                income_date,
                created_at,
                int(category_id) if category_id else None,
                resolved_detail,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_income(self, income_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT i.*, c.name AS client_name, cat.name AS category_name, "
            "cs.title AS case_title, sp.name AS product_name "
            "FROM incomes i "
            "LEFT JOIN clients c ON c.id=i.client_id "
            "LEFT JOIN categories cat ON cat.id=i.category_id "
            "LEFT JOIN cases cs ON cs.id=i.case_id "
            "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
            "WHERE i.id=?",
            (int(income_id),),
        ).fetchone()

    def update_income(
        self,
        income_id: int,
        *,
        amount_text: str,
        income_date: str,
        client_id: int | None = None,
        category_id: int | None = None,
        case_id: int | None = None,
        detail: str = "",
    ) -> None:
        amount_cents = _to_cents(amount_text)
        resolved_detail = (detail or "").strip()
        resolved_concept = resolved_detail or "(Sin detalle)"
        self.conn.execute(
            "UPDATE incomes SET amount_cents=?, income_date=?, client_id=?, category_id=?, "
            "case_id=?, detail=?, concept=? WHERE id=?",
            (
                amount_cents,
                income_date,
                int(client_id) if client_id else None,
                int(category_id) if category_id else None,
                int(case_id) if case_id else None,
                resolved_detail,
                resolved_concept,
                int(income_id),
            ),
        )
        self.conn.commit()

    def delete_income(self, income_id: int) -> None:
        self.conn.execute("DELETE FROM incomes WHERE id = ?", (int(income_id),))
        self.conn.commit()

    # --- Expenses
    def list_expenses(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT e.*, cat.name AS category_name "
                "FROM expenses e "
                "LEFT JOIN categories cat ON cat.id=e.category_id "
                "ORDER BY expense_date DESC, id DESC"
            ).fetchall()
        )

    def list_expenses_range(self, *, start_date: str | None, end_date: str | None) -> list[sqlite3.Row]:
        where, params = self._date_where("e.expense_date", start_date, end_date)
        sql = (
            "SELECT e.*, cat.name AS category_name "
            "FROM expenses e "
            "LEFT JOIN categories cat ON cat.id=e.category_id "
            f"{where} "
            "ORDER BY e.expense_date DESC, e.id DESC"
        )
        return list(self.conn.execute(sql, params).fetchall())

    def create_expense(
        self,
        *,
        category_id: int | None,
        detail: str,
        amount_text: str,
        expense_date: str,
        notes: str,
        created_at: str,
    ) -> int:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        cur = self.conn.execute(
            "INSERT INTO expenses(concept, amount_cents, expense_date, notes, created_at, category_id, detail) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                concept,
                amount_cents,
                expense_date,
                notes.strip(),
                created_at,
                int(category_id) if category_id else None,
                (detail or "").strip(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_expense(self, expense_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT e.*, cat.name AS category_name FROM expenses e "
            "LEFT JOIN categories cat ON cat.id=e.category_id WHERE e.id=?",
            (int(expense_id),),
        ).fetchone()

    def update_expense(
        self,
        expense_id: int,
        *,
        category_id: int | None,
        detail: str,
        amount_text: str,
        expense_date: str,
        notes: str,
    ) -> None:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self.conn.execute(
            "UPDATE expenses SET category_id=?, detail=?, concept=?, amount_cents=?, expense_date=?, notes=? WHERE id=?",
            (
                int(category_id) if category_id else None,
                (detail or "").strip(),
                concept,
                amount_cents,
                expense_date,
                (notes or "").strip(),
                int(expense_id),
            ),
        )
        self.conn.commit()

    def delete_expense(self, expense_id: int) -> None:
        self.conn.execute("DELETE FROM expenses WHERE id = ?", (int(expense_id),))
        self.conn.commit()

    # --- Costs (direct costs tied to what is sold)
    def list_costs_range(self, *, start_date: str | None, end_date: str | None) -> list[sqlite3.Row]:
        where, params = self._date_where("co.cost_date", start_date, end_date)
        sql = (
            "SELECT co.*, c.name AS client_name, cs.title AS case_title, "
            "cat.name AS category_name, sp.name AS product_name "
            "FROM costs co "
            "LEFT JOIN clients c ON c.id=co.client_id "
            "LEFT JOIN cases cs ON cs.id=co.case_id "
            "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
            "LEFT JOIN categories cat ON cat.id=co.category_id "
            f"{where} "
            "ORDER BY co.cost_date DESC, co.id DESC"
        )
        return list(self.conn.execute(sql, params).fetchall())

    def create_cost(
        self,
        *,
        client_id: int | None = None,
        case_id: int | None = None,
        category_id: int | None = None,
        detail: str,
        amount_text: str,
        cost_date: str,
        notes: str,
        created_at: str,
    ) -> int:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        cur = self.conn.execute(
            "INSERT INTO costs(client_id, case_id, category_id, concept, detail, amount_cents, cost_date, notes, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                int(category_id) if category_id else None,
                concept,
                (detail or "").strip(),
                amount_cents,
                cost_date,
                (notes or "").strip(),
                created_at,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_cost(self, cost_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT co.*, c.name AS client_name, cs.title AS case_title, "
            "cat.name AS category_name, sp.name AS product_name "
            "FROM costs co "
            "LEFT JOIN clients c ON c.id=co.client_id "
            "LEFT JOIN cases cs ON cs.id=co.case_id "
            "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
            "LEFT JOIN categories cat ON cat.id=co.category_id "
            "WHERE co.id=?",
            (int(cost_id),),
        ).fetchone()

    def update_cost(
        self,
        cost_id: int,
        *,
        client_id: int | None = None,
        case_id: int | None = None,
        category_id: int | None = None,
        detail: str,
        amount_text: str,
        cost_date: str,
        notes: str,
    ) -> None:
        amount_cents = _to_cents(amount_text)
        concept = (detail or "").strip() or "(Sin detalle)"
        self.conn.execute(
            "UPDATE costs SET client_id=?, case_id=?, category_id=?, concept=?, detail=?, "
            "amount_cents=?, cost_date=?, notes=? WHERE id=?",
            (
                int(client_id) if client_id else None,
                int(case_id) if case_id else None,
                int(category_id) if category_id else None,
                concept,
                (detail or "").strip(),
                amount_cents,
                cost_date,
                (notes or "").strip(),
                int(cost_id),
            ),
        )
        self.conn.commit()

    def delete_cost(self, cost_id: int) -> None:
        self.conn.execute("DELETE FROM costs WHERE id=?", (int(cost_id),))
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
    def list_payrolls(self) -> list[sqlite3.Row]:
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
        category = self.conn.execute("SELECT id FROM categories WHERE kind='expense' AND name='Nóminas'").fetchone()
        if not category:
            category_id = self.create_category(kind="expense", name="Nóminas", created_at=created_at)
        else:
            category_id = int(category["id"])
        detail = f"Nómina - {employee} - {period.strip()}"
        expense_id = self.create_expense(
            category_id=category_id,
            detail=detail,
            amount_text=amount_text,
            expense_date=payment_date,
            notes=notes,
            created_at=created_at,
        )
        amount_cents = _to_cents(amount_text)
        cur = self.conn.execute(
            "INSERT INTO payrolls(employee_name, role, period, amount_cents, payment_date, notes, expense_id, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (employee, (role or "").strip(), period.strip(), amount_cents, payment_date.strip(), (notes or "").strip(), expense_id, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_payroll(self, payroll_id: int) -> None:
        row = self.conn.execute("SELECT expense_id FROM payrolls WHERE id=?", (int(payroll_id),)).fetchone()
        self.conn.execute("DELETE FROM payrolls WHERE id=?", (int(payroll_id),))
        if row and row["expense_id"]:
            self.conn.execute("DELETE FROM expenses WHERE id=?", (int(row["expense_id"]),))
        self.conn.commit()

    # --- Attachments (stored on disk + metadata in SQLite)
    def list_attachments(self, *, entity_type: str, entity_id: int) -> list[sqlite3.Row]:
        if entity_type not in ATTACH_ENTITY_TYPES:
            raise ValueError("Tipo de adjunto inválido")
        return list(
            self.conn.execute(
                "SELECT * FROM attachments WHERE entity_type=? AND entity_id=? ORDER BY id DESC",
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
            "INSERT INTO attachments(entity_type, entity_id, original_name, stored_path, created_at) VALUES(?,?,?,?,?)",
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
            "SELECT stored_path FROM attachments WHERE id=?", (int(attachment_id),)
        ).fetchone()
        self.conn.execute("DELETE FROM attachments WHERE id=?", (int(attachment_id),))
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
    def list_cases(self, *, search: str | None = None, status: str | None = None, client_id: int | None = None) -> list[sqlite3.Row]:
        where = []
        params: list[Any] = []
        if search:
            where.append("(cs.title LIKE ? OR cs.service_area LIKE ? OR cl.name LIKE ? OR sp.name LIKE ?)")
            like = f"%{search.strip()}%"
            params.extend([like, like, like, like])
        if status and status != "Todos":
            where.append("cs.status = ?")
            params.append(status)
        if client_id:
            where.append("cs.client_id = ?")
            params.append(int(client_id))

        w = (" WHERE " + " AND ".join(where)) if where else ""
        sql = (
            "SELECT cs.*, cl.name AS client_name, sp.name AS product_name "
            "FROM cases cs JOIN clients cl ON cl.id=cs.client_id "
            "LEFT JOIN service_products sp ON sp.id=cs.service_product_id "
            f"{w} "
            "ORDER BY cs.id DESC"
        )
        return list(self.conn.execute(sql, tuple(params)).fetchall())

    def create_case(
        self,
        *,
        client_id: int,
        service_area: str,
        title: str,
        status: str,
        priority: str,
        opened_at: str,
        notes: str,
        created_at: str,
        service_product_id: int | None = None,
    ) -> int:
        if status not in CASE_STATUSES:
            raise ValueError("Estado de caso inválido")
        if priority not in CASE_PRIORITIES:
            raise ValueError("Prioridad inválida")
        cur = self.conn.execute(
            "INSERT INTO cases(client_id, service_area, title, status, priority, opened_at, closed_at, notes, created_at, service_product_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                int(client_id),
                service_area.strip(),
                title.strip(),
                status,
                priority,
                opened_at,
                None,
                notes.strip(),
                created_at,
                int(service_product_id) if service_product_id else None,
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
        notes: str,
        service_product_id: int | None = None,
    ) -> None:
        if status not in CASE_STATUSES:
            raise ValueError("Estado de caso inválido")
        if priority not in CASE_PRIORITIES:
            raise ValueError("Prioridad inválida")
        self.conn.execute(
            "UPDATE cases SET service_area=?, title=?, status=?, priority=?, opened_at=?, closed_at=?, notes=?, service_product_id=? WHERE id=?",
            (
                service_area.strip(),
                title.strip(),
                status,
                priority,
                opened_at,
                (closed_at or "").strip() or None,
                notes.strip(),
                int(service_product_id) if service_product_id else None,
                int(case_id),
            ),
        )
        self.conn.commit()

    def delete_case(self, case_id: int) -> None:
        self.conn.execute("DELETE FROM cases WHERE id=?", (int(case_id),))
        self.conn.commit()

    def case_choices(self, *, client_id: int | None = None) -> list[tuple[int, str]]:
        if client_id:
            rows = self.conn.execute(
                "SELECT id, title FROM cases WHERE client_id=? ORDER BY id DESC",
                (int(client_id),),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT id, title FROM cases ORDER BY id DESC").fetchall()
        return [(int(r["id"]), str(r["title"])) for r in rows]

    def list_case_tasks(self, case_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM case_tasks WHERE case_id=? ORDER BY done ASC, id DESC",
                (int(case_id),),
            ).fetchall()
        )

    def create_case_task(self, *, case_id: int, title: str, due_date: str | None, created_at: str) -> int:
        t = (title or "").strip()
        if not t:
            raise ValueError("Título requerido")
        cur = self.conn.execute(
            "INSERT INTO case_tasks(case_id, title, done, due_date, created_at) VALUES(?,?,?,?,?)",
            (int(case_id), t, 0, (due_date or "").strip() or None, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def set_case_task_done(self, task_id: int, done: bool) -> None:
        self.conn.execute("UPDATE case_tasks SET done=? WHERE id=?", (1 if done else 0, int(task_id)))
        self.conn.commit()

    def delete_case_task(self, task_id: int) -> None:
        self.conn.execute("DELETE FROM case_tasks WHERE id=?", (int(task_id),))
        self.conn.commit()

    # --- Categories
    def list_categories(self, *, kind: str) -> list[sqlite3.Row]:
        if kind not in CATEGORY_KINDS:
            raise ValueError("Tipo de categoría inválido")
        return list(
            self.conn.execute(
                "SELECT * FROM categories WHERE kind=? ORDER BY name ASC", (kind,)
            ).fetchall()
        )

    def create_category(self, *, kind: str, name: str, created_at: str) -> int:
        if kind not in CATEGORY_KINDS:
            raise ValueError("Tipo de categoría inválido")
        n = (name or "").strip()
        if not n:
            raise ValueError("Nombre requerido")
        cur = self.conn.execute(
            "INSERT INTO categories(kind, name, created_at) VALUES(?,?,?)",
            (kind, n, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_category(self, category_id: int, *, name: str) -> None:
        n = (name or "").strip()
        if not n:
            raise ValueError("Nombre requerido")
        self.conn.execute("UPDATE categories SET name=? WHERE id=?", (n, int(category_id)))
        self.conn.commit()

    def delete_category(self, category_id: int) -> None:
        # Leave existing records with category_id dangling; UI will show empty name.
        self.conn.execute("DELETE FROM categories WHERE id=?", (int(category_id),))
        self.conn.commit()

    def category_choices(self, *, kind: str) -> list[tuple[int, str]]:
        return [(int(r["id"]), str(r["name"])) for r in self.list_categories(kind=kind)]


    # --- Service catalog / products offered
    def list_service_products(self, *, category_id: int | None = None, active_only: bool = False) -> list[sqlite3.Row]:
        where = []
        params: list[Any] = []
        if category_id:
            where.append("sp.category_id=?")
            params.append(int(category_id))
        if active_only:
            where.append("sp.active=1")
        clause = " WHERE " + " AND ".join(where) if where else ""
        return list(
            self.conn.execute(
                "SELECT sp.*, cat.name AS category_name "
                "FROM service_products sp "
                "JOIN categories cat ON cat.id=sp.category_id "
                f"{clause} "
                "ORDER BY cat.name ASC, sp.name ASC",
                tuple(params),
            ).fetchall()
        )

    def create_service_product(
        self,
        *,
        category_id: int,
        name: str,
        description: str = "",
        base_price_text: str = "",
        active: bool = True,
        created_at: str,
    ) -> int:
        product_name = (name or "").strip()
        if not product_name:
            raise ValueError("Nombre del producto requerido")
        base_price_cents = _to_cents(base_price_text) if (base_price_text or "").strip() else None
        cur = self.conn.execute(
            "INSERT INTO service_products(category_id, name, description, base_price_cents, active, created_at) VALUES(?,?,?,?,?,?)",
            (int(category_id), product_name, (description or "").strip(), base_price_cents, 1 if active else 0, created_at),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_service_product(
        self,
        product_id: int,
        *,
        category_id: int,
        name: str,
        description: str = "",
        base_price_text: str = "",
        active: bool = True,
    ) -> None:
        product_name = (name or "").strip()
        if not product_name:
            raise ValueError("Nombre del producto requerido")
        base_price_cents = _to_cents(base_price_text) if (base_price_text or "").strip() else None
        self.conn.execute(
            "UPDATE service_products SET category_id=?, name=?, description=?, base_price_cents=?, active=? WHERE id=?",
            (int(category_id), product_name, (description or "").strip(), base_price_cents, 1 if active else 0, int(product_id)),
        )
        self.conn.commit()

    def delete_service_product(self, product_id: int) -> None:
        self.conn.execute("DELETE FROM service_products WHERE id=?", (int(product_id),))
        self.conn.commit()

    def service_product_choices(self, *, category_id: int | None = None) -> list[tuple[int, str]]:
        return [(int(row["id"]), str(row["name"])) for row in self.list_service_products(category_id=category_id, active_only=True)]

    # --- Dashboard
    def dashboard_summary(self) -> DashboardSummary:
        total_clients = int(self.conn.execute("SELECT COUNT(1) AS n FROM clients").fetchone()["n"])
        incomes = int(self.conn.execute("SELECT COALESCE(SUM(amount_cents), 0) AS s FROM incomes").fetchone()["s"])
        expenses = int(self.conn.execute("SELECT COALESCE(SUM(amount_cents), 0) AS s FROM expenses").fetchone()["s"])

        month_prefix = date.today().strftime("%Y-%m-")
        sessions_this_month = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE ?",
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
                "SELECT COUNT(DISTINCT client_id) AS n FROM sessions WHERE session_date LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()["n"]
        )
        sessions_total = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()["n"]
        )
        sessions_finalized = int(
            self.conn.execute(
                "SELECT COUNT(1) AS n FROM sessions WHERE session_date LIKE ? AND status = ?",
                (f"{month_prefix}%", "Finalizada"),
            ).fetchone()["n"]
        )
        incomes_cents = int(
            self.conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM incomes WHERE income_date LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()["s"]
        )
        expenses_cents = int(
            self.conn.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) AS s FROM expenses WHERE expense_date LIKE ?",
                (f"{month_prefix}%",),
            ).fetchone()["s"]
        )
        categories_total = int(self.conn.execute("SELECT COUNT(1) AS n FROM categories").fetchone()["n"])

        return {
            "clients_attended": clients_attended,
            "sessions_total": sessions_total,
            "sessions_finalized": sessions_finalized,
            "incomes_cents": incomes_cents,
            "expenses_cents": expenses_cents,
            "categories_total": categories_total,
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

    def category_totals(self, *, kind: str, start_date: str | None, end_date: str | None) -> list[tuple[str, int]]:
        if kind not in CATEGORY_KINDS:
            raise ValueError("Tipo de categoría inválido")

        if kind == "income":
            where, params = self._date_where("i.income_date", start_date, end_date)
            rows = self.conn.execute(
                f"""
                SELECT COALESCE(cat.name, '(Sin categoría)') AS name,
                       COALESCE(SUM(i.amount_cents), 0) AS total
                FROM incomes i
                LEFT JOIN categories cat ON cat.id=i.category_id
                {where}
                GROUP BY name
                ORDER BY total DESC
                """,
                params,
            ).fetchall()
        elif kind == "cost":
            where, params = self._date_where("co.cost_date", start_date, end_date)
            rows = self.conn.execute(
                f"""
                SELECT COALESCE(cat.name, '(Sin categoría)') AS name,
                       COALESCE(SUM(co.amount_cents), 0) AS total
                FROM costs co
                LEFT JOIN categories cat ON cat.id=co.category_id
                {where}
                GROUP BY name
                ORDER BY total DESC
                """,
                params,
            ).fetchall()
        else:
            where, params = self._date_where("e.expense_date", start_date, end_date)
            rows = self.conn.execute(
                f"""
                SELECT COALESCE(cat.name, '(Sin categoría)') AS name,
                       COALESCE(SUM(e.amount_cents), 0) AS total
                FROM expenses e
                LEFT JOIN categories cat ON cat.id=e.category_id
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
            GROUP BY name
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
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
            SELECT COALESCE(sp.name, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN cases cs ON cs.id=i.case_id
            LEFT JOIN service_products sp ON sp.id=cs.service_product_id
            {where}{service_filter}
            GROUP BY name
            HAVING total > 0
            ORDER BY total DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
        return [(str(row["name"]), int(row["total"] or 0)) for row in rows]

    def top_expenses_by_category(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        return self.category_totals(kind="expense", start_date=start_date, end_date=end_date)[: int(limit)]

    def top_costs_by_category(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int]]:
        return self.category_totals(kind="cost", start_date=start_date, end_date=end_date)[: int(limit)]

    def top_services_by_gross_profit(
        self, *, start_date: str | None = None, end_date: str | None = None, limit: int = 8
    ) -> list[tuple[str, int, int, int]]:
        income_where, income_params = self._date_where("i.income_date", start_date, end_date)
        cost_where, cost_params = self._date_where("co.cost_date", start_date, end_date)
        income_rows = self.conn.execute(
            f"""
            SELECT COALESCE(sp.name, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(i.amount_cents), 0) AS total
            FROM incomes i
            LEFT JOIN cases cs ON cs.id=i.case_id
            LEFT JOIN service_products sp ON sp.id=cs.service_product_id
            {income_where}{' AND i.case_id IS NOT NULL' if income_where else ' WHERE i.case_id IS NOT NULL'}
            GROUP BY name
            """,
            income_params,
        ).fetchall()
        cost_rows = self.conn.execute(
            f"""
            SELECT COALESCE(sp.name, cs.service_area, '(Sin servicio)') AS name,
                   COALESCE(SUM(co.amount_cents), 0) AS total
            FROM costs co
            LEFT JOIN cases cs ON cs.id=co.case_id
            LEFT JOIN service_products sp ON sp.id=cs.service_product_id
            {cost_where}{' AND co.case_id IS NOT NULL' if cost_where else ' WHERE co.case_id IS NOT NULL'}
            GROUP BY name
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

    # --- Helpers for UI
    def client_choices(self) -> list[tuple[int, str]]:
        rows = self.conn.execute("SELECT id, name FROM clients ORDER BY name ASC").fetchall()
        return [(int(r["id"]), str(r["name"])) for r in rows]

    @staticmethod
    def cents_to_text(cents: int) -> str:
        return _from_cents(cents)

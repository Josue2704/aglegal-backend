from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QTextCharFormat, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ...db import now_iso
from ...repositories import Repository, SESSION_STATUSES
from ..common import confirm, info, open_file, warn


class SessionsPage(QWidget):
    def __init__(self, repo: Repository, current_username: str = "admin"):
        super().__init__()
        self.repo = repo
        self.current_username = current_username
        self.selected_id: int | None = None
        self.selected_calendar_date = date.today().isoformat()

        title = QLabel("Agenda de sesiones")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Calendario, listado del día y formulario de seguimiento en una sola ruta clara.")
        subtitle.setObjectName("MutedText")

        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("AgendaCalendar")
        self.calendar.setStyleSheet(
            """
            QCalendarWidget {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #e3e8f0;
                border-radius: 16px;
            }
            QCalendarWidget QWidget#qt_calendar_navigationbar {
                background: #4f46e5;
            }
            QCalendarWidget QToolButton {
                color: #ffffff;
                background: transparent;
                border: none;
                padding: 6px;
                font-weight: 800;
            }
            QCalendarWidget QToolButton:hover {
                background: rgba(255,255,255,0.16);
                border-radius: 8px;
            }
            QCalendarWidget QSpinBox {
                background: rgba(255,255,255,0.20);
                color: #ffffff;
                border: 1px solid rgba(255,255,255,0.25);
                border-radius: 8px;
                padding: 3px;
            }
            QCalendarWidget QAbstractItemView {
                background: #ffffff;
                color: #0f172a;
                selection-background-color: #dbeafe;
                selection-color: #0f172a;
                alternate-background-color: #f8fafc;
                gridline-color: #e2e8f0;
            }
            """
        )
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.selectionChanged.connect(self._on_calendar_changed)

        self.day_list = QListWidget()
        self.day_list.currentItemChanged.connect(lambda *_: self._select_from_day_list())

        calendar_box = QGroupBox("Calendario")
        calendar_layout = QVBoxLayout()
        calendar_layout.addWidget(self.calendar)
        calendar_layout.addWidget(QLabel("Sesiones del día"))
        calendar_layout.addWidget(self.day_list)
        calendar_box.setLayout(calendar_layout)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["ID", "Fecha", "Hora", "Cliente", "Caso", "Tipo", "Estado", "Notas"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["Todas", *SESSION_STATUSES])
        self.filter_status.currentIndexChanged.connect(self.refresh)
        self.btn_today = QPushButton("Hoy")
        self.btn_today.setObjectName("SecondaryButton")
        self.btn_today.clicked.connect(self._go_today)
        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_pull_google = QPushButton("Traer de Google")
        self.btn_pull_google.setObjectName("SecondaryButton")
        self.btn_pull_google.clicked.connect(self._sync_google_pull)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Estado:"))
        toolbar.addWidget(self.filter_status)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_today)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_pull_google)

        list_box = QGroupBox("Todas las sesiones")
        list_layout = QVBoxLayout()
        list_layout.addLayout(toolbar)
        list_layout.addWidget(self.table)
        list_box.setLayout(list_layout)

        self.in_client = QComboBox()
        self.in_client.currentIndexChanged.connect(lambda *_: self._refresh_cases())
        self.in_case = QComboBox()
        self.in_date = QDateEdit()
        self.in_date.setCalendarPopup(True)
        self.in_date.setDisplayFormat("yyyy-MM-dd")
        self.in_date.setDate(QDate.currentDate())
        self.in_start_time = QTimeEdit()
        self.in_start_time.setDisplayFormat("HH:mm")
        self.in_start_time.setTime(QTime.fromString("09:00", "HH:mm"))
        self.in_end_time = QTimeEdit()
        self.in_end_time.setDisplayFormat("HH:mm")
        self.in_end_time.setTime(QTime.fromString("10:00", "HH:mm"))
        self.in_type = QLineEdit()
        self.in_type.setPlaceholderText("Ej. consulta inicial, audiencia, firma, seguimiento")
        self.in_status = QComboBox()
        self.in_status.addItems(SESSION_STATUSES)
        self.in_notes = QTextEdit()
        self.in_notes.setPlaceholderText("Acuerdos, pendientes, documentos recibidos, próximo paso...")
        self.in_notes.setFixedHeight(120)

        form = QFormLayout()
        form.addRow("Cliente:", self.in_client)
        form.addRow("Caso vinculado:", self.in_case)
        form.addRow("Fecha:", self.in_date)
        form.addRow("Hora inicio:", self.in_start_time)
        form.addRow("Hora fin:", self.in_end_time)
        form.addRow("Tipo de sesión:", self.in_type)
        form.addRow("Estado:", self.in_status)
        form.addRow("Notas útiles:", self.in_notes)

        self.attach_list = QListWidget()
        self.attach_list.currentItemChanged.connect(lambda *_: self._on_attach_select())
        self.btn_attach_add = QPushButton("Adjuntar documento")
        self.btn_attach_open = QPushButton("Abrir")
        self.btn_attach_open.setObjectName("SecondaryButton")
        self.btn_attach_remove = QPushButton("Quitar")
        self.btn_attach_remove.setObjectName("SecondaryButton")
        self.btn_attach_add.clicked.connect(self._attach_add)
        self.btn_attach_open.clicked.connect(self._attach_open)
        self.btn_attach_remove.clicked.connect(self._attach_remove)

        attach_btns = QHBoxLayout()
        attach_btns.addWidget(self.btn_attach_add)
        attach_btns.addWidget(self.btn_attach_open)
        attach_btns.addWidget(self.btn_attach_remove)
        attach_btns.addStretch(1)

        attachments = QGroupBox("Documentos de la sesión")
        attachments_layout = QVBoxLayout()
        attachments_layout.addWidget(self.attach_list)
        attachments_layout.addLayout(attach_btns)
        attachments.setLayout(attachments_layout)

        self.btn_new = QPushButton("Nueva sesión")
        self.btn_save = QPushButton("Guardar sesión")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setObjectName("SecondaryButton")
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_delete.clicked.connect(self._delete)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_new)
        actions.addWidget(self.btn_save)
        actions.addWidget(self.btn_delete)
        actions.addStretch(1)

        editor = QGroupBox("Crear / editar sesión")
        editor_layout = QVBoxLayout()
        editor_layout.addLayout(form)
        editor_layout.addLayout(actions)
        editor_layout.addWidget(attachments)
        editor_layout.addStretch(1)
        editor.setLayout(editor_layout)

        splitter = QSplitter()
        splitter.addWidget(calendar_box)
        splitter.addWidget(list_box)
        splitter.addWidget(editor)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([320, 560, 360])

        root = QVBoxLayout()
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(splitter, 1)
        self.setLayout(root)

        self.refresh()
        self._new()

    def refresh(self) -> None:
        self._refresh_clients()
        self._refresh_cases()
        rows = self._filtered_sessions()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            time_range = self._format_time_range(row["start_time"], row["end_time"])
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["session_date"] or ""))
            self.table.setItem(row_index, 2, QTableWidgetItem(time_range))
            self.table.setItem(row_index, 3, QTableWidgetItem(row["client_name"] or ""))
            self.table.setItem(row_index, 4, QTableWidgetItem(row["case_title"] or ""))
            self.table.setItem(row_index, 5, QTableWidgetItem(row["consult_type"] or ""))
            self.table.setItem(row_index, 6, QTableWidgetItem(row["status"] or ""))
            self.table.setItem(row_index, 7, QTableWidgetItem(row["notes"] or ""))
        self.table.resizeColumnsToContents()
        self._paint_calendar_dates()
        self._refresh_day_list()
        self._refresh_attachments()

    def _filtered_sessions(self) -> list:
        rows = self.repo.conn.execute(
            """
            SELECT s.*, c.name AS client_name, cs.title AS case_title
            FROM sessions s
            JOIN clients c ON c.id=s.client_id
            LEFT JOIN cases cs ON cs.id=s.case_id
            ORDER BY s.session_date DESC, COALESCE(s.start_time, '99:99') ASC, s.id DESC
            """
        ).fetchall()
        status = self.filter_status.currentText()
        if status != "Todas":
            rows = [row for row in rows if row["status"] == status]
        return list(rows)

    def _format_time_range(self, start_time: str | None, end_time: str | None) -> str:
        start = (start_time or "").strip()
        end = (end_time or "").strip()
        if start and end:
            return f"{start} - {end}"
        if start:
            return start
        return "Sin hora"

    def _refresh_clients(self) -> None:
        current = self.in_client.currentData()
        self.in_client.blockSignals(True)
        self.in_client.clear()
        for client_id, name in self.repo.client_choices():
            self.in_client.addItem(name, client_id)
        if current is not None:
            index = self.in_client.findData(current)
            if index >= 0:
                self.in_client.setCurrentIndex(index)
        self.in_client.blockSignals(False)

    def _refresh_cases(self) -> None:
        client_id = self.in_client.currentData()
        current = self.in_case.currentData()
        self.in_case.blockSignals(True)
        self.in_case.clear()
        self.in_case.addItem("(Sin caso)", None)
        if client_id:
            for case_id, title in self.repo.case_choices(client_id=int(client_id)):
                self.in_case.addItem(title, case_id)
        if current is not None:
            index = self.in_case.findData(current)
            if index >= 0:
                self.in_case.setCurrentIndex(index)
        self.in_case.blockSignals(False)

    def _paint_calendar_dates(self) -> None:
        default_format = QTextCharFormat()
        session_format = QTextCharFormat()
        session_format.setBackground(QColor("#dbeafe"))
        session_format.setForeground(QColor("#0f172a"))
        session_format.setFontWeight(700)
        today = date.today()
        for offset in range(-370, 370):
            qdate = QDate(today.year, today.month, today.day).addDays(offset)
            self.calendar.setDateTextFormat(qdate, default_format)
        dates = {row["session_date"] for row in self.repo.list_sessions() if row["session_date"]}
        for value in dates:
            parsed = QDate.fromString(value, "yyyy-MM-dd")
            if parsed.isValid():
                self.calendar.setDateTextFormat(parsed, session_format)

    def _refresh_day_list(self) -> None:
        self.day_list.clear()
        rows = [row for row in self.repo.list_sessions() if row["session_date"] == self.selected_calendar_date]
        if not rows:
            self.day_list.addItem("Sin sesiones para esta fecha")
            return
        for row in rows:
            item = QListWidgetItem(f'{row["client_name"]} · {row["consult_type"]} · {row["status"]}')
            time_range = self._format_time_range(row["start_time"], row["end_time"])
            item.setText(f'{time_range} | {row["client_name"]} | {row["consult_type"]} | {row["status"]}')
            item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
            self.day_list.addItem(item)

    def _on_calendar_changed(self) -> None:
        self.selected_calendar_date = self.calendar.selectedDate().toString("yyyy-MM-dd")
        self.in_date.setDate(self.calendar.selectedDate())
        self._refresh_day_list()

    def _go_today(self) -> None:
        self.calendar.setSelectedDate(QDate.currentDate())
        self._on_calendar_changed()

    def _select_from_day_list(self) -> None:
        item = self.day_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == int(session_id):
                self.table.selectRow(row)
                break

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_id = None
            self._refresh_attachments()
            return
        row = items[0].row()
        self.selected_id = int(self.table.item(row, 0).text())
        selected = [item for item in self._filtered_sessions() if int(item["id"]) == self.selected_id]
        if not selected:
            return
        session = selected[0]
        client_index = self.in_client.findText(session["client_name"] or "")
        if client_index >= 0:
            self.in_client.setCurrentIndex(client_index)
        self._refresh_cases()
        if session["case_id"]:
            case_index = self.in_case.findData(int(session["case_id"]))
            if case_index >= 0:
                self.in_case.setCurrentIndex(case_index)
        parsed = QDate.fromString(session["session_date"] or "", "yyyy-MM-dd")
        if parsed.isValid():
            self.in_date.setDate(parsed)
            self.calendar.setSelectedDate(parsed)
        start_time = QTime.fromString(session["start_time"] or "09:00", "HH:mm")
        end_time = QTime.fromString(session["end_time"] or "10:00", "HH:mm")
        self.in_start_time.setTime(start_time if start_time.isValid() else QTime.fromString("09:00", "HH:mm"))
        self.in_end_time.setTime(end_time if end_time.isValid() else QTime.fromString("10:00", "HH:mm"))
        self.in_type.setText(session["consult_type"] or "")
        status_index = self.in_status.findText(session["status"] or "")
        if status_index >= 0:
            self.in_status.setCurrentIndex(status_index)
        self.in_notes.setPlainText(session["notes"] or "")
        self._refresh_attachments()

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self._refresh_clients()
        self._refresh_cases()
        self.in_date.setDate(self.calendar.selectedDate())
        self.in_start_time.setTime(QTime.fromString("09:00", "HH:mm"))
        self.in_end_time.setTime(QTime.fromString("10:00", "HH:mm"))
        self.in_type.clear()
        self.in_status.setCurrentIndex(0)
        self.in_notes.clear()
        self._refresh_attachments()

    def _save(self) -> None:
        client_id = self.in_client.currentData()
        if not client_id:
            warn(self, "Sesiones", "Primero registra o selecciona un cliente.")
            return
        consult_type = self.in_type.text().strip()
        if not consult_type:
            warn(self, "Sesiones", "Indica el tipo de sesión.")
            return
        session_date = self.in_date.date().toString("yyyy-MM-dd")
        start_time = self.in_start_time.time().toString("HH:mm")
        end_time = self.in_end_time.time().toString("HH:mm")
        if self.in_end_time.time() <= self.in_start_time.time():
            warn(self, "Sesiones", "La hora fin debe ser mayor que la hora inicio.")
            return
        if self.selected_id is None:
            self.selected_id = self.repo.create_session(
                client_id=int(client_id),
                case_id=self.in_case.currentData(),
                session_date=session_date,
                start_time=start_time,
                end_time=end_time,
                consult_type=consult_type,
                notes=self.in_notes.toPlainText(),
                status=self.in_status.currentText(),
                created_at=now_iso(),
            )
            self._sync_google_create(self.selected_id)
            info(self, "Sesiones", "Sesión creada.")
        else:
            self.repo.update_session(
                self.selected_id,
                case_id=self.in_case.currentData(),
                session_date=session_date,
                start_time=start_time,
                end_time=end_time,
                consult_type=consult_type,
                notes=self.in_notes.toPlainText(),
                status=self.in_status.currentText(),
            )
            self._sync_google_update(self.selected_id)
            info(self, "Sesiones", "Sesión actualizada.")
        self.refresh()

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Sesiones", "Selecciona una sesión.")
            return
        if not confirm(self, "Sesiones", "¿Eliminar esta sesión?"):
            return
        self._sync_google_delete(self.selected_id)
        self.repo.delete_session(self.selected_id)
        self._new()
        self.refresh()

    def _google_calendar_service(self):
        try:
            from api.app.services import google_calendar as gcal
        except Exception:
            return None
        return gcal

    def _google_token_row(self):
        return self.repo.get_google_tokens(self.current_username)

    def _sync_google_create(self, session_id: int) -> None:
        gcal = self._google_calendar_service()
        token_row = self._google_token_row()
        if not gcal or not token_row:
            return
        session_row = self.repo.get_session(session_id)
        if not session_row:
            return
        event_id = gcal.create_event(token_row, session_row)
        if event_id:
            self.repo.set_session_gcal_event_id(session_id, event_id)

    def _sync_google_update(self, session_id: int) -> None:
        gcal = self._google_calendar_service()
        token_row = self._google_token_row()
        if not gcal or not token_row:
            return
        session_row = self.repo.get_session(session_id)
        if not session_row:
            return
        if session_row["gcal_event_id"]:
            gcal.update_event(token_row, session_row["gcal_event_id"], session_row)
        else:
            event_id = gcal.create_event(token_row, session_row)
            if event_id:
                self.repo.set_session_gcal_event_id(session_id, event_id)

    def _sync_google_delete(self, session_id: int) -> None:
        gcal = self._google_calendar_service()
        token_row = self._google_token_row()
        if not gcal or not token_row:
            return
        session_row = self.repo.get_session(session_id)
        if not session_row or not session_row["gcal_event_id"]:
            return
        gcal.delete_event(token_row, session_row["gcal_event_id"])

    def _google_calendar_client_id(self) -> int:
        row = self.repo.conn.execute(
            "SELECT id FROM clients WHERE name=? ORDER BY id LIMIT 1",
            ("Google Calendar",),
        ).fetchone()
        if row:
            return int(row["id"])
        return self.repo.create_client(
            name="Google Calendar",
            notes="Eventos importados desde Google Calendar sin cliente vinculado.",
            created_at=now_iso(),
        )

    def _parse_google_event(self, event: dict) -> dict | None:
        if event.get("status") == "cancelled":
            return None
        start = event.get("start", {})
        end = event.get("end", {})
        start_value = start.get("dateTime") or start.get("date")
        end_value = end.get("dateTime") or end.get("date")
        if not start_value:
            return None

        session_date = str(start_value)[:10]
        start_time = None
        end_time = None
        if "dateTime" in start:
            start_time = str(start_value)[11:16]
        if "dateTime" in end and end_value:
            end_time = str(end_value)[11:16]

        title = (event.get("summary") or "Evento de Google").strip()
        description = (event.get("description") or "").strip()
        return {
            "event_id": str(event.get("id") or ""),
            "session_date": session_date,
            "start_time": start_time,
            "end_time": end_time,
            "consult_type": title,
            "notes": description,
        }

    def _sync_google_pull(self) -> None:
        gcal = self._google_calendar_service()
        token_row = self._google_token_row()
        if not gcal:
            warn(self, "Google Calendar", "No se pudo cargar la integraciﾃｳn de Google Calendar.")
            return
        if not token_row:
            warn(self, "Google Calendar", "Primero conecta Google Calendar desde la API/configuraciﾃｳn.")
            return

        selected = self.calendar.selectedDate()
        center = date(selected.year(), selected.month(), selected.day())
        time_min = datetime.combine(center - timedelta(days=90), datetime.min.time(), tzinfo=timezone.utc)
        time_max = datetime.combine(center + timedelta(days=180), datetime.max.time(), tzinfo=timezone.utc)
        events = gcal.list_events(token_row, time_min, time_max)
        client_id = self._google_calendar_client_id()
        imported = 0
        updated = 0

        for event in events:
            parsed = self._parse_google_event(event)
            if not parsed or not parsed["event_id"]:
                continue
            existing = self.repo.conn.execute(
                "SELECT id FROM sessions WHERE gcal_event_id=?",
                (parsed["event_id"],),
            ).fetchone()
            if existing:
                self.repo.update_session(
                    int(existing["id"]),
                    case_id=None,
                    session_date=parsed["session_date"],
                    start_time=parsed["start_time"],
                    end_time=parsed["end_time"],
                    consult_type=parsed["consult_type"],
                    notes=parsed["notes"],
                    status="Pendiente",
                )
                updated += 1
            else:
                session_id = self.repo.create_session(
                    client_id=client_id,
                    case_id=None,
                    session_date=parsed["session_date"],
                    start_time=parsed["start_time"],
                    end_time=parsed["end_time"],
                    consult_type=parsed["consult_type"],
                    notes=parsed["notes"],
                    status="Pendiente",
                    created_at=now_iso(),
                )
                self.repo.set_session_gcal_event_id(session_id, parsed["event_id"])
                imported += 1

        self.refresh()
        info(self, "Google Calendar", f"Importados: {imported}. Actualizados: {updated}.")

    def _refresh_attachments(self) -> None:
        self.attach_list.clear()
        has_session = self.selected_id is not None
        self.btn_attach_add.setEnabled(has_session)
        self.btn_attach_open.setEnabled(False)
        self.btn_attach_remove.setEnabled(False)
        if not has_session:
            self.attach_list.addItem("Selecciona o guarda una sesión para adjuntar documentos")
            self.attach_list.setEnabled(False)
            return
        self.attach_list.setEnabled(True)
        rows = self.repo.list_attachments(entity_type="session", entity_id=self.selected_id)
        if not rows:
            self.attach_list.addItem("Sin documentos")
            return
        for row in rows:
            item = QListWidgetItem(row["original_name"])
            item.setData(Qt.ItemDataRole.UserRole, (int(row["id"]), str(row["stored_path"])))
            self.attach_list.addItem(item)
        self._on_attach_select()

    def _on_attach_select(self) -> None:
        item = self.attach_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        enabled = isinstance(data, tuple) and len(data) == 2
        self.btn_attach_open.setEnabled(enabled)
        self.btn_attach_remove.setEnabled(enabled)

    def _attach_add(self) -> None:
        if self.selected_id is None:
            warn(self, "Adjuntos", "Guarda o selecciona una sesión primero.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Adjuntar documento")
        if not path:
            return
        original = Path(path).name
        stored = self.repo.suggest_attachment_path("session", self.selected_id, original)
        try:
            self.repo.add_attachment(
                entity_type="session",
                entity_id=self.selected_id,
                source_path=path,
                stored_path=stored,
                original_name=original,
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Adjuntos", str(exc))
            return
        self._refresh_attachments()

    def _attach_open(self) -> None:
        item = self.attach_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if data:
            _, stored = data
            open_file(stored)

    def _attach_remove(self) -> None:
        item = self.attach_list.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not data:
            return
        attach_id, _ = data
        if not confirm(self, "Adjuntos", "¿Quitar este documento?"):
            return
        self.repo.delete_attachment(int(attach_id))
        self._refresh_attachments()

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...db import now_iso
from ...repositories import Repository
from ..common import confirm, info, warn


class ClientsPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_id: int | None = None

        title = QLabel("Clientes")
        title.setObjectName("PageTitle")

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nombre / teléfono / correo…")
        self.search.textChanged.connect(self.refresh)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Nombre", "Teléfono", "Correo", "Dirección", "Registro"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        # Form
        self.in_name = QLineEdit()
        self.in_phone = QLineEdit()
        self.in_email = QLineEdit()
        self.in_address = QLineEdit()
        self.in_notes = QTextEdit()
        self.in_notes.setFixedHeight(90)

        self.history = QTableWidget(0, 4)
        self.history.setHorizontalHeaderLabels(["Fecha", "Tipo", "Detalle", "Estado / monto"])
        self.history.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history.horizontalHeader().setStretchLastSection(True)

        form = QFormLayout()
        form.addRow("Nombre:", self.in_name)
        form.addRow("Teléfono:", self.in_phone)
        form.addRow("Correo:", self.in_email)
        form.addRow("Dirección:", self.in_address)
        form.addRow("Observaciones:", self.in_notes)

        self.btn_new = QPushButton("Nuevo")
        self.btn_save = QPushButton("Guardar")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_delete.clicked.connect(self._delete)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_save)
        btns.addWidget(self.btn_delete)
        btns.addStretch(1)

        layout = QGridLayout()
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(self.search, 1, 0, 1, 2)
        layout.addWidget(self.table, 2, 0, 1, 1)

        details = QWidget()
        details_layout = QVBoxLayout()
        details_layout.addLayout(form)
        details_layout.addLayout(btns)
        details_layout.addStretch(1)
        details.setLayout(details_layout)

        history_page = QWidget()
        history_layout = QVBoxLayout()
        history_help = QLabel("Historial consolidado del cliente: casos, sesiones e ingresos registrados.")
        history_help.setObjectName("MutedText")
        history_layout.addWidget(history_help)
        history_layout.addWidget(self.history)
        history_page.setLayout(history_layout)

        tabs = QTabWidget()
        tabs.addTab(details, "Datos")
        tabs.addTab(history_page, "Historial")

        right = QVBoxLayout()
        right.addWidget(tabs)
        layout.addLayout(right, 2, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        self.refresh()

    def refresh(self) -> None:
        rows = self.repo.list_clients(self.search.text())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(row["name"] or ""))
            self.table.setItem(r, 2, QTableWidgetItem(row["phone"] or ""))
            self.table.setItem(r, 3, QTableWidgetItem(row["email"] or ""))
            self.table.setItem(r, 4, QTableWidgetItem(row["address"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(row["created_at"] or ""))
        self.table.resizeColumnsToContents()
        self._refresh_history()


    def _refresh_history(self) -> None:
        if self.selected_id is None:
            self.history.setRowCount(0)
            return
        rows = self.repo.client_history(self.selected_id)
        self.history.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            self.history.setItem(row_index, 0, QTableWidgetItem(item["date"] or ""))
            self.history.setItem(row_index, 1, QTableWidgetItem(item["type"] or ""))
            self.history.setItem(row_index, 2, QTableWidgetItem(item["detail"] or ""))
            self.history.setItem(row_index, 3, QTableWidgetItem(item["status"] or ""))
        self.history.resizeColumnsToContents()

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        client_id = int(self.table.item(row, 0).text())
        self.selected_id = client_id
        selected = [c for c in self.repo.list_clients() if int(c["id"]) == client_id]
        if not selected:
            return
        c = selected[0]
        self.in_name.setText(c["name"] or "")
        self.in_phone.setText(c["phone"] or "")
        self.in_email.setText(c["email"] or "")
        self.in_address.setText(c["address"] or "")
        self.in_notes.setPlainText(c["notes"] or "")
        self._refresh_history()

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self.in_name.setText("")
        self.in_phone.setText("")
        self.in_email.setText("")
        self.in_address.setText("")
        self.in_notes.setPlainText("")
        self.history.setRowCount(0)
        self.in_name.setFocus()

    def _save(self) -> None:
        name = self.in_name.text().strip()
        if not name:
            warn(self, "Clientes", "El nombre es requerido.")
            return

        payload = dict(
            name=name,
            phone=self.in_phone.text(),
            email=self.in_email.text(),
            address=self.in_address.text(),
            notes=self.in_notes.toPlainText(),
        )

        if self.selected_id is None:
            self.repo.create_client(created_at=now_iso(), **payload)
            info(self, "Clientes", "Cliente creado.")
        else:
            self.repo.update_client(self.selected_id, **payload)
            info(self, "Clientes", "Cliente actualizado.")
        self.refresh()

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Clientes", "Selecciona un cliente.")
            return
        if not confirm(self, "Clientes", "¿Eliminar este cliente? (también borra sus sesiones)"):
            return
        self.repo.delete_client(self.selected_id)
        self._new()
        self.refresh()


from __future__ import annotations

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...db import now_iso
from ...repositories import Repository
from ..common import confirm, info, warn


class PayrollPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_id: int | None = None

        title = QLabel("Nóminas")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Registra pagos de personal; cada nómina también se refleja como gasto operativo.")
        subtitle.setObjectName("MutedText")

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "Empleado", "Cargo", "Periodo", "Monto", "Pago", "Notas"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.employee = QLineEdit()
        self.employee.setPlaceholderText("Nombre del empleado")
        self.role = QLineEdit()
        self.role.setPlaceholderText("Cargo / función")
        self.period = QLineEdit()
        self.period.setPlaceholderText("Ej. Junio 2026, Quincena 1")
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0.00")
        self.payment_date = QDateEdit()
        self.payment_date.setCalendarPopup(True)
        self.payment_date.setDisplayFormat("yyyy-MM-dd")
        self.payment_date.setDate(QDate.currentDate())
        self.notes = QTextEdit()
        self.notes.setFixedHeight(90)

        form = QFormLayout()
        form.addRow("Empleado:", self.employee)
        form.addRow("Cargo:", self.role)
        form.addRow("Periodo:", self.period)
        form.addRow("Monto:", self.amount)
        form.addRow("Fecha de pago:", self.payment_date)
        form.addRow("Notas:", self.notes)

        self.btn_new = QPushButton("Nueva nómina")
        self.btn_save = QPushButton("Registrar nómina")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setObjectName("SecondaryButton")
        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_refresh.clicked.connect(self.refresh)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_new)
        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_delete)
        buttons.addWidget(self.btn_refresh)
        buttons.addStretch(1)

        editor = QGroupBox("Pago de nómina")
        editor_layout = QVBoxLayout()
        editor_layout.addLayout(form)
        editor_layout.addLayout(buttons)
        editor_layout.addStretch(1)
        editor.setLayout(editor_layout)

        layout = QGridLayout()
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(subtitle, 1, 0, 1, 2)
        layout.addWidget(self.table, 2, 0)
        layout.addWidget(editor, 2, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)
        self.refresh()
        self._new()

    def refresh(self) -> None:
        rows = self.repo.list_payrolls()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["employee_name"] or ""))
            self.table.setItem(row_index, 2, QTableWidgetItem(row["role"] or ""))
            self.table.setItem(row_index, 3, QTableWidgetItem(row["period"] or ""))
            self.table.setItem(row_index, 4, QTableWidgetItem(f'$ {self.repo.cents_to_text(int(row["amount_cents"] or 0))}'))
            self.table.setItem(row_index, 5, QTableWidgetItem(row["payment_date"] or ""))
            self.table.setItem(row_index, 6, QTableWidgetItem(row["notes"] or ""))
        self.table.resizeColumnsToContents()

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_id = None
            return
        row = items[0].row()
        self.selected_id = int(self.table.item(row, 0).text())
        selected = [item for item in self.repo.list_payrolls() if int(item["id"]) == self.selected_id]
        if not selected:
            return
        item = selected[0]
        self.employee.setText(item["employee_name"] or "")
        self.role.setText(item["role"] or "")
        self.period.setText(item["period"] or "")
        self.amount.setText(self.repo.cents_to_text(int(item["amount_cents"] or 0)))
        parsed = QDate.fromString(item["payment_date"] or "", "yyyy-MM-dd")
        if parsed.isValid():
            self.payment_date.setDate(parsed)
        self.notes.setPlainText(item["notes"] or "")

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self.employee.clear()
        self.role.clear()
        self.period.clear()
        self.amount.clear()
        self.payment_date.setDate(QDate.currentDate())
        self.notes.clear()
        self.employee.setFocus()

    def _save(self) -> None:
        if self.selected_id is not None:
            warn(self, "Nóminas", "Para evitar descuadres contables, elimina y registra de nuevo si necesitas corregir una nómina.")
            return
        try:
            self.repo.create_payroll(
                employee_name=self.employee.text(),
                role=self.role.text(),
                period=self.period.text(),
                amount_text=self.amount.text(),
                payment_date=self.payment_date.date().toString("yyyy-MM-dd"),
                notes=self.notes.toPlainText(),
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Nóminas", str(exc))
            return
        info(self, "Nóminas", "Nómina registrada como gasto.")
        self._new()
        self.refresh()

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Nóminas", "Selecciona una nómina.")
            return
        if not confirm(self, "Nóminas", "¿Eliminar esta nómina y su gasto asociado?"):
            return
        self.repo.delete_payroll(self.selected_id)
        self._new()
        self.refresh()

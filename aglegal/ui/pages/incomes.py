from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGridLayout,
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


class IncomesPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_id: int | None = None

        title = QLabel("Ingresos")
        title.setObjectName("PageTitle")

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Cliente", "Concepto", "Monto", "Fecha", "Creado"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.in_client = QComboBox()
        self.in_client.addItem("(Sin cliente)", None)
        self.in_concept = QLineEdit()
        self.in_amount = QLineEdit()
        self.in_amount.setPlaceholderText("0.00")
        self.in_date = QLineEdit()
        self.in_date.setPlaceholderText("YYYY-MM-DD")

        form = QFormLayout()
        form.addRow("Cliente:", self.in_client)
        form.addRow("Concepto:", self.in_concept)
        form.addRow("Monto:", self.in_amount)
        form.addRow("Fecha:", self.in_date)

        self.btn_new = QPushButton("Nuevo")
        self.btn_add = QPushButton("Registrar")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_refresh = QPushButton("Actualizar")
        self.btn_new.clicked.connect(self._new)
        self.btn_add.clicked.connect(self._add)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_refresh.clicked.connect(self.refresh)

        btns = QHBoxLayout()
        btns.addWidget(self.btn_new)
        btns.addWidget(self.btn_add)
        btns.addWidget(self.btn_delete)
        btns.addWidget(self.btn_refresh)
        btns.addStretch(1)

        layout = QGridLayout()
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addWidget(self.table, 1, 0, 1, 1)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(btns)
        right.addStretch(1)
        layout.addLayout(right, 1, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        self.refresh()
        self._new()

    def refresh(self) -> None:
        self._refresh_clients()
        rows = self.repo.list_incomes()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(row["client_name"] or ""))
            self.table.setItem(r, 2, QTableWidgetItem(row["concept"] or ""))
            self.table.setItem(r, 3, QTableWidgetItem(self.repo.cents_to_text(int(row["amount_cents"] or 0))))
            self.table.setItem(r, 4, QTableWidgetItem(row["income_date"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(row["created_at"] or ""))
        self.table.resizeColumnsToContents()

    def _refresh_clients(self) -> None:
        current = self.in_client.currentData()
        self.in_client.blockSignals(True)
        self.in_client.clear()
        self.in_client.addItem("(Sin cliente)", None)
        for cid, name in self.repo.client_choices():
            self.in_client.addItem(name, cid)
        if current is not None:
            idx = self.in_client.findData(current)
            if idx >= 0:
                self.in_client.setCurrentIndex(idx)
        self.in_client.blockSignals(False)

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_id = None
            return
        row = items[0].row()
        self.selected_id = int(self.table.item(row, 0).text())

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self._refresh_clients()
        self.in_concept.setText("")
        self.in_amount.setText("")
        self.in_date.setText("")

    def _add(self) -> None:
        concept = self.in_concept.text().strip()
        amount = self.in_amount.text().strip()
        income_date = self.in_date.text().strip()
        if not concept or not amount or not income_date:
            warn(self, "Ingresos", "Concepto, monto y fecha son requeridos.")
            return
        try:
            self.repo.create_income(
                client_id=self.in_client.currentData(),
                concept=concept,
                amount_text=amount,
                income_date=income_date,
                created_at=now_iso(),
            )
        except Exception as e:
            warn(self, "Ingresos", str(e))
            return
        info(self, "Ingresos", "Ingreso registrado.")
        self.refresh()

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Ingresos", "Selecciona un ingreso.")
            return
        if not confirm(self, "Ingresos", "¿Eliminar este ingreso?"):
            return
        self.repo.delete_income(self.selected_id)
        self._new()
        self.refresh()


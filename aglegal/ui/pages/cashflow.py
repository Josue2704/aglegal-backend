from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis

from ...db import now_iso
from ...repositories import Repository
from ..common import confirm, info, open_file, warn


@dataclass(frozen=True)
class DateRange:
    start: date | None
    end: date | None

    def to_iso(self) -> tuple[str | None, str | None]:
        return (self.start.isoformat() if self.start else None, self.end.isoformat() if self.end else None)


class CashflowPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_type: str | None = None
        self.selected_id: int | None = None
        self.active_range = DateRange(None, None)

        title = QLabel("Finanzas")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Registra ingresos y gastos por separado; usa el resumen para decidir, no para adivinar.")
        subtitle.setObjectName("MutedText")

        self.period = QComboBox()
        self.period.addItems(["Mes actual", "Trimestre actual", "Año actual", "Personalizado", "Todo"])
        self.period.currentIndexChanged.connect(self._on_period_changed)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.dateChanged.connect(lambda *_: self._on_custom_changed())
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.dateChanged.connect(lambda *_: self._on_custom_changed())
        self.btn_apply = QPushButton("Aplicar periodo")
        self.btn_apply.clicked.connect(self._apply_filters)
        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.clicked.connect(self.refresh)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Periodo:"))
        filters.addWidget(self.period)
        filters.addWidget(QLabel("Desde:"))
        filters.addWidget(self.start_date)
        filters.addWidget(QLabel("Hasta:"))
        filters.addWidget(self.end_date)
        filters.addWidget(self.btn_apply)
        filters.addStretch(1)
        filters.addWidget(self.btn_refresh)

        self.lbl_incomes = QLabel("-")
        self.lbl_expenses = QLabel("-")
        self.lbl_balance = QLabel("-")
        self.lbl_margin = QLabel("-")
        self.card_income = _kpi_card("Ingresos del periodo", "-")
        self.card_expense = _kpi_card("Gastos del periodo", "-")
        self.card_balance = _kpi_card("Resultado neto", "-")
        self.card_margin = _kpi_card("Margen operativo", "-")

        kpis = QGridLayout()
        kpis.addWidget(self.card_income, 0, 0)
        kpis.addWidget(self.card_expense, 0, 1)
        kpis.addWidget(self.card_balance, 0, 2)
        kpis.addWidget(self.card_margin, 0, 3)

        self.chart_monthly = QChartView()
        self.chart_monthly.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_monthly.setMinimumHeight(260)
        self.chart_expenses = QChartView()
        self.chart_expenses.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_expenses.setMinimumHeight(260)

        analysis = QWidget()
        analysis_layout = QGridLayout()
        analysis_layout.addWidget(_wrap("Tendencia de ingresos vs gastos", self.chart_monthly), 0, 0)
        analysis_layout.addWidget(_wrap("Dónde se está yendo el dinero", self.chart_expenses), 0, 1)
        analysis_layout.setColumnStretch(0, 2)
        analysis_layout.setColumnStretch(1, 1)
        analysis.setLayout(analysis_layout)

        self.in_table = QTableWidget(0, 7)
        self.in_table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Caso", "Servicio", "Detalle", "Monto"])
        self.in_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.in_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.in_table.itemSelectionChanged.connect(self._on_income_select)
        self.in_table.horizontalHeader().setStretchLastSection(True)
        self.in_client = QComboBox()
        self.in_client.addItem("(Sin cliente)", None)
        self.in_client.currentIndexChanged.connect(lambda *_: self._refresh_income_cases())
        self.in_case = QComboBox()
        self.in_case.addItem("(Sin caso)", None)
        self.in_category = QComboBox()
        self.in_category.addItem("(Sin categoría)", None)
        self.in_detail = QLineEdit()
        self.in_detail.setPlaceholderText("Ej. honorarios caso López, escritura, asesoría mensual")
        self.in_amount = QLineEdit()
        self.in_amount.setPlaceholderText("0.00")
        self.in_date = QDateEdit()
        self.in_date.setCalendarPopup(True)
        self.in_date.setDisplayFormat("yyyy-MM-dd")
        self.in_date.setDate(QDate.currentDate())
        income_page = self._money_page(
            "Registrar ingreso",
            "Dinero que entra al despacho por honorarios, servicios u otros cobros.",
            self.in_table,
            [("Cliente:", self.in_client), ("Caso/servicio:", self.in_case), ("Categoría:", self.in_category), ("Detalle:", self.in_detail), ("Monto:", self.in_amount), ("Fecha:", self.in_date)],
            self._income_add,
            self._income_delete,
        )

        self.cost_table = QTableWidget(0, 7)
        self.cost_table.setHorizontalHeaderLabels(["ID", "Fecha", "Cliente", "Caso", "Categoría", "Detalle", "Monto"])
        self.cost_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.cost_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cost_table.itemSelectionChanged.connect(self._on_cost_select)
        self.cost_table.horizontalHeader().setStretchLastSection(True)
        self.cost_client = QComboBox()
        self.cost_client.addItem("(Sin cliente)", None)
        self.cost_client.currentIndexChanged.connect(lambda *_: self._refresh_cost_cases())
        self.cost_case = QComboBox()
        self.cost_case.addItem("(Sin caso)", None)
        self.cost_category = QComboBox()
        self.cost_category.addItem("(Sin categoría)", None)
        self.cost_detail = QLineEdit()
        self.cost_detail.setPlaceholderText("Ej. compra del producto, trámite directo, comisión, subcontratación")
        self.cost_amount = QLineEdit()
        self.cost_amount.setPlaceholderText("0.00")
        self.cost_date = QDateEdit()
        self.cost_date.setCalendarPopup(True)
        self.cost_date.setDisplayFormat("yyyy-MM-dd")
        self.cost_date.setDate(QDate.currentDate())
        self.cost_notes = QLineEdit()
        cost_page = self._money_page(
            "Registrar costo",
            "Costo directo de producir/adquirir lo que se vende. Afecta utilidad bruta por cliente y servicio.",
            self.cost_table,
            [("Cliente:", self.cost_client), ("Caso/servicio:", self.cost_case), ("Categoría:", self.cost_category), ("Detalle:", self.cost_detail), ("Monto:", self.cost_amount), ("Fecha:", self.cost_date), ("Observación:", self.cost_notes)],
            self._cost_add,
            self._cost_delete,
        )

        self.ex_table = QTableWidget(0, 5)
        self.ex_table.setHorizontalHeaderLabels(["ID", "Fecha", "Categoría", "Detalle", "Monto"])
        self.ex_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ex_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.ex_table.itemSelectionChanged.connect(self._on_expense_select)
        self.ex_table.horizontalHeader().setStretchLastSection(True)
        self.ex_category = QComboBox()
        self.ex_category.addItem("(Sin categoría)", None)
        self.ex_detail = QLineEdit()
        self.ex_detail.setPlaceholderText("Ej. papelería, transporte, impuestos, servicios")
        self.ex_amount = QLineEdit()
        self.ex_amount.setPlaceholderText("0.00")
        self.ex_date = QDateEdit()
        self.ex_date.setCalendarPopup(True)
        self.ex_date.setDisplayFormat("yyyy-MM-dd")
        self.ex_date.setDate(QDate.currentDate())
        self.ex_notes = QLineEdit()
        expense_page = self._money_page(
            "Registrar gasto",
            "Costos y salidas de dinero. Úsalo para controlar operación, facturas y compras.",
            self.ex_table,
            [("Categoría:", self.ex_category), ("Detalle:", self.ex_detail), ("Monto:", self.ex_amount), ("Fecha:", self.ex_date), ("Observación:", self.ex_notes)],
            self._expense_add,
            self._expense_delete,
        )

        self.attach_list = QListWidget()
        self.attach_list.currentItemChanged.connect(lambda *_: self._on_attach_select())
        self.btn_attach_add = QPushButton("Adjuntar factura / comprobante")
        self.btn_attach_open = QPushButton("Abrir")
        self.btn_attach_open.setObjectName("SecondaryButton")
        self.btn_attach_remove = QPushButton("Quitar")
        self.btn_attach_remove.setObjectName("SecondaryButton")
        self.btn_attach_add.clicked.connect(self._attach_add)
        self.btn_attach_open.clicked.connect(self._attach_open)
        self.btn_attach_remove.clicked.connect(self._attach_remove)
        attachments_page = QWidget()
        attachments_layout = QVBoxLayout()
        attachments_layout.addWidget(QLabel("Selecciona un ingreso, costo o gasto en su pestaña y adjunta el comprobante aquí."))
        attachments_layout.addWidget(self.attach_list, 1)
        attach_btns = QHBoxLayout()
        attach_btns.addWidget(self.btn_attach_add)
        attach_btns.addWidget(self.btn_attach_open)
        attach_btns.addWidget(self.btn_attach_remove)
        attach_btns.addStretch(1)
        attachments_layout.addLayout(attach_btns)
        attachments_page.setLayout(attachments_layout)

        self.tabs = QTabWidget()
        self.tabs.addTab(analysis, "Resumen")
        self.tabs.addTab(income_page, "Ingresos")
        self.tabs.addTab(cost_page, "Costos")
        self.tabs.addTab(expense_page, "Gastos")
        self.tabs.addTab(attachments_page, "Comprobantes")

        root = QVBoxLayout()
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(filters)
        root.addLayout(kpis)
        root.addWidget(self.tabs, 1)
        self.setLayout(root)

        self._init_default_period()
        self.refresh()

    def _money_page(self, title: str, help_text: str, table: QTableWidget, fields: list[tuple[str, QWidget]], save_cb, delete_cb) -> QWidget:
        page = QWidget()
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        help_label = QLabel(help_text)
        help_label.setObjectName("MutedText")
        form = QFormLayout()
        for label, widget in fields:
            form.addRow(label, widget)
        btn_save = QPushButton(title)
        btn_delete = QPushButton("Eliminar seleccionado")
        btn_delete.setObjectName("SecondaryButton")
        btn_save.clicked.connect(save_cb)
        btn_delete.clicked.connect(delete_cb)
        buttons = QHBoxLayout()
        buttons.addWidget(btn_save)
        buttons.addWidget(btn_delete)
        buttons.addStretch(1)
        editor = QGroupBox("Formulario")
        editor_layout = QVBoxLayout()
        editor_layout.addLayout(form)
        editor_layout.addLayout(buttons)
        editor.setLayout(editor_layout)
        layout = QGridLayout()
        layout.addWidget(heading, 0, 0, 1, 2)
        layout.addWidget(help_label, 1, 0, 1, 2)
        layout.addWidget(table, 2, 0)
        layout.addWidget(editor, 2, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        page.setLayout(layout)
        return page

    def refresh(self) -> None:
        self._refresh_clients()
        self._refresh_categories()
        self._refresh_incomes()
        self._refresh_costs()
        self._refresh_expenses()
        self._refresh_summary()
        self._refresh_charts()
        self._refresh_attachments()

    def _refresh_clients(self) -> None:
        current = self.in_client.currentData()
        self.in_client.blockSignals(True)
        self.in_client.clear()
        self.in_client.addItem("(Sin cliente)", None)
        for client_id, name in self.repo.client_choices():
            self.in_client.addItem(name, client_id)
        if current is not None:
            index = self.in_client.findData(current)
            if index >= 0:
                self.in_client.setCurrentIndex(index)
        self.in_client.blockSignals(False)
        self._refresh_income_cases()

        current_cost = self.cost_client.currentData()
        self.cost_client.blockSignals(True)
        self.cost_client.clear()
        self.cost_client.addItem("(Sin cliente)", None)
        for client_id, name in self.repo.client_choices():
            self.cost_client.addItem(name, client_id)
        if current_cost is not None:
            index = self.cost_client.findData(current_cost)
            if index >= 0:
                self.cost_client.setCurrentIndex(index)
        self.cost_client.blockSignals(False)
        self._refresh_cost_cases()

    def _refresh_income_cases(self) -> None:
        current = self.in_case.currentData()
        client_id = self.in_client.currentData()
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

    def _refresh_cost_cases(self) -> None:
        current = self.cost_case.currentData()
        client_id = self.cost_client.currentData()
        self.cost_case.blockSignals(True)
        self.cost_case.clear()
        self.cost_case.addItem("(Sin caso)", None)
        if client_id:
            for case_id, title in self.repo.case_choices(client_id=int(client_id)):
                self.cost_case.addItem(title, case_id)
        if current is not None:
            index = self.cost_case.findData(current)
            if index >= 0:
                self.cost_case.setCurrentIndex(index)
        self.cost_case.blockSignals(False)

    def _refresh_categories(self) -> None:
        for combo, kind in [(self.in_category, "income"), (self.cost_category, "cost"), (self.ex_category, "expense")]:
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(Sin categoría)", None)
            for category_id, name in self.repo.category_choices(kind=kind):
                combo.addItem(name, category_id)
            if current is not None:
                index = combo.findData(current)
                if index >= 0:
                    combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _refresh_incomes(self) -> None:
        start_iso, end_iso = self.active_range.to_iso()
        rows = self.repo.list_incomes_range(start_date=start_iso, end_date=end_iso)
        self.in_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.in_table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.in_table.setItem(row_index, 1, QTableWidgetItem(row["income_date"] or ""))
            self.in_table.setItem(row_index, 2, QTableWidgetItem(row["client_name"] or ""))
            self.in_table.setItem(row_index, 3, QTableWidgetItem(row["case_title"] or ""))
            self.in_table.setItem(row_index, 4, QTableWidgetItem(row["product_name"] or row["category_name"] or ""))
            self.in_table.setItem(row_index, 5, QTableWidgetItem(row["detail"] or row["concept"] or ""))
            self.in_table.setItem(row_index, 6, QTableWidgetItem(f'$ {self.repo.cents_to_text(int(row["amount_cents"] or 0))}'))
        self.in_table.resizeColumnsToContents()


    def _refresh_costs(self) -> None:
        start_iso, end_iso = self.active_range.to_iso()
        rows = self.repo.list_costs_range(start_date=start_iso, end_date=end_iso)
        self.cost_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.cost_table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.cost_table.setItem(row_index, 1, QTableWidgetItem(row["cost_date"] or ""))
            self.cost_table.setItem(row_index, 2, QTableWidgetItem(row["client_name"] or ""))
            self.cost_table.setItem(row_index, 3, QTableWidgetItem(row["case_title"] or ""))
            self.cost_table.setItem(row_index, 4, QTableWidgetItem(row["category_name"] or row["product_name"] or ""))
            self.cost_table.setItem(row_index, 5, QTableWidgetItem(row["detail"] or row["concept"] or ""))
            self.cost_table.setItem(row_index, 6, QTableWidgetItem(f'$ {self.repo.cents_to_text(int(row["amount_cents"] or 0))}'))
        self.cost_table.resizeColumnsToContents()

    def _refresh_expenses(self) -> None:
        start_iso, end_iso = self.active_range.to_iso()
        rows = self.repo.list_expenses_range(start_date=start_iso, end_date=end_iso)
        self.ex_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.ex_table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.ex_table.setItem(row_index, 1, QTableWidgetItem(row["expense_date"] or ""))
            self.ex_table.setItem(row_index, 2, QTableWidgetItem(row["category_name"] or ""))
            self.ex_table.setItem(row_index, 3, QTableWidgetItem(row["detail"] or row["concept"] or ""))
            self.ex_table.setItem(row_index, 4, QTableWidgetItem(f'$ {self.repo.cents_to_text(int(row["amount_cents"] or 0))}'))
        self.ex_table.resizeColumnsToContents()

    def _refresh_summary(self) -> None:
        start_iso, end_iso = self.active_range.to_iso()
        incomes_cents, expenses_cents = self.repo.cashflow_totals(start_date=start_iso, end_date=end_iso)
        balance = incomes_cents - expenses_cents
        margin = (balance / incomes_cents * 100) if incomes_cents else 0
        _set_kpi(self.card_income, f'$ {self.repo.cents_to_text(incomes_cents)}')
        _set_kpi(self.card_expense, f'$ {self.repo.cents_to_text(expenses_cents)}')
        _set_kpi(self.card_balance, f'$ {self.repo.cents_to_text(balance)}')
        _set_kpi(self.card_margin, f'{margin:.1f}%')

    def _refresh_charts(self) -> None:
        start_iso, end_iso = self.active_range.to_iso()
        rows = self.repo.cashflow_monthly(start_date=start_iso, end_date=end_iso)
        set_income = QBarSet("Ingresos")
        set_income.setColor(QColor("#2563eb"))
        set_expense = QBarSet("Gastos")
        set_expense.setColor(QColor("#ef4444"))
        labels = []
        for ym, income, expense in rows:
            labels.append(ym[-2:] if len(ym) == 7 else ym)
            set_income.append(income / 100)
            set_expense.append(expense / 100)
        if not labels:
            labels = ["Sin datos"]
            set_income.append(0)
            set_expense.append(0)
        series = QBarSeries()
        series.append(set_income)
        series.append(set_expense)
        chart = QChart()
        chart.addSeries(series)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)
        self.chart_monthly.setChart(chart)

        pie = QPieSeries()
        for name, cents in self.repo.category_totals(kind="expense", start_date=start_iso, end_date=end_iso)[:8]:
            if cents > 0:
                pie.append(name, cents / 100)
        chart2 = QChart()
        chart2.addSeries(pie)
        chart2.legend().setVisible(True)
        chart2.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
        self.chart_expenses.setChart(chart2)

    def _on_income_select(self) -> None:
        items = self.in_table.selectedItems()
        if not items:
            return
        self.selected_type = "income"
        self.selected_id = int(self.in_table.item(items[0].row(), 0).text())
        self.ex_table.clearSelection()
        self._refresh_attachments()


    def _on_cost_select(self) -> None:
        items = self.cost_table.selectedItems()
        if not items:
            return
        self.selected_type = "cost"
        self.selected_id = int(self.cost_table.item(items[0].row(), 0).text())
        self.in_table.clearSelection()
        self.ex_table.clearSelection()
        self._refresh_attachments()

    def _on_expense_select(self) -> None:
        items = self.ex_table.selectedItems()
        if not items:
            return
        self.selected_type = "expense"
        self.selected_id = int(self.ex_table.item(items[0].row(), 0).text())
        self.in_table.clearSelection()
        self._refresh_attachments()

    def _income_add(self) -> None:
        detail = self.in_detail.text().strip()
        amount = self.in_amount.text().strip()
        if not detail or not amount:
            warn(self, "Ingresos", "Detalle y monto son requeridos.")
            return
        try:
            self.repo.create_income(
                client_id=self.in_client.currentData(),
                category_id=self.in_category.currentData(),
                case_id=self.in_case.currentData(),
                detail=detail,
                amount_text=amount,
                income_date=self.in_date.date().toString("yyyy-MM-dd"),
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Ingresos", str(exc))
            return
        self.in_detail.clear()
        self.in_amount.clear()
        info(self, "Ingresos", "Ingreso registrado.")
        self.refresh()


    def _cost_add(self) -> None:
        detail = self.cost_detail.text().strip()
        amount = self.cost_amount.text().strip()
        if not detail or not amount:
            warn(self, "Costos", "Detalle y monto son requeridos.")
            return
        try:
            self.repo.create_cost(
                client_id=self.cost_client.currentData(),
                case_id=self.cost_case.currentData(),
                category_id=self.cost_category.currentData(),
                detail=detail,
                amount_text=amount,
                cost_date=self.cost_date.date().toString("yyyy-MM-dd"),
                notes=self.cost_notes.text(),
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Costos", str(exc))
            return
        self.cost_detail.clear()
        self.cost_amount.clear()
        self.cost_notes.clear()
        info(self, "Costos", "Costo registrado.")
        self.refresh()

    def _cost_delete(self) -> None:
        if self.selected_type != "cost" or self.selected_id is None:
            warn(self, "Costos", "Selecciona un costo.")
            return
        if confirm(self, "Costos", "¿Eliminar este costo?"):
            self.repo.delete_cost(self.selected_id)
            self.selected_type = None
            self.selected_id = None
            self.refresh()

    def _expense_add(self) -> None:
        detail = self.ex_detail.text().strip()
        amount = self.ex_amount.text().strip()
        if not detail or not amount:
            warn(self, "Gastos", "Detalle y monto son requeridos.")
            return
        try:
            self.repo.create_expense(
                category_id=self.ex_category.currentData(),
                detail=detail,
                amount_text=amount,
                expense_date=self.ex_date.date().toString("yyyy-MM-dd"),
                notes=self.ex_notes.text(),
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Gastos", str(exc))
            return
        self.ex_detail.clear()
        self.ex_amount.clear()
        self.ex_notes.clear()
        info(self, "Gastos", "Gasto registrado.")
        self.refresh()

    def _income_delete(self) -> None:
        if self.selected_type != "income" or self.selected_id is None:
            warn(self, "Ingresos", "Selecciona un ingreso.")
            return
        if confirm(self, "Ingresos", "¿Eliminar este ingreso?"):
            self.repo.delete_income(self.selected_id)
            self.selected_type = None
            self.selected_id = None
            self.refresh()

    def _expense_delete(self) -> None:
        if self.selected_type != "expense" or self.selected_id is None:
            warn(self, "Gastos", "Selecciona un gasto.")
            return
        if confirm(self, "Gastos", "¿Eliminar este gasto?"):
            self.repo.delete_expense(self.selected_id)
            self.selected_type = None
            self.selected_id = None
            self.refresh()

    def _refresh_attachments(self) -> None:
        self.attach_list.clear()
        valid = self.selected_type in ("income", "cost", "expense") and self.selected_id is not None
        self.btn_attach_add.setEnabled(valid)
        self.btn_attach_open.setEnabled(False)
        self.btn_attach_remove.setEnabled(False)
        if not valid:
            self.attach_list.addItem("Selecciona un ingreso, costo o gasto para ver comprobantes")
            self.attach_list.setEnabled(False)
            return
        self.attach_list.setEnabled(True)
        rows = self.repo.list_attachments(entity_type=self.selected_type, entity_id=self.selected_id)
        if not rows:
            self.attach_list.addItem("Sin comprobantes")
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
        if self.selected_type not in ("income", "cost", "expense") or self.selected_id is None:
            warn(self, "Comprobantes", "Selecciona un ingreso, costo o gasto primero.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Adjuntar comprobante")
        if not path:
            return
        original = Path(path).name
        stored = self.repo.suggest_attachment_path(self.selected_type, self.selected_id, original)
        try:
            self.repo.add_attachment(
                entity_type=self.selected_type,
                entity_id=self.selected_id,
                source_path=path,
                stored_path=stored,
                original_name=original,
                created_at=now_iso(),
            )
        except Exception as exc:
            warn(self, "Comprobantes", str(exc))
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
        if confirm(self, "Comprobantes", "¿Quitar este comprobante?"):
            self.repo.delete_attachment(int(attach_id))
            self._refresh_attachments()

    def _init_default_period(self) -> None:
        today = date.today()
        self.start_date.setDate(QDate(today.year, today.month, 1))
        self.end_date.setDate(QDate.currentDate())
        self._on_period_changed()

    def _on_period_changed(self) -> None:
        label = self.period.currentText()
        today = date.today()
        if label == "Todo":
            self.start_date.setEnabled(False)
            self.end_date.setEnabled(False)
            self.active_range = DateRange(None, None)
            self.refresh()
            return
        self.start_date.setEnabled(True)
        self.end_date.setEnabled(True)
        if label == "Personalizado":
            self._apply_filters()
            return
        if label == "Mes actual":
            start = today.replace(day=1)
        elif label == "Año actual":
            start = today.replace(month=1, day=1)
        else:
            quarter = (today.month - 1) // 3
            start = today.replace(month=quarter * 3 + 1, day=1)
        self.start_date.blockSignals(True)
        self.end_date.blockSignals(True)
        self.start_date.setDate(QDate(start.year, start.month, start.day))
        self.end_date.setDate(QDate.currentDate())
        self.start_date.blockSignals(False)
        self.end_date.blockSignals(False)
        self._apply_filters()

    def _on_custom_changed(self) -> None:
        if self.period.currentText() == "Personalizado":
            self._apply_filters()

    def _apply_filters(self) -> None:
        if self.period.currentText() == "Todo":
            self.active_range = DateRange(None, None)
        else:
            start = self.start_date.date().toPython()
            end = self.end_date.date().toPython()
            if end < start:
                warn(self, "Periodo", "La fecha final no puede ser menor a la inicial.")
                return
            self.active_range = DateRange(start, end)
        self.refresh()


def _wrap(title: str, widget: QWidget) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget)
    box.setLayout(layout)
    return box


def _kpi_card(label: str, value: str) -> QGroupBox:
    box = QGroupBox()
    box.setObjectName("KpiCard")
    label_widget = QLabel(label)
    label_widget.setObjectName("KpiLabel")
    value_widget = QLabel(value)
    value_widget.setObjectName("KpiValue")
    layout = QVBoxLayout()
    layout.addWidget(label_widget)
    layout.addWidget(value_widget)
    box.setLayout(layout)
    return box


def _set_kpi(card: QGroupBox, value: str) -> None:
    value_widget = card.findChild(QLabel, "KpiValue")
    if value_widget:
        value_widget.setText(value)

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QPieSeries, QValueAxis

from ...repositories import Repository


class DashboardPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo

        title = QLabel("Panel de control")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Operación, rentabilidad y gastos fuertes en una vista ejecutiva.")
        subtitle.setObjectName("MutedText")

        self.btn_refresh = QPushButton("Actualizar")
        self.btn_refresh.setObjectName("SecondaryButton")
        self.btn_refresh.clicked.connect(self.refresh)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch(1)
        header.addWidget(self.btn_refresh)

        self.kpi_open_cases = _kpi_card("Casos abiertos", "-")
        self.kpi_urgent_cases = _kpi_card("Prioridad alta", "-")
        self.kpi_next_sessions = _kpi_card("Sesiones próximos 7 días", "-")
        self.kpi_overdue_tasks = _kpi_card("Tareas vencidas", "-")
        self.kpi_month_income = _kpi_card("Ingresos del mes", "-")
        self.kpi_month_expense = _kpi_card("Gastos del mes", "-")
        self.kpi_month_balance = _kpi_card("Balance del mes", "-")
        self.kpi_closed_rate = _kpi_card("Sesiones finalizadas", "-")

        self.chart_cashflow = QChartView()
        self.chart_cashflow.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_cashflow.setMinimumHeight(260)
        self.chart_expenses = QChartView()
        self.chart_expenses.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_expenses.setMinimumHeight(260)
        self.upcoming_list = QListWidget()
        self.risk_list = QListWidget()

        self.kpi_top_service = _kpi_card("Servicio más rentable", "-")
        self.kpi_top_client = _kpi_card("Cliente más rentable", "-")
        self.kpi_top_expense = _kpi_card("Gasto más cabrón", "-")
        self.kpi_net_margin = _kpi_card("Margen bruto del mes", "-")
        self.chart_services = QChartView()
        self.chart_services.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_services.setMinimumHeight(280)
        self.chart_clients = QChartView()
        self.chart_clients.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_clients.setMinimumHeight(280)
        self.chart_expense_rank = QChartView()
        self.chart_expense_rank.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_expense_rank.setMinimumHeight(280)
        self.services_list = QListWidget()
        self.clients_list = QListWidget()
        self.expenses_list = QListWidget()

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_operations_tab(), "Operación")
        self.tabs.addTab(self._build_profitability_tab(), "Rentabilidad")

        root = QVBoxLayout()
        root.addLayout(header)
        root.addWidget(self.tabs, 1)
        self.setLayout(root)
        self.refresh()

    def _build_operations_tab(self) -> QWidget:
        page = QWidget()
        kpis = QGridLayout()
        cards = [
            self.kpi_open_cases,
            self.kpi_urgent_cases,
            self.kpi_next_sessions,
            self.kpi_overdue_tasks,
            self.kpi_month_income,
            self.kpi_month_expense,
            self.kpi_month_balance,
            self.kpi_closed_rate,
        ]
        for index, card in enumerate(cards):
            kpis.addWidget(card, index // 4, index % 4)

        charts = QGridLayout()
        charts.addWidget(_wrap("Tendencia últimos 6 meses", self.chart_cashflow), 0, 0)
        charts.addWidget(_wrap("Top gastos del mes", self.chart_expenses), 0, 1)
        charts.setColumnStretch(0, 2)
        charts.setColumnStretch(1, 1)

        lists = QGridLayout()
        lists.addWidget(_wrap("Agenda próxima", self.upcoming_list), 0, 0)
        lists.addWidget(_wrap("Atención requerida", self.risk_list), 0, 1)

        layout = QVBoxLayout()
        layout.addLayout(kpis)
        layout.addLayout(charts)
        layout.addLayout(lists)
        page.setLayout(layout)
        return page

    def _build_profitability_tab(self) -> QWidget:
        page = QWidget()
        note = QLabel("Rentabilidad = ingresos - costos directos. Los gastos operativos se analizan aparte.")
        note.setObjectName("MutedText")
        kpis = QGridLayout()
        for index, card in enumerate([self.kpi_top_service, self.kpi_top_client, self.kpi_top_expense, self.kpi_net_margin]):
            kpis.addWidget(card, 0, index)

        charts = QGridLayout()
        charts.addWidget(_wrap("Servicios que más facturan", self.chart_services), 0, 0)
        charts.addWidget(_wrap("Clientes que más facturan", self.chart_clients), 0, 1)
        charts.addWidget(_wrap("Gastos más fuertes", self.chart_expense_rank), 0, 2)
        charts.setColumnStretch(0, 1)
        charts.setColumnStretch(1, 1)
        charts.setColumnStretch(2, 1)

        lists = QGridLayout()
        lists.addWidget(_wrap("Ranking servicios", self.services_list), 0, 0)
        lists.addWidget(_wrap("Ranking clientes", self.clients_list), 0, 1)
        lists.addWidget(_wrap("Ranking gastos", self.expenses_list), 0, 2)

        layout = QVBoxLayout()
        layout.addWidget(note)
        layout.addLayout(kpis)
        layout.addLayout(charts)
        layout.addLayout(lists)
        page.setLayout(layout)
        return page

    def refresh(self) -> None:
        month = self.repo.dashboard_metrics_month()
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        today_iso = today.isoformat()
        next_week = (today + timedelta(days=7)).isoformat()

        open_cases = self.repo.conn.execute("SELECT COUNT(1) AS n FROM cases WHERE status <> 'Cerrado'").fetchone()["n"]
        urgent_cases = self.repo.conn.execute("SELECT COUNT(1) AS n FROM cases WHERE status <> 'Cerrado' AND priority='Alta'").fetchone()["n"]
        next_sessions = self.repo.conn.execute(
            "SELECT COUNT(1) AS n FROM sessions WHERE session_date >= ? AND session_date <= ? AND status <> 'Finalizada'",
            (today_iso, next_week),
        ).fetchone()["n"]
        overdue_tasks = self.repo.conn.execute(
            "SELECT COUNT(1) AS n FROM case_tasks WHERE done=0 AND due_date IS NOT NULL AND due_date < ?",
            (today_iso,),
        ).fetchone()["n"]
        sessions_total = max(int(month["sessions_total"]), 0)
        finalized = int(month["sessions_finalized"])
        closed_rate = (finalized / sessions_total * 100) if sessions_total else 0
        income = int(month["incomes_cents"])
        expense = int(month["expenses_cents"])
        cost = self.repo.cost_totals(start_date=month_start, end_date=today_iso)
        balance = income - expense
        gross_profit = income - cost
        margin = (gross_profit / income * 100) if income else 0

        _set_kpi(self.kpi_open_cases, str(open_cases))
        _set_kpi(self.kpi_urgent_cases, str(urgent_cases))
        _set_kpi(self.kpi_next_sessions, str(next_sessions))
        _set_kpi(self.kpi_overdue_tasks, str(overdue_tasks))
        _set_kpi(self.kpi_month_income, f'$ {self.repo.cents_to_text(income)}')
        _set_kpi(self.kpi_month_expense, f'$ {self.repo.cents_to_text(expense)}')
        _set_kpi(self.kpi_month_balance, f'$ {self.repo.cents_to_text(balance)}')
        _set_kpi(self.kpi_closed_rate, f'{closed_rate:.0f}%')
        _set_kpi(self.kpi_net_margin, f'{margin:.1f}%')

        self._refresh_cashflow_chart()
        self._refresh_expense_pie(month_start, today_iso)
        self._refresh_lists(today_iso, next_week)
        self._refresh_profitability(month_start, today_iso)

    def _refresh_profitability(self, start: str, end: str) -> None:
        services = self.repo.top_services_by_gross_profit(start_date=start, end_date=end, limit=8)
        clients = self.repo.top_clients_by_gross_profit(start_date=start, end_date=end, limit=8)
        expenses = self.repo.top_expenses_by_category(start_date=start, end_date=end, limit=8)

        _set_kpi(self.kpi_top_service, _profit_label(self.repo, services[0]) if services else "Sin datos")
        _set_kpi(self.kpi_top_client, _profit_label(self.repo, clients[0]) if clients else "Sin datos")
        _set_kpi(self.kpi_top_expense, _money_label(self.repo, expenses[0]) if expenses else "Sin datos")

        self.chart_services.setChart(_bar_chart("Servicios", [(name, profit) for name, _, _, profit in services], self.repo, "#2563eb"))
        self.chart_clients.setChart(_bar_chart("Clientes", [(name, profit) for name, _, _, profit in clients], self.repo, "#16a34a"))
        self.chart_expense_rank.setChart(_bar_chart("Gastos", expenses, self.repo, "#ef4444"))

        _fill_profit_list(self.services_list, services, self.repo, empty="Vincula ingresos y costos a casos para ver utilidad por servicio")
        _fill_profit_list(self.clients_list, clients, self.repo, empty="Sin utilidad por cliente este mes")
        _fill_money_list(self.expenses_list, expenses, self.repo, empty="Sin gastos este mes")

    def _refresh_lists(self, today_iso: str, next_week: str) -> None:
        self.upcoming_list.clear()
        sessions = self.repo.conn.execute(
            """
            SELECT s.session_date, s.consult_type, s.status, c.name AS client_name, cs.title AS case_title
            FROM sessions s
            JOIN clients c ON c.id=s.client_id
            LEFT JOIN cases cs ON cs.id=s.case_id
            WHERE s.session_date >= ? AND s.session_date <= ?
            ORDER BY s.session_date ASC, s.id ASC
            LIMIT 8
            """,
            (today_iso, next_week),
        ).fetchall()
        if not sessions:
            self.upcoming_list.addItem("Sin sesiones próximas registradas")
        for row in sessions:
            case_text = f' · {row["case_title"]}' if row["case_title"] else ""
            self.upcoming_list.addItem(f'{row["session_date"]} · {row["client_name"]}{case_text} · {row["consult_type"]}')

        self.risk_list.clear()
        tasks = self.repo.conn.execute(
            """
            SELECT t.title, t.due_date, cs.title AS case_title, cl.name AS client_name
            FROM case_tasks t
            JOIN cases cs ON cs.id=t.case_id
            JOIN clients cl ON cl.id=cs.client_id
            WHERE t.done=0 AND t.due_date IS NOT NULL AND t.due_date <= ?
            ORDER BY t.due_date ASC
            LIMIT 8
            """,
            (next_week,),
        ).fetchall()
        high_cases = self.repo.conn.execute(
            """
            SELECT cs.title, cl.name AS client_name, cs.status
            FROM cases cs
            JOIN clients cl ON cl.id=cs.client_id
            WHERE cs.status <> 'Cerrado' AND cs.priority='Alta'
            ORDER BY cs.id DESC
            LIMIT 5
            """
        ).fetchall()
        if not tasks and not high_cases:
            self.risk_list.addItem("Sin alertas críticas por ahora")
        for row in tasks:
            self.risk_list.addItem(f'Tarea: {row["due_date"]} · {row["client_name"]} · {row["title"]}')
        for row in high_cases:
            self.risk_list.addItem(f'Alta prioridad: {row["client_name"]} · {row["title"]} · {row["status"]}')

    def _refresh_cashflow_chart(self) -> None:
        today = date.today()
        months = []
        year, month = today.year, today.month
        for _ in range(6):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        months.reverse()
        rows = self.repo.cashflow_monthly(start_date=f"{months[0]}-01", end_date=today.isoformat())
        income_by = {ym: income for ym, income, _ in rows}
        expense_by = {ym: expense for ym, _, expense in rows}
        set_income = QBarSet("Ingresos")
        set_income.setColor(QColor("#2563eb"))
        set_expense = QBarSet("Gastos")
        set_expense.setColor(QColor("#ef4444"))
        for ym in months:
            set_income.append(income_by.get(ym, 0) / 100)
            set_expense.append(expense_by.get(ym, 0) / 100)
        series = QBarSeries()
        series.append(set_income)
        series.append(set_expense)
        chart = QChart()
        chart.addSeries(series)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        axis_x = QBarCategoryAxis()
        axis_x.append([ym[-2:] for ym in months])
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)
        axis_y = QValueAxis()
        axis_y.setLabelFormat("%.0f")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)
        self.chart_cashflow.setChart(chart)

    def _refresh_expense_pie(self, start: str, end: str) -> None:
        pie = QPieSeries()
        for name, cents in self.repo.top_expenses_by_category(start_date=start, end_date=end, limit=8):
            if cents > 0:
                pie.append(name, cents / 100)
        chart = QChart()
        chart.addSeries(pie)
        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignRight)
        self.chart_expenses.setChart(chart)


def _wrap(title: str, widget: QWidget) -> QGroupBox:
    box = QGroupBox(title)
    layout = QVBoxLayout()
    layout.addWidget(widget)
    box.setLayout(layout)
    return box


def _bar_chart(title: str, data: list[tuple[str, int]], repo: Repository, color: str) -> QChart:
    labels = [_short_label(name) for name, _ in data] or ["Sin datos"]
    bar_set = QBarSet(title)
    bar_set.setColor(QColor(color))
    values = [cents / 100 for _, cents in data] or [0]
    for value in values:
        bar_set.append(value)
    series = QBarSeries()
    series.append(bar_set)
    chart = QChart()
    chart.addSeries(series)
    chart.legend().setVisible(False)
    axis_x = QBarCategoryAxis()
    axis_x.append(labels)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(axis_x)
    axis_y = QValueAxis()
    axis_y.setLabelFormat("%.0f")
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_y)
    return chart


def _fill_money_list(widget: QListWidget, data: list[tuple[str, int]], repo: Repository, *, empty: str) -> None:
    widget.clear()
    if not data:
        widget.addItem(empty)
        return
    for index, (name, cents) in enumerate(data, start=1):
        widget.addItem(f'{index}. {name} · $ {repo.cents_to_text(cents)}')


def _fill_profit_list(widget: QListWidget, data: list[tuple[str, int, int, int]], repo: Repository, *, empty: str) -> None:
    widget.clear()
    if not data:
        widget.addItem(empty)
        return
    for index, (name, income, cost, profit) in enumerate(data, start=1):
        widget.addItem(f'{index}. {name} · utilidad $ {repo.cents_to_text(profit)} · ingresos $ {repo.cents_to_text(income)} · costos $ {repo.cents_to_text(cost)}')


def _profit_label(repo: Repository, item: tuple[str, int, int, int]) -> str:
    name, _, _, profit = item
    return f'{_short_label(name, 18)} · $ {repo.cents_to_text(profit)}'


def _money_label(repo: Repository, item: tuple[str, int]) -> str:
    name, cents = item
    return f'{_short_label(name, 18)} · $ {repo.cents_to_text(cents)}'


def _short_label(value: str, limit: int = 14) -> str:
    text = value or "-"
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    layout.addStretch(1)
    box.setLayout(layout)
    return box


def _set_kpi(card: QGroupBox, value: str) -> None:
    value_widget = card.findChild(QLabel, "KpiValue")
    if value_widget:
        value_widget.setText(value)

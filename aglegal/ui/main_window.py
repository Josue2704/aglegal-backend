from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QKeySequence, QShortcut

from ..repositories import Repository
from .pages.clients import ClientsPage
from .pages.categories import CategoriesPage
from .pages.cases import CasesPage
from .pages.dashboard import DashboardPage
from .pages.cashflow import CashflowPage
from .pages.sessions import SessionsPage
from .pages.payroll import PayrollPage
from .pages.users import UsersPage


class MainWindow(QMainWindow):
    def __init__(self, repo: Repository, current_username: str = "admin"):
        super().__init__()
        self.repo = repo
        self.current_username = current_username
        self.setWindowTitle("AGLEGAL - Demo")
        self.resize(1180, 720)

        self.page_dashboard = DashboardPage(repo)
        self.page_clients = ClientsPage(repo)
        self.page_cases = CasesPage(repo)
        self.page_sessions = SessionsPage(repo, current_username=current_username)
        self.page_cashflow = CashflowPage(repo)
        self.page_categories = CategoriesPage(repo)
        self.page_payroll = PayrollPage(repo)
        self.page_users = UsersPage(repo)

        self.nav = QListWidget()
        self.nav.setObjectName("Sidebar")
        self.nav.setFixedWidth(232)
        self.nav.setSpacing(2)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setMinimumHeight(360)
        self.nav.setUniformItemSizes(True)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.page_dashboard)
        self.stack.addWidget(self.page_clients)
        self.stack.addWidget(self.page_cases)
        self.stack.addWidget(self.page_sessions)
        self.stack.addWidget(self.page_cashflow)
        self.stack.addWidget(self.page_categories)
        self.stack.addWidget(self.page_payroll)
        self.stack.addWidget(self.page_users)

        self._add_nav_item("\u25a3  Dashboard", 0)
        self._add_nav_item("\u25c9  Clientes", 1)
        self._add_nav_item("\u25c6  Casos", 2)
        self._add_nav_item("\u25f7  Sesiones", 3)
        self._add_nav_item("\u2197  Finanzas", 4)
        self._add_nav_item("\u25a4  Categorías", 5)
        self._add_nav_item("$  Nóminas", 6)
        self._add_nav_item("⚙  Usuarios", 7)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setCurrentRow(0)

        sidebar = QFrame()
        sidebar.setObjectName("SidebarFrame")
        sbl = QVBoxLayout()
        brand = QLabel("AGLEGAL")
        brand.setObjectName("Brand")
        sub = QLabel("Gestión legal y finanzas")
        sub.setObjectName("BrandSub")
        sbl.addWidget(brand)
        sbl.addWidget(sub)
        sbl.addSpacing(10)
        sbl.addWidget(self.nav)
        sbl.addStretch(1)
        sidebar.setLayout(sbl)

        content = QWidget()
        content.setObjectName("MainContent")
        root = QHBoxLayout()
        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        content.setLayout(root)
        self.setCentralWidget(content)

        self.shortcut_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.shortcut_fullscreen.activated.connect(self._toggle_fullscreen)
        self._polish_tables()

    def _add_nav_item(self, label: str, index: int) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, index)
        self.nav.addItem(item)

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        item = self.nav.item(row)
        index = int(item.data(Qt.ItemDataRole.UserRole))
        self.stack.setCurrentIndex(index)
        page = self.stack.currentWidget()
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.showMaximized()
        else:
            self.showFullScreen()

    def _polish_tables(self) -> None:
        for table in self.findChildren(QTableWidget):
            table.setAlternatingRowColors(True)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(38)
            table.horizontalHeader().setMinimumHeight(42)
            table.horizontalHeader().setStretchLastSection(True)

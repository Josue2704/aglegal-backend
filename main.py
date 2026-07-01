from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from aglegal import db
from aglegal.repositories import Repository
from aglegal.ui.login import LoginDialog
from aglegal.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        * { font-family: Segoe UI; font-size: 12px; }

        QWidget { color: #111827; }
        QMainWindow { background: #eef2f7; }
        QWidget#MainContent { background: #eef2f7; }
        QStackedWidget {
            background: #eef2f7;
            border: none;
        }

        QLabel#PageTitle {
            font-size: 24px;
            font-weight: 900;
            color: #0f172a;
            padding: 4px 0 10px 0;
        }

        QLabel#MutedText { color: #64748b; padding-bottom: 6px; }
        QLabel#SectionTitle { font-size: 18px; font-weight: 900; color: #0f172a; }

        QToolTip {
            background: #0f172a;
            color: #ffffff;
            border: 1px solid #334155;
            border-radius: 8px;
            padding: 8px;
        }

        QTabWidget::pane {
            border: 1px solid #d8e0ec;
            border-radius: 18px;
            background: #ffffff;
            top: -1px;
            padding: 8px;
        }
        QTabBar::tab {
            background: #e9eef6;
            color: #334155;
            border: 1px solid #d3dce9;
            border-bottom: none;
            border-top-left-radius: 12px;
            border-top-right-radius: 12px;
            padding: 10px 18px;
            margin-right: 4px;
            font-weight: 800;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            color: #1d4ed8;
            border-color: #bfdbfe;
        }
        QTabBar::tab:hover:!selected {
            background: #f8fafc;
            color: #0f172a;
        }

        /* Sidebar */
        QFrame#SidebarFrame {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 #08111f, stop:0.58 #101827, stop:1 #172033);
            border-right: 1px solid rgba(255,255,255,0.08);
        }
        QLabel#Brand { color: #ffffff; font-size: 23px; font-weight: 900; letter-spacing: 1px; padding: 22px 18px 0 18px; }
        QLabel#BrandSub { color: rgba(226,232,240,0.72); padding: 0 18px 14px 18px; }
        QListWidget#Sidebar {
            background: transparent;
            border: none;
            outline: none;
            color: rgba(255,255,255,0.84);
            padding: 4px 10px;
        }
        QListWidget#Sidebar::item {
            padding: 11px 12px;
            margin: 2px 6px;
            border-radius: 12px;
        }
        QListWidget#Sidebar::item:selected {
            background: #4f46e5;
            color: #ffffff;
        }
        QListWidget#Sidebar::item:hover {
            background: rgba(255, 255, 255, 0.09);
        }

        /* Lists (default, excluding sidebar) */
        QListWidget {
            background: #ffffff;
            border: 1px solid #d8e0ec;
            border-radius: 16px;
            padding: 8px;
        }
        QListWidget::item {
            padding: 9px 11px;
            border-radius: 10px;
        }
        QListWidget::item:hover {
            background: #f1f5f9;
        }
        QListWidget::item:selected {
            background: #eef2ff;
            color: #111827;
        }

        /* Inputs */
        QLineEdit, QTextEdit, QComboBox, QDateEdit {
            background: #ffffff;
            border: 1px solid #cfd8e6;
            border-radius: 12px;
            padding: 10px 12px;
            selection-background-color: #c7d2fe;
        }
        QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QDateEdit:hover {
            border: 1px solid #aebcd0;
            background: #fbfdff;
        }
        QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {
            border: 1px solid #4f46e5;
            background: #fbfcff;
        }
        QComboBox::drop-down, QDateEdit::drop-down {
            border: none;
            width: 28px;
        }
        QComboBox QAbstractItemView {
            background: #ffffff;
            border: 1px solid #d8e0ec;
            border-radius: 10px;
            selection-background-color: #eef2ff;
            selection-color: #0f172a;
            padding: 6px;
            outline: none;
        }

        /* Calendar */
        QCalendarWidget {
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #e3e8f0;
            border-radius: 16px;
        }
        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background: #4f46e5;
            border-top-left-radius: 14px;
            border-top-right-radius: 14px;
        }
        QCalendarWidget QToolButton {
            background: transparent;
            color: #ffffff;
            border: none;
            border-radius: 8px;
            margin: 4px;
            padding: 6px;
            font-weight: 800;
        }
        QCalendarWidget QToolButton:hover {
            background: rgba(255,255,255,0.16);
        }
        QCalendarWidget QMenu {
            background: #ffffff;
            color: #0f172a;
            border: 1px solid #e3e8f0;
        }
        QCalendarWidget QSpinBox {
            background: rgba(255,255,255,0.18);
            color: #ffffff;
            border: 1px solid rgba(255,255,255,0.25);
            border-radius: 8px;
            padding: 4px;
            selection-background-color: #c7d2fe;
        }
        QCalendarWidget QAbstractItemView {
            background: #ffffff;
            color: #0f172a;
            alternate-background-color: #f8fafc;
            selection-background-color: #dbeafe;
            selection-color: #0f172a;
            border: none;
            outline: none;
            gridline-color: #e2e8f0;
        }
        QCalendarWidget QAbstractItemView:disabled {
            color: #94a3b8;
        }

        /* Buttons */
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #4f46e5, stop:1 #2563eb);
            color: #ffffff;
            border: 1px solid #4338ca;
            border-radius: 12px;
            padding: 10px 16px;
            font-weight: 800;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 #4338ca, stop:1 #1d4ed8);
        }
        QPushButton:disabled { background: #9ca3af; }
        QPushButton#SecondaryButton {
            background: #0f172a;
            color: #ffffff;
            border: 1px solid #020617;
        }
        QPushButton#SecondaryButton:hover { background: #1e293b; }

        /* Cards / group boxes */
        QGroupBox {
            border: 1px solid #d8e0ec;
            border-radius: 20px;
            margin-top: 14px;
            background: #ffffff;
            padding: 12px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 16px;
            padding: 0 8px;
            color: #334155;
            font-weight: 800;
            background: #ffffff;
        }
        QGroupBox#KpiCard {
            border: 1px solid #d6e0ef;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 #ffffff, stop:1 #f6f9ff);
            margin-top: 0px;
            padding: 14px;
        }
        QLabel#KpiLabel { color: #64748b; font-weight: 800; }
        QLabel#KpiValue { font-size: 22px; font-weight: 900; color: #0f172a; }

        /* Tables */
        QHeaderView::section {
            background: #f1f5f9;
            border: none;
            border-bottom: 1px solid #e2e8f0;
            border-right: 1px solid #e2e8f0;
            padding: 10px;
            font-weight: 800;
            color: #1e293b;
        }
        QTableWidget {
            border: 1px solid #d8e0ec;
            border-radius: 18px;
            gridline-color: #e8eef6;
            background: #ffffff;
            color: #111827;
            alternate-background-color: #f8fafc;
            selection-background-color: #eef2ff;
            outline: none;
        }
        QTableWidget::item {
            padding: 8px;
            border-bottom: 1px solid #f1f5f9;
        }
        QTableWidget::item:hover {
            background: #f8fafc;
        }
        QTableWidget::item:selected {
            background: #dbeafe;
            color: #111827;
        }
        QTableCornerButton::section {
            background: #f1f5f9;
            border: none;
            border-bottom: 1px solid #e2e8f0;
            border-right: 1px solid #e2e8f0;
            border-top-left-radius: 16px;
        }

        QSplitter::handle {
            background: #d8e0ec;
            border-radius: 3px;
        }
        QSplitter::handle:horizontal {
            width: 6px;
            margin: 10px 4px;
        }
        QSplitter::handle:vertical {
            height: 6px;
            margin: 4px 10px;
        }

        QScrollBar:vertical {
            background: transparent;
            width: 12px;
            margin: 4px;
        }
        QScrollBar::handle:vertical {
            background: #cbd5e1;
            border-radius: 6px;
            min-height: 28px;
        }
        QScrollBar::handle:vertical:hover { background: #94a3b8; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        QScrollBar:horizontal {
            background: transparent;
            height: 12px;
            margin: 4px;
        }
        QScrollBar::handle:horizontal {
            background: #cbd5e1;
            border-radius: 6px;
            min-width: 28px;
        }
        QScrollBar::handle:horizontal:hover { background: #94a3b8; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; }
        """
    )

    conn = db.connect()
    try:
        db.init_db(conn)
        repo = Repository(conn)

        login = LoginDialog(repo)
        if login.exec() != LoginDialog.DialogCode.Accepted:
            return 0

        win = MainWindow(repo, current_username=login.current_username or "admin")
        win.showMaximized()
        return app.exec()
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

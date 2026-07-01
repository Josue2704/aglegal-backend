from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from aglegal import db
from aglegal.repositories import Repository
from aglegal.ui.main_window import MainWindow
from aglegal.ui.pages.cashflow import CashflowPage
from aglegal.ui.pages.dashboard import DashboardPage


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    conn = db.connect()
    try:
        db.init_db(conn)
        repo = Repository(conn)

        assert repo.authenticate("admin", "admin"), "admin login should work"
        assert repo.category_choices(kind="income"), "income categories missing"
        assert repo.category_choices(kind="expense"), "expense categories missing"
        assert repo.category_choices(kind="cost"), "cost categories missing"
        assert repo.category_choices(kind="service"), "service categories missing"

        repo.dashboard_metrics_month()
        repo.top_clients_by_revenue(limit=5)
        repo.top_services_by_gross_profit(limit=5)
        repo.top_expenses_by_category(limit=5)

        pages = [DashboardPage(repo), CashflowPage(repo)]
        window = MainWindow(repo)
        assert window.nav.count() >= 8, "navigation entries missing"
        assert len(pages) == 2

        print("smoke-ok")
        return 0
    finally:
        conn.close()
        app.quit()


if __name__ == "__main__":
    raise SystemExit(main())

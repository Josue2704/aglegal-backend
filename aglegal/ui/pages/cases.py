from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
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
    QTextEdit,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QPixmap

from ...db import now_iso
from ...repositories import CASE_PRIORITIES, CASE_STATUSES, Repository
from ..common import confirm, info, open_file, warn


SERVICE_AREAS = [
    "Servicios Notariales",
    "Bienes Raíces e Inversiones",
    "Derecho Corporativo y Empresarial",
    "Derecho de Familia",
    "Representación en Juicios",
    "Derecho Administrativo",
    "Migratorio",
    "Otro",
]


class CasesPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_case_id: int | None = None

        title = QLabel("Casos / Expedientes")
        title.setObjectName("PageTitle")

        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por cliente / título / área…")
        self.search.textChanged.connect(self.refresh)

        self.filter_status = QComboBox()
        self.filter_status.addItems(["Todos", *CASE_STATUSES])
        self.filter_status.currentIndexChanged.connect(self.refresh)

        self.filter_client = QComboBox()
        self.filter_client.addItem("Todos", None)
        self.filter_client.currentIndexChanged.connect(self.refresh)

        filters = QHBoxLayout()
        filters.addWidget(self.search, 2)
        filters.addWidget(QLabel("Estado:"))
        filters.addWidget(self.filter_status)
        filters.addWidget(QLabel("Cliente:"))
        filters.addWidget(self.filter_client, 1)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Cliente", "Área", "Título", "Estado", "Prioridad", "Apertura"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        # Form
        self.in_client = QComboBox()
        self.in_area = QComboBox()
        self.in_area.currentIndexChanged.connect(lambda *_: self._refresh_products())
        self.in_product = QComboBox()
        self.in_product.addItem("(Sin producto específico)", None)
        self.in_title = QLineEdit()
        self.in_status = QComboBox()
        self.in_status.addItems(CASE_STATUSES)
        self.in_priority = QComboBox()
        self.in_priority.addItems(CASE_PRIORITIES)
        self.in_opened = QLineEdit()
        self.in_opened.setPlaceholderText("YYYY-MM-DD")
        self.in_closed = QLineEdit()
        self.in_closed.setPlaceholderText("YYYY-MM-DD (opcional)")
        self.in_notes = QTextEdit()
        self.in_notes.setFixedHeight(90)

        form = QFormLayout()
        form.addRow("Cliente:", self.in_client)
        form.addRow("Área:", self.in_area)
        form.addRow("Título:", self.in_title)
        form.addRow("Estado:", self.in_status)
        form.addRow("Prioridad:", self.in_priority)
        form.addRow("Apertura:", self.in_opened)
        form.addRow("Cierre:", self.in_closed)
        form.addRow("Notas:", self.in_notes)

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

        # Tasks + Docs
        self.tasks = QListWidget()
        self.task_title = QLineEdit()
        self.task_title.setPlaceholderText("Nueva tarea…")
        self.task_due = QLineEdit()
        self.task_due.setPlaceholderText("Vence (YYYY-MM-DD, opcional)")
        self.btn_task_add = QPushButton("Agregar")
        self.btn_task_add.clicked.connect(self._task_add)
        self.btn_task_done = QPushButton("Marcar hecho")
        self.btn_task_done.setObjectName("SecondaryButton")
        self.btn_task_done.clicked.connect(self._task_done_toggle)
        self.btn_task_del = QPushButton("Eliminar")
        self.btn_task_del.setObjectName("SecondaryButton")
        self.btn_task_del.clicked.connect(self._task_delete)

        task_controls = QHBoxLayout()
        task_controls.addWidget(self.task_title, 2)
        task_controls.addWidget(self.task_due, 1)
        task_controls.addWidget(self.btn_task_add)
        task_controls.addWidget(self.btn_task_done)
        task_controls.addWidget(self.btn_task_del)

        task_box = QGroupBox("Próximas acciones y checklist")
        task_l = QVBoxLayout()
        task_l.addWidget(self.tasks)
        task_l.addLayout(task_controls)
        task_box.setLayout(task_l)

        self.docs = QListWidget()
        self.docs.setMinimumHeight(140)
        self.btn_doc_add = QPushButton("Adjuntar…")
        self.btn_doc_open = QPushButton("Abrir")
        self.btn_doc_open.setObjectName("SecondaryButton")
        self.btn_doc_remove = QPushButton("Quitar")
        self.btn_doc_remove.setObjectName("SecondaryButton")
        self.btn_doc_add.clicked.connect(self._doc_add)
        self.btn_doc_open.clicked.connect(self._doc_open)
        self.btn_doc_remove.clicked.connect(self._doc_remove)
        self.docs.currentItemChanged.connect(lambda *_: self._doc_buttons())

        self.doc_preview = QStackedWidget()
        self.doc_preview.setMinimumHeight(140)
        self.preview_placeholder = QLabel("Vista previa: selecciona un documento")
        self.preview_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.doc_preview.addWidget(self.preview_placeholder)
        self.doc_preview.addWidget(self.preview_image)
        self.doc_preview.addWidget(self.preview_text)

        doc_btns = QHBoxLayout()
        doc_btns.addWidget(self.btn_doc_add)
        doc_btns.addWidget(self.btn_doc_open)
        doc_btns.addWidget(self.btn_doc_remove)
        doc_btns.addStretch(1)

        doc_box = QGroupBox("Documentos del expediente")
        doc_l = QVBoxLayout()
        doc_split = QSplitter()
        doc_split.setOrientation(Qt.Orientation.Horizontal)
        doc_split.addWidget(self.docs)
        doc_split.addWidget(self.doc_preview)
        doc_split.setStretchFactor(0, 1)
        doc_split.setStretchFactor(1, 2)
        doc_split.setSizes([260, 520])
        doc_l.addWidget(doc_split)
        doc_l.addLayout(doc_btns)
        doc_box.setLayout(doc_l)

        details_box = QGroupBox("Datos del expediente")
        details_layout = QVBoxLayout()
        details_layout.addLayout(form)
        details_layout.addLayout(btns)
        details_layout.addStretch(1)
        details_box.setLayout(details_layout)

        tabs = QTabWidget()
        tabs.addTab(details_box, "Datos")
        tabs.addTab(task_box, "Checklist")
        tabs.addTab(doc_box, "Documentos")

        right = QVBoxLayout()
        hint = QLabel("Selecciona un expediente para trabajar su información, acciones y documentos.")
        hint.setObjectName("MutedText")
        right.addWidget(hint)
        right.addWidget(tabs, 1)

        layout = QGridLayout()
        layout.addWidget(title, 0, 0, 1, 2)
        layout.addLayout(filters, 1, 0, 1, 2)
        layout.addWidget(self.table, 2, 0, 1, 1)
        layout.addLayout(right, 2, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        self.setLayout(layout)

        self.refresh()
        self._new()

    def refresh(self) -> None:
        self._refresh_clients()
        self._refresh_service_catalog()
        rows = self.repo.list_cases(
            search=self.search.text(),
            status=self.filter_status.currentText(),
            client_id=self.filter_client.currentData(),
        )
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(r, 1, QTableWidgetItem(row["client_name"] or ""))
            self.table.setItem(r, 2, QTableWidgetItem(row["service_area"] or ""))
            self.table.setItem(r, 3, QTableWidgetItem(row["product_name"] or ""))
            self.table.setItem(r, 4, QTableWidgetItem(row["title"] or ""))
            self.table.setItem(r, 5, QTableWidgetItem(row["status"] or ""))
            self.table.setItem(r, 6, QTableWidgetItem(row["priority"] or ""))
            self.table.setItem(r, 7, QTableWidgetItem(row["opened_at"] or ""))
        self.table.resizeColumnsToContents()

        self._refresh_tasks()
        self._refresh_docs()

    def _refresh_service_catalog(self) -> None:
        current = self.in_area.currentData()
        self.in_area.blockSignals(True)
        self.in_area.clear()
        for category_id, name in self.repo.category_choices(kind="service"):
            self.in_area.addItem(name, category_id)
        if current is not None:
            idx = self.in_area.findData(current)
            if idx >= 0:
                self.in_area.setCurrentIndex(idx)
        self.in_area.blockSignals(False)
        self._refresh_products()

    def _refresh_products(self) -> None:
        current = self.in_product.currentData()
        category_id = self.in_area.currentData()
        self.in_product.blockSignals(True)
        self.in_product.clear()
        self.in_product.addItem("(Sin producto específico)", None)
        if category_id:
            for product_id, name in self.repo.service_product_choices(category_id=int(category_id)):
                self.in_product.addItem(name, product_id)
        if current is not None:
            idx = self.in_product.findData(current)
            if idx >= 0:
                self.in_product.setCurrentIndex(idx)
        self.in_product.blockSignals(False)

    def _refresh_clients(self) -> None:
        cur_filter = self.filter_client.currentData()
        cur_form = self.in_client.currentData()

        self.filter_client.blockSignals(True)
        self.in_client.blockSignals(True)

        self.filter_client.clear()
        self.filter_client.addItem("Todos", None)
        self.in_client.clear()

        for cid, name in self.repo.client_choices():
            self.filter_client.addItem(name, cid)
            self.in_client.addItem(name, cid)

        if cur_filter is not None:
            idx = self.filter_client.findData(cur_filter)
            if idx >= 0:
                self.filter_client.setCurrentIndex(idx)
        if cur_form is not None:
            idx2 = self.in_client.findData(cur_form)
            if idx2 >= 0:
                self.in_client.setCurrentIndex(idx2)

        self.filter_client.blockSignals(False)
        self.in_client.blockSignals(False)

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_case_id = None
            self._refresh_tasks()
            self._refresh_docs()
            return
        row = items[0].row()
        case_id = int(self.table.item(row, 0).text())
        self.selected_case_id = case_id
        selected = [c for c in self.repo.list_cases() if int(c["id"]) == case_id]
        if not selected:
            return
        cs = selected[0]
        idx = self.in_client.findText(cs["client_name"] or "")
        if idx >= 0:
            self.in_client.setCurrentIndex(idx)
        idx_area = self.in_area.findText(cs["service_area"] or "")
        if idx_area >= 0:
            self.in_area.setCurrentIndex(idx_area)
        self._refresh_products()
        product_id = cs["service_product_id"] if "service_product_id" in cs.keys() else None
        if product_id:
            idx_product = self.in_product.findData(int(product_id))
            if idx_product >= 0:
                self.in_product.setCurrentIndex(idx_product)
        self.in_title.setText(cs["title"] or "")
        self.in_status.setCurrentText(cs["status"] or CASE_STATUSES[0])
        self.in_priority.setCurrentText(cs["priority"] or CASE_PRIORITIES[0])
        self.in_opened.setText(cs["opened_at"] or "")
        self.in_closed.setText(cs["closed_at"] or "")
        self.in_notes.setPlainText(cs["notes"] or "")
        self._refresh_tasks()
        self._refresh_docs()

    def _new(self) -> None:
        self.selected_case_id = None
        self.table.clearSelection()
        self._refresh_clients()
        if self.in_client.count() > 0:
            self.in_client.setCurrentIndex(0)
        self._refresh_service_catalog()
        if self.in_area.count() > 0:
            self.in_area.setCurrentIndex(0)
        self._refresh_products()
        self.in_title.setText("")
        self.in_status.setCurrentIndex(0)
        self.in_priority.setCurrentIndex(1)
        self.in_opened.setText(date.today().isoformat())
        self.in_closed.setText("")
        self.in_notes.setPlainText("")
        self._refresh_tasks()
        self._refresh_docs()

    def _save(self) -> None:
        client_id = self.in_client.currentData()
        if not client_id:
            warn(self, "Casos", "Debes registrar un cliente primero.")
            return
        title = self.in_title.text().strip()
        if not title:
            warn(self, "Casos", "El título es requerido.")
            return
        opened = self.in_opened.text().strip()
        status = self.in_status.currentText()
        priority = self.in_priority.currentText()
        area = self.in_area.currentText()
        product_id = self.in_product.currentData()
        closed = self.in_closed.text().strip() or None
        notes = self.in_notes.toPlainText()

        try:
            if self.selected_case_id is None:
                self.selected_case_id = self.repo.create_case(
                    client_id=int(client_id),
                    service_area=area,
                    title=title,
                    status=status,
                    priority=priority,
                    opened_at=opened,
                    notes=notes,
                    created_at=now_iso(),
                    service_product_id=product_id,
                )
                info(self, "Casos", "Caso creado.")
            else:
                self.repo.update_case(
                    self.selected_case_id,
                    service_area=area,
                    title=title,
                    status=status,
                    priority=priority,
                    opened_at=opened,
                    closed_at=closed,
                    notes=notes,
                    service_product_id=product_id,
                )
                info(self, "Casos", "Caso actualizado.")
        except Exception as e:
            warn(self, "Casos", str(e))
            return

        self.refresh()

    def _delete(self) -> None:
        if self.selected_case_id is None:
            warn(self, "Casos", "Selecciona un caso.")
            return
        if not confirm(self, "Casos", "¿Eliminar este caso? (también borra su checklist)"):
            return
        self.repo.delete_case(self.selected_case_id)
        self._new()
        self.refresh()

    # --- Tasks
    def _refresh_tasks(self) -> None:
        self.tasks.clear()
        enabled = self.selected_case_id is not None
        for w in [self.task_title, self.task_due, self.btn_task_add, self.btn_task_done, self.btn_task_del]:
            w.setEnabled(enabled)
        if not enabled:
            self.tasks.addItem("(Selecciona un caso para ver checklist)")
            self.tasks.setEnabled(False)
            return
        self.tasks.setEnabled(True)
        rows = self.repo.list_case_tasks(self.selected_case_id)
        if not rows:
            self.tasks.addItem("(Sin tareas)")
            return
        for r in rows:
            prefix = "✓" if int(r["done"] or 0) == 1 else "•"
            due = f'  (vence {r["due_date"]})' if r["due_date"] else ""
            item = QListWidgetItem(f"{prefix} {r['title']}{due}")
            item.setData(Qt.ItemDataRole.UserRole, (int(r["id"]), int(r["done"] or 0)))
            self.tasks.addItem(item)

    def _task_add(self) -> None:
        if self.selected_case_id is None:
            return
        try:
            self.repo.create_case_task(
                case_id=self.selected_case_id,
                title=self.task_title.text(),
                due_date=self.task_due.text(),
                created_at=now_iso(),
            )
        except Exception as e:
            warn(self, "Checklist", str(e))
            return
        self.task_title.setText("")
        self.task_due.setText("")
        self._refresh_tasks()

    def _task_done_toggle(self) -> None:
        item = self.tasks.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        task_id, done = data
        self.repo.set_case_task_done(int(task_id), done != 1)
        self._refresh_tasks()

    def _task_delete(self) -> None:
        item = self.tasks.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        task_id, _ = data
        if not confirm(self, "Checklist", "¿Eliminar esta tarea?"):
            return
        self.repo.delete_case_task(int(task_id))
        self._refresh_tasks()

    # --- Documents (attachments entity_type='case')
    def _refresh_docs(self) -> None:
        self.docs.clear()
        enabled = self.selected_case_id is not None
        self.btn_doc_add.setEnabled(enabled)
        self.btn_doc_open.setEnabled(False)
        self.btn_doc_remove.setEnabled(False)
        self._set_preview_placeholder()
        if not enabled:
            self.docs.addItem("(Selecciona un caso para ver documentos)")
            self.docs.setEnabled(False)
            return
        self.docs.setEnabled(True)
        rows = self.repo.list_attachments(entity_type="case", entity_id=self.selected_case_id)
        if not rows:
            self.docs.addItem("(Sin documentos)")
            return
        for r in rows:
            item = QListWidgetItem(f'{r["original_name"]}')
            item.setData(Qt.ItemDataRole.UserRole, (int(r["id"]), str(r["stored_path"])))
            self.docs.addItem(item)
        self._doc_buttons()

    def _doc_buttons(self) -> None:
        item = self.docs.currentItem()
        data = item.data(Qt.ItemDataRole.UserRole) if item else None
        ok = isinstance(data, tuple) and len(data) == 2
        self.btn_doc_open.setEnabled(ok)
        self.btn_doc_remove.setEnabled(ok)
        if ok:
            _, stored = data
            self._preview_file(stored)
        else:
            self._set_preview_placeholder()

    def _set_preview_placeholder(self) -> None:
        self.preview_placeholder.setText("Vista previa: selecciona un documento")
        self.doc_preview.setCurrentWidget(self.preview_placeholder)

    def _doc_add(self) -> None:
        if self.selected_case_id is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Adjuntar documento al caso")
        if not path:
            return
        original = Path(path).name
        stored = self.repo.suggest_attachment_path("case", self.selected_case_id, original)
        try:
            self.repo.add_attachment(
                entity_type="case",
                entity_id=self.selected_case_id,
                source_path=path,
                stored_path=stored,
                original_name=original,
                created_at=now_iso(),
            )
        except Exception as e:
            warn(self, "Documentos", str(e))
            return
        self._refresh_docs()

    def _doc_open(self) -> None:
        item = self.docs.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        _, stored = data
        open_file(stored)

    def _doc_remove(self) -> None:
        item = self.docs.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        attach_id, _ = data
        if not confirm(self, "Documentos", "¿Quitar este documento?"):
            return
        self.repo.delete_attachment(int(attach_id))
        self._refresh_docs()

    def _preview_file(self, stored_path: str) -> None:
        if not stored_path:
            self._set_preview_placeholder()
            return

        path = Path(stored_path)
        if not path.exists():
            self.preview_placeholder.setText("Vista previa: archivo no encontrado")
            self.doc_preview.setCurrentWidget(self.preview_placeholder)
            return

        suffix = path.suffix.lower()
        if suffix in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]:
            pix = QPixmap(str(path))
            if pix.isNull():
                self.preview_placeholder.setText("Vista previa: no se pudo cargar imagen")
                self.doc_preview.setCurrentWidget(self.preview_placeholder)
                return
            target = self.doc_preview.size()
            scaled = pix.scaled(
                max(320, target.width()),
                max(200, target.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview_image.setPixmap(scaled)
            self.doc_preview.setCurrentWidget(self.preview_image)
            return

        if suffix in [".txt", ".md", ".csv", ".log"]:
            try:
                data = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                try:
                    data = path.read_text(encoding="latin-1", errors="replace")
                except Exception:
                    self.preview_placeholder.setText("Vista previa: no se pudo leer el archivo")
                    self.doc_preview.setCurrentWidget(self.preview_placeholder)
                    return
            self.preview_text.setPlainText(data[:20000])
            self.doc_preview.setCurrentWidget(self.preview_text)
            return

        self.preview_placeholder.setText("Vista previa no disponible para este tipo de archivo")
        self.doc_preview.setCurrentWidget(self.preview_placeholder)

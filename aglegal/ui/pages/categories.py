from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...db import now_iso
from ...repositories import Repository
from ..common import confirm, info, warn


class CategoriesPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_id: int | None = None
        self.selected_product_id: int | None = None

        title = QLabel("Categorías y productos")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Administra categorías financieras y el catálogo de servicios/productos que ofrece el despacho.")
        subtitle.setObjectName("MutedText")

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_finance_tab(), "Finanzas")
        self.tabs.addTab(self._build_services_tab(), "Servicios ofrecidos")

        root = QVBoxLayout()
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addWidget(self.tabs, 1)
        self.setLayout(root)

        self.refresh()
        self._new()
        self._new_product()

    def _build_finance_tab(self) -> QWidget:
        page = QWidget()
        self.kind = QComboBox()
        self.kind.addItems(["Gastos", "Ingresos"])
        self.kind.currentIndexChanged.connect(self.refresh)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Nombre", "Creado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.in_name = QLineEdit()
        self.in_name.setPlaceholderText("Ej. Oficina, Honorarios, Transporte")
        form = QFormLayout()
        form.addRow("Nombre:", self.in_name)

        self.btn_new = QPushButton("Nueva categoría")
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

        editor = QGroupBox("Categoría financiera")
        editor_layout = QVBoxLayout()
        editor_layout.addLayout(form)
        editor_layout.addLayout(btns)
        editor_layout.addStretch(1)
        editor.setLayout(editor_layout)

        layout = QGridLayout()
        layout.addWidget(QLabel("Tipo:"), 0, 0)
        layout.addWidget(self.kind, 0, 1)
        layout.addWidget(self.table, 1, 0, 1, 1)
        layout.addWidget(editor, 1, 1)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 1)
        page.setLayout(layout)
        return page

    def _build_services_tab(self) -> QWidget:
        page = QWidget()
        self.service_categories = QTableWidget(0, 3)
        self.service_categories.setHorizontalHeaderLabels(["ID", "Categoría de servicio", "Creado"])
        self.service_categories.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.service_categories.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.service_categories.itemSelectionChanged.connect(self._on_service_category_select)
        self.service_categories.horizontalHeader().setStretchLastSection(True)

        self.service_name = QLineEdit()
        self.service_name.setPlaceholderText("Ej. Derecho de Familia")
        self.btn_service_new = QPushButton("Nueva categoría")
        self.btn_service_save = QPushButton("Guardar categoría")
        self.btn_service_delete = QPushButton("Eliminar")
        self.btn_service_new.clicked.connect(self._new_service_category)
        self.btn_service_save.clicked.connect(self._save_service_category)
        self.btn_service_delete.clicked.connect(self._delete_service_category)

        service_form = QFormLayout()
        service_form.addRow("Categoría:", self.service_name)
        service_buttons = QHBoxLayout()
        service_buttons.addWidget(self.btn_service_new)
        service_buttons.addWidget(self.btn_service_save)
        service_buttons.addWidget(self.btn_service_delete)
        service_buttons.addStretch(1)

        service_box = QGroupBox("Familias de servicios")
        service_layout = QVBoxLayout()
        service_layout.addWidget(QLabel("Ejemplos: Notarial, Familia, Juicios, Migratorio."))
        service_layout.addWidget(self.service_categories)
        service_layout.addLayout(service_form)
        service_layout.addLayout(service_buttons)
        service_box.setLayout(service_layout)

        self.products = QTableWidget(0, 6)
        self.products.setHorizontalHeaderLabels(["ID", "Producto/servicio", "Categoría", "Precio base", "Activo", "Descripción"])
        self.products.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.products.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.products.itemSelectionChanged.connect(self._on_product_select)
        self.products.horizontalHeader().setStretchLastSection(True)

        self.product_category = QComboBox()
        self.product_name = QLineEdit()
        self.product_name.setPlaceholderText("Ej. Divorcio, Poder, Compraventa")
        self.product_price = QLineEdit()
        self.product_price.setPlaceholderText("0.00 opcional")
        self.product_active = QCheckBox("Activo")
        self.product_active.setChecked(True)
        self.product_description = QTextEdit()
        self.product_description.setFixedHeight(80)
        self.product_description.setPlaceholderText("Qué incluye, requisitos, notas para venderlo mejor...")

        product_form = QFormLayout()
        product_form.addRow("Categoría:", self.product_category)
        product_form.addRow("Producto/servicio:", self.product_name)
        product_form.addRow("Precio base:", self.product_price)
        product_form.addRow("Estado:", self.product_active)
        product_form.addRow("Descripción:", self.product_description)

        self.btn_product_new = QPushButton("Nuevo producto")
        self.btn_product_save = QPushButton("Guardar producto")
        self.btn_product_delete = QPushButton("Eliminar")
        self.btn_product_new.clicked.connect(self._new_product)
        self.btn_product_save.clicked.connect(self._save_product)
        self.btn_product_delete.clicked.connect(self._delete_product)

        product_buttons = QHBoxLayout()
        product_buttons.addWidget(self.btn_product_new)
        product_buttons.addWidget(self.btn_product_save)
        product_buttons.addWidget(self.btn_product_delete)
        product_buttons.addStretch(1)

        product_box = QGroupBox("Productos / servicios ofrecidos")
        product_layout = QVBoxLayout()
        product_layout.addWidget(QLabel("Estos productos aparecen luego al crear un caso."))
        product_layout.addWidget(self.products)
        product_layout.addLayout(product_form)
        product_layout.addLayout(product_buttons)
        product_box.setLayout(product_layout)

        layout = QGridLayout()
        layout.addWidget(service_box, 0, 0)
        layout.addWidget(product_box, 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 2)
        page.setLayout(layout)
        return page

    def _kind_value(self) -> str:
        return "expense" if self.kind.currentText() == "Gastos" else "income"

    def refresh(self) -> None:
        self._refresh_finance_categories()
        self._refresh_service_categories()
        self._refresh_product_categories()
        self._refresh_products()

    def _refresh_finance_categories(self) -> None:
        rows = self.repo.list_categories(kind=self._kind_value())
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["name"] or ""))
            self.table.setItem(row_index, 2, QTableWidgetItem(row["created_at"] or ""))
        self.table.resizeColumnsToContents()

    def _refresh_service_categories(self) -> None:
        rows = self.repo.list_categories(kind="service")
        self.service_categories.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.service_categories.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.service_categories.setItem(row_index, 1, QTableWidgetItem(row["name"] or ""))
            self.service_categories.setItem(row_index, 2, QTableWidgetItem(row["created_at"] or ""))
        self.service_categories.resizeColumnsToContents()

    def _refresh_product_categories(self) -> None:
        current = self.product_category.currentData()
        self.product_category.blockSignals(True)
        self.product_category.clear()
        for category_id, name in self.repo.category_choices(kind="service"):
            self.product_category.addItem(name, category_id)
        if current is not None:
            index = self.product_category.findData(current)
            if index >= 0:
                self.product_category.setCurrentIndex(index)
        self.product_category.blockSignals(False)

    def _refresh_products(self) -> None:
        category_id = self._selected_service_category_id()
        rows = self.repo.list_service_products(category_id=category_id)
        self.products.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            price = "" if row["base_price_cents"] is None else f'$ {self.repo.cents_to_text(int(row["base_price_cents"]))}'
            active = "Sí" if int(row["active"] or 0) == 1 else "No"
            self.products.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.products.setItem(row_index, 1, QTableWidgetItem(row["name"] or ""))
            self.products.setItem(row_index, 2, QTableWidgetItem(row["category_name"] or ""))
            self.products.setItem(row_index, 3, QTableWidgetItem(price))
            self.products.setItem(row_index, 4, QTableWidgetItem(active))
            self.products.setItem(row_index, 5, QTableWidgetItem(row["description"] or ""))
        self.products.resizeColumnsToContents()

    def _selected_service_category_id(self) -> int | None:
        items = self.service_categories.selectedItems()
        if not items:
            return None
        return int(self.service_categories.item(items[0].row(), 0).text())

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_id = None
            return
        row = items[0].row()
        self.selected_id = int(self.table.item(row, 0).text())
        self.in_name.setText(self.table.item(row, 1).text())

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self.in_name.clear()
        self.in_name.setFocus()

    def _save(self) -> None:
        name = self.in_name.text().strip()
        if not name:
            warn(self, "Categorías", "El nombre es requerido.")
            return
        try:
            if self.selected_id is None:
                self.repo.create_category(kind=self._kind_value(), name=name, created_at=now_iso())
                info(self, "Categorías", "Categoría creada.")
            else:
                self.repo.update_category(self.selected_id, name=name)
                info(self, "Categorías", "Categoría actualizada.")
        except Exception as exc:
            warn(self, "Categorías", str(exc))
            return
        self.refresh()

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Categorías", "Selecciona una categoría.")
            return
        if not confirm(self, "Categorías", "¿Eliminar esta categoría?"):
            return
        self.repo.delete_category(self.selected_id)
        self._new()
        self.refresh()

    def _on_service_category_select(self) -> None:
        category_id = self._selected_service_category_id()
        if category_id is None:
            self.service_name.clear()
        else:
            self.service_name.setText(self.service_categories.item(self.service_categories.currentRow(), 1).text())
            index = self.product_category.findData(category_id)
            if index >= 0:
                self.product_category.setCurrentIndex(index)
        self._refresh_products()

    def _new_service_category(self) -> None:
        self.service_categories.clearSelection()
        self.service_name.clear()
        self.service_name.setFocus()

    def _save_service_category(self) -> None:
        name = self.service_name.text().strip()
        if not name:
            warn(self, "Servicios", "El nombre de la categoría es requerido.")
            return
        category_id = self._selected_service_category_id()
        try:
            if category_id is None:
                self.repo.create_category(kind="service", name=name, created_at=now_iso())
            else:
                self.repo.update_category(category_id, name=name)
        except Exception as exc:
            warn(self, "Servicios", str(exc))
            return
        self.refresh()

    def _delete_service_category(self) -> None:
        category_id = self._selected_service_category_id()
        if category_id is None:
            warn(self, "Servicios", "Selecciona una categoría de servicio.")
            return
        if not confirm(self, "Servicios", "¿Eliminar esta categoría y sus productos?"):
            return
        self.repo.delete_category(category_id)
        self._new_service_category()
        self.refresh()

    def _on_product_select(self) -> None:
        items = self.products.selectedItems()
        if not items:
            self.selected_product_id = None
            return
        row = items[0].row()
        self.selected_product_id = int(self.products.item(row, 0).text())
        product = [p for p in self.repo.list_service_products() if int(p["id"]) == self.selected_product_id]
        if not product:
            return
        item = product[0]
        index = self.product_category.findData(int(item["category_id"]))
        if index >= 0:
            self.product_category.setCurrentIndex(index)
        self.product_name.setText(item["name"] or "")
        self.product_price.setText("" if item["base_price_cents"] is None else self.repo.cents_to_text(int(item["base_price_cents"])))
        self.product_active.setChecked(int(item["active"] or 0) == 1)
        self.product_description.setPlainText(item["description"] or "")

    def _new_product(self) -> None:
        self.selected_product_id = None
        self.products.clearSelection()
        selected_category = self._selected_service_category_id()
        if selected_category:
            index = self.product_category.findData(selected_category)
            if index >= 0:
                self.product_category.setCurrentIndex(index)
        self.product_name.clear()
        self.product_price.clear()
        self.product_active.setChecked(True)
        self.product_description.clear()

    def _save_product(self) -> None:
        category_id = self.product_category.currentData()
        if not category_id:
            warn(self, "Productos", "Primero crea o selecciona una categoría de servicio.")
            return
        try:
            if self.selected_product_id is None:
                self.repo.create_service_product(
                    category_id=int(category_id),
                    name=self.product_name.text(),
                    description=self.product_description.toPlainText(),
                    base_price_text=self.product_price.text(),
                    active=self.product_active.isChecked(),
                    created_at=now_iso(),
                )
            else:
                self.repo.update_service_product(
                    self.selected_product_id,
                    category_id=int(category_id),
                    name=self.product_name.text(),
                    description=self.product_description.toPlainText(),
                    base_price_text=self.product_price.text(),
                    active=self.product_active.isChecked(),
                )
        except Exception as exc:
            warn(self, "Productos", str(exc))
            return
        self._new_product()
        self.refresh()

    def _delete_product(self) -> None:
        if self.selected_product_id is None:
            warn(self, "Productos", "Selecciona un producto.")
            return
        if not confirm(self, "Productos", "¿Eliminar este producto/servicio?"):
            return
        self.repo.delete_service_product(self.selected_product_id)
        self._new_product()
        self.refresh()

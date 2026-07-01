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
    QVBoxLayout,
    QWidget,
)

from ...db import now_iso
from ...repositories import Repository
from ..common import confirm, info, warn


class UsersPage(QWidget):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.selected_id: int | None = None

        title = QLabel("Usuarios y accesos")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Gestión básica de acceso: usuarios activos, rol visible y cambio de contraseña.")
        subtitle.setObjectName("MutedText")

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "Usuario", "Nombre", "Rol", "Activo", "Creado"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        self.table.horizontalHeader().setStretchLastSection(True)

        self.username = QLineEdit()
        self.username.setPlaceholderText("usuario")
        self.full_name = QLineEdit()
        self.full_name.setPlaceholderText("Nombre completo")
        self.role = QComboBox()
        self.role.addItems(["Administrador", "Usuario"])
        self.active = QCheckBox("Activo")
        self.active.setChecked(True)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Nueva contraseña")

        form = QFormLayout()
        form.addRow("Usuario:", self.username)
        form.addRow("Nombre:", self.full_name)
        form.addRow("Rol:", self.role)
        form.addRow("Estado:", self.active)
        form.addRow("Contraseña:", self.password)

        self.btn_new = QPushButton("Nuevo")
        self.btn_save = QPushButton("Guardar")
        self.btn_password = QPushButton("Cambiar contraseña")
        self.btn_password.setObjectName("SecondaryButton")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setObjectName("SecondaryButton")
        self.btn_new.clicked.connect(self._new)
        self.btn_save.clicked.connect(self._save)
        self.btn_password.clicked.connect(self._change_password)
        self.btn_delete.clicked.connect(self._delete)

        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_new)
        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_password)
        buttons.addWidget(self.btn_delete)
        buttons.addStretch(1)

        editor = QGroupBox("Datos de acceso")
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
        rows = self.repo.list_users()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["username"] or ""))
            self.table.setItem(row_index, 2, QTableWidgetItem(row["full_name"] or ""))
            self.table.setItem(row_index, 3, QTableWidgetItem(row["role"] or ""))
            self.table.setItem(row_index, 4, QTableWidgetItem("Sí" if int(row["active"] or 0) == 1 else "No"))
            self.table.setItem(row_index, 5, QTableWidgetItem(row["created_at"] or ""))
        self.table.resizeColumnsToContents()

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            self.selected_id = None
            return
        row = items[0].row()
        self.selected_id = int(self.table.item(row, 0).text())
        self.username.setText(self.table.item(row, 1).text())
        self.username.setEnabled(False)
        self.full_name.setText(self.table.item(row, 2).text())
        self.role.setCurrentText(self.table.item(row, 3).text() or "Usuario")
        self.active.setChecked(self.table.item(row, 4).text() == "Sí")
        self.password.clear()

    def _new(self) -> None:
        self.selected_id = None
        self.table.clearSelection()
        self.username.setEnabled(True)
        self.username.clear()
        self.full_name.clear()
        self.role.setCurrentText("Usuario")
        self.active.setChecked(True)
        self.password.clear()
        self.username.setFocus()

    def _save(self) -> None:
        try:
            if self.selected_id is None:
                self.repo.create_user(
                    username=self.username.text(),
                    password=self.password.text(),
                    full_name=self.full_name.text(),
                    role=self.role.currentText(),
                    active=self.active.isChecked(),
                    created_at=now_iso(),
                )
                info(self, "Usuarios", "Usuario creado.")
            else:
                self.repo.update_user(
                    self.selected_id,
                    full_name=self.full_name.text(),
                    role=self.role.currentText(),
                    active=self.active.isChecked(),
                )
                info(self, "Usuarios", "Usuario actualizado.")
        except Exception as exc:
            warn(self, "Usuarios", str(exc))
            return
        self.refresh()

    def _change_password(self) -> None:
        if self.selected_id is None:
            warn(self, "Usuarios", "Selecciona un usuario.")
            return
        try:
            self.repo.update_user_password(self.selected_id, self.password.text())
        except Exception as exc:
            warn(self, "Usuarios", str(exc))
            return
        self.password.clear()
        info(self, "Usuarios", "Contraseña actualizada.")

    def _delete(self) -> None:
        if self.selected_id is None:
            warn(self, "Usuarios", "Selecciona un usuario.")
            return
        if not confirm(self, "Usuarios", "¿Eliminar este usuario?"):
            return
        try:
            self.repo.delete_user(self.selected_id)
        except Exception as exc:
            warn(self, "Usuarios", str(exc))
            return
        self._new()
        self.refresh()

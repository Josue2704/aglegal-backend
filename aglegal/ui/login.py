from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .common import warn
from ..repositories import Repository


class LoginDialog(QDialog):
    def __init__(self, repo: Repository):
        super().__init__()
        self.repo = repo
        self.current_username: str | None = None
        self.setWindowTitle("AGLEGAL - Login")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setObjectName("LoginDialog")

        title = QLabel("Bienvenido a AGLEGAL")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setObjectName("LoginTitle")

        self.username = QLineEdit()
        self.username.setPlaceholderText("Usuario")
        self.username.setText("admin")

        self.password = QLineEdit()
        self.password.setPlaceholderText("Contraseña")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setText("admin")

        form = QFormLayout()
        form.addRow("Usuario:", self.username)
        form.addRow("Contraseña:", self.password)

        self.btn_login = QPushButton("Entrar")
        self.btn_login.clicked.connect(self._on_login)
        self.btn_login.setDefault(True)
        self.btn_login.setObjectName("PrimaryButton")

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(self.btn_login)

        root = QVBoxLayout()
        subtitle = QLabel("Ingresa tus credenciales para continuar")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setObjectName("LoginSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(8)
        root.addLayout(form)
        root.addLayout(btns)
        self.setLayout(root)

        self.setStyleSheet(
            """
            QDialog#LoginDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                            stop:0 #0b1220, stop:1 #111827);
                border-radius: 14px;
            }
            QLabel { color: #e5e7eb; }
            QLabel#LoginTitle { font-size: 24px; font-weight: 900; color: #ffffff; margin: 8px 0 0 0; }
            QLabel#LoginSubtitle { color: rgba(226,232,240,0.74); margin-bottom: 8px; }
            QLineEdit {
                background: rgba(255,255,255,0.11);
                border: 1px solid rgba(255,255,255,0.20);
                border-radius: 12px;
                padding: 11px 13px;
                color: #ffffff;
            }
            QLineEdit:focus { border: 1px solid #818cf8; background: rgba(255,255,255,0.16); }
            QPushButton#PrimaryButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                            stop:0 #6366f1, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 12px;
                padding: 11px 18px;
                font-weight: 800;
            }
            QPushButton#PrimaryButton:hover { background: #4338ca; }
            """
        )

    def _on_login(self) -> None:
        u = self.username.text().strip()
        p = self.password.text()
        if not u or not p:
            warn(self, "Login", "Usuario y contraseña son requeridos.")
            return
        if not self.repo.authenticate(u, p):
            warn(self, "Login", "Credenciales inválidas.")
            return
        self.current_username = u
        self.accept()

"""Dialog for one authenticated server entry.

The password is handed to the caller for storage in the Windows Credential
Manager.  It is never written into the settings database.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...core.network import valid_proxy_host
from ..theme import ThemeManager
from .common import (
    BaseDialog,
    make_divider,
    make_header,
    make_label,
    primary_button,
    secondary_button,
)


class SiteAuthDialog(BaseDialog):
    def __init__(
        self,
        theme: ThemeManager,
        entry: dict | None = None,
        has_password: bool = False,
        parent=None,
    ) -> None:
        super().__init__(theme, parent)
        self._result: tuple[str, str, str, str] | None = None
        self._has_password = has_password
        self.setWindowTitle("Server authentication")
        self.setMinimumWidth(540)
        self.setSizeGripEnabled(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(9)
        root.addWidget(
            make_header(
                "Server authentication",
                "IDM signs in to this host automatically. The password is kept "
                "in Windows Credential Manager, never in the settings database.",
            )
        )

        root.addWidget(make_label("Host", "FieldLabel"))
        self.host_edit = QLineEdit(str((entry or {}).get("host") or ""))
        self.host_edit.setPlaceholderText("downloads.example.com")
        self.host_edit.setMinimumHeight(30)
        root.addWidget(self.host_edit)

        root.addWidget(make_label("User name", "FieldLabel"))
        self.username_edit = QLineEdit(str((entry or {}).get("username") or ""))
        self.username_edit.setMinimumHeight(30)
        root.addWidget(self.username_edit)

        root.addWidget(make_label("Authentication", "FieldLabel"))
        self.scheme_combo = QComboBox()
        self.scheme_combo.addItem("Basic (most servers)", "basic")
        self.scheme_combo.addItem("Digest", "digest")
        scheme = str((entry or {}).get("scheme") or "basic")
        index = self.scheme_combo.findData(scheme)
        self.scheme_combo.setCurrentIndex(max(0, index))
        root.addWidget(self.scheme_combo)

        root.addWidget(make_label("Password", "FieldLabel"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumHeight(30)
        if has_password:
            self.password_edit.setPlaceholderText(
                "A password is saved. Leave blank to keep it."
            )
        else:
            self.password_edit.setPlaceholderText("Password")
        root.addWidget(self.password_edit)

        hint = QLabel(
            "The user name and password are sent only to this exact host. "
            "Redirects to another host never receive the credentials."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        root.addWidget(make_divider())
        footer = QHBoxLayout()
        footer.setSpacing(8)
        footer.addStretch(1)
        cancel = secondary_button("Cancel")
        save = primary_button("Save")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept)
        footer.addWidget(cancel)
        footer.addWidget(save)
        root.addLayout(footer)

    @property
    def has_password(self) -> bool:
        return self._has_password

    def _accept(self) -> None:
        host = self.host_edit.text().strip().lower()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not valid_proxy_host(host):
            self._error("Enter a valid host name without a scheme or path.")
            return
        if not username:
            self._error("Enter the user name for this host.")
            return
        if not password and not self._has_password:
            self._error("Enter the password for this host.")
            return
        if any(ord(character) < 32 for character in username):
            self._error("The user name contains invalid characters.")
            return
        self._result = (
            host,
            username,
            str(self.scheme_combo.currentData() or "basic"),
            password,
        )
        self.accept()

    def _error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def values(self) -> tuple[str, str, str, str]:
        if self._result is None:
            raise RuntimeError("The dialog has not been accepted.")
        return self._result


__all__ = ["SiteAuthDialog"]

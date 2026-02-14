from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class CommandPaletteDialog(QDialog):
    def __init__(self, actions: dict[str, Callable[[], None]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Befehlspalette")
        self.setModal(True)
        self.resize(520, 380)

        self._actions = actions

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Befehl:"))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Aktion eingeben...")
        row.addWidget(self.search)
        layout.addLayout(row)

        self.list_widget = QListWidget(self)
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._execute_selected)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._execute_selected())
        self._refresh("")

        self.search.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _refresh(self, text: str) -> None:
        self.list_widget.clear()
        needle = text.casefold().strip()
        for name in sorted(self._actions):
            if needle and needle not in name.casefold():
                continue
            self.list_widget.addItem(QListWidgetItem(name))

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _execute_selected(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        action = self._actions.get(item.text())
        if action is None:
            return
        self.accept()
        action()

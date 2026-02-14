from __future__ import annotations

import base64
import html
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from terminology_manager.persistence.models import Chapter
from terminology_manager.services.terminology_service import TerminologyService
from terminology_manager.ui.image_editor_dialog import ImageEditorDialog


class ChapterDialog(QDialog):
    def __init__(self, chapter: Chapter | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kapitel")
        self.resize(360, 150)

        form = QFormLayout(self)
        self.name_de = QLineEdit(self)
        self.name_en = QLineEdit(self)
        self.visible = QCheckBox("In Suche sichtbar", self)
        self.visible.setChecked(True)

        if chapter is not None:
            self.name_de.setText(chapter.name_de)
            self.name_en.setText(chapter.name_en)
            self.visible.setChecked(chapter.visible)

        form.addRow("Name (DE)", self.name_de)
        form.addRow("Name (EN)", self.name_en)
        form.addRow("", self.visible)

        buttons = QHBoxLayout()
        ok = QPushButton("Speichern", self)
        cancel = QPushButton("Abbrechen", self)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        form.addRow(buttons)

    def payload(self) -> tuple[str, str, bool]:
        return self.name_de.text().strip(), self.name_en.text().strip(), self.visible.isChecked()


class MainWindow(QMainWindow):
    def __init__(self, service: TerminologyService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("Terminologie-Manager")
        self.resize(1380, 860)

        self.is_unlocked = False
        self.current_term_id: int | None = None
        self.current_image_bytes: bytes | None = None
        self.edit_buttons: list[QPushButton] = []
        self.lock_icon = QIcon()
        self.unlock_icon = QIcon()

        self._build_ui()
        self._refresh_all()
        self._set_lock_state(False)

    def _build_ui(self) -> None:
        top = QToolBar("Menü")
        top.setMovable(False)
        self.addToolBar(top)

        self.logo_label = QLabel(self)
        self.logo_label.setMinimumWidth(150)
        top.addWidget(self.logo_label)

        top.addSeparator()
        self.btn_new = QAction("Neuer Begriff", self)
        self.btn_save = QAction("Speichern", self)
        self.btn_delete = QAction("Löschen", self)
        self.btn_manage_chapters = QAction("Kapitel verwalten", self)
        self.btn_history = QAction("Historie", self)
        for action, slot in [
            (self.btn_new, self._new_term),
            (self.btn_save, self._save_term),
            (self.btn_delete, self._delete_term),
            (self.btn_manage_chapters, self._manage_chapters),
            (self.btn_history, self._show_history),
        ]:
            action.triggered.connect(slot)
            top.addAction(action)

        top.addSeparator()
        self.btn_import = QAction("Importieren", self)
        self.btn_export = QAction("Exportieren", self)
        self.btn_import.triggered.connect(self._import_file)
        self.btn_export.triggered.connect(self._export_file)
        top.addAction(self.btn_import)
        top.addAction(self.btn_export)

        # Spacer drückt die Bearbeitungs-Sperre an den rechten Rand der Toolbar.
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(spacer)

        self._load_lock_icons()
        self.lock_action = QAction("Bearbeitung entsperren", self)
        self.lock_action.setCheckable(True)
        self.lock_action.triggered.connect(self._toggle_lock)
        top.addAction(self.lock_action)
        self._configure_shortcuts()

        root = QSplitter(self)
        self.setCentralWidget(root)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("FTS5-Suche (de/en/Beschreibung/Synonyme)")
        self.search_input.textChanged.connect(self._search)
        left_layout.addWidget(self.search_input)

        self.result_tree = QTreeWidget(self)
        self.result_tree.setColumnCount(3)
        self.result_tree.setHeaderLabels(["Begriff", "Kapitel", "Rang"])
        self.result_tree.itemSelectionChanged.connect(self._on_result_selected)
        left_layout.addWidget(self.result_tree, 1)

        self.snippet_browser = QTextBrowser(self)
        self.snippet_browser.setPlaceholderText("Markierte Treffer erscheinen hier")
        left_layout.addWidget(self.snippet_browser, 1)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)

        editor_top_row = QHBoxLayout()

        form = QWidget(self)
        form_layout = QFormLayout(form)
        self.term_de = QLineEdit(self)
        self.term_en = QLineEdit(self)
        self.term_de_desc = QTextEdit(self)
        self.term_en_desc = QTextEdit(self)
        form_layout.addRow("Deutsch", self.term_de)
        form_layout.addRow("Englisch", self.term_en)
        form_layout.addRow("Beschreibung (DE)", self.term_de_desc)
        form_layout.addRow("Beschreibung (EN)", self.term_en_desc)
        editor_top_row.addWidget(form, 2)

        image_panel = QWidget(self)
        image_panel_layout = QVBoxLayout(image_panel)
        self.image_preview = QLabel("(kein Bild)", self)
        self.image_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_preview.setFixedSize(300, 220)
        self.image_preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.image_preview.setStyleSheet("border:1px solid #666;")
        image_panel_layout.addWidget(self.image_preview, alignment=Qt.AlignmentFlag.AlignTop)
        image_buttons = QHBoxLayout()
        self.btn_pick_image = QPushButton("Bild wählen", self)
        self.btn_edit_image = QPushButton("Bild bearbeiten", self)
        self.btn_clear_image = QPushButton("Leeren", self)
        self.btn_pick_image.clicked.connect(self._pick_image)
        self.btn_edit_image.clicked.connect(self._edit_image)
        self.btn_clear_image.clicked.connect(self._clear_image)
        image_buttons.addWidget(self.btn_pick_image)
        image_buttons.addWidget(self.btn_edit_image)
        image_buttons.addWidget(self.btn_clear_image)
        image_panel_layout.addLayout(image_buttons)
        image_panel_layout.addStretch(1)
        editor_top_row.addWidget(image_panel, 1)

        right_layout.addLayout(editor_top_row)

        self.chapter_list = QListWidget(self)
        right_layout.addWidget(QLabel("Kapitel"))
        right_layout.addWidget(self.chapter_list)

        self.syn_table = QTableWidget(self)
        self.syn_table.setColumnCount(3)
        self.syn_table.setHorizontalHeaderLabels(["Sprache", "Synonym", "Zugelassen"])
        self.syn_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(QLabel("Synonyme"))
        syn_buttons = QHBoxLayout()
        self.btn_syn_add = QPushButton("+", self)
        self.btn_syn_del = QPushButton("-", self)
        self.btn_syn_add.clicked.connect(lambda: self._append_table_row(self.syn_table, ["de", "", "1"]))
        self.btn_syn_del.clicked.connect(lambda: self._remove_selected_table_row(self.syn_table))
        syn_buttons.addWidget(self.btn_syn_add)
        syn_buttons.addWidget(self.btn_syn_del)
        syn_buttons.addStretch(1)
        right_layout.addLayout(syn_buttons)
        right_layout.addWidget(self.syn_table)

        self.ann_table = QTableWidget(self)
        self.ann_table.setColumnCount(3)
        self.ann_table.setHorizontalHeaderLabels(["Sprache", "Anmerkung", "Zugelassen"])
        self.ann_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        right_layout.addWidget(QLabel("Anmerkungen"))
        ann_buttons = QHBoxLayout()
        self.btn_ann_add = QPushButton("+", self)
        self.btn_ann_del = QPushButton("-", self)
        self.btn_ann_add.clicked.connect(lambda: self._append_table_row(self.ann_table, ["de", "", "1"]))
        self.btn_ann_del.clicked.connect(lambda: self._remove_selected_table_row(self.ann_table))
        ann_buttons.addWidget(self.btn_ann_add)
        ann_buttons.addWidget(self.btn_ann_del)
        ann_buttons.addStretch(1)
        right_layout.addLayout(ann_buttons)
        right_layout.addWidget(self.ann_table)

        dup_row = QHBoxLayout()
        self.btn_check_duplicates = QPushButton("Duplikate prüfen", self)
        self.btn_check_duplicates.clicked.connect(self._check_duplicates)
        self.duplicate_output = QLabel("", self)
        self.duplicate_output.setWordWrap(True)
        dup_row.addWidget(self.btn_check_duplicates)
        dup_row.addWidget(self.duplicate_output, 1)
        right_layout.addLayout(dup_row)

        self.edit_buttons = [
            self.btn_pick_image,
            self.btn_edit_image,
            self.btn_clear_image,
            self.btn_syn_add,
            self.btn_syn_del,
            self.btn_ann_add,
            self.btn_ann_del,
            self.btn_check_duplicates,
        ]
        for button in self.edit_buttons:
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        root.addWidget(left)
        root.addWidget(right)
        root.setSizes([520, 860])

        self.setStatusBar(QStatusBar(self))

    def _configure_shortcuts(self) -> None:
        shortcut_map = [
            (self.lock_action, "Ctrl+L"),
            (self.btn_new, "Ctrl+N"),
            (self.btn_save, "Ctrl+S"),
            (self.btn_delete, "Ctrl+R"),
            (self.btn_manage_chapters, "Ctrl+K"),
            (self.btn_history, "Ctrl+H"),
        ]
        for action, sequence in shortcut_map:
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
            action.setStatusTip(f"{action.text()} ({sequence})")
            action.setToolTip(f"{action.text()} ({sequence})")

    def _refresh_all(self) -> None:
        self._load_logo()
        self._load_chapters()
        self._search(self.search_input.text())

    def _load_lock_icons(self) -> None:
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        locked_svg = assets_dir / "lock-closed.svg"
        unlocked_svg = assets_dir / "lock-open.svg"
        self.lock_icon = self._colored_svg_icon(locked_svg, QColor("#DC2626"))  # red
        self.unlock_icon = self._colored_svg_icon(unlocked_svg, QColor("#16A34A"))  # green

    def _colored_svg_icon(self, path: Path, color: QColor, size: int = 18) -> QIcon:
        if not path.exists():
            return QIcon()
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QIcon()

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()
        return QIcon(pixmap)

    def _load_logo(self) -> None:
        logo_path = Path(__file__).resolve().parents[1] / "assets" / "k&z_logo.svg"
        if not logo_path.exists():
            self.logo_label.setText("Terminologie-Manager")
            return
        renderer = QSvgRenderer(str(logo_path))
        if not renderer.isValid():
            self.logo_label.setText("Terminologie-Manager")
            return
        pix = QPixmap(220, 64)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        renderer.render(painter)
        painter.end()
        self.logo_label.setPixmap(
            pix.scaled(140, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )

    def _load_chapters(self, selected_ids: list[int] | None = None) -> None:
        selected = set(selected_ids or [])
        self.chapter_list.clear()
        for chapter in self.service.list_chapters():
            item = QListWidgetItem(f"{chapter.name_de} | {chapter.name_en}")
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if chapter.id in selected else Qt.CheckState.Unchecked
            )
            if not chapter.visible:
                item.setForeground(Qt.GlobalColor.darkGray)
            self.chapter_list.addItem(item)

    def _set_lock_state(self, unlocked: bool) -> None:
        self.is_unlocked = unlocked
        self.lock_action.setText("Bearbeitung sperren" if unlocked else "Bearbeitung entsperren")
        self.lock_action.setIcon(self.unlock_icon if unlocked else self.lock_icon)
        self.lock_action.setStatusTip(f"{self.lock_action.text()} (Ctrl+L)")
        self.lock_action.setToolTip(f"{self.lock_action.text()} (Ctrl+L)")

        for widget in [
            self.term_de,
            self.term_en,
            self.term_de_desc,
            self.term_en_desc,
            self.chapter_list,
            self.syn_table,
            self.ann_table,
        ]:
            widget.setEnabled(unlocked)

        for action in [
            self.btn_new,
            self.btn_save,
            self.btn_delete,
            self.btn_manage_chapters,
            self.btn_import,
        ]:
            action.setEnabled(unlocked)
        for button in self.edit_buttons:
            button.setEnabled(unlocked)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor if unlocked else Qt.CursorShape.ForbiddenCursor
            )

    def _toggle_lock(self, checked: bool) -> None:
        self._set_lock_state(checked)
        self.statusBar().showMessage("Bearbeitung entsperrt" if checked else "Bearbeitung gesperrt", 3000)

    def _search(self, query: str) -> None:
        self.result_tree.clear()
        if not query.strip():
            self.snippet_browser.clear()
            for term in self.service.list_terms():
                item = QTreeWidgetItem([f"{term['de']} / {term['en']}", "", ""])
                item.setData(0, Qt.ItemDataRole.UserRole, term["id"])
                self.result_tree.addTopLevelItem(item)
            return

        grouped: dict[str, list[Any]] = {}
        for row in self.service.search(query, include_hidden_chapters=False):
            key = row.chapter_de or "(Ohne Kapitel)"
            grouped.setdefault(key, []).append(row)

        for chapter_name, rows in grouped.items():
            group_item = QTreeWidgetItem([chapter_name, "", ""])
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.result_tree.addTopLevelItem(group_item)
            for row in rows:
                item = QTreeWidgetItem([f"{row.de} / {row.en}", chapter_name, f"{row.rank:.3f}"])
                item.setData(0, Qt.ItemDataRole.UserRole, row.term_id)
                item.setData(1, Qt.ItemDataRole.UserRole, row)
                group_item.addChild(item)
            group_item.setExpanded(True)

    def _on_result_selected(self) -> None:
        items = self.result_tree.selectedItems()
        if not items:
            return
        item = items[0]
        term_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(term_id, int):
            return
        self._load_term(term_id)

        row = item.data(1, Qt.ItemDataRole.UserRole)
        if row is not None:
            snippet_html = (
                f"<b>DE</b>: {html.escape(row.snippet_de)}<br>"
                f"<b>EN</b>: {html.escape(row.snippet_en)}<br>"
                f"<b>Synonyme</b>: {html.escape(row.snippet_synonyms)}"
            )
            snippet_html = snippet_html.replace("&lt;mark&gt;", "<mark>").replace("&lt;/mark&gt;", "</mark>")
            self.snippet_browser.setHtml(snippet_html)

    def _load_term(self, term_id: int) -> None:
        term = self.service.get_term(term_id)
        if term is None:
            return

        self.current_term_id = term_id
        self.term_de.setText(term["de"])
        self.term_en.setText(term["en"])
        self.term_de_desc.setPlainText(term["de_desc"])
        self.term_en_desc.setPlainText(term["en_desc"])

        selected_chapters = [int(cid) for cid in term.get("chapter_ids", [])]
        self._load_chapters(selected_chapters)

        self._load_table(
            self.syn_table,
            rows=[
                [str(s.get("lang", "de")), str(s.get("synonym", "")), "1" if s.get("allowed", True) else "0"]
                for s in term.get("synonyms", [])
            ],
        )
        self._load_table(
            self.ann_table,
            rows=[
                [str(a.get("lang", "de")), str(a.get("note", "")), "1" if a.get("allowed", True) else "0"]
                for a in term.get("annotations", [])
            ],
        )

        image_has_data = bool(term.get("image"))
        self.current_image_bytes = self._decode_image(term) if image_has_data else None
        self._refresh_image_preview()

    def _decode_image(self, term: dict[str, Any]) -> bytes | None:
        raw = term.get("image_bytes")
        if isinstance(raw, bytes):
            return raw
        image_b64 = term.get("image_b64")
        if isinstance(image_b64, str) and image_b64:
            return base64.b64decode(image_b64)
        return self.current_image_bytes

    def _load_table(self, table: QTableWidget, rows: list[list[str]]) -> None:
        table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, value in enumerate(row):
                table.setItem(r_idx, c_idx, QTableWidgetItem(value))

    def _append_table_row(self, table: QTableWidget, values: list[str]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for col, value in enumerate(values):
            table.setItem(row, col, QTableWidgetItem(value))

    def _remove_selected_table_row(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    def _table_rows(self, table: QTableWidget, text_column_name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for r in range(table.rowCount()):
            lang_item = table.item(r, 0)
            value_item = table.item(r, 1)
            allowed_item = table.item(r, 2)
            if lang_item is None or value_item is None:
                continue
            value_text = value_item.text().strip()
            if not value_text:
                continue
            rows.append(
                {
                    "lang": lang_item.text().strip() or "de",
                    text_column_name: value_text,
                    "allowed": (allowed_item.text().strip() if allowed_item else "1") in {"1", "true", "True", "yes"},
                }
            )
        return rows

    def _new_term(self) -> None:
        if not self.is_unlocked:
            return
        self.current_term_id = None
        self.current_image_bytes = None
        self.term_de.clear()
        self.term_en.clear()
        self.term_de_desc.clear()
        self.term_en_desc.clear()
        self._load_chapters([])
        self.syn_table.setRowCount(0)
        self.ann_table.setRowCount(0)
        self._refresh_image_preview()

    def _save_term(self) -> None:
        if not self.is_unlocked:
            return
        de = self.term_de.text().strip()
        en = self.term_en.text().strip()
        if not de or not en:
            QMessageBox.warning(self, "Fehlende Daten", "Deutsch- und Englisch-Begriff sind Pflicht.")
            return

        chapter_ids: list[int] = []
        for idx in range(self.chapter_list.count()):
            item = self.chapter_list.item(idx)
            if item.checkState() == Qt.CheckState.Checked:
                chapter_ids.append(int(item.data(Qt.ItemDataRole.UserRole)))

        term_id = self.service.save_term(
            term_id=self.current_term_id,
            de=de,
            en=en,
            de_desc=self.term_de_desc.toPlainText(),
            en_desc=self.term_en_desc.toPlainText(),
            image=self.current_image_bytes,
            synonyms=self._table_rows(self.syn_table, "synonym"),
            annotations=self._table_rows(self.ann_table, "note"),
            chapter_ids=chapter_ids,
        )

        self.current_term_id = term_id
        self.statusBar().showMessage("Begriff gespeichert", 3000)
        self._search(self.search_input.text())

    def _delete_term(self) -> None:
        if not self.is_unlocked or self.current_term_id is None:
            return
        if QMessageBox.question(
            self, "Löschen", "Diesen Begriff wirklich löschen?"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.service.delete_term(self.current_term_id)
        self.statusBar().showMessage("Begriff gelöscht", 3000)
        self._new_term()
        self._search(self.search_input.text())

    def _pick_image(self) -> None:
        if not self.is_unlocked:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Bild auswählen", "", "Bilder (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        self.current_image_bytes = Path(path).read_bytes()
        self._refresh_image_preview()

    def _edit_image(self) -> None:
        if not self.is_unlocked or not self.current_image_bytes:
            return
        dialog = ImageEditorDialog(self.current_image_bytes, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_image_bytes = dialog.edited_bytes
            self._refresh_image_preview()

    def _clear_image(self) -> None:
        if not self.is_unlocked:
            return
        self.current_image_bytes = None
        self._refresh_image_preview()

    def _refresh_image_preview(self) -> None:
        if not self.current_image_bytes:
            self.image_preview.setText("(kein Bild)")
            self.image_preview.setPixmap(QPixmap())
            return
        pix = QPixmap()
        pix.loadFromData(self.current_image_bytes)
        self.image_preview.setPixmap(
            pix.scaled(
                self.image_preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _manage_chapters(self) -> None:
        if not self.is_unlocked:
            return
        chapters = self.service.list_chapters()
        selector = QDialog(self)
        selector.setWindowTitle("Kapitel verwalten")
        selector.resize(480, 400)
        layout = QVBoxLayout(selector)
        list_widget = QListWidget(selector)
        for chapter in chapters:
            item = QListWidgetItem(
                f"{chapter.name_de} | {chapter.name_en} ({'sichtbar' if chapter.visible else 'versteckt'})"
            )
            item.setData(Qt.ItemDataRole.UserRole, chapter.id)
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QHBoxLayout()
        b_add = QPushButton("Hinzufügen", selector)
        b_edit = QPushButton("Bearbeiten", selector)
        b_delete = QPushButton("Löschen", selector)
        b_close = QPushButton("Schließen", selector)
        buttons.addWidget(b_add)
        buttons.addWidget(b_edit)
        buttons.addWidget(b_delete)
        buttons.addWidget(b_close)
        layout.addLayout(buttons)

        def add_chapter() -> None:
            dlg = ChapterDialog(parent=selector)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            name_de, name_en, visible = dlg.payload()
            self.service.save_chapter(None, name_de, name_en, visible)
            selector.accept()

        def edit_chapter() -> None:
            item = list_widget.currentItem()
            if item is None:
                return
            chapter_id = int(item.data(Qt.ItemDataRole.UserRole))
            chapter = next((c for c in chapters if c.id == chapter_id), None)
            if chapter is None:
                return
            dlg = ChapterDialog(chapter=chapter, parent=selector)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            name_de, name_en, visible = dlg.payload()
            self.service.save_chapter(chapter_id, name_de, name_en, visible)
            selector.accept()

        def delete_chapter() -> None:
            item = list_widget.currentItem()
            if item is None:
                return
            chapter_id = int(item.data(Qt.ItemDataRole.UserRole))
            self.service.delete_chapter(chapter_id)
            selector.accept()

        b_add.clicked.connect(add_chapter)
        b_edit.clicked.connect(edit_chapter)
        b_delete.clicked.connect(delete_chapter)
        b_close.clicked.connect(selector.reject)

        selector.exec()
        self._load_chapters()
        self._search(self.search_input.text())

    def _check_duplicates(self) -> None:
        synonyms = [
            self.syn_table.item(r, 1).text()
            for r in range(self.syn_table.rowCount())
            if self.syn_table.item(r, 1) is not None
        ]
        report = self.service.detect_duplicates(self.term_de.text(), self.term_en.text(), synonyms)

        parts: list[str] = []
        if report.exact_term_ids:
            parts.append(f"Exakte Begriff-Duplikate: {report.exact_term_ids}")
        if report.exact_synonym_term_ids:
            parts.append(f"Exakte Synonym-Duplikate: {report.exact_synonym_term_ids}")
        if report.fuzzy_hits:
            top = ", ".join(f"{h.value} ({h.score:.2f})" for h in report.fuzzy_hits[:4])
            parts.append(f"Ähnlichkeits-Treffer: {top}")
        self.duplicate_output.setText(" | ".join(parts) if parts else "Keine Duplikate gefunden.")

    def _show_history(self) -> None:
        if self.current_term_id is None:
            return
        records = self.service.history_for_term(self.current_term_id)
        records = [rec for rec in records if self._history_has_visible_change(rec.action, rec.before_json, rec.after_json)]
        dlg = QDialog(self)
        dlg.setWindowTitle("Versionshistorie")
        dlg.resize(980, 620)
        layout = QVBoxLayout(dlg)

        if not records:
            browser = QTextBrowser(dlg)
            browser.setText("Keine relevanten Historieneinträge vorhanden")
            layout.addWidget(browser)
        else:
            splitter = QSplitter(Qt.Orientation.Horizontal, dlg)
            event_list = QListWidget(splitter)
            event_list.setMinimumWidth(350)
            details = QTextBrowser(splitter)
            splitter.addWidget(event_list)
            splitter.addWidget(details)
            splitter.setSizes([380, 600])
            layout.addWidget(splitter)

            for rec in records:
                summary = self._history_summary(rec.action, rec.before_json, rec.after_json)
                action = self._history_action_label(rec.action)
                timestamp = rec.changed_at.strftime("%d.%m.%Y %H:%M:%S")
                item = QListWidgetItem(f"{timestamp} | {action}\n{summary}")
                item.setData(Qt.ItemDataRole.UserRole, rec)
                event_list.addItem(item)

            def on_select() -> None:
                selected = event_list.currentItem()
                if selected is None:
                    return
                rec = selected.data(Qt.ItemDataRole.UserRole)
                details.setHtml(self._history_details_html(rec.action, rec.before_json, rec.after_json, rec.changed_at))

            event_list.itemSelectionChanged.connect(on_select)
            event_list.setCurrentRow(0)

        btn = QPushButton("Schließen", dlg)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()

    def _history_action_label(self, action: str) -> str:
        return {
            "create": "Erstellt",
            "update": "Geändert",
            "delete": "Gelöscht",
        }.get(action, action)

    def _history_summary(self, action: str, before_json: str | None, after_json: str | None) -> str:
        changes = self._history_changes(before_json, after_json)
        if action == "create":
            return "Eintrag wurde angelegt."
        if action == "delete":
            return "Eintrag wurde gelöscht."
        if not changes:
            return "Keine Feldänderungen erkannt."
        names = ", ".join(change[0] for change in changes[:4])
        if len(changes) > 4:
            names += f" (+{len(changes) - 4} weitere)"
        return f"Geänderte Felder: {names}"

    def _history_details_html(
        self,
        action: str,
        before_json: str | None,
        after_json: str | None,
        changed_at: Any,
    ) -> str:
        timestamp = changed_at.strftime("%d.%m.%Y %H:%M:%S")
        before_data = self._history_parse_json(before_json)
        after_data = self._history_parse_json(after_json)
        changes = self._history_changes(before_json, after_json)
        header = f"<h3>{self._history_action_label(action)} am {timestamp}</h3>"

        if action == "create":
            rows = "".join(
                f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(self._history_value_str(v))}</td></tr>"
                for k, v in sorted(after_data.items())
                if k not in {"image_b64"}
            )
            return (
                header
                + "<p>Neuer Datensatz:</p><table>"
                + rows
                + "</table>"
                + self._history_image_preview_block(None, after_data.get("image_b64"))
            )

        if action == "delete":
            rows = "".join(
                f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(self._history_value_str(v))}</td></tr>"
                for k, v in sorted(before_data.items())
                if k not in {"image_b64"}
            )
            return (
                header
                + "<p>Gelöschter Datensatz:</p><table>"
                + rows
                + "</table>"
                + self._history_image_preview_block(before_data.get("image_b64"), None)
            )

        if not changes:
            return header + "<p>Keine darstellbaren Änderungen.</p>"

        rows = "".join(
            (
                "<tr>"
                f"<td><b>{html.escape(field)}</b></td>"
                f"<td>{html.escape(self._history_value_str(old))}</td>"
                f"<td>{html.escape(self._history_value_str(new))}</td>"
                "</tr>"
            )
            for field, old, new in changes
        )
        return_html = (
            header
            + "<table border='0' cellspacing='6'>"
            + "<tr><th align='left'>Feld</th><th align='left'>Vorher</th><th align='left'>Nachher</th></tr>"
            + rows
            + "</table>"
        )
        before_image = before_data.get("image_b64")
        after_image = after_data.get("image_b64")
        if before_image != after_image:
            return_html += self._history_image_preview_block(before_image, after_image)
        return return_html

    def _history_changes(self, before_json: str | None, after_json: str | None) -> list[tuple[str, Any, Any]]:
        before = self._history_parse_json(before_json)
        after = self._history_parse_json(after_json)
        ignored = {"updated_at", "image_b64"}
        fields = sorted((set(before.keys()) | set(after.keys())) - ignored)
        changes: list[tuple[str, Any, Any]] = []
        for field in fields:
            old = before.get(field)
            new = after.get(field)
            if old != new:
                changes.append((field, old, new))
        return changes

    def _history_parse_json(self, payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _history_value_str(self, value: Any) -> str:
        if isinstance(value, list):
            return f"{len(value)} Einträge"
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        if value is None:
            return "—"
        if isinstance(value, bool):
            return "Ja" if value else "Nein"
        return str(value)

    def _history_has_visible_change(
        self, action: str, before_json: str | None, after_json: str | None
    ) -> bool:
        if action in {"create", "delete"}:
            return True
        changes = self._history_changes(before_json, after_json)
        if changes:
            return True
        before = self._history_parse_json(before_json)
        after = self._history_parse_json(after_json)
        return before.get("image_b64") != after.get("image_b64")

    def _history_image_preview_block(self, before_b64: Any, after_b64: Any) -> str:
        def img_html(data: Any) -> str:
            if not isinstance(data, str) or not data.strip():
                return "<span style='color:#9CA3AF'>(kein Bild)</span>"
            return (
                "<img style='max-width:220px; max-height:160px; border:1px solid #374151; border-radius:6px;' "
                f"src='data:image/png;base64,{data}' />"
            )

        if (not isinstance(before_b64, str) or not before_b64.strip()) and (
            not isinstance(after_b64, str) or not after_b64.strip()
        ):
            return ""

        return (
            "<h4>Bild</h4>"
            "<table border='0' cellspacing='8'>"
            "<tr><th align='left'>Vorher</th><th align='left'>Nachher</th></tr>"
            f"<tr><td>{img_html(before_b64)}</td><td>{img_html(after_b64)}</td></tr>"
            "</table>"
        )

    def _import_file(self) -> None:
        if not self.is_unlocked:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Importieren",
            "",
            "Unterstützt (*.json *.csv *.xlsx *.xls)",
        )
        if not path:
            return
        count = self.service.import_file(Path(path))
        self.statusBar().showMessage(f"{count} Begriffe importiert", 5000)
        self._search(self.search_input.text())

    def _export_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportieren",
            "terms.json",
            "JSON (*.json);;CSV (*.csv);;Excel (*.xlsx)",
        )
        if not path:
            return
        self.service.export_all(Path(path))
        self.statusBar().showMessage("Export abgeschlossen", 3000)

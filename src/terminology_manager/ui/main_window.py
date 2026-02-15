from __future__ import annotations

import base64
import html
import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSignalBlocker,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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
)

from terminology_manager.domain.entities import SearchResult
from terminology_manager.persistence.models import Chapter
from terminology_manager.services.terminology_service import TerminologyService
from terminology_manager.ui.image_editor_dialog import ImageEditorDialog

EDIT_MODE_PIN = os.getenv("TERM_MANAGER_EDIT_PIN", "1234")
PIN_LENGTH = 4


class SearchWorkerSignals(QObject):
    finished = Signal(int, str, list)


class SearchWorker(QRunnable):
    def __init__(self, request_id: int, query: str, service: TerminologyService) -> None:
        super().__init__()
        self.request_id = request_id
        self.query = query
        self.service = service
        self.signals = SearchWorkerSignals()

    def run(self) -> None:
        rows: list[SearchResult] = self.service.search(self.query, include_hidden_chapters=False)
        payload: list[tuple[SearchResult, str]] = []
        seen: set[int] = set()
        for row in rows:
            if row.term_id in seen:
                continue
            seen.add(row.term_id)
            term = self.service.get_term(row.term_id) or {}
            image_b64 = str(term.get("image_b64", "") or "")
            payload.append((row, image_b64))
            if len(payload) >= 25:
                break
        self.signals.finished.emit(self.request_id, self.query, payload)


class ChapterDialog(QDialog):
    def __init__(
        self,
        chapter: Chapter | None = None,
        chapters: list[Chapter] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kapitel")
        self.resize(460, 220)

        form = QFormLayout(self)
        self.name_de = QLineEdit(self)
        self.name_en = QLineEdit(self)
        self.visible = QCheckBox("In Suche sichtbar", self)
        self.parent_combo = QComboBox(self)
        self.visible.setChecked(True)
        self.parent_combo.addItem("Kein Elternkapitel", None)

        if chapter is not None:
            self.name_de.setText(chapter.name_de)
            self.name_en.setText(chapter.name_en)
            self.visible.setChecked(chapter.visible)

        for c in sorted(chapters or [], key=lambda x: x.name_de.casefold()):
            if chapter is not None and c.id == chapter.id:
                continue
            label = f"{c.name_de} | {c.name_en}" if c.name_en else c.name_de
            self.parent_combo.addItem(label, c.id)
            if chapter is not None and chapter.parent_id == c.id:
                self.parent_combo.setCurrentIndex(self.parent_combo.count() - 1)

        form.addRow("Name (DE)", self.name_de)
        form.addRow("Name (EN)", self.name_en)
        form.addRow("Elternkapitel", self.parent_combo)
        form.addRow("", self.visible)

        buttons = QHBoxLayout()
        ok = QPushButton("Speichern", self)
        cancel = QPushButton("Abbrechen", self)
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        form.addRow(buttons)

    def payload(self) -> tuple[str, str, bool, int | None]:
        parent_id = self.parent_combo.currentData()
        return (
            self.name_de.text().strip(),
            self.name_en.text().strip(),
            self.visible.isChecked(),
            int(parent_id) if isinstance(parent_id, int) else None,
        )


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
        self.search_dropdown: QListWidget | None = None
        self.search_debounce = QTimer(self)
        self.search_debounce.setSingleShot(True)
        self.search_debounce.timeout.connect(self._run_search_from_input)
        self.search_pool = QThreadPool.globalInstance()
        self.search_request_id = 0

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

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Suche (de/en/Beschreibung/Synonyme)")
        self.search_input.setMinimumWidth(220)
        self.search_input.setMaximumWidth(260)
        self.search_input.setFixedHeight(36)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.returnPressed.connect(self._select_first_search_result)
        top.addWidget(self.search_input)

        self.search_dropdown = QListWidget(self)
        self.search_dropdown.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.search_dropdown.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.search_dropdown.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_dropdown.setIconSize(QSize(28, 28))
        self.search_dropdown.hide()
        self.search_dropdown.itemClicked.connect(self._on_search_result_clicked)

        self._load_lock_icons()
        self.lock_action = QAction("Bearbeitung entsperren", self)
        self.lock_action.setCheckable(True)
        self.lock_action.triggered.connect(self._toggle_lock)
        top.addAction(self.lock_action)
        self._configure_shortcuts()

        main = QWidget(self)
        main_layout = QHBoxLayout(main)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(12)
        self.setCentralWidget(main)

        sidebar = QWidget(self)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addWidget(QLabel("Kapitel / Begriffe"))

        self.sidebar_tree_filter_input = QLineEdit(self)
        self.sidebar_tree_filter_input.setPlaceholderText("Kapitel filtern...")
        self.sidebar_tree_filter_input.textChanged.connect(self._on_sidebar_chapter_filter_changed)
        sidebar_layout.addWidget(self.sidebar_tree_filter_input)

        self.sidebar_term_tree = QTreeWidget(self)
        self.sidebar_term_tree.setColumnCount(1)
        self.sidebar_term_tree.setHeaderHidden(True)
        self.sidebar_term_tree.setRootIsDecorated(True)
        self.sidebar_term_tree.setIndentation(16)
        self.sidebar_term_tree.itemSelectionChanged.connect(self._on_sidebar_term_selected)
        sidebar_layout.addWidget(self.sidebar_term_tree, 1)
        main_layout.addWidget(sidebar, 1)

        content = QWidget(self)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        main_layout.addWidget(content, 4)

        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        content_layout.addWidget(left_panel, 2)
        content_layout.addWidget(right_panel, 1)

        form = QWidget(self)
        form_layout = QFormLayout(form)
        self.term_de = QLineEdit(self)
        self.term_en = QLineEdit(self)
        self.term_de_desc = QTextEdit(self)
        self.term_en_desc = QTextEdit(self)
        self.term_de.setMinimumWidth(620)
        self.term_en.setMinimumWidth(620)
        self.term_de_desc.setMinimumWidth(620)
        self.term_en_desc.setMinimumWidth(620)
        self.term_de_desc.setMaximumHeight(90)
        self.term_en_desc.setMaximumHeight(90)
        form_layout.addRow("Deutsch", self.term_de)
        form_layout.addRow("Englisch", self.term_en)
        form_layout.addRow("Beschreibung (DE)", self.term_de_desc)
        form_layout.addRow("Beschreibung (EN)", self.term_en_desc)
        left_layout.addWidget(form)

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
        right_layout.addWidget(image_panel)

        self.chapter_filter_input = QLineEdit(self)
        self.chapter_filter_input.setPlaceholderText("Kapitel filtern...")
        self.chapter_filter_input.textChanged.connect(self._on_chapter_filter_changed)
        right_layout.addWidget(QLabel("Kapitel / Unterkapitel"))
        right_layout.addWidget(self.chapter_filter_input)

        self.chapter_list = QTreeWidget(self)
        self.chapter_list.setColumnCount(1)
        self.chapter_list.setHeaderLabels([" "])
        self.chapter_list.setHeaderHidden(True)
        self.chapter_list.header().hide()
        self.chapter_list.header().setVisible(False)
        self.chapter_list.header().setFixedHeight(0)
        self.chapter_list.header().setMinimumSectionSize(0)
        self.chapter_list.header().setDefaultSectionSize(0)
        self.chapter_list.setRootIsDecorated(True)
        self.chapter_list.setIndentation(18)
        self.chapter_list.setMinimumHeight(180)
        self.chapter_list.setAlternatingRowColors(True)
        self.chapter_list.setUniformRowHeights(True)
        self.chapter_list.header().setStretchLastSection(True)
        right_layout.addWidget(self.chapter_list, 1)

        self.syn_table = QTableWidget(self)
        self.syn_table.setColumnCount(3)
        self.syn_table.setHorizontalHeaderLabels(["Sprache", "Synonym", "Zugelassen"])
        self.syn_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.syn_table.verticalHeader().setVisible(False)
        self.syn_table.setCornerButtonEnabled(False)
        left_layout.addWidget(QLabel("Synonyme"))
        syn_buttons = QHBoxLayout()
        self.btn_syn_add = QPushButton("+", self)
        self.btn_syn_del = QPushButton("-", self)
        self.btn_syn_add.clicked.connect(
            lambda: self._append_table_row(self.syn_table, ["de", "", "1"])
        )
        self.btn_syn_del.clicked.connect(lambda: self._remove_selected_table_row(self.syn_table))
        syn_buttons.addWidget(self.btn_syn_add)
        syn_buttons.addWidget(self.btn_syn_del)
        syn_buttons.addStretch(1)
        left_layout.addLayout(syn_buttons)
        left_layout.addWidget(self.syn_table, 1)

        self.ann_table = QTableWidget(self)
        self.ann_table.setColumnCount(3)
        self.ann_table.setHorizontalHeaderLabels(["Sprache", "Anmerkung", "Zugelassen"])
        self.ann_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ann_table.verticalHeader().setVisible(False)
        self.ann_table.setCornerButtonEnabled(False)
        left_layout.addWidget(QLabel("Anmerkungen"))
        ann_buttons = QHBoxLayout()
        self.btn_ann_add = QPushButton("+", self)
        self.btn_ann_del = QPushButton("-", self)
        self.btn_ann_add.clicked.connect(
            lambda: self._append_table_row(self.ann_table, ["de", "", "1"])
        )
        self.btn_ann_del.clicked.connect(lambda: self._remove_selected_table_row(self.ann_table))
        ann_buttons.addWidget(self.btn_ann_add)
        ann_buttons.addWidget(self.btn_ann_del)
        ann_buttons.addStretch(1)
        left_layout.addLayout(ann_buttons)
        left_layout.addWidget(self.ann_table, 1)

        dup_row = QHBoxLayout()
        self.btn_check_duplicates = QPushButton("Duplikate prüfen", self)
        self.btn_check_duplicates.clicked.connect(self._check_duplicates)
        self.duplicate_output = QLabel("", self)
        self.duplicate_output.setWordWrap(True)
        dup_row.addWidget(self.btn_check_duplicates)
        dup_row.addWidget(self.duplicate_output, 1)
        left_layout.addLayout(dup_row)

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

    def _on_search_text_changed(self, _text: str) -> None:
        # Debounce verhindert UI-Blockaden bei schnellem Tippen.
        self.search_debounce.start(140)

    def _run_search_from_input(self) -> None:
        if not self.search_input.isVisible() or not self.search_input.isVisibleTo(self):
            self._hide_search_dropdown()
            return
        self._start_search(self.search_input.text().strip())

    def _refresh_all(self) -> None:
        self._load_logo()
        self._load_chapters()
        self._refresh_term_sidebar()
        self._search(self.search_input.text())

    def _refresh_term_sidebar(self) -> None:
        chapter_filter = self.sidebar_tree_filter_input.text().strip().casefold()
        selected_term_id = self.current_term_id
        chapters = self.service.list_chapters()
        by_parent: dict[int | None, list[Chapter]] = {}
        by_id: dict[int, Chapter] = {}
        for chapter in chapters:
            by_parent.setdefault(chapter.parent_id, []).append(chapter)
            by_id[chapter.id] = chapter
        for items in by_parent.values():
            items.sort(key=lambda c: c.name_de.casefold())

        visible_chapter_ids: set[int] = set()
        if chapter_filter:
            def mark_descendants(chapter_id: int) -> None:
                for child in by_parent.get(chapter_id, []):
                    if child.id in visible_chapter_ids:
                        continue
                    visible_chapter_ids.add(child.id)
                    mark_descendants(child.id)

            for chapter in chapters:
                de = chapter.name_de.casefold()
                en = chapter.name_en.casefold()
                if chapter_filter in de or chapter_filter in en:
                    visible_chapter_ids.add(chapter.id)
                    mark_descendants(chapter.id)
                    parent_id = chapter.parent_id
                    while isinstance(parent_id, int):
                        visible_chapter_ids.add(parent_id)
                        parent = by_id.get(parent_id)
                        parent_id = parent.parent_id if parent is not None else None

        terms_by_chapter: dict[int, list[tuple[int, str]]] = {}
        terms_without_chapter: list[tuple[int, str]] = []
        terms = self.service.list_terms()
        for term in sorted(terms, key=lambda t: str(t.get("de", "")).casefold()):
            term_id_raw = term.get("id")
            if not isinstance(term_id_raw, int):
                continue
            raw_chapter_ids = term.get("chapter_ids", [])
            if not isinstance(raw_chapter_ids, list):
                raw_chapter_ids = []
            chapter_ids = [cid for cid in raw_chapter_ids if isinstance(cid, int)]
            title = f"{term.get('de', '')} | {term.get('en', '')}".strip()
            if not chapter_ids:
                terms_without_chapter.append((term_id_raw, title))
                continue
            for chapter_id in chapter_ids:
                terms_by_chapter.setdefault(chapter_id, []).append((term_id_raw, title))

        with QSignalBlocker(self.sidebar_term_tree):
            self.sidebar_term_tree.clear()

            def add_chapter_nodes(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for chapter in by_parent.get(parent_id, []):
                    if chapter_filter and chapter.id not in visible_chapter_ids:
                        continue
                    chapter_text = (
                        f"{chapter.name_de} | {chapter.name_en}" if chapter.name_en else chapter.name_de
                    )
                    chapter_item = QTreeWidgetItem([chapter_text])
                    chapter_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    font = QFont(chapter_item.font(0))
                    font.setBold(True)
                    chapter_item.setFont(0, font)
                    if parent_item is None:
                        self.sidebar_term_tree.addTopLevelItem(chapter_item)
                    else:
                        parent_item.addChild(chapter_item)

                    for term_id, title in terms_by_chapter.get(chapter.id, []):
                        term_item = QTreeWidgetItem([title])
                        term_item.setData(0, Qt.ItemDataRole.UserRole, term_id)
                        chapter_item.addChild(term_item)

                    add_chapter_nodes(chapter_item, chapter.id)

            add_chapter_nodes(None, None)

            show_uncategorized = not chapter_filter or "ohne kapitel".find(chapter_filter) >= 0
            if show_uncategorized:
                uncategorized = QTreeWidgetItem(["Ohne Kapitel"])
                unc_font = QFont(uncategorized.font(0))
                unc_font.setBold(True)
                uncategorized.setFont(0, unc_font)
                self.sidebar_term_tree.addTopLevelItem(uncategorized)
                for term_id, title in terms_without_chapter:
                    term_item = QTreeWidgetItem([title])
                    term_item.setData(0, Qt.ItemDataRole.UserRole, term_id)
                    uncategorized.addChild(term_item)

            self.sidebar_term_tree.expandAll()
            if isinstance(selected_term_id, int):
                selected_item = self._find_sidebar_term_item(selected_term_id)
                if selected_item is not None:
                    self.sidebar_term_tree.setCurrentItem(selected_item)

    def _find_sidebar_term_item(self, term_id: int) -> QTreeWidgetItem | None:
        def search(node: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = node.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(data, int) and data == term_id:
                return node
            for i in range(node.childCount()):
                hit = search(node.child(i))
                if hit is not None:
                    return hit
            return None

        for i in range(self.sidebar_term_tree.topLevelItemCount()):
            top = self.sidebar_term_tree.topLevelItem(i)
            if top is None:
                continue
            found = search(top)
            if found is not None:
                return found
        return None

    def _on_sidebar_chapter_filter_changed(self, _text: str) -> None:
        self._refresh_term_sidebar()

    def _on_sidebar_term_selected(self) -> None:
        current = self.sidebar_term_tree.currentItem()
        if current is None:
            return
        term_id = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(term_id, int) and term_id != self.current_term_id:
            self._load_term(term_id)

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
            pix.scaled(
                140,
                42,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _load_chapters(self, selected_ids: list[int] | None = None) -> None:
        selected = set(selected_ids or [])
        filter_text = (
            self.chapter_filter_input.text().strip().casefold()
            if hasattr(self, "chapter_filter_input")
            else ""
        )
        self.chapter_list.clear()
        chapters = self.service.list_chapters()
        by_parent: dict[int | None, list[Chapter]] = {}
        by_id: dict[int, Chapter] = {}
        for chapter in chapters:
            by_parent.setdefault(chapter.parent_id, []).append(chapter)
            by_id[chapter.id] = chapter
        for items in by_parent.values():
            items.sort(key=lambda c: c.name_de.casefold())

        visible_ids: set[int] = set()
        if filter_text:
            def mark_descendants(chapter_id: int) -> None:
                for child in by_parent.get(chapter_id, []):
                    if child.id in visible_ids:
                        continue
                    visible_ids.add(child.id)
                    mark_descendants(child.id)

            for chapter in chapters:
                de = chapter.name_de.casefold()
                en = chapter.name_en.casefold()
                if filter_text in de or filter_text in en:
                    visible_ids.add(chapter.id)
                    mark_descendants(chapter.id)
                    parent_id = chapter.parent_id
                    while isinstance(parent_id, int):
                        visible_ids.add(parent_id)
                        parent = by_id.get(parent_id)
                        parent_id = parent.parent_id if parent is not None else None

        def add_nodes(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
            for chapter in by_parent.get(parent_id, []):
                if filter_text and chapter.id not in visible_ids:
                    continue
                text = (
                    f"{chapter.name_de} | {chapter.name_en}" if chapter.name_en else chapter.name_de
                )
                node = QTreeWidgetItem([text])
                node.setData(0, Qt.ItemDataRole.UserRole, chapter.id)
                node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                node.setCheckState(
                    0, Qt.CheckState.Checked if chapter.id in selected else Qt.CheckState.Unchecked
                )
                if not chapter.visible:
                    node.setForeground(0, Qt.GlobalColor.darkGray)
                if parent_id is None:
                    font = QFont(node.font(0))
                    font.setBold(True)
                    node.setFont(0, font)
                if parent_item is None:
                    self.chapter_list.addTopLevelItem(node)
                else:
                    parent_item.addChild(node)
                add_nodes(node, chapter.id)

        add_nodes(None, None)
        self.chapter_list.expandAll()

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
            self.chapter_filter_input,
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

    def _on_chapter_filter_changed(self, _text: str) -> None:
        selected = self._selected_chapter_ids_from_tree()
        self._load_chapters(selected_ids=selected)

    def _selected_chapter_ids_from_tree(self) -> list[int]:
        selected: list[int] = []
        root = self.chapter_list.invisibleRootItem()

        def collect(node: QTreeWidgetItem) -> None:
            chapter_id = node.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(chapter_id, int) and node.checkState(0) == Qt.CheckState.Checked:
                selected.append(chapter_id)
            for i in range(node.childCount()):
                collect(node.child(i))

        for i in range(root.childCount()):
            collect(root.child(i))
        return selected

    def _toggle_lock(self, checked: bool) -> None:
        if checked and not self._request_edit_pin():
            with QSignalBlocker(self.lock_action):
                self.lock_action.setChecked(False)
            self._set_lock_state(False)
            self.statusBar().showMessage("Falsche PIN - Bearbeitung bleibt gesperrt", 3000)
            return
        self._set_lock_state(checked)
        self.statusBar().showMessage(
            "Bearbeitung entsperrt" if checked else "Bearbeitung gesperrt", 3000
        )

    def _request_edit_pin(self) -> bool:
        entered, ok = QInputDialog.getText(
            self,
            "PIN erforderlich",
            f"Bitte {PIN_LENGTH}-stellige PIN eingeben:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return False
        value = entered.strip()
        if len(value) != PIN_LENGTH:
            QMessageBox.warning(
                self, "Ungültige PIN", f"Die PIN muss genau {PIN_LENGTH} Zeichen lang sein."
            )
            return False
        return value == EDIT_MODE_PIN

    def _search(self, query: str) -> None:
        self._start_search(query.strip())

    def _start_search(self, query: str) -> None:
        if self.search_dropdown is None:
            return
        if not self.search_input.isVisible() or not self.search_input.isVisibleTo(self):
            self._hide_search_dropdown()
            return
        if not query:
            self.search_dropdown.clear()
            self.search_dropdown.hide()
            return
        self.search_dropdown.clear()
        self.search_dropdown.hide()

        self.search_request_id += 1
        request_id = self.search_request_id
        worker = SearchWorker(request_id=request_id, query=query, service=self.service)
        worker.signals.finished.connect(self._apply_search_results)
        self.search_pool.start(worker)

    def _apply_search_results(
        self, request_id: int, query: str, rows_with_images: list[tuple[SearchResult, str]]
    ) -> None:
        if self.search_dropdown is None:
            return
        if (
            not self.search_input.isVisible()
            or not self.search_input.isVisibleTo(self)
            or not self.search_input.hasFocus()
        ):
            self._hide_search_dropdown()
            return
        if request_id != self.search_request_id:
            return
        if query != self.search_input.text().strip():
            return

        self.search_dropdown.clear()
        for row, image_b64 in rows_with_images:
            chapter = row.chapter_de or "Ohne Kapitel"
            title = f"{row.de} / {row.en}"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, row.term_id)
            self.search_dropdown.addItem(item)
            self.search_dropdown.setItemWidget(
                item, self._build_search_result_widget(title, chapter, image_b64)
            )
            item.setSizeHint(QSize(0, 68))

        if self.search_dropdown.count() == 0:
            self.search_dropdown.hide()
            return

        self._position_search_dropdown()
        self.search_dropdown.setCurrentRow(0)
        self.search_dropdown.show()
        self.search_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_search_result_widget(self, title: str, chapter: str, image_b64: str) -> QWidget:
        widget = QWidget(self.search_dropdown)
        widget.setFixedHeight(60)
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        thumb_label = QLabel(widget)
        thumb_label.setFixedSize(36, 36)
        thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if image_b64:
            image_bytes = base64.b64decode(image_b64)
            pix = QPixmap()
            if pix.loadFromData(image_bytes):
                thumb = pix.scaled(
                    36,
                    36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb_label.setPixmap(thumb)
        row.addWidget(thumb_label)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        title_label = QLabel(title, widget)
        chapter_label = QLabel(chapter, widget)
        ch_font = chapter_label.font()
        ch_font.setItalic(True)
        chapter_label.setFont(ch_font)
        chapter_label.setStyleSheet("color: #9CA3AF;")

        text_col.addWidget(title_label)
        text_col.addWidget(chapter_label)
        row.addLayout(text_col, 1)
        return widget

    def _position_search_dropdown(self) -> None:
        if self.search_dropdown is None:
            return
        if not self.search_input.isVisible() or not self.search_input.isVisibleTo(self):
            self._hide_search_dropdown()
            return
        width = self.search_input.width()
        row_h = self.search_dropdown.sizeHintForRow(0) if self.search_dropdown.count() > 0 else 24
        height = min(10, self.search_dropdown.count()) * row_h + 8
        local_pos = self.search_input.mapTo(self, self.search_input.rect().bottomLeft())
        self.search_dropdown.setGeometry(local_pos.x(), local_pos.y() + 2, width, max(120, height))
        self.search_dropdown.raise_()

    def _on_search_result_clicked(self, item: QListWidgetItem) -> None:
        term_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(term_id, int):
            self._load_term(term_id)
        if self.search_dropdown is not None:
            self.search_dropdown.hide()

    def _select_first_search_result(self) -> None:
        if self.search_dropdown is None or self.search_dropdown.count() == 0:
            return
        item = self.search_dropdown.item(0)
        if item is not None:
            self._on_search_result_clicked(item)

    def _hide_search_dropdown(self) -> None:
        if self.search_dropdown is None:
            return
        self.search_dropdown.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.search_dropdown is not None and self.search_dropdown.isVisible():
            self._position_search_dropdown()

    def _load_term(self, term_id: int) -> None:
        term = self.service.get_term(term_id)
        if term is None:
            return

        self.current_term_id = term_id
        with QSignalBlocker(self.sidebar_term_tree):
            item = self._find_sidebar_term_item(term_id)
            if item is not None:
                self.sidebar_term_tree.setCurrentItem(item)
        self.term_de.setText(term["de"])
        self.term_en.setText(term["en"])
        self.term_de_desc.setPlainText(term["de_desc"])
        self.term_en_desc.setPlainText(term["en_desc"])

        selected_chapters = [int(cid) for cid in term.get("chapter_ids", [])]
        self._load_chapters(selected_chapters)

        self._load_table(
            self.syn_table,
            rows=[
                [
                    str(s.get("lang", "de")),
                    str(s.get("synonym", "")),
                    "1" if s.get("allowed", True) else "0",
                ]
                for s in term.get("synonyms", [])
            ],
        )
        self._load_table(
            self.ann_table,
            rows=[
                [
                    str(a.get("lang", "de")),
                    str(a.get("note", "")),
                    "1" if a.get("allowed", True) else "0",
                ]
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
                    "allowed": (allowed_item.text().strip() if allowed_item else "1")
                    in {"1", "true", "True", "yes"},
                }
            )
        return rows

    def _new_term(self) -> None:
        if not self.is_unlocked:
            return
        self.current_term_id = None
        with QSignalBlocker(self.sidebar_term_tree):
            self.sidebar_term_tree.clearSelection()
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
            QMessageBox.warning(
                self, "Fehlende Daten", "Deutsch- und Englisch-Begriff sind Pflicht."
            )
            return

        chapter_ids: list[int] = []
        root = self.chapter_list.invisibleRootItem()

        def collect_checked(node: QTreeWidgetItem) -> None:
            chapter_id = node.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(chapter_id, int) and node.checkState(0) == Qt.CheckState.Checked:
                chapter_ids.append(chapter_id)
            for i in range(node.childCount()):
                collect_checked(node.child(i))

        for i in range(root.childCount()):
            collect_checked(root.child(i))

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
        self._refresh_term_sidebar()
        self._search(self.search_input.text())

    def _delete_term(self) -> None:
        if not self.is_unlocked or self.current_term_id is None:
            return
        if (
            QMessageBox.question(self, "Löschen", "Diesen Begriff wirklich löschen?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.service.delete_term(self.current_term_id)
        self.statusBar().showMessage("Begriff gelöscht", 3000)
        self._new_term()
        self._refresh_term_sidebar()
        self._search(self.search_input.text())

    def _pick_image(self) -> None:
        if not self.is_unlocked:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Bild auswählen", "", "Bilder (*.png *.jpg *.jpeg *.webp)"
        )
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
        selector = QDialog(self)
        selector.setWindowTitle("Kapitel verwalten")
        selector.resize(700, 520)
        layout = QVBoxLayout(selector)
        tree = QTreeWidget(selector)
        tree.setColumnCount(1)
        tree.setHeaderLabels([" "])
        tree.setHeaderHidden(True)
        tree.header().hide()
        tree.header().setVisible(False)
        tree.header().setFixedHeight(0)
        tree.header().setMinimumSectionSize(0)
        tree.header().setDefaultSectionSize(0)
        tree.setRootIsDecorated(True)
        tree.setIndentation(18)
        layout.addWidget(tree)

        buttons = QHBoxLayout()
        b_add = QPushButton("Hinzufügen", selector)
        b_edit = QPushButton("Bearbeiten", selector)
        b_delete = QPushButton("Löschen", selector)
        b_close = QPushButton("Schließen", selector)
        buttons.addWidget(b_add)
        buttons.addWidget(b_edit)
        buttons.addWidget(b_delete)
        buttons.addStretch(1)
        buttons.addWidget(b_close)
        layout.addLayout(buttons)

        def refresh_tree(select_id: int | None = None) -> list[Chapter]:
            chapters = self.service.list_chapters()
            by_parent: dict[int | None, list[Chapter]] = {}
            for ch in chapters:
                by_parent.setdefault(ch.parent_id, []).append(ch)
            for items in by_parent.values():
                items.sort(key=lambda c: c.name_de.casefold())
            tree.clear()

            def add_nodes(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for ch in by_parent.get(parent_id, []):
                    base = f"{ch.name_de} | {ch.name_en}" if ch.name_en else ch.name_de
                    label = f"{base} ({'sichtbar' if ch.visible else 'versteckt'})"
                    node = QTreeWidgetItem([label])
                    node.setData(0, Qt.ItemDataRole.UserRole, ch.id)
                    if not ch.visible:
                        node.setForeground(0, Qt.GlobalColor.darkGray)
                    if parent_item is None:
                        tree.addTopLevelItem(node)
                    else:
                        parent_item.addChild(node)
                    if select_id is not None and ch.id == select_id:
                        tree.setCurrentItem(node)
                    add_nodes(node, ch.id)

            add_nodes(None, None)
            tree.expandAll()
            return chapters

        chapters_cache = refresh_tree()

        def add_chapter() -> None:
            dlg = ChapterDialog(chapters=chapters_cache, parent=selector)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            name_de, name_en, visible, parent_id = dlg.payload()
            new_id = self.service.save_chapter(None, name_de, name_en, visible, parent_id=parent_id)
            nonlocal_chapters_refresh(new_id)

        def edit_chapter() -> None:
            current = tree.currentItem()
            if current is None:
                return
            chapter_id = current.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(chapter_id, int):
                return
            chapter = next((c for c in chapters_cache if c.id == chapter_id), None)
            if chapter is None:
                return
            dlg = ChapterDialog(chapter=chapter, chapters=chapters_cache, parent=selector)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            name_de, name_en, visible, parent_id = dlg.payload()
            self.service.save_chapter(chapter_id, name_de, name_en, visible, parent_id=parent_id)
            nonlocal_chapters_refresh(chapter_id)

        def delete_chapter() -> None:
            current = tree.currentItem()
            if current is None:
                return
            chapter_id = current.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(chapter_id, int):
                return
            if (
                QMessageBox.question(
                    selector, "Kapitel löschen", "Kapitel (inkl. Unterkapitel) wirklich löschen?"
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            self.service.delete_chapter(chapter_id)
            nonlocal_chapters_refresh()

        def nonlocal_chapters_refresh(select_id: int | None = None) -> None:
            nonlocal chapters_cache
            chapters_cache = refresh_tree(select_id)
            self._load_chapters()
            self._refresh_term_sidebar()
            self._search(self.search_input.text())

        b_add.clicked.connect(add_chapter)
        b_edit.clicked.connect(edit_chapter)
        b_delete.clicked.connect(delete_chapter)
        b_close.clicked.connect(selector.reject)

        selector.exec()

    def _check_duplicates(self) -> None:
        synonyms: list[str] = []
        for r in range(self.syn_table.rowCount()):
            item = self.syn_table.item(r, 1)
            if item is not None:
                synonyms.append(item.text())
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
        records = [
            rec
            for rec in records
            if self._history_has_visible_change(rec.action, rec.before_json, rec.after_json)
        ]
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
                details.setHtml(
                    self._history_details_html(
                        rec.action, rec.before_json, rec.after_json, rec.changed_at
                    )
                )

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

    def _history_changes(
        self, before_json: str | None, after_json: str | None
    ) -> list[tuple[str, Any, Any]]:
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
        self._refresh_term_sidebar()
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

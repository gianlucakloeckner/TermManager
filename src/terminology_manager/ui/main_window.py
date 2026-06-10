from __future__ import annotations

import base64
import html
import json
import os
import subprocess
import sys
import tempfile
import threading
import zipfile
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
    QAbstractItemView,
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
    QProgressDialog,
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

from terminology_manager.config import AppConfig
from terminology_manager.domain.entities import SearchResult
from terminology_manager.persistence.models import Chapter
from terminology_manager.services.terminology_service import TerminologyService
from terminology_manager.services.update_service import GitHubUpdateService, UpdateCheckResult
from terminology_manager.ui.image_editor_dialog import ImageEditorDialog

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
        payload: list[tuple[SearchResult, str, str]] = []
        seen: set[int] = set()
        for row in rows:
            if row.term_id in seen:
                continue
            seen.add(row.term_id)
            term = self.service.get_term(row.term_id) or {}
            image_b64 = str(term.get("image_b64", "") or "")
            de_desc = str(term.get("de_desc", "") or "")
            payload.append((row, image_b64, de_desc))
            if len(payload) >= 25:
                break
        self.signals.finished.emit(self.request_id, self.query, payload)


class UpdateCheckWorkerSignals(QObject):
    finished = Signal(object)  # UpdateCheckResult | Exception


class UpdateCheckWorker(QRunnable):
    def __init__(self, service: "GitHubUpdateService", current_version: str) -> None:
        super().__init__()
        self.service = service
        self.current_version = current_version
        self.signals = UpdateCheckWorkerSignals()

    def run(self) -> None:
        try:
            result = self.service.check_for_update(self.current_version)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.finished.emit(exc)


class DownloadWorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)  # Path
    error = Signal(str)
    cancelled = Signal()


class DownloadWorker(QRunnable):
    def __init__(
        self,
        service: "GitHubUpdateService",
        url: str,
        target_dir: Path,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self.service = service
        self.url = url
        self.target_dir = target_dir
        self.cancel_event = cancel_event
        self.signals = DownloadWorkerSignals()

    def run(self) -> None:
        try:
            result = self.service.download_asset(
                self.url, self.target_dir, self.signals.progress.emit, self.cancel_event
            )
            self.signals.finished.emit(result)
        except Exception as exc:
            if self.cancel_event.is_set():
                self.signals.cancelled.emit()
            else:
                self.signals.error.emit(str(exc))


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
    def __init__(self, service: TerminologyService, config: AppConfig) -> None:
        super().__init__()
        self.service = service
        self.config = config
        self.update_service = GitHubUpdateService(
            owner=self.config.update_repo_owner,
            repo=self.config.update_repo_name,
        )
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
        self._update_progress: QProgressDialog | None = None

        self._build_ui()
        self._refresh_all()
        self._set_lock_state(False)
        self._ensure_edit_pin_in_db()
        if self.config.auto_update_check:
            QTimer.singleShot(1200, self._check_for_updates_silent)

    def _build_ui(self) -> None:
        top = QToolBar("Menü")
        top.setMovable(False)
        self.addToolBar(top)

        top.addSeparator()
        self.btn_new = QAction("Neuer Begriff", self)
        self.btn_save = QAction("Speichern", self)
        self.btn_delete = QAction("Löschen", self)
        self.btn_batch_edit = QAction("Batch bearbeiten", self)
        self.btn_manage_chapters = QAction("Kapitel verwalten", self)
        self.btn_history = QAction("Historie", self)
        self.btn_settings = QAction("Einstellungen", self)
        for action, slot in [
            (self.btn_new, self._new_term),
            (self.btn_save, self._save_term),
            (self.btn_delete, self._delete_term),
            (self.btn_batch_edit, self._open_batch_edit),
            (self.btn_manage_chapters, self._manage_chapters),
            (self.btn_history, self._show_history),
            (self.btn_settings, self._open_settings),
        ]:
            action.triggered.connect(slot)
            top.addAction(action)

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
        self.syn_table.setColumnCount(2)
        self.syn_table.setHorizontalHeaderLabels(["Synonym", "Zugelassen"])
        self.syn_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.syn_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.syn_table.setColumnWidth(1, 44)
        self.syn_table.verticalHeader().setVisible(False)
        self.syn_table.setCornerButtonEnabled(False)
        left_layout.addWidget(QLabel("Synonyme"))
        syn_buttons = QHBoxLayout()
        self.btn_syn_add = QPushButton("+", self)
        self.btn_syn_del = QPushButton("-", self)
        self.btn_syn_add.clicked.connect(lambda: self._append_table_row(self.syn_table, ["", "1"]))
        self.btn_syn_del.clicked.connect(lambda: self._remove_selected_table_row(self.syn_table))
        syn_buttons.addWidget(self.btn_syn_add)
        syn_buttons.addWidget(self.btn_syn_del)
        syn_buttons.addStretch(1)
        left_layout.addLayout(syn_buttons)
        left_layout.addWidget(self.syn_table, 1)

        self.ann_table = QTableWidget(self)
        self.ann_table.setColumnCount(2)
        self.ann_table.setHorizontalHeaderLabels(["Anmerkung", "Zugelassen"])
        self.ann_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.ann_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.ann_table.setColumnWidth(1, 44)
        self.ann_table.verticalHeader().setVisible(False)
        self.ann_table.setCornerButtonEnabled(False)
        left_layout.addWidget(QLabel("Anmerkungen"))
        ann_buttons = QHBoxLayout()
        self.btn_ann_add = QPushButton("+", self)
        self.btn_ann_del = QPushButton("-", self)
        self.btn_ann_add.clicked.connect(lambda: self._append_table_row(self.ann_table, ["", "1"]))
        self.btn_ann_del.clicked.connect(lambda: self._remove_selected_table_row(self.ann_table))
        ann_buttons.addWidget(self.btn_ann_add)
        ann_buttons.addWidget(self.btn_ann_del)
        ann_buttons.addStretch(1)
        left_layout.addLayout(ann_buttons)
        left_layout.addWidget(self.ann_table, 1)

        self.edit_buttons = [
            self.btn_pick_image,
            self.btn_edit_image,
            self.btn_clear_image,
            self.btn_syn_add,
            self.btn_syn_del,
            self.btn_ann_add,
            self.btn_ann_del,
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
            (self.btn_batch_edit, "Ctrl+B"),
            (self.btn_manage_chapters, "Ctrl+K"),
            (self.btn_history, "Ctrl+H"),
            (self.btn_settings, "Ctrl+,"),
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

            def add_chapter_nodes(
                parent_item: QTreeWidgetItem | None, parent_id: int | None
            ) -> None:
                for chapter in by_parent.get(parent_id, []):
                    if chapter_filter and chapter.id not in visible_chapter_ids:
                        continue
                    chapter_text = (
                        f"{chapter.name_de} | {chapter.name_en}"
                        if chapter.name_en
                        else chapter.name_de
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
            self.btn_batch_edit,
            self.btn_manage_chapters,
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
        current_pin = self.service.get_edit_pin() or self.config.edit_pin
        return value == current_pin

    def _ensure_edit_pin_in_db(self) -> None:
        current_pin = self.service.get_edit_pin()
        if not current_pin:
            self.service.set_edit_pin(self.config.edit_pin)

    def _open_settings(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Einstellungen")
        dlg.resize(680, 340)
        layout = QVBoxLayout(dlg)

        form = QFormLayout()
        db_path_input = QLineEdit(str(self.config.database_path), dlg)
        db_browse_btn = QPushButton("Durchsuchen", dlg)
        db_row = QHBoxLayout()
        db_row.addWidget(db_path_input, 1)
        db_row.addWidget(db_browse_btn)
        db_row_widget = QWidget(dlg)
        db_row_widget.setLayout(db_row)
        form.addRow("Datenbank-Datei", db_row_widget)

        current_pin_input = QLineEdit(dlg)
        current_pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        new_pin_input = QLineEdit(dlg)
        new_pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        confirm_pin_input = QLineEdit(dlg)
        confirm_pin_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Aktuelle PIN", current_pin_input)
        form.addRow("Neue PIN", new_pin_input)
        form.addRow("PIN bestätigen", confirm_pin_input)

        auto_update_check = QCheckBox("Beim Start automatisch nach Updates suchen", dlg)
        auto_update_check.setChecked(self.config.auto_update_check)
        form.addRow("", auto_update_check)

        hint = QLabel("PIN muss genau 4 Zeichen haben.", dlg)
        hint.setStyleSheet("color: #9CA3AF;")
        form.addRow("", hint)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        btn_check_updates = QPushButton("Jetzt nach Updates suchen", dlg)
        btn_save = QPushButton("Speichern", dlg)
        btn_cancel = QPushButton("Abbrechen", dlg)
        buttons.addWidget(btn_check_updates)
        buttons.addStretch(1)
        buttons.addWidget(btn_save)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

        def browse_db_path() -> None:
            path, _ = QFileDialog.getSaveFileName(
                dlg,
                "Datenbank-Datei auswählen",
                db_path_input.text().strip() or str(self.config.database_path),
                "SQLite (*.sqlite3 *.db);;Alle Dateien (*)",
            )
            if path:
                db_path_input.setText(path)

        def save_settings() -> None:
            db_text = db_path_input.text().strip()
            if not db_text:
                QMessageBox.warning(dlg, "Ungültiger Pfad", "Bitte einen Datenbank-Pfad angeben.")
                return
            new_db_path = Path(db_text).expanduser()

            current_pin = current_pin_input.text().strip()
            new_pin = new_pin_input.text().strip()
            confirm_pin = confirm_pin_input.text().strip()
            wants_pin_change = bool(current_pin or new_pin or confirm_pin)
            db_pin = self.service.get_edit_pin() or self.config.edit_pin
            if wants_pin_change:
                if current_pin != db_pin:
                    QMessageBox.warning(dlg, "Ungültige PIN", "Die aktuelle PIN ist falsch.")
                    return
                if len(new_pin) != PIN_LENGTH:
                    QMessageBox.warning(
                        dlg,
                        "Ungültige PIN",
                        f"Die neue PIN muss genau {PIN_LENGTH} Zeichen lang sein.",
                    )
                    return
                if new_pin != confirm_pin:
                    QMessageBox.warning(
                        dlg,
                        "Ungültige PIN",
                        "Neue PIN und Bestätigung stimmen nicht überein.",
                    )
                    return

            db_changed = new_db_path != self.config.database_path
            pin_changed = wants_pin_change and new_pin != db_pin
            auto_changed = auto_update_check.isChecked() != self.config.auto_update_check
            if not db_changed and not pin_changed:
                if not auto_changed:
                    dlg.accept()
                    return

            self.config.database_path = new_db_path
            if pin_changed:
                self.service.set_edit_pin(new_pin)
            self.config.auto_update_check = auto_update_check.isChecked()

            try:
                self.config.database_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.save()
            except OSError as exc:
                QMessageBox.critical(
                    dlg, "Fehler", f"Einstellungen konnten nicht gespeichert werden:\n{exc}"
                )
                return

            messages: list[str] = []
            if pin_changed:
                messages.append("PIN wurde aktualisiert.")
            if db_changed:
                messages.append("Datenbankpfad wurde aktualisiert. Neustart erforderlich.")
            if auto_changed:
                messages.append("Update-Einstellungen wurden aktualisiert.")
            QMessageBox.information(dlg, "Einstellungen gespeichert", "\n".join(messages))
            dlg.accept()

        db_browse_btn.clicked.connect(browse_db_path)
        btn_check_updates.clicked.connect(lambda: self._check_for_updates_manual())
        btn_save.clicked.connect(save_settings)
        btn_cancel.clicked.connect(dlg.reject)
        dlg.exec()

    def _check_for_updates_silent(self) -> None:
        self._check_for_updates(show_no_update=False, show_errors=False)

    def _check_for_updates_manual(self) -> None:
        self._check_for_updates(show_no_update=True, show_errors=True)

    def _check_for_updates(self, show_no_update: bool, show_errors: bool) -> None:
        worker = UpdateCheckWorker(self.update_service, self.config.app_version)
        worker.signals.finished.connect(
            lambda result: self._on_update_check_finished(result, show_no_update, show_errors)
        )
        self.search_pool.start(worker)

    def _on_update_check_finished(
        self, result: object, show_no_update: bool, show_errors: bool
    ) -> None:
        if isinstance(result, BaseException):
            if show_errors:
                QMessageBox.warning(self, "Update-Prüfung fehlgeschlagen", str(result))
            return
        if not isinstance(result, UpdateCheckResult):
            return
        if not result.update_available:
            if show_no_update:
                QMessageBox.information(
                    self,
                    "Kein Update verfügbar",
                    f"Aktuelle Version {result.current_version} ist auf dem neuesten Stand.",
                )
            return
        self._prompt_update(result)

    def _prompt_update(self, result: UpdateCheckResult) -> None:
        notes = (result.release_notes or "").strip()
        if len(notes) > 700:
            notes = notes[:700] + "\n..."
        message = (
            f"Neue Version verfügbar: {result.latest_version}\n"
            f"Aktuell installiert: {result.current_version}\n\n"
            "Update jetzt herunterladen?"
        )
        if notes:
            message += f"\n\nRelease Notes:\n{notes}"
        choice = QMessageBox.question(
            self,
            "Update verfügbar",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        target = result.download_url or result.release_url
        if not target:
            QMessageBox.warning(self, "Update", "Kein Download-Link verfügbar.")
            return
        self._download_and_apply_update(target, result.latest_version)

    def _download_and_apply_update(self, url: str, latest_version: str) -> None:
        cancel_event = threading.Event()

        progress = QProgressDialog("Update wird heruntergeladen...", "Abbrechen", 0, 100, self)
        progress.setWindowTitle("Update")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.canceled.connect(cancel_event.set)
        self._update_progress = progress
        progress.show()

        target_dir = Path(tempfile.gettempdir()) / "terminology_manager_updates" / latest_version
        worker = DownloadWorker(self.update_service, url, target_dir, cancel_event)

        def on_progress(read_bytes: int, total_bytes: int) -> None:
            if self._update_progress is None:
                return
            if total_bytes > 0:
                self._update_progress.setValue(min(100, int(read_bytes * 100 / total_bytes)))
            else:
                self._update_progress.setValue(0)

        def on_finished(file_path: object) -> None:
            if self._update_progress is not None:
                self._update_progress.setValue(100)
                self._update_progress.close()
                self._update_progress = None
            if isinstance(file_path, Path):
                self._apply_downloaded_update(file_path)

        def on_error(message: str) -> None:
            if self._update_progress is not None:
                self._update_progress.close()
                self._update_progress = None
            QMessageBox.warning(self, "Update-Download fehlgeschlagen", message)

        def on_cancelled() -> None:
            if self._update_progress is not None:
                self._update_progress.close()
                self._update_progress = None

        worker.signals.progress.connect(on_progress)
        worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(on_error)
        worker.signals.cancelled.connect(on_cancelled)
        self.search_pool.start(worker)

    def _apply_downloaded_update(self, file_path: Path) -> None:
        if sys.platform.startswith("win"):
            self._apply_downloaded_update_windows(file_path)
        elif sys.platform == "darwin":
            self._apply_downloaded_update_macos(file_path)
        else:
            QMessageBox.information(
                self,
                "Update heruntergeladen",
                f"Update wurde heruntergeladen:\n{file_path}\n\nBitte manuell installieren.",
            )

    def _apply_downloaded_update_macos(self, file_path: Path) -> None:
        is_frozen = bool(getattr(sys, "frozen", False))
        if not is_frozen:
            QMessageBox.information(
                self,
                "Update heruntergeladen",
                f"Update wurde heruntergeladen:\n{file_path}\n\nEntwicklungsmodus: manuelle Installation.",
            )
            return

        current_exe = Path(sys.executable).resolve()
        current_bundle = current_exe.parents[2]
        if not str(current_bundle).endswith(".app"):
            QMessageBox.information(
                self,
                "Update heruntergeladen",
                f"Update wurde heruntergeladen:\n{file_path}\n\nBitte manuell installieren.",
            )
            return

        if file_path.suffix.lower() != ".zip":
            QMessageBox.warning(self, "Update", "Unbekanntes Update-Format.")
            return

        extract_dir = file_path.with_suffix("")
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(file_path, "r") as archive:
                archive.extractall(extract_dir)
        except Exception as exc:
            QMessageBox.warning(self, "Update", f"Entpacken fehlgeschlagen:\n{exc}")
            return

        app_bundles = list(extract_dir.glob("*.app"))
        if not app_bundles:
            QMessageBox.information(
                self,
                "Update heruntergeladen",
                f"Update wurde heruntergeladen:\n{file_path}\n\nBitte manuell installieren.",
            )
            return

        new_bundle = app_bundles[0]
        updater_sh = file_path.parent / "apply_update.sh"
        script = (
            "#!/bin/sh\n"
            "set -e\n"
            'APP_PID="$1"\n'
            'BUNDLE_PATH="$2"\n'
            'NEW_BUNDLE="$3"\n'
            'while kill -0 "$APP_PID" 2>/dev/null; do\n'
            "    sleep 0.5\n"
            "done\n"
            'rm -rf "$BUNDLE_PATH"\n'
            'cp -r "$NEW_BUNDLE" "$BUNDLE_PATH"\n'
            'open "$BUNDLE_PATH"\n'
        )
        updater_sh.write_text(script, encoding="utf-8")
        updater_sh.chmod(0o755)
        subprocess.Popen(
            [str(updater_sh), str(os.getpid()), str(current_bundle), str(new_bundle)],
            start_new_session=True,
        )
        QMessageBox.information(self, "Update", "Update wird installiert. Die App wird neu gestartet.")
        self.close()

    def _apply_downloaded_update_windows(self, file_path: Path) -> None:
        is_frozen = bool(getattr(sys, "frozen", False))
        if not is_frozen:
            QMessageBox.information(
                self,
                "Update heruntergeladen",
                f"Update wurde heruntergeladen:\n{file_path}\n\nEntwicklungsmodus: manuelle Installation.",
            )
            return

        current_exe = Path(sys.executable).resolve()
        if file_path.suffix.lower() == ".zip":
            extract_dir = file_path.with_suffix("")
            if extract_dir.exists():
                for child in extract_dir.glob("*"):
                    if child.is_file():
                        child.unlink(missing_ok=True)
            extract_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(file_path, "r") as archive:
                archive.extractall(extract_dir)
            candidate = extract_dir / current_exe.name
            if not candidate.exists():
                exe_files = list(extract_dir.rglob("*.exe"))
                if not exe_files:
                    QMessageBox.warning(self, "Update", "Keine EXE im Update-Paket gefunden.")
                    return
                candidate = exe_files[0]
            new_exe = candidate
        elif file_path.suffix.lower() == ".exe":
            new_exe = file_path
        else:
            QMessageBox.warning(self, "Update", "Unbekanntes Update-Format.")
            return

        updater_bat = file_path.parent / "apply_update.bat"
        bat_content = (
            "@echo off\n"
            "setlocal\n"
            f"set TARGET={current_exe}\n"
            f"set SOURCE={new_exe}\n"
            f"set PID={os.getpid()}\n"
            ":waitloop\n"
            "tasklist /FI \"PID eq %PID%\" | find \"%PID%\" >nul\n"
            "if not errorlevel 1 (\n"
            "  timeout /t 1 /nobreak >nul\n"
            "  goto waitloop\n"
            ")\n"
            "copy /Y \"%SOURCE%\" \"%TARGET%\" >nul\n"
            "start \"\" \"%TARGET%\"\n"
            "exit /b 0\n"
        )
        updater_bat.write_text(bat_content, encoding="utf-8")
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        subprocess.Popen(["cmd", "/c", str(updater_bat)], creationflags=creationflags)
        QMessageBox.information(self, "Update", "Update wird installiert. Die App wird neu gestartet.")
        self.close()

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
        self, request_id: int, query: str, rows_with_images: list[tuple[SearchResult, str, str]]
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
        for row, image_b64, de_desc in rows_with_images:
            chapter = row.chapter_de or "Ohne Kapitel"
            title = f"{row.de} / {row.en}"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, row.term_id)
            self.search_dropdown.addItem(item)
            self.search_dropdown.setItemWidget(
                item, self._build_search_result_widget(title, chapter, de_desc, image_b64)
            )
            item.setSizeHint(QSize(0, 52))

        if self.search_dropdown.count() == 0:
            self.search_dropdown.hide()
            return

        self._position_search_dropdown()
        self.search_dropdown.setCurrentRow(0)
        self.search_dropdown.show()
        self.search_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _build_search_result_widget(
        self, title: str, chapter: str, de_desc: str, image_b64: str
    ) -> QWidget:
        widget = QWidget(self.search_dropdown)
        widget.setFixedHeight(48)
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 1, 6, 1)
        row.setSpacing(6)

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
        text_col.setSpacing(0)
        text_col.setAlignment(Qt.AlignmentFlag.AlignTop)

        title_label = QLabel(title, widget)
        title_label.setMargin(0)
        title_label.setStyleSheet("margin: 0px; padding: 0px;")
        chapter_label = QLabel(chapter, widget)
        chapter_label.setMargin(0)
        ch_font = chapter_label.font()
        ch_font.setItalic(True)
        chapter_label.setFont(ch_font)
        chapter_label.setStyleSheet("color: #9CA3AF; margin: 0px; padding: 0px;")
        clean_desc = " ".join(de_desc.split())
        if len(clean_desc) > 90:
            clean_desc = clean_desc[:87] + "..."
        desc_label = QLabel(clean_desc, widget)
        desc_label.setMargin(0)
        desc_label.setStyleSheet("color: #9CA3AF; margin: 0px; padding: 0px;")
        desc_label.setWordWrap(False)

        text_col.addWidget(title_label, 0, Qt.AlignmentFlag.AlignTop)
        text_col.addWidget(chapter_label, 0, Qt.AlignmentFlag.AlignTop)
        text_col.addWidget(desc_label, 0, Qt.AlignmentFlag.AlignTop)
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
                [str(s.get("synonym", "")), "1" if s.get("allowed", True) else "0"]
                for s in term.get("synonyms", [])
            ],
        )
        self._load_table(
            self.ann_table,
            rows=[
                [str(a.get("note", "")), "1" if a.get("allowed", True) else "0"]
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
            text_value = row[0] if len(row) > 0 else ""
            allowed_value = row[1] if len(row) > 1 else "1"
            table.setItem(r_idx, 0, QTableWidgetItem(text_value))
            table.setCellWidget(
                r_idx,
                1,
                self._build_allowed_combo(allowed_value in {"1", "true", "True", "yes"}),
            )

    def _append_table_row(self, table: QTableWidget, values: list[str]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        text_value = values[0] if len(values) > 0 else ""
        allowed_value = values[1] if len(values) > 1 else "1"
        table.setItem(row, 0, QTableWidgetItem(text_value))
        table.setCellWidget(
            row,
            1,
            self._build_allowed_combo(allowed_value in {"1", "true", "True", "yes"}),
        )

    def _build_allowed_combo(self, allowed: bool) -> QComboBox:
        combo = QComboBox(self)
        combo.addItem("✓", "1")
        combo.addItem("✗", "0")
        combo.setItemData(0, QColor("#16A34A"), Qt.ItemDataRole.ForegroundRole)
        combo.setItemData(1, QColor("#DC2626"), Qt.ItemDataRole.ForegroundRole)
        combo.setCurrentIndex(0 if allowed else 1)
        combo.setStyleSheet("QComboBox { font-weight: 700; }")
        return combo

    def _remove_selected_table_row(self, table: QTableWidget) -> None:
        row = table.currentRow()
        if row >= 0:
            table.removeRow(row)

    def _table_rows(self, table: QTableWidget, text_column_name: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for r in range(table.rowCount()):
            value_item = table.item(r, 0)
            allowed_combo = table.cellWidget(r, 1)
            if value_item is None:
                continue
            value_text = value_item.text().strip()
            if not value_text:
                continue
            allowed_data = "1"
            if isinstance(allowed_combo, QComboBox):
                selected = allowed_combo.currentData()
                if isinstance(selected, str):
                    allowed_data = selected
            rows.append(
                {
                    "lang": "de",
                    text_column_name: value_text,
                    "allowed": allowed_data == "1",
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

        synonyms_rows = self._table_rows(self.syn_table, "synonym")
        annotations_rows = self._table_rows(self.ann_table, "note")
        duplicate_report = self.service.detect_duplicates(
            de,
            en,
            [str(row.get("synonym", "")) for row in synonyms_rows],
            exclude_term_id=self.current_term_id,
        )
        exact_term_ids = duplicate_report.exact_term_ids
        exact_syn_ids = duplicate_report.exact_synonym_term_ids
        fuzzy_hits = duplicate_report.fuzzy_hits
        if exact_term_ids or exact_syn_ids or fuzzy_hits:
            hints: list[str] = []
            if exact_term_ids:
                hints.append(f"Exakte Begriffe: {exact_term_ids}")
            if exact_syn_ids:
                hints.append(f"Exakte Synonyme: {exact_syn_ids}")
            if fuzzy_hits:
                top = ", ".join(f"{h.value} ({h.score:.2f})" for h in fuzzy_hits[:4])
                hints.append(f"Ähnliche Treffer: {top}")
            proceed = QMessageBox.question(
                self,
                "Mögliche Duplikate gefunden",
                "Es wurden mögliche Duplikate erkannt:\n\n"
                + "\n".join(hints)
                + "\n\nTrotzdem speichern?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        term_id = self.service.save_term(
            term_id=self.current_term_id,
            de=de,
            en=en,
            de_desc=self.term_de_desc.toPlainText(),
            en_desc=self.term_en_desc.toPlainText(),
            image=self.current_image_bytes,
            synonyms=synonyms_rows,
            annotations=annotations_rows,
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
            confirm = QMessageBox(selector)
            confirm.setIcon(QMessageBox.Icon.Warning)
            confirm.setWindowTitle("Kapitel löschen")
            confirm.setText("Kapitel und alle Unterkapitel wirklich löschen?")
            confirm.setInformativeText("Wie sollen die zugeordneten Begriffe behandelt werden?")
            with_terms_btn = confirm.addButton(
                "Mit Begriffen löschen", QMessageBox.ButtonRole.DestructiveRole
            )
            keep_terms_btn = confirm.addButton(
                "Begriffe behalten (ohne Kapitel)", QMessageBox.ButtonRole.AcceptRole
            )
            confirm.addButton(QMessageBox.StandardButton.Cancel)
            confirm.exec()
            clicked = confirm.clickedButton()
            if clicked == with_terms_btn:
                self.service.delete_chapter(chapter_id, delete_terms=True)
            elif clicked == keep_terms_btn:
                self.service.delete_chapter(chapter_id, delete_terms=False)
            else:
                return
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

    def _open_batch_edit(self) -> None:
        if not self.is_unlocked:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Batch-Bearbeitung")
        dlg.resize(920, 620)
        layout = QHBoxLayout(dlg)

        left = QWidget(dlg)
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Begriffe auswählen"))
        filter_input = QLineEdit(left)
        filter_input.setPlaceholderText("Begriffe filtern...")
        left_layout.addWidget(filter_input)

        term_list = QListWidget(left)
        term_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        left_layout.addWidget(term_list, 1)
        layout.addWidget(left, 1)

        right = QWidget(dlg)
        right_layout = QVBoxLayout(right)
        right_layout.addWidget(QLabel("Kapitelzuweisung (ersetzen)"))
        chapter_tree = QTreeWidget(right)
        chapter_tree.setColumnCount(1)
        chapter_tree.setHeaderHidden(True)
        chapter_tree.setRootIsDecorated(True)
        chapter_tree.setIndentation(16)
        right_layout.addWidget(chapter_tree, 1)
        layout.addWidget(right, 1)

        button_row = QHBoxLayout()
        btn_assign = QPushButton("Kapitel zuweisen", dlg)
        btn_delete = QPushButton("Begriffe löschen", dlg)
        btn_close = QPushButton("Schließen", dlg)
        button_row.addWidget(btn_assign)
        button_row.addWidget(btn_delete)
        button_row.addStretch(1)
        button_row.addWidget(btn_close)
        right_layout.addLayout(button_row)

        all_terms = self.service.list_terms()

        def refresh_term_list() -> None:
            needle = filter_input.text().strip().casefold()
            term_list.clear()
            for term in sorted(all_terms, key=lambda t: str(t.get("de", "")).casefold()):
                de = str(term.get("de", "")).strip()
                en = str(term.get("en", "")).strip()
                title = f"{de} | {en}".strip()
                if needle and needle not in title.casefold():
                    continue
                term_id = term.get("id")
                if not isinstance(term_id, int):
                    continue
                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, term_id)
                term_list.addItem(item)

        def refresh_chapter_tree() -> None:
            chapter_tree.clear()
            chapters = self.service.list_chapters()
            by_parent: dict[int | None, list[Chapter]] = {}
            for chapter in chapters:
                by_parent.setdefault(chapter.parent_id, []).append(chapter)
            for items in by_parent.values():
                items.sort(key=lambda c: c.name_de.casefold())

            def add_nodes(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
                for chapter in by_parent.get(parent_id, []):
                    text = (
                        f"{chapter.name_de} | {chapter.name_en}"
                        if chapter.name_en
                        else chapter.name_de
                    )
                    node = QTreeWidgetItem([text])
                    node.setData(0, Qt.ItemDataRole.UserRole, chapter.id)
                    node.setFlags(node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    node.setCheckState(0, Qt.CheckState.Unchecked)
                    if parent_item is None:
                        chapter_tree.addTopLevelItem(node)
                    else:
                        parent_item.addChild(node)
                    add_nodes(node, chapter.id)

            add_nodes(None, None)
            chapter_tree.expandAll()

        def selected_term_ids() -> list[int]:
            ids: list[int] = []
            for item in term_list.selectedItems():
                term_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(term_id, int):
                    ids.append(term_id)
            return ids

        def selected_chapter_ids() -> list[int]:
            ids: list[int] = []
            root = chapter_tree.invisibleRootItem()

            def collect(node: QTreeWidgetItem) -> None:
                chapter_id = node.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(chapter_id, int) and node.checkState(0) == Qt.CheckState.Checked:
                    ids.append(chapter_id)
                for i in range(node.childCount()):
                    collect(node.child(i))

            for i in range(root.childCount()):
                collect(root.child(i))
            return ids

        def assign_chapters() -> None:
            ids = selected_term_ids()
            if not ids:
                QMessageBox.warning(
                    dlg, "Keine Auswahl", "Bitte mindestens einen Begriff auswählen."
                )
                return
            chapter_ids = selected_chapter_ids()
            for term_id in ids:
                term = self.service.get_term(term_id)
                if term is None:
                    continue
                image_bytes: bytes | None = None
                image_b64 = term.get("image_b64")
                if isinstance(image_b64, str) and image_b64:
                    image_bytes = base64.b64decode(image_b64)
                synonyms = term.get("synonyms", [])
                annotations = term.get("annotations", [])
                self.service.save_term(
                    term_id=term_id,
                    de=str(term.get("de", "")),
                    en=str(term.get("en", "")),
                    de_desc=str(term.get("de_desc", "")),
                    en_desc=str(term.get("en_desc", "")),
                    image=image_bytes,
                    synonyms=synonyms if isinstance(synonyms, list) else [],
                    annotations=annotations if isinstance(annotations, list) else [],
                    chapter_ids=chapter_ids,
                )
            self._load_chapters()
            self._refresh_term_sidebar()
            self._search(self.search_input.text())
            if self.current_term_id in ids:
                self._load_term(self.current_term_id)
            self.statusBar().showMessage(f"{len(ids)} Begriffe aktualisiert", 3000)

        def delete_terms() -> None:
            ids = selected_term_ids()
            if not ids:
                QMessageBox.warning(
                    dlg, "Keine Auswahl", "Bitte mindestens einen Begriff auswählen."
                )
                return
            if (
                QMessageBox.question(
                    dlg,
                    "Begriffe löschen",
                    f"Wirklich {len(ids)} Begriffe löschen?",
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            for term_id in ids:
                self.service.delete_term(term_id)
            if self.current_term_id in ids:
                self._new_term()
            nonlocal all_terms
            all_terms = self.service.list_terms()
            refresh_term_list()
            self._load_chapters()
            self._refresh_term_sidebar()
            self._search(self.search_input.text())
            self.statusBar().showMessage(f"{len(ids)} Begriffe gelöscht", 3000)

        filter_input.textChanged.connect(refresh_term_list)
        btn_assign.clicked.connect(assign_chapters)
        btn_delete.clicked.connect(delete_terms)
        btn_close.clicked.connect(dlg.accept)

        refresh_term_list()
        refresh_chapter_tree()
        dlg.exec()

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

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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    QRect,
    QRectF,
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
TOOLBAR_ICON_SIZE = 26
HISTORY_FIELD_ORDER = [
    "de",
    "en",
    "de_desc",
    "en_desc",
    "annotations",
    "synonyms",
    "chapter_ids",
    "image",
]


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
    finished = Signal(
        object, bool, bool
    )  # UpdateCheckResult | Exception, show_no_update, show_errors


class UpdateCheckWorker(QRunnable):
    def __init__(
        self,
        service: GitHubUpdateService,
        current_version: str,
        show_no_update: bool,
        show_errors: bool,
    ) -> None:
        super().__init__()
        self.service = service
        self.current_version = current_version
        self.show_no_update = show_no_update
        self.show_errors = show_errors
        self.signals = UpdateCheckWorkerSignals()

    def run(self) -> None:
        try:
            result: object = self.service.check_for_update(self.current_version)
        except Exception as exc:
            result = exc
        self.signals.finished.emit(result, self.show_no_update, self.show_errors)


class DownloadWorkerSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)  # Path
    error = Signal(str)
    cancelled = Signal()


class DownloadWorker(QRunnable):
    def __init__(
        self,
        service: GitHubUpdateService,
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


class ChapterManagerDialog(QDialog):
    """Master-Detail-Dialog: links Kapitelbaum, rechts Inline-Bearbeitung."""

    def __init__(
        self,
        service: TerminologyService,
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._on_changed = on_changed
        self._chapters: list[Chapter] = []
        self._edit_id: int | None = None  # None = neues Kapitel anlegen

        self.setWindowTitle("Kapitel verwalten")
        self.resize(860, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        content = QHBoxLayout()
        content.setSpacing(12)
        root.addLayout(content, 1)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._filter_input = QLineEdit(self)
        self._filter_input.setPlaceholderText("Kapitel filtern …")
        self._filter_input.textChanged.connect(lambda: self._rebuild_tree())
        left.addWidget(self._filter_input)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(18)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        left.addWidget(self._tree, 1)

        tree_buttons = QHBoxLayout()
        self._btn_new = QPushButton("Neues Kapitel", self)
        self._btn_new_child = QPushButton("Neues Unterkapitel", self)
        self._btn_delete = QPushButton("Löschen", self)
        self._btn_new.clicked.connect(lambda: self._start_new())
        self._btn_new_child.clicked.connect(self._start_new_child)
        self._btn_delete.clicked.connect(self._delete_selected)
        tree_buttons.addWidget(self._btn_new)
        tree_buttons.addWidget(self._btn_new_child)
        tree_buttons.addStretch(1)
        tree_buttons.addWidget(self._btn_delete)
        left.addLayout(tree_buttons)
        content.addLayout(left, 1)

        panel = QWidget(self)
        panel.setFixedWidth(320)
        right = QVBoxLayout(panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        self._mode_label = QLabel("Neues Kapitel", panel)
        self._mode_label.setStyleSheet("font-weight: 700; font-size: 14px;")
        right.addWidget(self._mode_label)

        form = QFormLayout()
        form.setSpacing(8)
        self._name_de = QLineEdit(panel)
        self._name_de.setPlaceholderText("Kapitelname (Deutsch)")
        self._name_en = QLineEdit(panel)
        self._name_en.setPlaceholderText("Chapter name (English)")
        self._parent_combo = QComboBox(panel)
        self._visible = QCheckBox("In Suche sichtbar", panel)
        self._visible.setChecked(True)
        form.addRow("Name (DE)", self._name_de)
        form.addRow("Name (EN)", self._name_en)
        form.addRow("Elternkapitel", self._parent_combo)
        form.addRow("", self._visible)
        right.addLayout(form)

        self._btn_save = QPushButton("Kapitel anlegen", panel)
        self._btn_save.clicked.connect(self._save)
        right.addWidget(self._btn_save)
        hint = QLabel("Änderungen wirken sofort auf Sidebar und Suche.", panel)
        hint.setStyleSheet("color: #9CA3AF;")
        hint.setWordWrap(True)
        right.addWidget(hint)
        right.addStretch(1)
        content.addWidget(panel)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        btn_close = QPushButton("Schließen", self)
        btn_close.clicked.connect(self.accept)
        bottom.addWidget(btn_close)
        root.addLayout(bottom)

        self._name_de.returnPressed.connect(self._save)
        self._name_en.returnPressed.connect(self._save)

        self._reload()
        self._start_new()

    def _reload(self, select_id: int | None = None) -> None:
        self._chapters = self._service.list_chapters()
        self._rebuild_tree(select_id=select_id)

    def _children_by_parent(self) -> dict[int | None, list[Chapter]]:
        by_parent: dict[int | None, list[Chapter]] = {}
        for chapter in self._chapters:
            by_parent.setdefault(chapter.parent_id, []).append(chapter)
        for items in by_parent.values():
            items.sort(key=lambda c: c.name_de.casefold())
        return by_parent

    def _rebuild_tree(self, select_id: int | None = None) -> None:
        query = self._filter_input.text().strip().casefold()
        by_parent = self._children_by_parent()

        def matches(chapter: Chapter) -> bool:
            return (
                not query
                or query in chapter.name_de.casefold()
                or query in (chapter.name_en or "").casefold()
            )

        def subtree_matches(chapter: Chapter) -> bool:
            if matches(chapter):
                return True
            return any(subtree_matches(child) for child in by_parent.get(chapter.id, []))

        self._tree.blockSignals(True)
        self._tree.clear()

        def add_nodes(parent_item: QTreeWidgetItem | None, parent_id: int | None) -> None:
            for chapter in by_parent.get(parent_id, []):
                if not subtree_matches(chapter):
                    continue
                base = (
                    f"{chapter.name_de} | {chapter.name_en}" if chapter.name_en else chapter.name_de
                )
                label = base if chapter.visible else f"{base} (versteckt)"
                node = QTreeWidgetItem([label])
                node.setData(0, Qt.ItemDataRole.UserRole, chapter.id)
                if not chapter.visible:
                    node.setForeground(0, Qt.GlobalColor.darkGray)
                if parent_item is None:
                    self._tree.addTopLevelItem(node)
                else:
                    parent_item.addChild(node)
                add_nodes(node, chapter.id)

        add_nodes(None, None)
        self._tree.expandAll()
        self._tree.blockSignals(False)
        if select_id is not None:
            self._select_in_tree(select_id)

    def _select_in_tree(self, chapter_id: int) -> None:
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, Qt.ItemDataRole.UserRole) == chapter_id:
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(self._tree.topLevelItemCount()):
            top_item = self._tree.topLevelItem(i)
            if top_item is None:
                continue
            found = walk(top_item)
            if found is not None:
                self._tree.setCurrentItem(found)
                return

    def _selected_chapter(self) -> Chapter | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        chapter_id = item.data(0, Qt.ItemDataRole.UserRole)
        return next((c for c in self._chapters if c.id == chapter_id), None)

    def _descendant_ids(self, chapter_id: int) -> set[int]:
        by_parent = self._children_by_parent()
        out: set[int] = set()

        def walk(parent_id: int) -> None:
            for child in by_parent.get(parent_id, []):
                out.add(child.id)
                walk(child.id)

        walk(chapter_id)
        return out

    def _rebuild_parent_combo(self, exclude: set[int], selected: int | None) -> None:
        self._parent_combo.clear()
        self._parent_combo.addItem("Kein Elternkapitel", None)
        for chapter in sorted(self._chapters, key=lambda c: c.name_de.casefold()):
            if chapter.id in exclude:
                continue
            label = f"{chapter.name_de} | {chapter.name_en}" if chapter.name_en else chapter.name_de
            self._parent_combo.addItem(label, chapter.id)
            if selected is not None and chapter.id == selected:
                self._parent_combo.setCurrentIndex(self._parent_combo.count() - 1)

    def _on_selection_changed(self) -> None:
        chapter = self._selected_chapter()
        self._btn_new_child.setEnabled(chapter is not None)
        self._btn_delete.setEnabled(chapter is not None)
        if chapter is None:
            return
        self._edit_id = chapter.id
        self._mode_label.setText(f"Kapitel bearbeiten: {chapter.name_de}")
        self._name_de.setText(chapter.name_de)
        self._name_en.setText(chapter.name_en)
        self._visible.setChecked(chapter.visible)
        # Selbst und Nachfahren ausschließen, sonst entstehen Zyklen im Baum.
        self._rebuild_parent_combo(
            exclude={chapter.id} | self._descendant_ids(chapter.id),
            selected=chapter.parent_id,
        )
        self._btn_save.setText("Änderungen speichern")

    def _start_new(self, parent_id: int | None = None) -> None:
        self._edit_id = None
        self._tree.blockSignals(True)
        self._tree.clearSelection()
        self._tree.setCurrentItem(None)  # type: ignore[call-overload]
        self._tree.blockSignals(False)
        self._btn_new_child.setEnabled(False)
        self._btn_delete.setEnabled(False)
        self._mode_label.setText("Neues Kapitel")
        self._name_de.clear()
        self._name_en.clear()
        self._visible.setChecked(True)
        self._rebuild_parent_combo(exclude=set(), selected=parent_id)
        self._btn_save.setText("Kapitel anlegen")
        self._name_de.setFocus()

    def _start_new_child(self) -> None:
        chapter = self._selected_chapter()
        self._start_new(parent_id=chapter.id if chapter is not None else None)

    def _save(self) -> None:
        name_de = self._name_de.text().strip()
        name_en = self._name_en.text().strip()
        if not name_de:
            QMessageBox.warning(self, "Kapitel", "Name (DE) darf nicht leer sein.")
            return
        parent_data = self._parent_combo.currentData()
        parent_id = int(parent_data) if isinstance(parent_data, int) else None
        try:
            saved_id = self._service.save_chapter(
                self._edit_id, name_de, name_en, self._visible.isChecked(), parent_id=parent_id
            )
        except Exception as exc:
            QMessageBox.warning(self, "Kapitel speichern fehlgeschlagen", str(exc))
            return
        self._on_changed()
        self._reload(select_id=saved_id)

    def _delete_selected(self) -> None:
        chapter = self._selected_chapter()
        if chapter is None:
            return
        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Icon.Warning)
        confirm.setWindowTitle("Kapitel löschen")
        confirm.setText(f"Kapitel „{chapter.name_de}“ und alle Unterkapitel löschen?")
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
            self._service.delete_chapter(chapter.id, delete_terms=True)
        elif clicked == keep_terms_btn:
            self._service.delete_chapter(chapter.id, delete_terms=False)
        else:
            return
        self._on_changed()
        self._reload()
        self._start_new()


class RecommendationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Vorschlag machen")
        self.setFixedSize(400, 160)
        form = QFormLayout(self)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(10)
        self.de_input = QLineEdit(self)
        self.de_input.setPlaceholderText("Deutschen Begriff eingeben …")
        self.en_input = QLineEdit(self)
        self.en_input.setPlaceholderText("English term …")
        form.addRow("Deutsch", self.de_input)
        form.addRow("Englisch", self.en_input)
        buttons = QHBoxLayout()
        btn_submit = QPushButton("Vorschlag einreichen", self)
        btn_cancel = QPushButton("Abbrechen", self)
        btn_submit.clicked.connect(self._submit)
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_submit)
        buttons.addWidget(btn_cancel)
        form.addRow(buttons)

    def _submit(self) -> None:
        if not self.de_input.text().strip() and not self.en_input.text().strip():
            QMessageBox.warning(
                self,
                "Fehlende Felder",
                "Bitte mindestens einen Begriff (Deutsch oder Englisch) eingeben.",
            )
            return
        self.accept()

    def payload(self) -> tuple[str, str]:
        return self.de_input.text().strip(), self.en_input.text().strip()


class RecommendationReviewDialog(QDialog):
    def __init__(self, service: TerminologyService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._accepted_term_id: int | None = None
        self.setWindowTitle("Vorschläge")
        self.resize(640, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(["Deutsch", "Englisch", "Eingereicht am", ""])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)
        btn_close = QPushButton("Schließen", self)
        btn_close.clicked.connect(self.accept)
        hbox = QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(btn_close)
        layout.addLayout(hbox)
        self._reload()

    @property
    def accepted_term_id(self) -> int | None:
        return self._accepted_term_id

    def _reload(self) -> None:
        recs = self._service.list_pending_recommendations()
        self._table.setRowCount(len(recs))
        for row_idx, rec in enumerate(recs):
            created_raw = str(rec.get("created_at", ""))
            self._table.setItem(row_idx, 0, QTableWidgetItem(str(rec.get("de", ""))))
            self._table.setItem(row_idx, 1, QTableWidgetItem(str(rec.get("en", ""))))
            self._table.setItem(row_idx, 2, QTableWidgetItem(created_raw[:10]))
            rec_id = int(rec["id"])
            action_widget = QWidget(self)
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(4)
            btn_accept = QPushButton("✓ Annehmen", action_widget)
            btn_accept.setStyleSheet("color: #16A34A; font-weight: 700;")
            btn_deny = QPushButton("✗ Ablehnen", action_widget)
            btn_deny.setStyleSheet("color: #DC2626; font-weight: 700;")
            btn_accept.clicked.connect(lambda _, r=rec_id: self._on_accept(r))
            btn_deny.clicked.connect(lambda _, r=rec_id: self._on_deny(r))
            action_layout.addWidget(btn_accept)
            action_layout.addWidget(btn_deny)
            self._table.setCellWidget(row_idx, 3, action_widget)

    def _on_accept(self, rec_id: int) -> None:
        try:
            self._accepted_term_id = self._service.accept_recommendation(rec_id)
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_deny(self, rec_id: int) -> None:
        try:
            self._service.deny_recommendation(rec_id)
            self._reload()
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))


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
        self._sidebar_flat = False

        self._build_ui()
        self._refresh_all()
        self._set_lock_state(False)
        self._refresh_recommendation_badge()
        self._ensure_edit_pin_in_db()
        if self.config.auto_update_check:
            QTimer.singleShot(1200, self._check_for_updates_silent)

    def _build_ui(self) -> None:
        top = QToolBar("Menü")
        top.setMovable(False)
        top.setFixedHeight(64)
        top.setStyleSheet("QToolBar { spacing: 4px; }")
        self.addToolBar(top)

        logo_label = QLabel(self)
        logo_pixmap = self._toolbar_logo_pixmap(width=180, height=52)
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap)
            logo_label.setFixedSize(logo_pixmap.width(), 56)
            logo_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            top.addWidget(logo_label)

        top.addSeparator()
        self.btn_recommend = QAction("Vorschlag machen", self)
        self.btn_recommend.setToolTip("Neuen Begriff vorschlagen")
        self.btn_recommend.triggered.connect(self._on_recommend_clicked)
        top.addAction(self.btn_recommend)

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
        self._review_recommendations_action = QAction("Vorschläge prüfen", self)
        self._review_recommendations_action.setIcon(self.notification_icon)
        self._review_recommendations_action.triggered.connect(
            self._on_review_recommendations_clicked
        )
        self._review_recommendations_action.setVisible(False)
        top.addAction(self._review_recommendations_action)

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

        filter_row = QWidget(self)
        filter_row_layout = QHBoxLayout(filter_row)
        filter_row_layout.setContentsMargins(0, 0, 0, 0)
        filter_row_layout.setSpacing(4)
        self.sidebar_tree_filter_input = QLineEdit(self)
        self.sidebar_tree_filter_input.setPlaceholderText("Kapitel filtern...")
        self.sidebar_tree_filter_input.textChanged.connect(self._on_sidebar_chapter_filter_changed)
        filter_row_layout.addWidget(self.sidebar_tree_filter_input, 1)
        self.sidebar_sort_btn = QPushButton("A-Z", self)
        self.sidebar_sort_btn.setCheckable(True)
        self.sidebar_sort_btn.setFixedWidth(64)
        btn_height = self.sidebar_sort_btn.sizeHint().height()
        self.sidebar_tree_filter_input.setFixedHeight(btn_height)
        self.sidebar_sort_btn.setToolTip("Alphabetische Liste ohne Gruppen anzeigen")
        self.sidebar_sort_btn.toggled.connect(self._on_sidebar_flat_toggled)
        filter_row_layout.addWidget(self.sidebar_sort_btn)
        sidebar_layout.addWidget(filter_row)

        self.sidebar_term_tree = QTreeWidget(self)
        self.sidebar_term_tree.setColumnCount(1)
        self.sidebar_term_tree.setHeaderHidden(True)
        self.sidebar_term_tree.setRootIsDecorated(True)
        self.sidebar_term_tree.setIndentation(16)
        self.sidebar_term_tree.setAlternatingRowColors(False)
        self.sidebar_term_tree.itemSelectionChanged.connect(self._on_sidebar_term_selected)
        sidebar_layout.addWidget(self.sidebar_term_tree, 1)
        sidebar.setMinimumWidth(320)
        main_layout.addWidget(sidebar, 2)

        content = QWidget(self)
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        main_layout.addWidget(content, 5)

        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        right_panel = QWidget(self)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        content_layout.addWidget(left_panel, 3)
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
        self.annotations_text = QTextEdit(self)
        self.annotations_text.setMinimumWidth(620)
        self.annotations_text.setMaximumHeight(110)
        form_layout.addRow("Deutsch", self.term_de)
        form_layout.addRow("Englisch", self.term_en)
        form_layout.addRow("Beschreibung (DE)", self.term_de_desc)
        form_layout.addRow("Beschreibung (EN)", self.term_en_desc)
        form_layout.addRow("Anmerkungen", self.annotations_text)
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

        self.edit_buttons = [
            self.btn_pick_image,
            self.btn_edit_image,
            self.btn_clear_image,
            self.btn_syn_add,
            self.btn_syn_del,
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

    def _on_sidebar_flat_toggled(self, flat: bool) -> None:
        self._sidebar_flat = flat
        self.sidebar_sort_btn.setText("Kapitel" if flat else "A-Z")
        self.sidebar_sort_btn.setToolTip(
            "Kapitelstruktur anzeigen" if flat else "Alphabetische Liste ohne Gruppen anzeigen"
        )
        self.sidebar_tree_filter_input.setPlaceholderText(
            "Begriff filtern..." if flat else "Kapitel filtern..."
        )
        self._refresh_term_sidebar()

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
        if self._sidebar_flat:
            self._refresh_term_sidebar_flat()
            return
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

    def _refresh_term_sidebar_flat(self) -> None:
        needle = self.sidebar_tree_filter_input.text().strip().casefold()
        selected_term_id = self.current_term_id
        terms = self.service.list_terms()
        with QSignalBlocker(self.sidebar_term_tree):
            self.sidebar_term_tree.clear()
            for term in sorted(terms, key=lambda t: str(t.get("de", "")).casefold()):
                de = str(term.get("de", ""))
                en = str(term.get("en", ""))
                if needle and needle not in de.casefold() and needle not in en.casefold():
                    continue
                term_id = term.get("id")
                if not isinstance(term_id, int):
                    continue
                title = f"{de} | {en}".strip(" |")
                item = QTreeWidgetItem([title])
                item.setData(0, Qt.ItemDataRole.UserRole, term_id)
                self.sidebar_term_tree.addTopLevelItem(item)
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
        self.lock_icon = self._colored_svg_icon(
            locked_svg, QColor("#DC2626"), size=TOOLBAR_ICON_SIZE
        )  # red
        self.unlock_icon = self._colored_svg_icon(
            unlocked_svg, QColor("#16A34A"), size=TOOLBAR_ICON_SIZE
        )  # green
        notification_svg = assets_dir / "notification.svg"
        self.notification_icon = self._colored_svg_icon(
            notification_svg, QColor("#9CA3AF"), size=TOOLBAR_ICON_SIZE
        )  # grey when no pending recommendations

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

    def _notification_badge_icon(self, count: int, size: int = TOOLBAR_ICON_SIZE) -> QIcon:
        path = Path(__file__).resolve().parents[1] / "assets" / "notification.svg"
        if not path.exists():
            return QIcon()
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QIcon()

        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(QRect(0, 0, size, size), QColor("#16A34A"))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        badge_d = max(12, round(size * 0.6))
        badge = QRect(size - badge_d, 0, badge_d, badge_d)
        painter.setBrush(QColor("#DC2626"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(badge)
        painter.setPen(QColor("#FFFFFF"))
        font = QFont()
        font.setPixelSize(max(7, round(badge_d * 0.7)))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "9+" if count > 9 else str(count))
        painter.end()
        return QIcon(pixmap)

    def _svg_pixmap(self, path: Path, width: int, height: int) -> QPixmap:
        if not path.exists():
            return QPixmap()
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()

        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap

    def _toolbar_logo_pixmap(self, width: int, height: int) -> QPixmap:
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        png_path = assets_dir / "k&z_logo.png"
        if not png_path.exists():
            return QPixmap()
        pixmap = QPixmap(str(png_path))
        if pixmap.isNull():
            return QPixmap()
        return pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
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

        for line_edit in [self.term_de, self.term_en]:
            line_edit.setReadOnly(not unlocked)
        for text_edit in [self.term_de_desc, self.term_en_desc, self.annotations_text]:
            text_edit.setReadOnly(not unlocked)
        self.syn_table.setEditTriggers(
            QAbstractItemView.EditTrigger.AllEditTriggers
            if unlocked
            else QAbstractItemView.EditTrigger.NoEditTriggers
        )
        for widget in [self.chapter_filter_input, self.chapter_list]:
            widget.setEnabled(unlocked)

        for action in [
            self.btn_new,
            self.btn_save,
            self.btn_delete,
            self.btn_batch_edit,
            self.btn_manage_chapters,
        ]:
            action.setEnabled(unlocked)
            action.setVisible(unlocked)
        for button in self.edit_buttons:
            button.setEnabled(unlocked)
            button.setCursor(
                Qt.CursorShape.PointingHandCursor if unlocked else Qt.CursorShape.ForbiddenCursor
            )
        self._review_recommendations_action.setVisible(unlocked)
        self.btn_recommend.setVisible(not unlocked)

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
        if checked:
            self._refresh_recommendation_badge()
        self.statusBar().showMessage(
            "Bearbeitung entsperrt" if checked else "Bearbeitung gesperrt", 3000
        )

    def _on_recommend_clicked(self) -> None:
        dlg = RecommendationDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        de, en = dlg.payload()
        try:
            self.service.submit_recommendation(de, en)
            self._refresh_recommendation_badge()
            self.statusBar().showMessage("Vorschlag eingereicht", 3000)
        except Exception as exc:
            QMessageBox.warning(self, "Fehler", str(exc))

    def _on_review_recommendations_clicked(self) -> None:
        dlg = RecommendationReviewDialog(service=self.service, parent=self)
        dlg.exec()
        term_id = dlg.accepted_term_id
        if term_id is not None:
            self._refresh_term_sidebar()
            self._load_term(term_id)
        self._refresh_recommendation_badge()

    def _refresh_recommendation_badge(self) -> None:
        count = self.service.count_pending_recommendations()
        label = f"Vorschläge prüfen ({count})" if count > 0 else "Vorschläge prüfen"
        self._review_recommendations_action.setText(label)
        self._review_recommendations_action.setToolTip(label)
        self._review_recommendations_action.setIcon(
            self._notification_badge_icon(count) if count > 0 else self.notification_icon
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
        worker = UpdateCheckWorker(
            self.update_service, self.config.app_version, show_no_update, show_errors
        )
        # Bound-Method-Slot: Qt queued den Aufruf in den Main-Thread (GUI-sicher).
        worker.signals.finished.connect(self._on_update_check_finished)
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
        # Bound-Method-Slots: Qt queued die Aufrufe in den Main-Thread (GUI-sicher).
        worker.signals.progress.connect(self._on_update_download_progress)
        worker.signals.finished.connect(self._on_update_download_finished)
        worker.signals.error.connect(self._on_update_download_error)
        worker.signals.cancelled.connect(self._on_update_download_cancelled)
        self.search_pool.start(worker)

    def _on_update_download_progress(self, read_bytes: int, total_bytes: int) -> None:
        if self._update_progress is None:
            return
        if total_bytes > 0:
            self._update_progress.setValue(min(100, int(read_bytes * 100 / total_bytes)))
        else:
            self._update_progress.setValue(0)

    def _close_update_progress(self) -> None:
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress = None

    def _on_update_download_finished(self, file_path: object) -> None:
        self._close_update_progress()
        if isinstance(file_path, Path):
            self._apply_downloaded_update(file_path)

    def _on_update_download_error(self, message: str) -> None:
        self._close_update_progress()
        QMessageBox.warning(self, "Update-Download fehlgeschlagen", message)

    def _on_update_download_cancelled(self) -> None:
        self._close_update_progress()

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
        QMessageBox.information(
            self, "Update", "Update wird installiert. Die App wird neu gestartet."
        )
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
            'tasklist /FI "PID eq %PID%" | find "%PID%" >nul\n'
            "if not errorlevel 1 (\n"
            "  timeout /t 1 /nobreak >nul\n"
            "  goto waitloop\n"
            ")\n"
            'copy /Y "%SOURCE%" "%TARGET%" >nul\n'
            'start "" "%TARGET%"\n'
            "exit /b 0\n"
        )
        updater_bat.write_text(bat_content, encoding="utf-8")
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
            getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        subprocess.Popen(["cmd", "/c", str(updater_bat)], creationflags=creationflags)
        QMessageBox.information(
            self, "Update", "Update wird installiert. Die App wird neu gestartet."
        )
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
        self.annotations_text.setPlainText(str(term.get("annotations", "")))

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
        self.annotations_text.clear()
        self._load_chapters([])
        self.syn_table.setRowCount(0)
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
            annotations=self.annotations_text.toPlainText(),
            image=self.current_image_bytes,
            synonyms=synonyms_rows,
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
        dlg = ChapterManagerDialog(self.service, on_changed=self._on_chapters_changed, parent=self)
        dlg.exec()

    def _on_chapters_changed(self) -> None:
        self._load_chapters()
        self._refresh_term_sidebar()
        self._search(self.search_input.text())

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
                self.service.save_term(
                    term_id=term_id,
                    de=str(term.get("de", "")),
                    en=str(term.get("en", "")),
                    de_desc=str(term.get("de_desc", "")),
                    en_desc=str(term.get("en_desc", "")),
                    annotations=str(term.get("annotations", "")),
                    image=image_bytes,
                    synonyms=synonyms if isinstance(synonyms, list) else [],
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
        self._history_chapter_names = {c.id: c.name_de for c in self.service.list_chapters()}
        dlg = QDialog(self)
        dlg.setWindowTitle("Versionshistorie")
        dlg.resize(1000, 640)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        if not records:
            empty = QLabel("Keine relevanten Historieneinträge vorhanden", dlg)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #9CA3AF; font-size: 14px;")
            layout.addWidget(empty, 1)
        else:
            splitter = QSplitter(Qt.Orientation.Horizontal, dlg)
            event_list = QListWidget(splitter)
            event_list.setMinimumWidth(340)
            event_list.setSpacing(2)
            details = QTextBrowser(splitter)
            details.document().setDocumentMargin(14)
            splitter.addWidget(event_list)
            splitter.addWidget(details)
            splitter.setSizes([360, 640])
            layout.addWidget(splitter, 1)

            for rec in records:
                item = QListWidgetItem(event_list)
                item.setData(Qt.ItemDataRole.UserRole, rec)
                row = QWidget(event_list)
                row_layout = QVBoxLayout(row)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(3)
                head = QHBoxLayout()
                head.setSpacing(8)
                action_label = QLabel(self._history_action_label(rec.action), row)
                action_label.setStyleSheet(
                    f"color: {self._history_action_color(rec.action)}; font-weight: 700;"
                )
                date_label = QLabel(rec.changed_at.strftime("%d.%m.%Y %H:%M"), row)
                date_label.setStyleSheet("color: #9CA3AF;")
                head.addWidget(action_label)
                head.addStretch(1)
                head.addWidget(date_label)
                summary_label = QLabel(
                    self._history_summary(rec.action, rec.before_json, rec.after_json), row
                )
                summary_label.setStyleSheet("color: #9CA3AF;")
                row_layout.addLayout(head)
                row_layout.addWidget(summary_label)
                item.setSizeHint(row.sizeHint())
                event_list.setItemWidget(item, row)

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

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        btn = QPushButton("Schließen", dlg)
        btn.clicked.connect(dlg.accept)
        button_row.addWidget(btn)
        layout.addLayout(button_row)
        dlg.exec()

    def _history_action_label(self, action: str) -> str:
        return {
            "create": "Erstellt",
            "update": "Geändert",
            "delete": "Gelöscht",
        }.get(action, action)

    def _history_action_color(self, action: str) -> str:
        return {
            "create": "#16A34A",
            "update": "#2563EB",
            "delete": "#DC2626",
        }.get(action, "#9CA3AF")

    def _history_field_label(self, field: str) -> str:
        return {
            "de": "Begriff (DE)",
            "en": "Begriff (EN)",
            "de_desc": "Beschreibung (DE)",
            "en_desc": "Beschreibung (EN)",
            "annotations": "Anmerkungen",
            "synonyms": "Synonyme",
            "chapter_ids": "Kapitel",
            "image": "Bild",
        }.get(field, field)

    def _history_summary(self, action: str, before_json: str | None, after_json: str | None) -> str:
        changes = self._history_changes(before_json, after_json)
        if action == "create":
            return "Eintrag wurde angelegt."
        if action == "delete":
            return "Eintrag wurde gelöscht."
        if not changes:
            return "Keine Feldänderungen erkannt."
        names = ", ".join(self._history_field_label(change[0]) for change in changes[:3])
        if len(changes) > 3:
            names += f" (+{len(changes) - 3} weitere)"
        return f"Geändert: {names}"

    def _history_colors(self) -> dict[str, str]:
        is_dark = self.palette().window().color().lightness() < 128
        if is_dark:
            return {
                "muted": "#9CA3AF",
                "head_bg": "#374151",
                "head_fg": "#E5E7EB",
                "old_bg": "#42201F",
                "old_fg": "#FCA5A5",
                "new_bg": "#14352A",
                "new_fg": "#86EFAC",
                "row_bg": "#1F2937",
            }
        return {
            "muted": "#6B7280",
            "head_bg": "#F3F4F6",
            "head_fg": "#111827",
            "old_bg": "#FEF2F2",
            "old_fg": "#B91C1C",
            "new_bg": "#F0FDF4",
            "new_fg": "#15803D",
            "row_bg": "#FAFAFA",
        }

    def _history_html_value(self, field: str, value: Any) -> str:
        return html.escape(self._history_value_str(field, value)).replace("\n", "<br/>")

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
        colors = self._history_colors()
        header = (
            f"<p><span style='font-size:16px; font-weight:700; "
            f"color:{self._history_action_color(action)};'>"
            f"{self._history_action_label(action)}</span>"
            f"&nbsp;&nbsp;<span style='color:{colors['muted']};'>am {timestamp}</span></p>"
        )

        if action in {"create", "delete"}:
            data = after_data if action == "create" else before_data
            intro = "Neuer Datensatz" if action == "create" else "Gelöschter Datensatz"
            rows = []
            for field in HISTORY_FIELD_ORDER:
                if field not in data:
                    continue
                value = self._history_html_value(field, data.get(field))
                if value == "—":
                    continue
                rows.append(
                    "<tr>"
                    f"<td width='170' bgcolor='{colors['row_bg']}'>"
                    f"<b>{self._history_field_label(field)}</b></td>"
                    f"<td>{value}</td>"
                    "</tr>"
                )
            image_b64 = data.get("image_b64")
            return (
                header
                + f"<p style='color:{colors['muted']};'>{intro}:</p>"
                + "<table width='100%' cellspacing='0' cellpadding='8' border='0'>"
                + "".join(rows)
                + "</table>"
                + self._history_image_preview_block(
                    image_b64 if action == "delete" else None,
                    image_b64 if action == "create" else None,
                )
            )

        if not changes:
            return header + "<p>Keine darstellbaren Änderungen.</p>"

        rows = [
            "<tr>"
            f"<th align='left' bgcolor='{colors['head_bg']}' width='170'>"
            f"<span style='color:{colors['head_fg']};'>Feld</span></th>"
            f"<th align='left' bgcolor='{colors['head_bg']}'>"
            f"<span style='color:{colors['head_fg']};'>Vorher</span></th>"
            f"<th align='left' bgcolor='{colors['head_bg']}'>"
            f"<span style='color:{colors['head_fg']};'>Nachher</span></th>"
            "</tr>"
        ]
        for field, old, new in changes:
            rows.append(
                "<tr>"
                f"<td bgcolor='{colors['row_bg']}'><b>{self._history_field_label(field)}</b></td>"
                f"<td bgcolor='{colors['old_bg']}'><span style='color:{colors['old_fg']};'>"
                f"{self._history_html_value(field, old)}</span></td>"
                f"<td bgcolor='{colors['new_bg']}'><span style='color:{colors['new_fg']};'>"
                f"{self._history_html_value(field, new)}</span></td>"
                "</tr>"
            )
        return_html = (
            header
            + "<table width='100%' cellspacing='0' cellpadding='8' border='0'>"
            + "".join(rows)
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
        ignored = {"id", "created_at", "updated_at", "image_b64"}
        order = {field: i for i, field in enumerate(HISTORY_FIELD_ORDER)}
        fields = sorted(
            (set(before.keys()) | set(after.keys())) - ignored,
            key=lambda f: (order.get(f, len(order)), f),
        )
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

    def _history_value_str(self, field: str, value: Any) -> str:
        if field == "synonyms" and isinstance(value, list):
            parts = [
                f"{entry.get('synonym', '')} ({entry.get('lang', '')})"
                for entry in value
                if isinstance(entry, dict) and str(entry.get("synonym", "")).strip()
            ]
            return ", ".join(parts) if parts else "—"
        if field == "chapter_ids" and isinstance(value, list):
            names = [
                getattr(self, "_history_chapter_names", {}).get(cid, f"Kapitel #{cid}")
                for cid in value
            ]
            return ", ".join(names) if names else "—"
        if field == "image":
            return "vorhanden" if value else "—"
        if value is None or (isinstance(value, str) and not value.strip()):
            return "—"
        if isinstance(value, bool):
            return "Ja" if value else "Nein"
        if isinstance(value, list):
            return f"{len(value)} Einträge"
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
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

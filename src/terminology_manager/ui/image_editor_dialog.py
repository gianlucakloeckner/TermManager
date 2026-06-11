from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from terminology_manager.services.image_editor import (
    crop_box,
    encode_jpeg,
    flip,
    load_rgba,
    resize_to,
    rotate90,
)

_HANDLE_HIT = 8  # Trefferradius der Anfasser in Pixeln


class _ImageCanvas(QWidget):
    """Zeichnet das Bild eingepasst und stellt im Crop-Modus eine Auswahl bereit."""

    selection_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._crop_mode = False
        self._sel: QRect | None = None  # in Bildkoordinaten
        self._drag: str | None = None  # "new" | "move" | Anfasser ("tl", "t", ...)
        self._drag_start = QPoint()
        self._sel_start = QRect()
        self.setMinimumSize(480, 360)
        self.setMouseTracking(True)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.clear_selection()
        self.update()

    def set_crop_mode(self, enabled: bool) -> None:
        self._crop_mode = enabled
        if not enabled:
            self.clear_selection()
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def selection(self) -> QRect | None:
        if self._sel is None or self._sel.width() < 2 or self._sel.height() < 2:
            return None
        return QRect(self._sel)

    def clear_selection(self) -> None:
        had_selection = self._sel is not None
        self._sel = None
        self._drag = None
        if had_selection:
            self.selection_changed.emit(False)
        self.update()

    # --- Geometrie ---------------------------------------------------------

    def _view_geometry(self) -> tuple[float, QRectF]:
        if self._pixmap.isNull():
            return 1.0, QRectF()
        margin = 12.0
        avail_w = max(1.0, self.width() - 2 * margin)
        avail_h = max(1.0, self.height() - 2 * margin)
        scale = min(avail_w / self._pixmap.width(), avail_h / self._pixmap.height(), 4.0)
        w = self._pixmap.width() * scale
        h = self._pixmap.height() * scale
        return scale, QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _img_point(self, pos: QPointF) -> QPoint:
        scale, target = self._view_geometry()
        x = (pos.x() - target.x()) / scale
        y = (pos.y() - target.y()) / scale
        x = max(0.0, min(x, self._pixmap.width() - 1))
        y = max(0.0, min(y, self._pixmap.height() - 1))
        return QPoint(round(x), round(y))

    def _widget_rect(self, rect: QRect) -> QRectF:
        scale, target = self._view_geometry()
        return QRectF(
            target.x() + rect.x() * scale,
            target.y() + rect.y() * scale,
            rect.width() * scale,
            rect.height() * scale,
        )

    def _handle_points(self, rect: QRectF) -> dict[str, QPointF]:
        return {
            "tl": rect.topLeft(),
            "t": QPointF(rect.center().x(), rect.top()),
            "tr": rect.topRight(),
            "l": QPointF(rect.left(), rect.center().y()),
            "r": QPointF(rect.right(), rect.center().y()),
            "bl": rect.bottomLeft(),
            "b": QPointF(rect.center().x(), rect.bottom()),
            "br": rect.bottomRight(),
        }

    def _hit_handle(self, pos: QPointF) -> str | None:
        if self._sel is None:
            return None
        for name, point in self._handle_points(self._widget_rect(self._sel)).items():
            if abs(pos.x() - point.x()) <= _HANDLE_HIT and abs(pos.y() - point.y()) <= _HANDLE_HIT:
                return name
        return None

    # --- Maus ---------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            not self._crop_mode
            or self._pixmap.isNull()
            or event.button() != Qt.MouseButton.LeftButton
        ):
            return
        pos = event.position()
        handle = self._hit_handle(pos)
        if handle is not None and self._sel is not None:
            self._drag = handle
            self._sel_start = QRect(self._sel)
        elif self._sel is not None and self._widget_rect(self._sel).contains(pos):
            self._drag = "move"
            self._drag_start = self._img_point(pos)
            self._sel_start = QRect(self._sel)
        else:
            self._drag = "new"
            self._drag_start = self._img_point(pos)
            self._sel = QRect(self._drag_start, self._drag_start)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._crop_mode or self._pixmap.isNull():
            return
        pos = event.position()
        if self._drag is None:
            self._update_cursor(pos)
            return
        img_pos = self._img_point(pos)
        if self._drag == "new":
            self._sel = QRect(self._drag_start, img_pos).normalized()
        elif self._drag == "move":
            delta = img_pos - self._drag_start
            left = max(
                0,
                min(
                    self._sel_start.left() + delta.x(),
                    self._pixmap.width() - self._sel_start.width(),
                ),
            )
            top = max(
                0,
                min(
                    self._sel_start.top() + delta.y(),
                    self._pixmap.height() - self._sel_start.height(),
                ),
            )
            self._sel = QRect(QPoint(left, top), self._sel_start.size())
        else:
            rect = QRect(self._sel_start)
            if "l" in self._drag:
                rect.setLeft(img_pos.x())
            if "r" in self._drag:
                rect.setRight(img_pos.x())
            if "t" in self._drag:
                rect.setTop(img_pos.y())
            if "b" in self._drag:
                rect.setBottom(img_pos.y())
            self._sel = rect.normalized()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is None:
            return
        self._drag = None
        if self._sel is not None and (self._sel.width() < 2 or self._sel.height() < 2):
            self._sel = None
        self.selection_changed.emit(self.selection() is not None)
        self.update()

    def _update_cursor(self, pos: QPointF) -> None:
        cursors = {
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
        }
        handle = self._hit_handle(pos)
        if handle is not None:
            self.setCursor(cursors[handle])
        elif self._sel is not None and self._widget_rect(self._sel).contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # --- Zeichnen -----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#15171A"))
        if self._pixmap.isNull():
            painter.end()
            return
        _, target = self._view_geometry()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))

        if self._crop_mode and self._sel is not None and self._sel.width() > 0:
            sel = self._widget_rect(self._sel)
            overlay = QColor(0, 0, 0, 130)
            painter.fillRect(
                QRectF(target.x(), target.y(), target.width(), sel.y() - target.y()), overlay
            )
            painter.fillRect(
                QRectF(target.x(), sel.bottom(), target.width(), target.bottom() - sel.bottom()),
                overlay,
            )
            painter.fillRect(
                QRectF(target.x(), sel.y(), sel.x() - target.x(), sel.height()), overlay
            )
            painter.fillRect(
                QRectF(sel.right(), sel.y(), target.right() - sel.right(), sel.height()), overlay
            )

            painter.setPen(QPen(QColor("#2563EB"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(sel)

            painter.setBrush(QColor("#FFFFFF"))
            painter.setPen(QPen(QColor("#2563EB"), 1))
            for point in self._handle_points(sel).values():
                painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))

            size_text = f"{self._sel.width()} × {self._sel.height()} px"  # noqa: RUF001
            text_y = sel.top() - 8 if sel.top() - 20 > target.top() else sel.top() + 18
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(QPointF(sel.left() + 2, text_y), size_text)
        painter.end()


class ImageEditorDialog(QDialog):
    def __init__(self, image_bytes: bytes, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bildbearbeitung")
        self.resize(960, 640)

        self._original = image_bytes
        self._history: list[Image.Image] = [load_rgba(image_bytes)]
        self._index = 0
        self._sync_guard = False

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        self._btn_crop = QPushButton("Zuschneiden", self)
        self._btn_crop.setCheckable(True)
        self._btn_crop.toggled.connect(self._on_crop_toggled)
        self._btn_crop_apply = QPushButton("Zuschnitt anwenden", self)
        self._btn_crop_apply.setEnabled(False)
        self._btn_crop_apply.clicked.connect(self._apply_crop)
        self._btn_crop_clear = QPushButton("Auswahl aufheben", self)
        self._btn_crop_clear.setEnabled(False)
        self._btn_rot_left = QPushButton("↺ 90° links", self)
        self._btn_rot_left.clicked.connect(lambda: self._push(rotate90(self._current(), False)))
        self._btn_rot_right = QPushButton("↻ 90° rechts", self)
        self._btn_rot_right.clicked.connect(lambda: self._push(rotate90(self._current(), True)))
        self._btn_flip_h = QPushButton("⇆ Spiegeln", self)
        self._btn_flip_h.clicked.connect(lambda: self._push(flip(self._current(), True)))
        self._btn_flip_v = QPushButton("⇅ Spiegeln", self)
        self._btn_flip_v.clicked.connect(lambda: self._push(flip(self._current(), False)))
        for button in [
            self._btn_crop,
            self._btn_crop_apply,
            self._btn_crop_clear,
            self._btn_rot_left,
            self._btn_rot_right,
            self._btn_flip_h,
            self._btn_flip_v,
        ]:
            tools.addWidget(button)
        tools.addStretch(1)
        root.addLayout(tools)

        second_row = QHBoxLayout()
        second_row.setSpacing(6)
        self._btn_resize = QPushButton("Größe ändern", self)
        self._btn_resize.setCheckable(True)
        second_row.addWidget(self._btn_resize)

        self._resize_panel = QWidget(self)
        resize_layout = QHBoxLayout(self._resize_panel)
        resize_layout.setContentsMargins(0, 0, 0, 0)
        resize_layout.setSpacing(6)
        self._spin_w = QSpinBox(self._resize_panel)
        self._spin_w.setRange(1, 10000)
        self._spin_h = QSpinBox(self._resize_panel)
        self._spin_h.setRange(1, 10000)
        self._aspect = QCheckBox("Seitenverhältnis beibehalten", self._resize_panel)
        self._aspect.setChecked(True)
        btn_resize_apply = QPushButton("Anwenden", self._resize_panel)
        btn_resize_apply.clicked.connect(self._apply_resize)
        resize_layout.addWidget(QLabel("Breite", self._resize_panel))
        resize_layout.addWidget(self._spin_w)
        resize_layout.addWidget(QLabel("Höhe", self._resize_panel))
        resize_layout.addWidget(self._spin_h)
        resize_layout.addWidget(self._aspect)
        resize_layout.addWidget(btn_resize_apply)
        self._resize_panel.setVisible(False)
        self._btn_resize.toggled.connect(self._resize_panel.setVisible)
        self._spin_w.valueChanged.connect(self._on_width_changed)
        self._spin_h.valueChanged.connect(self._on_height_changed)
        second_row.addWidget(self._resize_panel)

        second_row.addStretch(1)
        self._btn_undo = QPushButton("↶ Rückgängig", self)
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton("↷ Wiederholen", self)
        self._btn_redo.clicked.connect(self._redo)
        self._btn_reset = QPushButton("Zurücksetzen", self)
        self._btn_reset.clicked.connect(self._reset)
        second_row.addWidget(self._btn_undo)
        second_row.addWidget(self._btn_redo)
        second_row.addWidget(self._btn_reset)
        root.addLayout(second_row)

        self._canvas = _ImageCanvas(self)
        self._canvas.selection_changed.connect(self._on_selection_changed)
        self._btn_crop_clear.clicked.connect(self._canvas.clear_selection)
        root.addWidget(self._canvas, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self._info = QLabel("", self)
        self._info.setStyleSheet("color: #9CA3AF;")
        bottom.addWidget(self._info)
        bottom.addStretch(1)
        bottom.addWidget(QLabel("JPEG-Qualität", self))
        self._quality = QSlider(Qt.Orientation.Horizontal, self)
        self._quality.setRange(10, 95)
        self._quality.setValue(85)
        self._quality.setFixedWidth(140)
        self._quality_value = QLabel("85", self)
        self._quality.valueChanged.connect(lambda v: self._quality_value.setText(str(v)))
        self._quality.sliderReleased.connect(self._update_info)
        bottom.addWidget(self._quality)
        bottom.addWidget(self._quality_value)
        btn_cancel = QPushButton("Abbrechen", self)
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Übernehmen", self)
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_ok)
        root.addLayout(bottom)

        QShortcut(QKeySequence.StandardKey.Undo, self, self._undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self._redo)

        self._refresh()

    @property
    def edited_bytes(self) -> bytes:
        # Unverändert: Original-Bytes zurückgeben, um Re-Encoding zu vermeiden.
        if self._index == 0:
            return self._original
        return encode_jpeg(self._current(), self._quality.value())

    # --- Verlauf -------------------------------------------------------------

    def _current(self) -> Image.Image:
        return self._history[self._index]

    def _push(self, img: Image.Image) -> None:
        self._history = self._history[: self._index + 1]
        self._history.append(img)
        self._index += 1
        self._refresh()

    def _undo(self) -> None:
        if self._index > 0:
            self._index -= 1
            self._refresh()

    def _redo(self) -> None:
        if self._index < len(self._history) - 1:
            self._index += 1
            self._refresh()

    def _reset(self) -> None:
        self._history = self._history[:1]
        self._index = 0
        self._refresh()

    # --- Operationen ----------------------------------------------------------

    def _on_crop_toggled(self, enabled: bool) -> None:
        self._canvas.set_crop_mode(enabled)
        if not enabled:
            self._btn_crop_apply.setEnabled(False)
            self._btn_crop_clear.setEnabled(False)

    def _on_selection_changed(self, has_selection: bool) -> None:
        self._btn_crop_apply.setEnabled(has_selection)
        self._btn_crop_clear.setEnabled(has_selection)

    def _apply_crop(self) -> None:
        selection = self._canvas.selection()
        if selection is None:
            return
        self._push(
            crop_box(
                self._current(),
                selection.x(),
                selection.y(),
                selection.width(),
                selection.height(),
            )
        )

    def _apply_resize(self) -> None:
        self._push(resize_to(self._current(), self._spin_w.value(), self._spin_h.value()))

    def _on_width_changed(self, value: int) -> None:
        if self._sync_guard or not self._aspect.isChecked():
            return
        img = self._current()
        self._sync_guard = True
        self._spin_h.setValue(max(1, round(value * img.height / img.width)))
        self._sync_guard = False

    def _on_height_changed(self, value: int) -> None:
        if self._sync_guard or not self._aspect.isChecked():
            return
        img = self._current()
        self._sync_guard = True
        self._spin_w.setValue(max(1, round(value * img.width / img.height)))
        self._sync_guard = False

    # --- Anzeige ---------------------------------------------------------------

    def _refresh(self) -> None:
        img = self._current()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pixmap = QPixmap()
        pixmap.loadFromData(buf.getvalue())
        self._canvas.set_pixmap(pixmap)

        self._btn_undo.setEnabled(self._index > 0)
        self._btn_redo.setEnabled(self._index < len(self._history) - 1)
        self._btn_reset.setEnabled(self._index > 0)
        self._btn_crop_apply.setEnabled(False)
        self._btn_crop_clear.setEnabled(False)

        self._sync_guard = True
        self._spin_w.setValue(img.width)
        self._spin_h.setValue(img.height)
        self._sync_guard = False
        self._update_info()

    def _update_info(self) -> None:
        img = self._current()
        estimate_kb = len(encode_jpeg(img, self._quality.value())) / 1024
        self._info.setText(
            f"{img.width} × {img.height} px · ca. {estimate_kb:.0f} KB"  # noqa: RUF001
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._canvas.selection() is not None:
            self._canvas.clear_selection()
            return
        super().keyPressEvent(event)

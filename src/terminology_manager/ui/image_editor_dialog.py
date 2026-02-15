from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from terminology_manager.services.image_editor import ImageEditOptions, apply_image_edits


class ImageEditorDialog(QDialog):
    def __init__(self, image_bytes: bytes, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bildbearbeitung")
        self.resize(760, 520)

        self._original = image_bytes
        self._edited = image_bytes

        root = QHBoxLayout(self)

        controls = QVBoxLayout()
        form = QFormLayout()

        self.crop_x = QSpinBox(self)
        self.crop_y = QSpinBox(self)
        self.crop_w = QSpinBox(self)
        self.crop_h = QSpinBox(self)
        self.rotate = QSpinBox(self)
        self.resize_w = QSpinBox(self)
        self.resize_h = QSpinBox(self)
        self.quality = QSpinBox(self)

        for spin in [
            self.crop_x,
            self.crop_y,
            self.crop_w,
            self.crop_h,
            self.resize_w,
            self.resize_h,
        ]:
            spin.setRange(0, 9999)
        self.rotate.setRange(-360, 360)
        self.quality.setRange(10, 95)
        self.quality.setValue(85)

        form.addRow("Zuschneiden X", self.crop_x)
        form.addRow("Zuschneiden Y", self.crop_y)
        form.addRow("Zuschneiden B", self.crop_w)
        form.addRow("Zuschneiden H", self.crop_h)
        form.addRow("Drehen", self.rotate)
        form.addRow("Breite", self.resize_w)
        form.addRow("Höhe", self.resize_h)
        form.addRow("JPEG-Qualität", self.quality)

        controls.addLayout(form)

        btn_apply = QPushButton("Anwenden", self)
        btn_reset = QPushButton("Zurücksetzen", self)
        btn_apply.clicked.connect(self._apply)
        btn_reset.clicked.connect(self._reset)
        controls.addWidget(btn_apply)
        controls.addWidget(btn_reset)
        controls.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        controls.addWidget(buttons)

        root.addLayout(controls, 0)

        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumWidth(420)
        root.addWidget(self.preview, 1)

        self._refresh_preview(self._edited)

    @property
    def edited_bytes(self) -> bytes:
        return self._edited

    def _reset(self) -> None:
        self._edited = self._original
        self._refresh_preview(self._edited)

    def _apply(self) -> None:
        options = ImageEditOptions(
            crop_x=self.crop_x.value(),
            crop_y=self.crop_y.value(),
            crop_w=self.crop_w.value(),
            crop_h=self.crop_h.value(),
            rotate_deg=self.rotate.value(),
            resize_w=self.resize_w.value(),
            resize_h=self.resize_h.value(),
            quality=self.quality.value(),
        )
        self._edited = apply_image_edits(self._edited, options)
        self._refresh_preview(self._edited)

    def _refresh_preview(self, data: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            with Image.open(io.BytesIO(data)) as img:
                rgb = img.convert("RGB")
                buf = io.BytesIO()
                rgb.save(buf, format="JPEG")
                pixmap.loadFromData(buf.getvalue())
        self.preview.setPixmap(
            pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

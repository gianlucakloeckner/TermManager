from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image


@dataclass(slots=True)
class ImageEditOptions:
    crop_x: int = 0
    crop_y: int = 0
    crop_w: int = 0
    crop_h: int = 0
    rotate_deg: int = 0
    resize_w: int = 0
    resize_h: int = 0
    quality: int = 85


def apply_image_edits(image_bytes: bytes, options: ImageEditOptions) -> bytes:
    with Image.open(io.BytesIO(image_bytes)) as img_in:
        img = img_in.convert("RGBA")

        if options.crop_w > 0 and options.crop_h > 0:
            x1 = max(0, options.crop_x)
            y1 = max(0, options.crop_y)
            x2 = min(img.width, x1 + options.crop_w)
            y2 = min(img.height, y1 + options.crop_h)
            if x2 > x1 and y2 > y1:
                img = img.crop((x1, y1, x2, y2))

        if options.rotate_deg % 360 != 0:
            img = img.rotate(-options.rotate_deg, expand=True)

        if options.resize_w > 0 and options.resize_h > 0:
            img = img.resize((options.resize_w, options.resize_h), Image.Resampling.LANCZOS)

        out = io.BytesIO()
        quality = max(10, min(95, options.quality))
        rgb = img.convert("RGB")
        rgb.save(out, format="JPEG", quality=quality, optimize=True)
        return out.getvalue()

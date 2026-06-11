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


def load_rgba(image_bytes: bytes) -> Image.Image:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.convert("RGBA")


def encode_jpeg(img: Image.Image, quality: int = 85) -> bytes:
    out = io.BytesIO()
    img.convert("RGB").save(out, format="JPEG", quality=max(10, min(95, quality)), optimize=True)
    return out.getvalue()


def rotate90(img: Image.Image, clockwise: bool) -> Image.Image:
    transpose = Image.Transpose.ROTATE_270 if clockwise else Image.Transpose.ROTATE_90
    return img.transpose(transpose)


def flip(img: Image.Image, horizontal: bool) -> Image.Image:
    transpose = Image.Transpose.FLIP_LEFT_RIGHT if horizontal else Image.Transpose.FLIP_TOP_BOTTOM
    return img.transpose(transpose)


def crop_box(img: Image.Image, x: int, y: int, w: int, h: int) -> Image.Image:
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img.width, x1 + max(1, w))
    y2 = min(img.height, y1 + max(1, h))
    if x2 <= x1 or y2 <= y1:
        return img
    return img.crop((x1, y1, x2, y2))


def resize_to(img: Image.Image, w: int, h: int) -> Image.Image:
    return img.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)


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

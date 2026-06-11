import io

from PIL import Image

from terminology_manager.services.image_editor import (
    ImageEditOptions,
    apply_image_edits,
    crop_box,
    encode_jpeg,
    flip,
    load_rgba,
    resize_to,
    rotate90,
)


def _png_bytes(width: int = 100, height: int = 60) -> bytes:
    img = Image.new("RGB", (width, height), (255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_apply_image_edits() -> None:
    img = Image.new("RGB", (100, 100), (255, 0, 0))
    src = io.BytesIO()
    img.save(src, format="PNG")

    out = apply_image_edits(
        src.getvalue(),
        ImageEditOptions(
            crop_x=10, crop_y=10, crop_w=50, crop_h=50, rotate_deg=90, resize_w=40, resize_h=40
        ),
    )

    edited = Image.open(io.BytesIO(out))
    assert edited.width == 40
    assert edited.height == 40


def test_load_rgba_and_encode_jpeg() -> None:
    img = load_rgba(_png_bytes())
    assert img.mode == "RGBA"
    assert (img.width, img.height) == (100, 60)

    out = encode_jpeg(img, quality=80)
    decoded = Image.open(io.BytesIO(out))
    assert decoded.format == "JPEG"
    assert (decoded.width, decoded.height) == (100, 60)


def test_rotate90_swaps_dimensions() -> None:
    img = load_rgba(_png_bytes(100, 60))
    rotated = rotate90(img, clockwise=True)
    assert (rotated.width, rotated.height) == (60, 100)
    back = rotate90(rotated, clockwise=False)
    assert (back.width, back.height) == (100, 60)


def test_flip_keeps_dimensions() -> None:
    img = load_rgba(_png_bytes(100, 60))
    assert (flip(img, horizontal=True).size) == (100, 60)
    assert (flip(img, horizontal=False).size) == (100, 60)


def test_crop_box_clamps_to_image() -> None:
    img = load_rgba(_png_bytes(100, 60))
    cropped = crop_box(img, 10, 10, 50, 30)
    assert (cropped.width, cropped.height) == (50, 30)

    overflow = crop_box(img, 80, 40, 100, 100)
    assert (overflow.width, overflow.height) == (20, 20)

    invalid = crop_box(img, 200, 200, 50, 50)
    assert (invalid.width, invalid.height) == (100, 60)


def test_resize_to() -> None:
    img = load_rgba(_png_bytes(100, 60))
    resized = resize_to(img, 50, 30)
    assert (resized.width, resized.height) == (50, 30)

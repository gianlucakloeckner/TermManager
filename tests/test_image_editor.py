import io

from PIL import Image

from terminology_manager.services.image_editor import ImageEditOptions, apply_image_edits


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

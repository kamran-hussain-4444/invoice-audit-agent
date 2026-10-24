"""Photos and scans: straighten (EXIF), shrink to a sensible size and send as image blocks."""

import base64
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from invoice_audit.loaders.errors import LoaderError

MAX_TIFF_PAGES = 10


def _encode(image: Image.Image, prefer_png: bool) -> tuple[str, bytes]:
    jpeg = BytesIO()
    image.save(jpeg, format="JPEG", quality=90)
    best = ("image/jpeg", jpeg.getvalue())
    if prefer_png:
        png = BytesIO()
        image.save(png, format="PNG", optimize=True)
        if len(png.getvalue()) < len(best[1]):
            best = ("image/png", png.getvalue())
    return best


def _prepare(frame: Image.Image, max_edge: int) -> Image.Image:
    frame = ImageOps.exif_transpose(frame)  # phone photos are often stored sideways with a rotation tag
    frame = frame.convert("RGB")
    frame.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    return frame


def image_blocks(data: bytes, max_edge: int) -> list[dict]:
    try:
        image = Image.open(BytesIO(data))
        is_png = image.format == "PNG"
        frames = []
        for index in range(min(getattr(image, "n_frames", 1), MAX_TIFF_PAGES)):
            image.seek(index)
            frames.append(_prepare(image.copy(), max_edge))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise LoaderError("Unreadable or corrupt image") from None

    blocks = []
    for frame in frames:
        media_type, encoded = _encode(frame, prefer_png=is_png)
        blocks.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(encoded).decode("ascii"),
                },
            }
        )
    return blocks

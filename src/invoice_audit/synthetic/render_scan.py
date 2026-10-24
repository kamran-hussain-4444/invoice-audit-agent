"""Turn a digital PDF into realistic "paper" copies: scanned PDF, PNG scan and phone photo (JPG).

All randomness comes from the `seed` argument, so the same seed gives the same images.
"""

import random
from io import BytesIO

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


def rasterise(pdf_bytes: bytes, dpi: int = 150) -> Image.Image:
    """First page of the PDF as an RGB image."""
    document = pdfium.PdfDocument(pdf_bytes)
    try:
        page = document[0]
        image = page.render(scale=dpi / 72).to_pil().convert("RGB")
        page.close()
    finally:
        document.close()
    return image


def _noise(image: Image.Image, rng: np.random.Generator, strength: float) -> Image.Image:
    array = np.asarray(image).astype(np.int16)
    array = array + rng.normal(0, strength, array.shape).astype(np.int16)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def _speckle(image: Image.Image, rng: np.random.Generator, fraction: float) -> Image.Image:
    array = np.asarray(image).copy()
    mask = rng.random(array.shape[:2]) < fraction
    values = rng.choice(np.array([0, 255], dtype=np.uint8), size=int(mask.sum()))
    array[mask] = values if array.ndim == 2 else values[:, None]
    return Image.fromarray(array)


def _jpeg(image: Image.Image, quality: int) -> bytes:
    out = BytesIO()
    image.save(out, format="JPEG", quality=quality, optimize=False)
    return out.getvalue()


def _scan_look(image: Image.Image, seed: int) -> Image.Image:
    """Greyscale, slightly crooked, a little noisy: like a flatbed or MFD scan."""
    rng = random.Random(seed)
    grey = ImageOps.grayscale(image)
    grey = grey.rotate(rng.uniform(-2, 2), resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    grey = _noise(grey, np.random.default_rng(seed), strength=9)
    return ImageEnhance.Contrast(grey).enhance(1.15)


def scanned_pdf(pdf_bytes: bytes, seed: int) -> bytes:
    """Image-only PDF (no text layer) with JPEG artefacts."""
    image = _scan_look(rasterise(pdf_bytes), seed)
    image = Image.open(BytesIO(_jpeg(image, 55)))  # bake in compression artefacts
    out = BytesIO()
    image.save(out, format="PDF", resolution=150.0)
    return out.getvalue()


def png_scan(pdf_bytes: bytes, seed: int) -> bytes:
    image = _scan_look(rasterise(pdf_bytes), seed)
    image = _speckle(image, np.random.default_rng(seed + 1), 0.0015)
    out = BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def photo_jpg(pdf_bytes: bytes, seed: int, blur: float = 0.8) -> bytes:
    """Phone photo of a printed invoice: perspective skew, uneven light, slight blur, JPEG q≈70."""
    rng = random.Random(seed)
    page = rasterise(pdf_bytes, dpi=110)
    w, h = page.size
    pad = 60
    desk = Image.new("RGB", (w + 2 * pad, h + 2 * pad), (118, 104, 88))  # wooden desk behind the paper
    desk.paste(page, (pad, pad))
    W, H = desk.size

    def jitter(value: float) -> float:
        return value + rng.uniform(-0.035, 0.035) * W

    # Perspective: map a slightly distorted quadrilateral back onto the output rectangle.
    quad = (jitter(0), jitter(0), jitter(0), H + rng.uniform(-0.03, 0.03) * H,
            W + rng.uniform(-0.035, 0.035) * W, H + rng.uniform(-0.03, 0.03) * H, jitter(W), jitter(0))  # fmt: skip
    photo = desk.transform(desk.size, Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC)

    # Uneven lighting: a gradient from one corner.
    gradient = (
        np.linspace(rng.uniform(0.72, 0.85), 1.05, W)[None, :] * np.linspace(1.0, rng.uniform(0.8, 0.9), H)[:, None]
    )
    array = np.asarray(photo).astype(np.float32) * gradient[:, :, None]
    photo = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))
    photo = photo.filter(ImageFilter.GaussianBlur(blur))
    photo = _noise(photo, np.random.default_rng(seed), strength=5)
    return _jpeg(photo, 70)

"""Фото кандидатов (план бэкенда §8.4): приём ≤PHOTO_MAX_MB → Pillow
ресайз до 640 px по большей стороне, JPEG q80 → bytes в BinaryField.
"""
from __future__ import annotations

import hashlib
import io

from django.conf import settings
from PIL import Image

MAX_DIMENSION = 640
JPEG_QUALITY = 80

MIME_JPEG = "image/jpeg"


class PhotoTooLargeError(Exception):
    """Превышен лимит размера (вежливый отказ в форме админки)."""


class PhotoInvalidError(Exception):
    """Файл не распознан как изображение."""


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Прозрачность (PNG/GIF-палитра) → белая подложка → RGB."""
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def process_photo(source) -> dict:
    """Ресайз и пережатие фото.

    source — UploadedFile (или file-like с .size) либо bytes.
    Возвращает {"data": bytes, "mime": "image/jpeg", "etag": sha256[:32]}.

    Raises:
        PhotoTooLargeError: исходник больше settings.PHOTO_MAX_MB.
        PhotoInvalidError: не изображение.
    """
    if hasattr(source, "read"):
        size = getattr(source, "size", None)
        raw = source.read()
        if size is None:
            size = len(raw)
    else:
        raw = bytes(source)
        size = len(raw)

    max_bytes = settings.PHOTO_MAX_MB * 1024 * 1024
    if size > max_bytes:
        raise PhotoTooLargeError(
            f"Фото больше {settings.PHOTO_MAX_MB} МБ — уменьшите и загрузите снова"
        )

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise PhotoInvalidError("Не удалось распознать изображение") from exc

    img = _flatten_to_rgb(img)
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
    data = buf.getvalue()
    return {
        "data": data,
        "mime": MIME_JPEG,
        "etag": hashlib.sha256(data).hexdigest()[:32],
    }

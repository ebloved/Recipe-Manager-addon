"""Локальное хранилище изображений рецептов.

Файлы не кладутся в JSON/SQLite: в рецепте остаются только URL вариантов.
Имя каталога — SHA-256 исходного файла, поэтому URL можно кэшировать
навсегда. Варианты: thumb (карточка), card (модалка), full (просмотр/шер).
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

from config import MEDIA_DIR

try:  # HEIC/HEIF с iPhone; без пакета просто нет поддержки.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # noqa: BLE001
    pass

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 50_000_000
FULL_MAX_SIDE = 1600

# name: (width, height, quality)
_CROP_VARIANTS: dict[str, tuple[int, int, int]] = {
    "thumb": (480, 360, 78),
    "card": (960, 720, 80),
}
_VARIANTS = {"thumb", "card", "full"}
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_LOCK = asyncio.Lock()


class MediaError(ValueError):
    """Ошибка валидации/обработки изображения."""


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if img.mode == "P" and "transparency" in img.info:
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def _open_image(data: bytes) -> Image.Image:
    if not data:
        raise MediaError("empty file")
    try:
        img = Image.open(io.BytesIO(data))
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)
        img = ImageOps.exif_transpose(img)
    except UnidentifiedImageError as exc:
        raise MediaError("unsupported image format") from exc
    except Exception as exc:  # noqa: BLE001
        raise MediaError(f"cannot read image: {exc}") from exc

    if img.width * img.height > MAX_PIXELS:
        raise MediaError("image is too large")
    return _to_rgb(img)


def _save_webp(img: Image.Image, path: Path, quality: int) -> None:
    img.save(
        path,
        format="WEBP",
        quality=quality,
        method=6,
        optimize=True,
    )


def _process(data: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    target = MEDIA_DIR / digest
    final_files = [target / f"{name}.webp" for name in ("thumb", "card", "full")]

    if all(p.is_file() for p in final_files):
        full = Image.open(target / "full.webp")
        return _metadata(digest, full.width, full.height, full=True)

    base = _open_image(data)
    if target.exists():
        # Неполный каталог после падения/старого формата — пересоберём.
        shutil.rmtree(target, ignore_errors=True)
    tmp = MEDIA_DIR / f".tmp-{digest}-{uuid.uuid4().hex}"
    tmp.mkdir(parents=True, exist_ok=False)
    try:
        for name, (w, h, quality) in _CROP_VARIANTS.items():
            variant = ImageOps.fit(
                base,
                (w, h),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            _save_webp(variant, tmp / f"{name}.webp", quality)

        full = base.copy()
        full.thumbnail((FULL_MAX_SIDE, FULL_MAX_SIDE), Image.Resampling.LANCZOS)
        _save_webp(full, tmp / "full.webp", 82)

        # Атомарно публикуем каталог. Если параллельный запрос успел
        # создать его — используем готовый вариант.
        try:
            tmp.rename(target)
        except OSError:
            if target.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                raise
        return _metadata(digest, full.width, full.height, full=True)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


def _metadata(digest: str, width: int, height: int, full: bool = False) -> dict[str, Any]:
    return {
        "hash": digest,
        "thumb_url": f"/media/{digest}/thumb.webp",
        "card_url": f"/media/{digest}/card.webp",
        "full_url": f"/media/{digest}/full.webp",
        "width": width,
        "height": height,
        "full": full,
    }


async def save_image(data: bytes) -> dict[str, Any]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise MediaError("file is too large (max 15 MB)")
    async with _LOCK:
        return await asyncio.to_thread(_process, data)


def variant_path(digest: str, variant: str) -> Path | None:
    if not _HASH_RE.fullmatch(digest or "") or variant not in _VARIANTS:
        return None
    path = MEDIA_DIR / digest / f"{variant}.webp"
    return path if path.is_file() else None


def delete_image(digest: str) -> bool:
    if not _HASH_RE.fullmatch(digest or ""):
        return False
    path = MEDIA_DIR / digest
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
        return True
    return False

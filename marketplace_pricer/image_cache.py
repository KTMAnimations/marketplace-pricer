from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from marketplace_pricer.config import Settings


_ALLOWED_EXTS: tuple[str, ...] = ("jpg", "jpeg", "png", "webp", "gif")


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, list) and not value:
            continue
        return value
    return None


def extract_image_url(raw: dict[str, Any]) -> str | None:
    value = _first_non_empty(
        raw.get("image_url"),
        raw.get("image"),
        raw.get("thumbnail_url"),
        raw.get("thumbnail"),
    )
    if isinstance(value, str) and value.strip():
        return value.strip()

    for key in ("images", "image_urls", "photos", "photo_urls"):
        maybe = raw.get(key)
        if isinstance(maybe, list) and maybe:
            first = maybe[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
            if isinstance(first, dict):
                nested = _first_non_empty(first.get("url"), first.get("src"))
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()

    return None


def _hash_key(unique_key: str) -> str:
    return hashlib.sha256(unique_key.encode("utf-8")).hexdigest()[:24]


def _infer_ext_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    ct = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    return mapping.get(ct)


def _infer_ext_from_url(url: str) -> str | None:
    try:
        path = urlparse(url).path or ""
    except Exception:
        return None
    _, ext = os.path.splitext(path)
    if not ext:
        return None
    cleaned = ext.lstrip(".").lower()
    return cleaned if cleaned in _ALLOWED_EXTS else None


def _find_existing(cache_dir: Path, *, base: str) -> Path | None:
    for ext in _ALLOWED_EXTS:
        p = cache_dir / f"{base}.{ext}"
        if p.exists():
            return p
    return None


def cache_image_for_listing(
    settings: Settings,
    *,
    source: str,
    unique_key: str,
    image_url: str,
    max_bytes: int = 6_000_000,
) -> tuple[str, str] | None:
    """
    Download an image URL to the local cache.

    Returns:
      (relative_path_under_data_dir, local_url_path)
    """
    image_url = image_url.strip()
    if not image_url or image_url.startswith("data:"):
        return None

    images_dir = Path(settings.data_dir) / "images"
    cache_dir = images_dir / str(source)
    cache_dir.mkdir(parents=True, exist_ok=True)

    base = _hash_key(unique_key)
    existing = _find_existing(cache_dir, base=base)
    if existing:
        rel = str(existing.relative_to(Path(settings.data_dir)))
        return rel, f"/{rel}"

    tmp_path: Path | None = None
    try:
        with requests.get(
            image_url,
            stream=True,
            headers={
                "User-Agent": "marketplace-pricer/0.1 (+local)",
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            },
            timeout=20,
        ) as resp:
            resp.raise_for_status()

            ext = (
                _infer_ext_from_content_type(resp.headers.get("Content-Type"))
                or _infer_ext_from_url(image_url)
                or "jpg"
            )
            if ext not in _ALLOWED_EXTS:
                ext = "jpg"

            final_path = cache_dir / f"{base}.{ext}"
            tmp_path = cache_dir / f"{base}.{ext}.tmp"

            bytes_written = 0
            with tmp_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    bytes_written += len(chunk)
                    if bytes_written > int(max_bytes):
                        raise RuntimeError("image too large")
                    f.write(chunk)

            tmp_path.replace(final_path)

            rel = str(final_path.relative_to(Path(settings.data_dir)))
            return rel, f"/{rel}"
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        return None

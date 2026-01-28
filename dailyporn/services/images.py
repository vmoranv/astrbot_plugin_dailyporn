from __future__ import annotations

import asyncio
import hashlib
import os
import warnings
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from ..config import DailyPornConfig
from .http import HttpService


class ImageService:
    def __init__(self, *, plugin_name: str, cfg: DailyPornConfig, http: HttpService):
        self._cfg = cfg
        self._http = http
        base_root = get_astrbot_data_path()
        base_dir = Path(os.path.join(str(base_root), "plugin_data", plugin_name))
        self._cache_dir = base_dir / "cache" / "covers"

    async def get_cover_path(self, url: str) -> Optional[str]:
        url = (url or "").strip()
        if not url:
            return None

        mosaic_level = self._cfg.mosaic_level
        key = hashlib.sha1(f"{url}|{mosaic_level}".encode("utf-8")).hexdigest()
        out_path = self._cache_dir / f"{key}.png"
        if out_path.exists():
            return str(out_path)

        data = await self._http.safe_get_bytes(url, proxy=self._cfg.proxy)
        if not data:
            return None

        await asyncio.to_thread(self._cache_dir.mkdir, parents=True, exist_ok=True)

        if mosaic_level <= 0:
            try:
                await asyncio.to_thread(out_path.write_bytes, data)
                return str(out_path)
            except Exception:
                logger.exception("[dailyporn] cover save failed")
                return None

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                Image.MAX_IMAGE_PIXELS = 30_000_000
                img = Image.open(BytesIO(data))
                img.load()
                img = img.convert("RGB")
            pixelated = self._pixelate(img, mosaic_level=mosaic_level)
            await asyncio.to_thread(pixelated.save, out_path, "PNG", optimize=True)
            return str(out_path)
        except Exception:
            logger.exception("[dailyporn] cover process failed")
            return None

    @staticmethod
    def _pixelate(img: Image.Image, *, mosaic_level: int) -> Image.Image:
        level = max(0, min(100, int(mosaic_level)))
        if level <= 0:
            return img

        w, h = img.size
        # Map 1..100 -> 2..40
        factor = 2 + int(level / 100 * 38)
        small_w = max(1, w // factor)
        small_h = max(1, h // factor)

        small = img.resize((small_w, small_h), resample=Image.Resampling.NEAREST)
        return small.resize((w, h), resample=Image.Resampling.NEAREST)

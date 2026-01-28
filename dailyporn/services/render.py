import asyncio
import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from astrbot.api import logger
from PIL import Image

from ..config import DailyPornConfig
from ..models import HotItem
from ..sections import SECTIONS, section_display
from .images import ImageService

HtmlRenderFn = Callable[..., Awaitable[Any]]


def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


class RenderService:
    _MAX_RENDER_BYTES = 2_000_000

    def __init__(
        self,
        *,
        cfg: DailyPornConfig,
        images: ImageService,
        html_render: Optional[HtmlRenderFn],
        templates_dir: Path,
    ):
        self._cfg = cfg
        self._images = images
        self._html_render = html_render
        self._templates_dir = templates_dir
        self._template_cache: dict[str, str] = {}

    async def render_daily(
        self, recos: dict[str, HotItem], *, reason: str
    ) -> str | None:
        if self._cfg.delivery_mode != "html_image":
            return None
        if not self._html_render:
            return None

        blocks = []
        for section_key in [s.key for s in SECTIONS]:
            item = recos.get(section_key)
            if not item:
                continue
            blocks.append(
                {
                    "title": f"{section_display(section_key)} 推荐",
                    "items": [await self._item_ctx(item)],
                }
            )

        ctx = {
            "title": "DailyPorn 日报",
            "subtitle": f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · 触发: {reason}",
            "blocks": blocks,
            "mosaic_level": self._cfg.mosaic_level,
        }
        return await self._render(ctx)

    async def render_section(self, section: str, items: list[HotItem]) -> str | None:
        if self._cfg.delivery_mode != "html_image":
            return None
        if not self._html_render:
            return None

        blocks = [
            {
                "title": f"{section_display(section)} 热门",
                "items": [await self._item_ctx(i) for i in items],
            }
        ]

        ctx = {
            "title": "DailyPorn 热榜",
            "subtitle": f"{datetime.now().strftime('%Y-%m-%d %H:%M')} · 分区: {section_display(section)}",
            "blocks": blocks,
            "mosaic_level": self._cfg.mosaic_level,
        }
        return await self._render(ctx)

    def _select_template(self) -> str:
        name = (self._cfg.render_template_name or "pornhub").strip().lower()
        if name in {"pornhub", "ph"}:
            filename = "dailyporn_pornhub.html"
        else:
            filename = "dailyporn_pornhub.html"

        if filename in self._template_cache:
            return self._template_cache[filename]

        path = self._templates_dir / filename
        try:
            html = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"[dailyporn] template load failed: {path} ({e})")
            html = ""

        html = (html or "").strip()
        if not html:
            fallback_path = self._templates_dir / "dailyporn_fallback.html"
            try:
                html = fallback_path.read_text(encoding="utf-8").strip()
            except Exception as e:
                logger.warning(
                    f"[dailyporn] fallback template load failed: {fallback_path} ({e})"
                )
                html = ""

        self._template_cache[filename] = html
        return html

    def _render_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "full_page": bool(self._cfg.render_full_page),
        }
        image_type = (self._cfg.render_image_type or "").strip().lower()
        if image_type in {"png", "jpeg"}:
            options["type"] = image_type
        if image_type == "jpeg":
            options["quality"] = int(self._cfg.render_quality)
        if self._cfg.render_omit_background:
            options["omit_background"] = True
        if self._cfg.render_timeout_ms > 0:
            options["timeout"] = int(self._cfg.render_timeout_ms)
        return options

    async def _render(self, ctx: dict[str, Any]) -> str | None:
        template_str = self._select_template()
        try:
            send_mode = (self._cfg.render_send_mode or "url").strip().lower()
            result = await self._html_render(
                template_str,
                ctx,
                options=self._render_options(),
                return_url=send_mode == "url",
            )
            if send_mode == "url":
                if isinstance(result, str) and result.startswith(("http://", "https://")):
                    return result
            out_path = Path(str(result)).resolve()
            out_path = await self._compress_render(out_path)
            if send_mode == "base64":
                data = await asyncio.to_thread(out_path.read_bytes)
                return base64.b64encode(data).decode("ascii")
            return str(out_path)
        except Exception as e:
            logger.warning(f"[dailyporn] html_render failed: {e}")
            return None

    async def _item_ctx(self, item: HotItem) -> dict[str, Any]:
        cover_data_uri = ""
        if item.cover_url:
            cover_data_uri = await self._cover_data_uri(item.cover_url)

        duration = ""
        if isinstance(item.meta, dict):
            duration = str(item.meta.get("duration") or "").strip()

        return {
            "source": item.source,
            "title": item.title,
            "url": item.url,
            "stars": item.stars,
            "views": item.views,
            "duration": duration,
            "cover": cover_data_uri,
        }

    async def _cover_data_uri(self, url: str) -> str:
        cover_path = await self._images.get_cover_path(url)
        if not cover_path:
            return ""

        try:
            data = await asyncio.to_thread(Path(cover_path).read_bytes)
        except Exception:
            return ""
        mime = _guess_mime(data)
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    async def _compress_render(self, path: Path) -> Path:
        try:
            size = path.stat().st_size
        except Exception:
            return path

        image_type = (self._cfg.render_image_type or "png").strip().lower()
        quality = max(10, min(100, int(self._cfg.render_quality or 82)))

        if image_type == "jpeg":
            return await asyncio.to_thread(self._save_as_jpeg, path, quality)

        if not self._cfg.render_omit_background and size > self._MAX_RENDER_BYTES:
            return await asyncio.to_thread(self._save_as_jpeg, path, quality)

        await asyncio.to_thread(self._optimize_png, path)
        return path

    @staticmethod
    def _save_as_jpeg(path: Path, quality: int) -> Path:
        out_path = path.with_suffix(".jpg")
        with Image.open(path) as img:
            if img.mode not in {"RGB", "L"}:
                img = img.convert("RGB")
            img.save(
                out_path,
                "JPEG",
                quality=quality,
                optimize=True,
                progressive=True,
            )
        if out_path != path:
            try:
                path.unlink()
            except Exception:
                pass
        return out_path

    @staticmethod
    def _optimize_png(path: Path) -> None:
        with Image.open(path) as img:
            img.save(path, "PNG", optimize=True, compress_level=9)

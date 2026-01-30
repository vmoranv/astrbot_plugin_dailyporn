import asyncio
import base64
import io
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from astrbot.api import logger
from PIL import Image, ImageDraw, ImageFont, ImageOps

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
    _LOCAL_CANVAS_WIDTH = 980
    _LOCAL_PADDING = 24
    _LOCAL_GAP = 16
    _LOCAL_BG = (11, 11, 13)
    _LOCAL_PANEL = (17, 17, 21)
    _LOCAL_CARD = (22, 22, 28)
    _LOCAL_STROKE = (36, 36, 44)
    _LOCAL_TEXT = (242, 242, 242)
    _LOCAL_MUTED = (167, 167, 176)
    _LOCAL_ACCENT = (255, 177, 0)
    _LOCAL_FONT_CANDIDATES = (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyh.ttf",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    )

    def __init__(
        self,
        *,
        cfg: DailyPornConfig,
        images: ImageService,
        html_render: Optional[HtmlRenderFn],
        templates_dir: Path,
        render_dir: Path,
    ):
        self._cfg = cfg
        self._images = images
        self._html_render = html_render
        self._templates_dir = templates_dir
        self._render_dir = render_dir
        self._template_cache: dict[str, str] = {}

    async def render_daily(
        self, recos: dict[str, HotItem], *, reason: str
    ) -> str | None:
        if self._cfg.delivery_mode != "html_image":
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
        try:
            backend = (self._cfg.render_backend or "remote").strip().lower()
            send_mode = (self._cfg.render_send_mode or "url").strip().lower()
            if backend != "local" and self._html_render:
                template_str = self._select_template()
                try:
                    result = await self._html_render(
                        template_str,
                        ctx,
                        options=self._render_options(),
                        return_url=send_mode == "url",
                    )
                    if send_mode == "url":
                        if isinstance(result, str) and result.startswith(
                            ("http://", "https://")
                        ):
                            return result
                    out_path = Path(str(result)).resolve()
                    out_path = await self._compress_render(out_path)
                    if send_mode == "base64":
                        data = await asyncio.to_thread(out_path.read_bytes)
                        return base64.b64encode(data).decode("ascii")
                    return str(out_path)
                except Exception as e:
                    logger.warning(f"[dailyporn] html_render failed: {e}")

            local_path = await asyncio.to_thread(self._render_local, ctx)
            if local_path:
                out_path = await self._compress_render(local_path)
                if send_mode == "base64":
                    data = await asyncio.to_thread(out_path.read_bytes)
                    return base64.b64encode(data).decode("ascii")
                return str(out_path)
        except Exception as e:
            logger.warning(f"[dailyporn] local render failed: {e}")
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

    def _render_local(self, ctx: dict[str, Any]) -> Path | None:
        blocks = ctx.get("blocks") if isinstance(ctx.get("blocks"), list) else []
        if not blocks:
            return None

        title = str(ctx.get("title") or "DailyPorn").strip()
        subtitle = str(ctx.get("subtitle") or "").strip()

        width = self._LOCAL_CANVAS_WIDTH
        padding = self._LOCAL_PADDING
        gap = self._LOCAL_GAP

        title_font = self._load_font(30)
        subtitle_font = self._load_font(14)
        block_font = self._load_font(16)
        item_title_font = self._load_font(14)
        meta_font = self._load_font(12)

        scratch = Image.new("RGB", (width, 10))
        scratch_draw = ImageDraw.Draw(scratch)

        def text_height(font: ImageFont.ImageFont) -> int:
            return self._text_size(scratch_draw, "Hg", font)[1]

        title_h = self._text_size(scratch_draw, title, title_font)[1]
        subtitle_h = (
            self._text_size(scratch_draw, subtitle, subtitle_font)[1] if subtitle else 0
        )
        header_height = title_h + (subtitle_h + 6 if subtitle else 0) + 12

        source_h = text_height(meta_font)
        item_title_h = text_height(item_title_font)
        stats_h = text_height(meta_font)
        meta_height = 10 + source_h + 4 + item_title_h * 2 + 6 + stats_h + 10

        content_height = header_height
        block_layouts: list[dict[str, int]] = []
        for block in blocks:
            items = block.get("items") if isinstance(block, dict) else None
            items = items if isinstance(items, list) else []
            if not items:
                continue
            count = len(items)
            cols = 1 if count <= 1 else 2 if count == 2 else 3
            card_width = (width - padding * 2 - gap * (cols - 1)) // cols
            thumb_height = int(card_width * 9 / 16)
            card_height = thumb_height + meta_height
            rows = (count + cols - 1) // cols
            block_title_h = self._text_size(
                scratch_draw, str(block.get("title") or ""), block_font
            )[1]
            block_height = (
                block_title_h
                + 8
                + rows * card_height
                + gap * (rows - 1)
                + 12
            )
            content_height += block_height
            block_layouts.append(
                {
                    "cols": cols,
                    "card_width": card_width,
                    "thumb_height": thumb_height,
                    "card_height": card_height,
                    "block_title_h": block_title_h,
                    "count": count,
                    "rows": rows,
                }
            )

        height = padding * 2 + content_height
        height = max(height, padding * 2 + header_height + 20)

        img = Image.new("RGB", (width, height), self._LOCAL_BG)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            (padding // 2, padding // 2, width - padding // 2, height - padding // 2),
            radius=18,
            fill=self._LOCAL_PANEL,
            outline=self._LOCAL_STROKE,
            width=2,
        )

        cursor_y = padding
        draw.text((padding, cursor_y), title, font=title_font, fill=self._LOCAL_TEXT)
        cursor_y += title_h + 6
        if subtitle:
            draw.text(
                (padding, cursor_y),
                subtitle,
                font=subtitle_font,
                fill=self._LOCAL_MUTED,
            )
            cursor_y += subtitle_h
        cursor_y += 12

        layout_index = 0
        for block in blocks:
            items = block.get("items") if isinstance(block, dict) else None
            items = items if isinstance(items, list) else []
            if not items:
                continue
            layout = block_layouts[layout_index]
            layout_index += 1

            block_title = str(block.get("title") or "").strip()
            draw.text(
                (padding, cursor_y),
                block_title,
                font=block_font,
                fill=self._LOCAL_TEXT,
            )
            cursor_y += layout["block_title_h"] + 8

            cols = layout["cols"]
            card_width = layout["card_width"]
            thumb_height = layout["thumb_height"]
            card_height = layout["card_height"]

            for idx, item in enumerate(items):
                col = idx % cols
                row = idx // cols
                x = padding + col * (card_width + gap)
                y = cursor_y + row * (card_height + gap)

                draw.rounded_rectangle(
                    (x, y, x + card_width, y + card_height),
                    radius=12,
                    fill=self._LOCAL_CARD,
                    outline=self._LOCAL_STROKE,
                    width=1,
                )

                cover = self._decode_cover(str(item.get("cover") or ""))
                thumb_box = (x, y, x + card_width, y + thumb_height)
                if cover:
                    try:
                        cover = ImageOps.fit(
                            cover,
                            (card_width, thumb_height),
                            method=Image.Resampling.LANCZOS,
                        )
                        img.paste(cover, (x, y))
                    except Exception:
                        cover = None
                if not cover:
                    draw.rectangle(
                        thumb_box,
                        fill=(20, 20, 26),
                        outline=self._LOCAL_STROKE,
                        width=1,
                    )
                    draw.text(
                        (x + 12, y + thumb_height // 2 - 8),
                        "No Cover",
                        font=meta_font,
                        fill=self._LOCAL_MUTED,
                    )

                meta_y = y + thumb_height
                draw.line(
                    (x, meta_y, x + card_width, meta_y),
                    fill=self._LOCAL_STROKE,
                    width=1,
                )

                meta_pad = 10
                meta_x = x + meta_pad
                meta_width = card_width - meta_pad * 2
                cursor = meta_y + meta_pad

                source = str(item.get("source") or "").strip()
                if source:
                    draw.text(
                        (meta_x, cursor),
                        source,
                        font=meta_font,
                        fill=self._LOCAL_ACCENT,
                    )
                cursor += source_h + 4

                title_text = str(item.get("title") or "").strip()
                title_lines = self._wrap_text(
                    scratch_draw, title_text, item_title_font, meta_width, max_lines=2
                )
                for line in title_lines:
                    draw.text(
                        (meta_x, cursor),
                        line,
                        font=item_title_font,
                        fill=self._LOCAL_TEXT,
                    )
                    cursor += item_title_h + 2

                stars = item.get("stars")
                views = item.get("views")
                duration = str(item.get("duration") or "").strip()
                stars_text = "-" if stars is None else str(stars)
                views_text = "-" if views is None else str(views)
                stats = f"star: {stars_text}  views: {views_text}"
                if duration:
                    stats = f"{stats}  {duration}"

                stats_y = y + card_height - meta_pad - stats_h
                draw.text(
                    (meta_x, stats_y),
                    stats,
                    font=meta_font,
                    fill=self._LOCAL_MUTED,
                )

            cursor_y += layout["rows"] * card_height + gap * (layout["rows"] - 1) + 12

        self._render_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._render_dir / f"daily_{uuid4().hex[:8]}.png"
        img.save(out_path, "PNG", optimize=True)
        return out_path

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        for path in self._LOCAL_FONT_CANDIDATES:
            try:
                if Path(path).exists():
                    return ImageFont.truetype(path, size=size)
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
        *,
        max_lines: int = 0,
    ) -> list[str]:
        if not text:
            return []
        lines: list[str] = []
        current = ""
        for ch in text:
            test = current + ch
            if self._text_size(draw, test, font)[0] <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = ch
                if max_lines and len(lines) >= max_lines:
                    current = ""
                    break
        if current and (not max_lines or len(lines) < max_lines):
            lines.append(current)

        if max_lines and len(lines) >= max_lines:
            lines = lines[:max_lines]
            total_len = sum(len(line) for line in lines)
            if total_len < len(text):
                last = lines[-1]
                ellipsis = "..."
                while last and self._text_size(draw, last + ellipsis, font)[0] > max_width:
                    last = last[:-1]
                lines[-1] = f"{last}{ellipsis}" if last else ellipsis
        return lines

    @staticmethod
    def _decode_cover(data_uri: str) -> Image.Image | None:
        value = (data_uri or "").strip()
        if not value:
            return None
        if value.startswith("data:"):
            try:
                _, b64 = value.split("base64,", 1)
                data = base64.b64decode(b64)
                return Image.open(io.BytesIO(data)).convert("RGB")
            except Exception:
                return None
        try:
            path = Path(value)
            if path.exists():
                return Image.open(path).convert("RGB")
        except Exception:
            return None
        return None

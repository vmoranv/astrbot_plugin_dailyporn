import asyncio
import base64
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from astrbot.api import logger

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
            html = _FALLBACK_TEMPLATE.strip()

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
            path = await self._html_render(
                template_str,
                ctx,
                options=self._render_options(),
                return_url=False,
            )
            return str(Path(str(path)).resolve())
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


_FALLBACK_TEMPLATE = r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    :root{
      --bg:#0b0b0d;
      --panel:#111115;
      --panel2:#0f0f13;
      --text:#f2f2f2;
      --muted:#a7a7b0;
      --accent:#ffb100;
      --accent2:#ff7a00;
      --stroke:rgba(255,255,255,.08);
      --shadow: 0 18px 50px rgba(0,0,0,.55);
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      background:
        radial-gradient(1200px 700px at 10% -10%, rgba(255,177,0,.18), transparent 55%),
        radial-gradient(900px 600px at 90% 0%, rgba(255,122,0,.12), transparent 50%),
        radial-gradient(900px 700px at 50% 120%, rgba(255,177,0,.10), transparent 55%),
        var(--bg);
      color:var(--text);
      font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, -apple-system, Segoe UI, sans-serif;
    }
    .wrap{
      width: 980px;
      margin: 28px auto 36px;
      padding: 18px 18px 22px;
      border: 1px solid var(--stroke);
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(17,17,21,.95), rgba(12,12,16,.92));
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
    }
    .wrap:before{
      content:"";
      position:absolute;
      inset:-200px -240px auto auto;
      width: 520px;
      height: 520px;
      background: radial-gradient(circle at 30% 30%, rgba(255,177,0,.32), transparent 60%);
      transform: rotate(12deg);
      filter: blur(0px);
      opacity:.8;
      pointer-events:none;
    }
    .header{
      display:flex;
      align-items:flex-end;
      justify-content:space-between;
      gap:12px;
      padding: 6px 6px 14px;
      border-bottom: 1px solid var(--stroke);
      margin-bottom: 14px;
    }
    .brand{
      display:flex;
      flex-direction:column;
      gap:6px;
      min-width: 0;
    }
    .brand h1{
      margin:0;
      font-size: 34px;
      letter-spacing:.6px;
      line-height: 1.06;
      font-weight: 900;
    }
    .brand h1 .a{
      color: var(--accent);
      text-shadow: 0 2px 0 rgba(0,0,0,.55);
    }
    .brand .sub{
      font-size: 14px;
      color: var(--muted);
      letter-spacing:.2px;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
      max-width: 720px;
    }
    .badge{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding: 10px 12px;
      border-radius: 999px;
      background: linear-gradient(180deg, rgba(255,177,0,.18), rgba(255,177,0,.06));
      border: 1px solid rgba(255,177,0,.25);
      color: rgba(255,225,165,.95);
      font-size: 13px;
      font-weight: 700;
    }
    .badge .dot{
      width: 9px; height: 9px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(255,177,0,.14);
    }

    .block{ margin: 14px 6px 0; }
    .block-title{
      display:flex;
      align-items:center;
      gap:10px;
      font-size: 16px;
      font-weight: 900;
      letter-spacing:.4px;
      margin: 10px 0 12px;
    }
    .block-title:before{
      content:"";
      width: 10px; height: 10px;
      border-radius: 2px;
      background: linear-gradient(180deg, var(--accent), var(--accent2));
      box-shadow: 0 0 0 4px rgba(255,177,0,.12);
    }
    .grid{
      display:grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .card{
      border: 1px solid var(--stroke);
      border-radius: 14px;
      background: linear-gradient(180deg, rgba(17,17,21,.9), rgba(12,12,16,.88));
      overflow: hidden;
      position: relative;
    }
    .thumb{
      height: 175px;
      background: rgba(255,255,255,.03);
      border-bottom: 1px solid var(--stroke);
      position: relative;
      overflow:hidden;
    }
    .thumb img{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display:block;
      filter: saturate(1.06) contrast(1.05);
    }
    .thumb .ph{
      position:absolute;
      inset:0;
      display:flex;
      align-items:center;
      justify-content:center;
      color: rgba(255,255,255,.35);
      font-size: 14px;
      letter-spacing: .35px;
      background:
        radial-gradient(220px 120px at 50% 30%, rgba(255,177,0,.16), transparent 65%),
        rgba(0,0,0,.15);
    }
    .meta{
      padding: 10px 12px 12px;
      display:flex;
      flex-direction:column;
      gap: 10px;
      min-height: 140px;
    }
    .row{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap: 8px;
      font-size: 12px;
      color: var(--muted);
    }
    .src{
      display:inline-flex;
      align-items:center;
      gap:6px;
      font-weight: 800;
      color: rgba(255,255,255,.78);
      max-width: 70%;
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .src .tag{
      padding: 3px 8px;
      border-radius: 999px;
      background: rgba(255,177,0,.10);
      border: 1px solid rgba(255,177,0,.22);
      color: rgba(255,225,165,.95);
      font-weight: 900;
      letter-spacing: .2px;
    }
    .score{
      font-weight: 800;
      letter-spacing:.1px;
      color: rgba(255,255,255,.72);
      text-align:right;
      white-space:nowrap;
    }
    .title{
      margin:0;
      font-size: 14px;
      line-height: 1.25;
      font-weight: 800;
      color: rgba(255,255,255,.92);
      display:-webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow:hidden;
      min-height: 36px;
    }
    .link{
      font-size: 12px;
      color: rgba(255,177,0,.92);
      overflow:hidden;
      text-overflow:ellipsis;
      white-space:nowrap;
    }
    .footer{
      margin: 16px 6px 0;
      padding-top: 12px;
      border-top: 1px solid var(--stroke);
      color: rgba(255,255,255,.45);
      font-size: 12px;
      display:flex;
      justify-content:space-between;
      gap: 10px;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="brand">
        <h1><span class="a">Daily</span>Porn</h1>
        <div class="sub">{{ subtitle }}</div>
      </div>
      <div class="badge"><span class="dot"></span>mosaic {{ mosaic_level }}</div>
    </div>

    {% for block in blocks %}
      <div class="block">
        <div class="block-title">{{ block.title }}</div>
        <div class="grid">
          {% for item in block.items %}
          <div class="card">
            <div class="thumb">
              {% if item.cover %}
                <img src="{{ item.cover }}" alt="cover" />
              {% else %}
                <div class="ph">No Cover</div>
              {% endif %}
            </div>
            <div class="meta">
              <div class="row">
                <div class="src"><span class="tag">{{ item.source }}</span></div>
                <div class="score">star {{ item.stars if item.stars is not none else '-' }} · views {{ item.views if item.views is not none else '-' }}</div>
              </div>
              <p class="title">{{ item.title }}</p>
              {% if item.duration %}<div class="row">时长 {{ item.duration }}</div>{% endif %}
              <div class="link">{{ item.url }}</div>
            </div>
          </div>
          {% endfor %}
        </div>
      </div>
    {% endfor %}

    <div class="footer">
      <div>DailyPorn · HTML Render</div>
      <div>{{ title }}</div>
    </div>
  </div>
</body>
</html>
"""

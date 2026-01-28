from __future__ import annotations

import base64
import html as _html
import io
import re
from urllib.parse import urljoin

from PIL import Image, ImageDraw

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource


class MmdHubSource(BaseSource):
    source_id = "mmdhub"
    display_name = "MMDHub"
    sections = {"3d"}

    _ROOT_URL = "https://www.mmdhub.net"
    _TRENDING_URL = f"{_ROOT_URL}/videos/top"

    _RE_WATCH = re.compile(r'/en/watch/([^"\'<>\\s]+)\.html', re.IGNORECASE)
    _RE_TITLE_META = re.compile(
        r'property="og:title"\s+content="([^"]+)"', re.IGNORECASE
    )
    _RE_TITLE_H1 = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.IGNORECASE)
    _RE_TITLE_TAG = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
    _RE_THUMB = re.compile(r'property="og:image"\s+content="([^"]+)"', re.IGNORECASE)
    _RE_VIEWS = re.compile(r"(\d[\d,]*)\s*(?:views?|次观看|播放)", re.IGNORECASE)
    _RE_LIKES_DATA = re.compile(r'data-likes="(\d+)"', re.IGNORECASE)
    _RE_DISLIKES_DATA = re.compile(r'data-dislikes="(\d+)"', re.IGNORECASE)
    _RE_DURATION = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        list_html = await self._http.get_text(self._TRENDING_URL, proxy=proxy)
        slugs = []
        for slug in self._RE_WATCH.findall(list_html):
            if slug not in slugs:
                slugs.append(slug)
            if len(slugs) >= max(limit, 8):
                break

        items: list[HotItem] = []
        for slug in slugs:
            url = f"{self._ROOT_URL}/en/watch/{slug}.html"
            try:
                html = await self._http.get_text(url, proxy=proxy)
            except Exception:
                continue

            title = (
                self._extract_first(
                    html, [self._RE_TITLE_META, self._RE_TITLE_H1, self._RE_TITLE_TAG]
                )
                or slug
            )
            title = (
                _html.unescape(title)
                .replace(" - MMDHub", "")
                .replace(" | MMDHub", "")
                .strip()
            )

            thumb = self._extract_first(html, [self._RE_THUMB]) or ""
            if thumb and not thumb.startswith("http"):
                thumb = urljoin(self._ROOT_URL, thumb)
            if thumb:
                thumb = self._fallback_data_url(title, thumb)

            views = parse_compact_int(self._extract_first(html, [self._RE_VIEWS]))
            likes = parse_compact_int(self._extract_first(html, [self._RE_LIKES_DATA]))
            dislikes = parse_compact_int(
                self._extract_first(html, [self._RE_DISLIKES_DATA])
            )
            duration = self._extract_first(html, [self._RE_DURATION]) or ""

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=url,
                    cover_url=thumb,
                    stars=likes,
                    views=views,
                    meta={
                        "duration": duration,
                        "dislikes": dislikes,
                    },
                )
            )
            if len(items) >= limit:
                break

        return items

    @staticmethod
    def _fallback_data_url(title: str, original: str) -> str:
        if "mmdhub.net/upload/photos" not in original:
            return original

        img = Image.new("RGB", (640, 360), (15, 15, 19))
        draw = ImageDraw.Draw(img)
        text = (title or "MMDHub").strip()
        if len(text) > 32:
            text = text[:32] + "…"
        draw.text((24, 24), "MMDHub", fill=(255, 177, 0))
        draw.text((24, 80), text, fill=(240, 240, 240))

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content)
            if m:
                return (m.group(1) or "").strip()
        return None

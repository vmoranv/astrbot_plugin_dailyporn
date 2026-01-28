from __future__ import annotations

import html as _html
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource


class HanimeSource(BaseSource):
    source_id = "hanime"
    display_name = "Hanime"
    sections = {"2.5d"}

    _BASE_URL = "https://hanime1.me"
    _SEARCH_URL = f"{_BASE_URL}/search?sort=views"

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
        "Referer": _BASE_URL,
    }

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._http.get_text(
            self._SEARCH_URL, proxy=proxy, headers=self._HEADERS
        )
        soup = BeautifulSoup(html or "", "html.parser")

        items: list[HotItem] = []
        seen: set[str] = set()

        for a in soup.select('a.video-link[href*="watch?v="]'):
            href = (a.get("href") or "").strip()
            if not href:
                continue

            full_url = (
                href if href.startswith("http") else urljoin(self._BASE_URL, href)
            )
            vid = parse_qs(urlparse(full_url).query).get("v", [""])[0].strip()
            if not vid:
                continue
            if vid in seen:
                continue
            seen.add(vid)

            container = a.find_parent(class_="video-item-container") or a.parent
            title = (container.get("title") or "").strip() if container else ""

            img = a.find("img")
            if not title and img:
                title = (img.get("alt") or img.get("title") or "").strip()
            if not title:
                title = f"Video {vid}"

            thumb = ""
            if img:
                thumb = (img.get("data-src") or img.get("src") or "").strip()
            if thumb and not thumb.startswith("http"):
                thumb = urljoin(self._BASE_URL, thumb)

            views = None
            stars = None
            try:
                detail = await self._http.get_text(
                    full_url, proxy=proxy, headers=self._HEADERS
                )
                views = self._extract_views(detail)
                stars = self._extract_stars(detail)
                if title.startswith("Video "):
                    title = self._extract_detail_title(detail) or title
                if not thumb:
                    thumb = self._extract_detail_thumb(detail) or thumb
            except Exception:
                pass

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=thumb,
                    stars=stars,
                    views=views,
                )
            )
            if len(items) >= limit:
                break

        return items

    @staticmethod
    def _extract_thumbnail_for_id(html: str, video_id: str) -> str:
        patterns = [
            rf'<a[^>]+href="/watch\?v={video_id}"[^>]*>.*?<img[^>]+(?:src|data-src)="([^"]+)"',
            rf'<img[^>]+(?:src|data-src)="([^"]+)"[^>]*>.*?<a[^>]+href="/watch\?v={video_id}"',
            rf'href="/watch\?v={video_id}".*?<img[^>]+(?:src|data-src)="([^"]+)"',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE | re.DOTALL)
            if m:
                return (m.group(1) or "").strip()
        return ""

    @staticmethod
    def _extract_title_for_id(html: str, video_id: str) -> str:
        patterns = [
            rf'href="/watch\?v={video_id}"[^>]*>.*?<[^>]*class="[^"]*(?:title|card-mobile-title|home-rows-videos-title)[^"]*"[^>]*>([^<]+)<',
            rf'<a[^>]+href="/watch\?v={video_id}"[^>]*title="([^"]+)"',
            rf'href="/watch\?v={video_id}".*?alt="([^"]+)"',
        ]
        for p in patterns:
            m = re.search(p, html, re.IGNORECASE | re.DOTALL)
            if m:
                title = _html.unescape(m.group(1)).strip()
                if title and len(title) > 1:
                    return title
        return ""

    @staticmethod
    def _extract_views(detail_html: str) -> int | None:
        m = re.search(
            r"觀看次數[：:]\s*([\d,.]+(?:万|萬)?)\s*次", detail_html, re.IGNORECASE
        )
        if not m:
            m = re.search(
                r"([\d,.]+(?:万|萬)?)\s*次(?:觀看|观看)?", detail_html, re.IGNORECASE
            )
        if not m:
            return None
        raw = (m.group(1) or "").replace("萬", "万")
        return parse_compact_int(raw)

    @staticmethod
    def _extract_stars(detail_html: str) -> int | None:
        # Hanime "like" widget often renders like: "thumb_up</i>100% (4)"
        m = re.search(
            r"video-like-btn[\s\S]{0,400}?\((\d[\d,]*)\)",
            detail_html,
            re.IGNORECASE,
        )
        if m:
            return parse_compact_int(m.group(1))

        m = re.search(
            r"thumb_up</i>[\s\S]{0,160}?\((\d[\d,]*)\)",
            detail_html,
            re.IGNORECASE,
        )
        if m:
            return parse_compact_int(m.group(1))

        m = re.search(r"thumb_up</i>\s*(\d{1,3})%", detail_html, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                return None

        return None

    @staticmethod
    def _extract_detail_title(detail_html: str) -> str:
        m = re.search(
            r'<h3[^>]*class="[^"]*video-details-title[^"]*"[^>]*>([^<]+)</h3>',
            detail_html,
            re.IGNORECASE,
        )
        if m:
            return _html.unescape(m.group(1)).strip()
        m = re.search(r"<title>([^<]+)</title>", detail_html, re.IGNORECASE)
        if m:
            return _html.unescape(m.group(1)).strip()
        return ""

    @staticmethod
    def _extract_detail_thumb(detail_html: str) -> str:
        m = re.search(
            r'poster["\']?\s*[=:]\s*["\']([^"\']+)["\']', detail_html, re.IGNORECASE
        )
        if m:
            return m.group(1).strip()
        m = re.search(
            r'<meta\s+property="og:image"\s+content="([^"]+)"',
            detail_html,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
        return ""

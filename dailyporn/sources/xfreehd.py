from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import parse_tube_list


class XFreeHDSource(BaseSource):
    source_id = "xfreehd"
    display_name = "XFreeHD"
    sections = {"real"}

    _BASE_URL = "https://xfreehd.com"
    _HOT_URLS = [
        f"{_BASE_URL}/",
        f"{_BASE_URL}/trending",
        f"{_BASE_URL}/most-viewed",
        f"{_BASE_URL}/top",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"/video/\d+", re.IGNORECASE),
        re.compile(r"^/video/\d+", re.IGNORECASE),
    ]

    _RE_VIDEO_ID = re.compile(r"/video/(\d+)", re.IGNORECASE)
    _RE_DETAIL_VIEWS = re.compile(r"(?i)\b(\d[\d,]*)\s*views?\b")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._fetch_first(proxy)
        items = parse_tube_list(
            html,
            base_url=self._BASE_URL,
            source_id=self.source_id,
            section=section,
            link_patterns=self._LINK_PATTERNS,
            limit=limit,
        )
        if not items:
            return items

        enriched: list[HotItem] = []
        for it in items:
            try:
                detail = await self._http.get_text(it.url, proxy=proxy, headers=self._HEADERS)
            except Exception:
                enriched.append(it)
                continue

            likes, views, extra_meta = self._parse_detail_stats(it.url, detail)
            meta = dict(it.meta) if isinstance(it.meta, dict) else {}
            meta.update(extra_meta)

            enriched.append(
                HotItem(
                    source=it.source,
                    section=it.section,
                    title=it.title,
                    url=it.url,
                    cover_url=it.cover_url,
                    stars=likes if likes is not None else it.stars,
                    views=views if views is not None else it.views,
                    meta=meta,
                )
            )

        return enriched

    async def _fetch_first(self, proxy: str) -> str:
        last_err: Exception | None = None
        for url in self._HOT_URLS:
            try:
                return await self._http.get_text(
                    url, proxy=proxy, headers=self._HEADERS
                )
            except Exception as e:
                last_err = e
        if last_err:
            raise last_err
        raise RuntimeError("no url")

    def _parse_detail_stats(
        self, url: str, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        likes = None
        m = self._RE_VIDEO_ID.search(url or "")
        vid = m.group(1) if m else ""
        if vid:
            span = soup.select_one(f"#vote_like_{vid} span.btn.num")
            if span:
                likes = parse_compact_int(span.get_text(" ", strip=True))
        if likes is None:
            # Fallback: any vote_like_* element.
            el = soup.select_one("[id^='vote_like_'] span.btn.num")
            if el:
                likes = parse_compact_int(el.get_text(" ", strip=True))

        views = None
        views_el = soup.select_one(".big-views span.text-white:last-of-type")
        if views_el:
            views = parse_compact_int(views_el.get_text(" ", strip=True))
        if views is None:
            t = soup.get_text(" ", strip=True)
            views = parse_compact_int(self._extract_first(t, [self._RE_DETAIL_VIEWS]))

        meta: dict[str, object] = {}
        return likes, views, meta

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import parse_tube_list


class XNXXSource(BaseSource):
    source_id = "xnxx"
    display_name = "XNXX"
    sections = {"real"}

    _BASE_URL = "https://www.xnxx.com"
    _HOT_URLS = [
        f"{_BASE_URL}/todays-selection",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"^/video-", re.IGNORECASE),
        re.compile(r"/video-", re.IGNORECASE),
    ]

    _RE_DETAIL_VIEWS = re.compile(
        r"(\d[\d,\.]*[KMB]?)\s*views?", re.IGNORECASE
    )
    _RE_DETAIL_LIKES = re.compile(
        r"vote-action-good[\s\S]{0,200}?class=[\"']value[\"'][^>]*>([^<]+)<",
        re.IGNORECASE,
    )
    _RE_DETAIL_DISLIKES = re.compile(
        r"vote-action-bad[\s\S]{0,200}?class=[\"']value[\"'][^>]*>([^<]+)<",
        re.IGNORECASE,
    )
    _RE_DETAIL_TITLE_OG = re.compile(
        r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )

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
                detail_html = await self._http.get_text(
                    it.url, proxy=proxy, headers=self._HEADERS
                )
            except Exception:
                enriched.append(it)
                continue

            likes, views, extra_meta = self._parse_detail_stats(detail_html)
            detail_title = self._extract_detail_title(detail_html)
            stars = likes if likes is not None else it.stars
            v = views if views is not None else it.views
            meta = dict(it.meta) if isinstance(it.meta, dict) else {}
            meta.update(extra_meta)
            title = it.title
            if (not title) or title.startswith("http"):
                title = detail_title or title

            enriched.append(
                HotItem(
                    source=it.source,
                    section=it.section,
                    title=title,
                    url=it.url,
                    cover_url=it.cover_url,
                    stars=stars,
                    views=v,
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
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        views = None
        for sel in (
            "[itemprop='interactionCount']",
            "[itemprop='userInteractionCount']",
            ".video-views",
            ".viewcount",
            ".views",
        ):
            el = soup.select_one(sel)
            if el:
                t = el.get("content") or el.get("data-views") or el.get_text(
                    " ", strip=True
                )
                views = parse_compact_int(t)
                if views is not None:
                    break
        if views is None:
            views = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_VIEWS])
            )

        likes = None
        dislikes = None
        el = soup.select_one("a.vote-action-good span.value")
        if el:
            likes = parse_compact_int(el.get_text(" ", strip=True))
        el = soup.select_one("a.vote-action-bad span.value")
        if el:
            dislikes = parse_compact_int(el.get_text(" ", strip=True))

        if likes is None:
            likes = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_LIKES])
            )
        if dislikes is None:
            dislikes = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_DISLIKES])
            )

        meta: dict[str, object] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes

        return likes, views, meta

    def _extract_detail_title(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        el = soup.select_one(".video-title-container .video-title strong")
        if not el:
            el = soup.select_one(".video-title strong")
        if el:
            title = el.get_text(" ", strip=True)
            if title:
                return title
        return self._extract_first(html, [self._RE_DETAIL_TITLE_OG]) or ""

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

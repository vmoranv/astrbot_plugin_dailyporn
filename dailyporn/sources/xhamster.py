from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int, parse_percent_int
from .base import BaseSource
from .tube_common import parse_tube_list


class XHamsterSource(BaseSource):
    source_id = "xhamster"
    display_name = "xHamster"
    sections = {"real"}

    _BASE_URL = "https://xhamster.com"
    _HOT_URLS = [
        f"{_BASE_URL}/best/daily",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"^/videos/", re.IGNORECASE),
        re.compile(r"/videos/", re.IGNORECASE),
    ]

    _RE_JSON_VIEWS = re.compile(
        r'(?i)"(?:views|viewCount|view_count|viewsCount)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_TEXT_VIEWS = re.compile(r"(?i)\b(\d[\d,]{3,})\s*views?\b")
    _RE_LIKE_DISLIKE_PAIR = re.compile(
        r"\b(\d[\d,\.]*[KMB]?)\s*/\s*(\d[\d,\.]*[KMB]?)\b", re.IGNORECASE
    )
    _RE_RATING_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._fetch_first(proxy)
        candidates = parse_tube_list(
            html,
            base_url=self._BASE_URL,
            source_id=self.source_id,
            section=section,
            link_patterns=self._LINK_PATTERNS,
            limit=max(limit * 8, limit),
        )
        out: list[HotItem] = []
        for item in candidates:
            if "/creators/videos/" in item.url:
                continue
            if re.search(r"/videos/[^/]*\\d", item.url) and item.cover_url:
                out.append(item)
                if len(out) >= limit:
                    break

        if len(out) < limit:
            for item in candidates:
                if "/creators/videos/" in item.url:
                    continue
                if item in out:
                    continue
                if item.cover_url:
                    out.append(item)
                    if len(out) >= limit:
                        break

        if len(out) < limit:
            for item in candidates:
                if "/creators/videos/" in item.url:
                    continue
                if item in out:
                    continue
                out.append(item)
                if len(out) >= limit:
                    break

        # Enrich with detail-page stats to avoid list-page heuristic mistakes.
        enriched: list[HotItem] = []
        for it in out:
            try:
                detail = await self._http.get_text(
                    it.url, proxy=proxy, headers=self._HEADERS
                )
            except Exception:
                enriched.append(it)
                continue

            likes, views, extra_meta = self._parse_detail_stats(detail)
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
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")
        text = soup.get_text(" ", strip=True)

        views = None
        # DOM hints first
        for el in soup.select("[aria-label*='views']"):
            v = parse_compact_int(el.get("aria-label"))
            if v is not None:
                views = v
                break
        if views is None:
            eye_icon = soup.select_one("i.xh-icon.eye")
            if eye_icon:
                span = eye_icon.find_next_sibling("span")
                if span:
                    views = parse_compact_int(span.get_text(" ", strip=True))

        # Schema hints
        for sel in ("[itemprop='interactionCount']", "[itemprop='userInteractionCount']"):
            el = soup.select_one(sel)
            if el:
                v = parse_compact_int(el.get("content") or el.get_text(" ", strip=True))
                if v is not None:
                    views = v
                    break
        if views is None:
            views = parse_compact_int(self._extract_first(html, [self._RE_JSON_VIEWS]))
        if views is None:
            views = parse_compact_int(self._extract_first(text, [self._RE_TEXT_VIEWS]))

        likes = None
        dislikes = None
        rating_percent = None

        info = soup.select_one(".rb-new__info")
        if info:
            pair_text = info.get_text(" ", strip=True)
            m = self._RE_LIKE_DISLIKE_PAIR.search(pair_text)
            if m:
                likes = parse_compact_int(m.group(1))
                dislikes = parse_compact_int(m.group(2))
            label = info.get("aria-label") or ""
            if likes is None or dislikes is None:
                m = re.search(
                    r"(\d[\d,\.]*[KMB]?)\s*likes?.*?(\d[\d,\.]*[KMB]?)\s*dislikes?",
                    label,
                    re.IGNORECASE,
                )
                if m:
                    likes = parse_compact_int(m.group(1))
                    dislikes = parse_compact_int(m.group(2))
            rating_percent = parse_percent_int(label) or rating_percent

        # Many xHamster pages show a pair like "766,027 / 3,312" near the like controls.
        if likes is None or dislikes is None:
            for m in self._RE_LIKE_DISLIKE_PAIR.finditer(text or ""):
                a = parse_compact_int(m.group(1))
                b = parse_compact_int(m.group(2))
                if a is None or b is None:
                    continue
                if a <= 0:
                    continue
                if b < 0:
                    continue
                # Plausibility: likes > dislikes and both far smaller than views.
                if b > a:
                    continue
                if views is not None and a > views:
                    continue
                likes = a
                dislikes = b
                break

        if rating_percent is None:
            like_icon = soup.select_one("[aria-label*='%'][aria-label*='like']")
            if like_icon:
                rating_percent = parse_percent_int(like_icon.get("aria-label"))
        if rating_percent is None:
            rating_percent = parse_percent_int(
                self._extract_first(text, [self._RE_RATING_PERCENT])
            )

        meta: dict[str, object] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes
        if rating_percent is not None:
            meta["rating_percent"] = rating_percent

        return likes, views, meta

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

from __future__ import annotations

import random
import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import parse_tube_list


class XVideosSource(BaseSource):
    source_id = "xvideos"
    display_name = "XVideos"
    sections = {"real"}

    _BASE_URL = "https://www.xvideos.com"
    _MONTHLY_PAGES = 3
    _HOT_URLS = []

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"^/video", re.IGNORECASE),
    ]

    _RE_DETAIL_VIEWS = re.compile(
        r'class=["\']mobile-hide["\'][^>]*>(\d[\d,\.]*[KMB]?)<', re.IGNORECASE
    )
    _RE_DETAIL_LIKES = re.compile(
        r'class=["\']rating-good-nbr["\'][^>]*>([^<]+)<', re.IGNORECASE
    )
    _RE_DETAIL_DISLIKES = re.compile(
        r'class=["\']rating-bad-nbr["\'][^>]*>([^<]+)<', re.IGNORECASE
    )
    _RE_DETAIL_VOTES_TOTAL = re.compile(
        r'class=["\']rating-total-txt["\'][^>]*>([^<]+)<', re.IGNORECASE
    )
    _RE_DETAIL_RATING_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")

    def __init__(self, http: HttpService):
        self._http = http
        self._HOT_URLS = self._monthly_best_urls()

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        urls = self._monthly_best_urls()
        self._HOT_URLS = urls

        candidates: list[HotItem] = []
        seen: set[str] = set()
        page_limit = max(limit * 8, 60)
        for url in urls:
            try:
                html = await self._http.get_text(url, proxy=proxy, headers=self._HEADERS)
            except Exception:
                continue
            for item in parse_tube_list(
                html,
                base_url=self._BASE_URL,
                source_id=self.source_id,
                section=section,
                link_patterns=self._LINK_PATTERNS,
                limit=page_limit,
            ):
                if item.url in seen:
                    continue
                seen.add(item.url)
                candidates.append(item)

        if candidates:
            if len(candidates) <= limit:
                items = candidates
            else:
                items = random.sample(candidates, k=limit)
        else:
            items = []
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
            stars = likes if likes is not None else it.stars
            v = views if views is not None else it.views
            meta = dict(it.meta) if isinstance(it.meta, dict) else {}
            meta.update(extra_meta)

            enriched.append(
                HotItem(
                    source=it.source,
                    section=it.section,
                    title=it.title,
                    url=it.url,
                    cover_url=it.cover_url,
                    stars=stars,
                    views=v,
                    meta=meta,
                )
            )

        return enriched

    def _monthly_best_urls(self) -> list[str]:
        now = datetime.utcnow()
        base = f"{self._BASE_URL}/best/{now:%Y-%m}"
        return [base] + [f"{base}/{i}" for i in range(1, self._MONTHLY_PAGES)]

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
            "#v-views strong.mobile-hide",
            "#v-views strong",
            "#video-views strong",
            ".video-views strong",
            ".video-views .mobile-hide",
            "strong.mobile-hide",
        ):
            el = soup.select_one(sel)
            if el:
                views = parse_compact_int(el.get_text(" ", strip=True))
                if views is not None:
                    break
        if views is None:
            views = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_VIEWS])
            )

        likes = None
        dislikes = None
        rating_percent = None
        total_votes = None
        el = soup.select_one(".rating-good-nbr")
        if el:
            likes = parse_compact_int(el.get_text(" ", strip=True))
        el = soup.select_one(".rating-bad-nbr")
        if el:
            dislikes = parse_compact_int(el.get_text(" ", strip=True))

        perc_el = soup.select_one(".rate-infos .rating-good-perc")
        if perc_el:
            rating_percent = parse_compact_int(
                perc_el.get_text(" ", strip=True).replace("%", "")
            )

        total_el = soup.select_one(".rate-infos .rating-total-txt")
        if total_el:
            raw = re.sub(
                r"[^0-9.,KMBkmb]",
                "",
                total_el.get_text(" ", strip=True),
            )
            total_votes = parse_compact_int(raw)

        if likes is None:
            likes = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_LIKES])
            )
        if dislikes is None:
            dislikes = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_DISLIKES])
            )
        if rating_percent is None:
            rating_percent = parse_compact_int(
                self._extract_first(html, [self._RE_DETAIL_RATING_PERCENT])
            )
        if total_votes is None:
            raw = self._extract_first(html, [self._RE_DETAIL_VOTES_TOTAL])
            if raw:
                raw = re.sub(r"[^0-9.,KMBkmb]", "", raw)
                total_votes = parse_compact_int(raw)

        if likes is None and rating_percent is not None and total_votes is not None:
            likes = int(round(total_votes * (rating_percent / 100.0)))
        if dislikes is None and total_votes is not None and likes is not None:
            dislikes = max(0, total_votes - likes)

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

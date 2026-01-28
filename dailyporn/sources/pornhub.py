from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import parse_tube_list


class PornhubSource(BaseSource):
    source_id = "pornhub"
    display_name = "PornHub"
    sections = {"real"}

    _BASE_URL = "https://www.pornhub.com"
    _HOT_URLS = [
        f"{_BASE_URL}/video?o=mv",  # most viewed
        f"{_BASE_URL}/video?o=tr",  # trending
        f"{_BASE_URL}/video",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "age_verified=1; hasVisited=1; platform=pc",
    }

    _LINK_PATTERNS = [
        re.compile(r"/view_video\.php\?viewkey=", re.IGNORECASE),
    ]

    _RE_JSON_VIEWS = re.compile(
        r'(?i)"(?:views|viewCount|view_count)"\s*:\s*"?(\d[\d,\.]*[KMB]?)"?'
    )
    _RE_JSON_LIKES = re.compile(
        r'(?i)"(?:votesUp|upVotes|likes|likeCount|votes_up|votesUpCount)"\s*:\s*"?(\d[\d,\.]*[KMB]?)"?'
    )
    _RE_JSON_DISLIKES = re.compile(
        r'(?i)"(?:votesDown|downVotes|dislikes|dislikeCount|votes_down|votesDownCount)"\s*:\s*"?(\d[\d,\.]*[KMB]?)"?'
    )
    _RE_DOM_LIKES = re.compile(
        r"(?is)(?:votesUp|likeCount|rateUp)[^<]{0,40}>\s*(\d[\d,\.]*[KMB]?)\s*<"
    )
    _RE_DOM_DISLIKES = re.compile(
        r"(?is)(?:votesDown|dislikeCount|rateDown)[^<]{0,40}>\s*(\d[\d,\.]*[KMB]?)\s*<"
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

        # Enrich with detail-page stats (likes/dislikes/views). The listing pages
        # often omit vote counts or render them via JS, which would otherwise show
        # up as 0 in debug reports.
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

        # Views
        views = None
        views_el = soup.select_one("div.views .count")
        if views_el:
            views = parse_compact_int(views_el.get_text(" ", strip=True))
        for sel in (
            "[itemprop='interactionCount']",
            "[itemprop='userInteractionCount']",
            "[data-video-views]",
        ):
            el = soup.select_one(sel)
            if el:
                t = el.get("content") or el.get("data-video-views") or el.get_text(
                    " ", strip=True
                )
                views = parse_compact_int(t)
                if views is not None:
                    break
        if views is None:
            views = parse_compact_int(
                self._extract_first(html, [self._RE_JSON_VIEWS])
            )

        # Likes/dislikes
        likes = None
        dislikes = None
        likes_el = soup.select_one(".votesUp")
        if likes_el:
            likes = parse_compact_int(
                str(likes_el.get("data-rating") or likes_el.get_text(" ", strip=True))
            )
        dislikes_el = soup.select_one(".votesDown")
        if dislikes_el:
            dislikes = parse_compact_int(
                str(
                    dislikes_el.get("data-rating")
                    or dislikes_el.get_text(" ", strip=True)
                )
            )

        # Common data-* carriers
        for key in ("data-votes-up", "data-video-votes-up", "data-likes"):
            el = soup.select_one(f"[{key}]")
            if el and likes is None:
                likes = parse_compact_int(str(el.get(key) or ""))
                if likes is not None:
                    break
        for key in ("data-votes-down", "data-video-votes-down", "data-dislikes"):
            el = soup.select_one(f"[{key}]")
            if el and dislikes is None:
                dislikes = parse_compact_int(str(el.get(key) or ""))
                if dislikes is not None:
                    break

        if likes is None:
            likes = parse_compact_int(
                self._extract_first(html, [self._RE_JSON_LIKES, self._RE_DOM_LIKES])
            )
        if dislikes is None:
            dislikes = parse_compact_int(
                self._extract_first(
                    html, [self._RE_JSON_DISLIKES, self._RE_DOM_DISLIKES]
                )
            )

        meta: dict[str, object] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes
        return likes, views, meta

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

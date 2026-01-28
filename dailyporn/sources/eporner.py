from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int, parse_percent_int
from .base import BaseSource
from .tube_common import parse_tube_list


class EPornerSource(BaseSource):
    source_id = "eporner"
    display_name = "EPorner"
    sections = {"real"}

    _BASE_URL = "https://www.eporner.com"
    _HOT_URLS = [
        f"{_BASE_URL}/",
        f"{_BASE_URL}/most-viewed/",
        f"{_BASE_URL}/top-rated/",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"/hd-porn/", re.IGNORECASE),
        re.compile(r"/video-", re.IGNORECASE),
    ]

    _RE_STATS_BLOCK = re.compile(r"(?is)Statistics.*?(?:Comments|Report|Download)")
    _RE_VIEWS = re.compile(r"(?i)\b(\d[\d,\.]*)\s*views?\b")
    _RE_LIKES = re.compile(r"(?i)\b(\d[\d,\.]*)\s*(?:likes?|upvotes?|votes?)\b")
    _RE_DISLIKES = re.compile(r"(?i)\b(\d[\d,\.]*)\s*dislikes?\b")
    _RE_JSON_LIKES = re.compile(
        r'(?i)"(?:likes|like_count|votes_up|upvotes?)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_JSON_DISLIKES = re.compile(
        r'(?i)"(?:dislikes|dislike_count|votes_down|downvotes?)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_JSON_VIEWS = re.compile(
        r'(?i)"(?:views|view_count|views_count|viewCount)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_RATING_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
    _RE_COMMENTS_BLOCK_NUMBERS = re.compile(
        r"(?is)([\d,]{8,})\s*Comments?\s*\(\s*\d+\s*\)"
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

    def _parse_detail_stats(
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        views = None
        likes = None
        dislikes = None

        views_el = soup.select_one("#cinemaviews1") or soup.select_one(
            "#cinemaviews2"
        )
        if views_el:
            views = parse_compact_int(views_el.get_text(" ", strip=True))

        like_el = soup.select_one(".likeup i, .likeup small")
        if like_el:
            likes = parse_compact_int(like_el.get_text(" ", strip=True))

        dislike_el = soup.select_one(".likedown i, .likedown small")
        if dislike_el:
            dislikes = parse_compact_int(dislike_el.get_text(" ", strip=True))

        # Try DOM hints first.
        if views is None:
            for el in soup.select(
                "[itemprop='interactionCount'], [itemprop='userInteractionCount']"
            ):
                t = el.get("content") or el.get_text(" ", strip=True)
                c = parse_compact_int(t)
                if c is not None and (views is None or c > views):
                    views = c

        # Fallback: parse a "Statistics" block where counts may run together.
        block = ""
        m = self._RE_STATS_BLOCK.search(html or "")
        if m:
            block = m.group(0)

        if views is None:
            views = parse_compact_int(
                self._extract_first(block or html, [self._RE_VIEWS, self._RE_JSON_VIEWS])
            )
        if likes is None:
            likes = parse_compact_int(
                self._extract_first(block or html, [self._RE_LIKES, self._RE_JSON_LIKES])
            )
        if dislikes is None:
            dislikes = parse_compact_int(
                self._extract_first(
                    block or html, [self._RE_DISLIKES, self._RE_JSON_DISLIKES]
                )
            )

        # If labels are missing, infer ordering from the stats block: views >> likes >> dislikes.
        if (likes is None or dislikes is None) and block:
            nums = []
            for s in re.findall(r"\d[\d,]{2,}", block):
                n = parse_compact_int(s)
                if n is not None:
                    nums.append(n)
            nums = sorted(set(nums), reverse=True)
            if views is None and nums:
                views = nums[0]
            if likes is None and len(nums) >= 2:
                likes = nums[1]
            if dislikes is None and len(nums) >= 3:
                dislikes = nums[2]

        # Some pages concatenate numbers right before the "Comments (N)" token, e.g.
        # "6,232,010158042659Comments (39)" -> views=6,232,010 likes=158,042 dislikes=659.
        if likes is None or dislikes is None:
            m = self._RE_COMMENTS_BLOCK_NUMBERS.search(html or "")
            if m:
                views2, likes2, dislikes2 = self._split_compacted_stats(m.group(1))
                if views is None and views2 is not None:
                    views = views2
                if likes is None and likes2 is not None:
                    likes = likes2
                if dislikes is None and dislikes2 is not None:
                    dislikes = dislikes2

        rating_percent = parse_percent_int(self._extract_first(html, [self._RE_RATING_PERCENT]))

        meta: dict[str, object] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes
        if rating_percent is not None:
            meta["rating_percent"] = rating_percent

        return likes, views, meta

    @staticmethod
    def _split_compacted_stats(
        s: str,
    ) -> tuple[int | None, int | None, int | None]:
        raw = (s or "").replace(",", "").strip()
        if not raw.isdigit() or len(raw) < 10:
            return None, None, None

        best: tuple[int, int, int] | None = None
        # Try to split into 3 integers: views, likes, dislikes.
        for i in range(4, len(raw) - 2):
            for j in range(i + 1, len(raw) - 1):
                try:
                    a = int(raw[:i])
                    b = int(raw[i:j])
                    c = int(raw[j:])
                except Exception:
                    continue
                # Plausibility constraints.
                if a < 1000:
                    continue
                if c < 0 or c > 5_000_000:
                    continue
                if b < 0 or b > a:
                    continue
                if c > b:
                    continue
                if a > 5_000_000_000:
                    continue
                cand = (a, b, c)
                if best is None:
                    best = cand
                    continue
                # Prefer larger views, then larger likes, then smaller dislikes.
                if (cand[0], cand[1], -cand[2]) > (best[0], best[1], -best[2]):
                    best = cand

        if best is None:
            return None, None, None
        return best

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

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

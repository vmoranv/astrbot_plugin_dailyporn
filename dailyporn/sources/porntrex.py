from __future__ import annotations

import random
import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int, parse_percent_int
from .base import BaseSource
from .tube_common import parse_tube_list


class PornTrexSource(BaseSource):
    source_id = "porntrex"
    display_name = "PornTrex"
    sections = {"real"}

    _BASE_URL = "https://www.porntrex.com"
    _HOT_URLS = [
        f"{_BASE_URL}/top-rated/daily/",
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

    _RE_VIEWS = re.compile(r"(?i)\b(\d[\d\s,]{3,})\s*views?\b")
    _RE_AFTER_AGO_VIEWS = re.compile(
        r"(?i)\b(?:seconds?|minutes?|hours?|days?|weeks?|months?|years?)\s+ago\b\s+(\d[\d\s,]{3,})"
    )
    _RE_JSON_VIEWS = re.compile(
        r'(?i)"(?:views|view_count|viewCount|viewsCount)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_JSON_LIKES = re.compile(
        r'(?i)"(?:likes|like_count|votes_up|upVotes|votesUp|favorites|favourites)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_JSON_DISLIKES = re.compile(
        r'(?i)"(?:dislikes|dislike_count|votes_down|downVotes|votesDown)"\s*:\s*"?(\d[\d,]*)"?'
    )
    _RE_RATING_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
    _RE_VOTES_TOTAL = re.compile(
        r"(?i)\b(\d[\d\s,]{2,})\s*(?:votes?|ratings?)\b"
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
            limit=max(limit * 6, limit),
        )
        if len(items) > limit:
            items = random.sample(items, k=limit)
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

        views = None
        likes = None
        dislikes = None

        likes_el = soup.select_one(
            ".btn-subscribe .button-infow, .btn-subscribe-ajax .button-infow"
        )
        if likes_el:
            likes = parse_compact_int(likes_el.get_text(" ", strip=True))

        for icon in soup.select(".info-block .fa-eye"):
            parent = icon.parent
            if not parent:
                continue
            badge = parent.find("em", class_="badge") or parent.find(
                "span", class_="badge"
            )
            if badge:
                views = parse_compact_int(badge.get_text(" ", strip=True))
                if views is not None:
                    break

        # Try JSON-LD interactionStatistic and similar.
        for el in soup.select("script[type='application/ld+json']"):
            txt = el.get_text(strip=True)
            if not txt:
                continue
            v = parse_compact_int(self._extract_first(txt, [self._RE_JSON_VIEWS]))
            if v is not None and views is None:
                views = v
                break
        if views is None:
            views = parse_compact_int(
                self._extract_first(html, [self._RE_VIEWS, self._RE_JSON_VIEWS])
            )
        if views is None:
            views = parse_compact_int(self._extract_first(html, [self._RE_AFTER_AGO_VIEWS]))

        if likes is None:
            likes = parse_compact_int(self._extract_first(html, [self._RE_JSON_LIKES]))
        if dislikes is None:
            dislikes = parse_compact_int(
                self._extract_first(html, [self._RE_JSON_DISLIKES])
            )

        rating_percent = parse_percent_int(
            self._extract_first(html, [self._RE_RATING_PERCENT])
        )
        votes_total = parse_compact_int(self._extract_first(html, [self._RE_VOTES_TOTAL]))

        # If the site only exposes rating% + total votes, convert it into an
        # estimated like-count so "stars" is comparable across sources.
        if likes is None and rating_percent is not None and votes_total is not None:
            likes = int(round(votes_total * (rating_percent / 100.0)))

        meta: dict[str, object] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes
        if rating_percent is not None:
            meta["rating_percent"] = rating_percent
        if votes_total is not None:
            meta["votes_total"] = votes_total

        return likes, views, meta

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

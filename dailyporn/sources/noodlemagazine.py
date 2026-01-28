from __future__ import annotations

import random
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import extract_img_url, extract_title


class NoodleMagazineSource(BaseSource):
    source_id = "noodlemagazine"
    display_name = "NoodleMagazine"
    sections = {"real"}

    _ROOT_URL = "https://noodlemagazine.com"
    # Daily popular list (server-rendered with view ordering).
    _HOT_URL = f"{_ROOT_URL}/popular/day?sort_by=views&sort_order=desc&p=0"

    _RE_DURATION = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")
    _RE_VIEWS_TEXT = re.compile(r"(?i)\b(\d[\d,.]*[KMB]?)\s*views?\b")
    _RE_LIKE_BLOCK = re.compile(r"(?is)\b(\d[\d,.]*[KMB]?)\b\s*(?:likes?|like)\b")
    _RE_DISLIKE_BLOCK = re.compile(r"(?is)\b(\d[\d,.]*[KMB]?)\b\s*(?:dislikes?|dislike)\b")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._http.get_text(self._HOT_URL, proxy=proxy)
        soup = BeautifulSoup(html or "", "html.parser")

        items: list[HotItem] = []
        seen: set[str] = set()

        for a in soup.select('a.item_link[href^="/watch/"]'):
            href = (a.get("href") or "").strip()
            if not href.startswith("/watch/"):
                continue

            full_url = urljoin(self._ROOT_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            img = a.find("img")
            cover = extract_img_url(img)
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            if cover and cover.startswith("/"):
                cover = urljoin(self._ROOT_URL, cover)

            title = extract_title(a, img) or href.replace("/watch/", "")

            card = a.find_parent("div", class_="item") or a.parent

            views = None
            duration = ""

            views_el = card.select_one(".m_views") if card else None
            if views_el:
                views = parse_compact_int(views_el.get_text(" ", strip=True))

            time_el = card.select_one(".m_time") if card else None
            if time_el:
                m = self._RE_DURATION.search(time_el.get_text(" ", strip=True))
                duration = (m.group(1) if m else "").strip()

            likes = None
            dislikes = None

            # Detail page contains like/dislike counters.
            try:
                detail = await self._http.get_text(full_url, proxy=proxy)
            except Exception:
                detail = ""

            if detail:
                detail_soup = BeautifulSoup(detail, "html.parser")
                views_el = detail_soup.select_one(".h_info .meta span")
                if views_el:
                    views = parse_compact_int(views_el.get_text(" ", strip=True))

                likes_el = detail_soup.select_one(".h_info .actions a.like span")
                if likes_el:
                    likes = parse_compact_int(likes_el.get_text(" ", strip=True))

                dislikes_el = detail_soup.select_one(
                    ".h_info .actions a.dislike span"
                )
                if dislikes_el:
                    dislikes = parse_compact_int(dislikes_el.get_text(" ", strip=True))

                t = " ".join(detail_soup.get_text(" ").split())
                if likes is None:
                    likes = parse_compact_int(
                        self._extract_first(t, [self._RE_LIKE_BLOCK])
                    )
                if dislikes is None:
                    dislikes = parse_compact_int(
                        self._extract_first(t, [self._RE_DISLIKE_BLOCK])
                    )
                if views is None:
                    views = parse_compact_int(
                        self._extract_first(t, [self._RE_VIEWS_TEXT])
                    )

            meta: dict[str, object] = {}
            if duration:
                meta["duration"] = duration
            if dislikes is not None:
                meta["dislikes"] = dislikes

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=cover,
                    stars=likes,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= max(limit * 6, limit):
                break

        if not items:
            return items

        if len(items) > limit:
            items = random.sample(items, k=limit)

        return items

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content or "")
            if m:
                return (m.group(1) or "").strip()
        return None

import re

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import parse_tube_list


class XXXGFPornSource(BaseSource):
    source_id = "xxxgfporn"
    display_name = "XXXGFPORN"
    sections = {"real"}

    _ROOT_URL = "https://www.xxxgfporn.com"
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": _ROOT_URL,
    }

    _LINK_PATTERNS = [
        re.compile(r"/video/[^\s]+\.html", re.IGNORECASE),
    ]

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        url = f"{self._ROOT_URL}/top-rated/"
        html = await self._http.get_text(url, proxy=proxy, headers=self._HEADERS)
        items = parse_tube_list(
            html,
            base_url=self._ROOT_URL,
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

    def _parse_detail_stats(
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        views = None
        for icon in soup.select(".stats-container .i-eye"):
            parent = icon.parent
            if not parent:
                continue
            label = parent.find("span", class_="sub-label")
            if label:
                views = parse_compact_int(label.get_text(" ", strip=True))
                if views is not None:
                    break

        likes = None
        votes_el = soup.select_one(".vote-summary-count.total")
        if votes_el:
            likes = parse_compact_int(votes_el.get_text(" ", strip=True))

        return likes, views, {}

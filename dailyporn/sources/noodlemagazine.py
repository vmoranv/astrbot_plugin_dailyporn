from __future__ import annotations

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
    # Homepage popular is now JS-driven; use server-rendered search page which contains watch cards.
    _HOT_URL = f"{_ROOT_URL}/video/porn"

    _RE_DURATION = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")

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

            meta = {"duration": duration} if duration else {}

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=cover,
                    stars=None,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

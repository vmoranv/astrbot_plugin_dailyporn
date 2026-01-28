from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource


class SmutbaSource(BaseSource):
    source_id = "smutba"
    display_name = "Smutba"
    sections = {"3d"}

    _BASE_URL = "https://smutba.se"
    _HOT_URL = f"{_BASE_URL}/?sort=most_viewed"

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    _RE_PROJECT = re.compile(r"/project/([a-f0-9-]{8,36})/", re.IGNORECASE)
    _RE_VIEWS = re.compile(
        r"<strong>Views</strong>\s*<br[^>]*>\s*(\d+)", re.IGNORECASE | re.DOTALL
    )
    _RE_DOWNLOADS = re.compile(
        r"<strong>Downloads</strong>\s*<br[^>]*>\s*(\d+)", re.IGNORECASE | re.DOTALL
    )
    _RE_OG_IMAGE = re.compile(r'property="og:image"\s+content="([^"]+)"', re.IGNORECASE)

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._http.get_text(
            self._HOT_URL, proxy=proxy, headers=self._HEADERS
        )
        soup = BeautifulSoup(html, "html.parser")

        items: list[HotItem] = []
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            m = self._RE_PROJECT.search(href)
            if not m:
                continue

            model_id = m.group(1)
            if model_id in seen:
                continue
            seen.add(model_id)

            full_url = urljoin(self._BASE_URL, href)
            title = (a.get_text(" ", strip=True) or "").strip() or model_id
            img = a.find("img")
            thumb = ""
            if img:
                thumb = img.get("src", "") or img.get("data-src", "")
            if thumb and not thumb.startswith("http"):
                thumb = urljoin(self._BASE_URL, thumb)

            views = None
            downloads = None
            try:
                detail_html = await self._http.get_text(
                    full_url, proxy=proxy, headers=self._HEADERS
                )
                dsoup = BeautifulSoup(detail_html or "", "html.parser")

                def _stat(label: str) -> int | None:
                    strong = dsoup.find(
                        "strong",
                        string=re.compile(
                            rf"^\s*{re.escape(label)}\s*$", re.IGNORECASE
                        ),
                    )
                    if strong and strong.parent:
                        txt = strong.parent.get_text(" ", strip=True)
                        txt = re.sub(
                            rf"\b{re.escape(label)}\b", " ", txt, flags=re.IGNORECASE
                        )
                        m = re.search(r"(\d[\d,\.]*)", txt)
                        if m:
                            return parse_compact_int(m.group(1))
                    m = re.search(
                        rf"{re.escape(label)}\s*[^\d]{{0,40}}(\d[\d,\.]*)",
                        detail_html,
                        re.IGNORECASE,
                    )
                    if m:
                        return parse_compact_int(m.group(1))
                    return None

                views = _stat("Views")
                downloads = _stat("Downloads")

                if not thumb:
                    mo = self._RE_OG_IMAGE.search(detail_html)
                    if mo:
                        thumb = mo.group(1)
            except Exception:
                pass

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=thumb,
                    stars=downloads,
                    views=views,
                )
            )
            if len(items) >= limit:
                break

        return items

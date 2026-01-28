from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import extract_img_url, extract_title


class SexComSource(BaseSource):
    source_id = "sexcom"
    display_name = "Sex.com"
    sections = {"real"}

    _BASE_URL = "https://www.sex.com"
    _HOT_URL = f"{_BASE_URL}/en/videos"

    _RE_DURATION = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?)")
    _RE_RATING = re.compile(r"(\d{1,3})%")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._http.get_text(self._HOT_URL, proxy=proxy)
        soup = BeautifulSoup(html or "", "html.parser")

        items: list[HotItem] = []
        seen: set[str] = set()

        for card in soup.select('[data-testid="video-card"]'):
            a = card.find("a", attrs={"data-testid": "video-link"}) or card.find(
                "a", href=True
            )
            href = (a.get("href") or "").strip() if a else ""
            if not href.startswith("/en/videos/"):
                continue

            url = urljoin(self._BASE_URL, href)
            if url in seen:
                continue
            seen.add(url)

            img = (a.find("img") if a else None) or card.find("img")
            cover = extract_img_url(img)
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            if cover and cover.startswith("/"):
                cover = urljoin(self._BASE_URL, cover)

            title = extract_title(a, img) or url

            text = card.get_text(" ", strip=True)

            duration = ""
            m = self._RE_DURATION.search(text)
            if m:
                duration = (m.group(1) or "").strip()

            stars = None
            mr = self._RE_RATING.search(text)
            if mr:
                try:
                    stars = int(mr.group(1))
                except Exception:
                    stars = None

            views = None
            tail = text
            if duration:
                tail = tail.replace(duration, " ", 1)

            views_token = ""
            for tok in tail.split():
                if not tok or ":" in tok or tok.endswith("%"):
                    continue
                if (
                    tok.startswith("<")
                    or tok.endswith(("K", "M", "B"))
                    or tok.replace(",", "").replace(".", "").isdigit()
                ):
                    views_token = tok
                    break

            if views_token:
                views = parse_compact_int(views_token.lstrip("<>").strip())

            meta = {"duration": duration} if duration else {}

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=url,
                    cover_url=cover,
                    stars=stars,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

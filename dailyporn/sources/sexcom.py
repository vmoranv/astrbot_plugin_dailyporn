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
    _RE_LT_NUMBER = re.compile(r"^<\s*(\d[\d,.]*)([KMB]?)$", re.IGNORECASE)

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
                t = views_token.strip()
                mlt = self._RE_LT_NUMBER.match(t)
                if mlt:
                    # Sex.com sometimes shows a non-exact counter like "<1K".
                    # Use a conservative integer just below the threshold and
                    # keep the raw text in meta for transparency.
                    approx = parse_compact_int((mlt.group(1) or "").strip() + (mlt.group(2) or ""))
                    if approx is not None and approx > 0:
                        views = approx - 1
                    else:
                        views = None
                else:
                    views = parse_compact_int(t.lstrip("<>").strip())

            meta: dict[str, object] = {}
            if duration:
                meta["duration"] = duration
            if stars is not None:
                meta["rating_percent"] = stars
            if views_token:
                meta["views_text"] = views_token

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

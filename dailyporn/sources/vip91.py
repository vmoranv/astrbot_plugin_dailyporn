from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService, HttpStatusError
from .base import BaseSource, SourceBlockedError


class Vip91Source(BaseSource):
    source_id = "91vip"
    display_name = "91Porn"
    sections = {"real"}

    _BASE_URL = "https://91porn.com"
    _HOT_URL = f"{_BASE_URL}/v.php?category=rf&viewtype=basic&page=1"

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": _BASE_URL,
        "DNT": "1",
    }

    _VIDEO_CARD_SELECTOR = ".well-sm.videos-text-align"
    _TITLE_SELECTOR = ".video-title"
    _RE_PROTOCOL_RELATIVE = re.compile(r"^//")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        try:
            html = await self._http.get_text(
                self._HOT_URL, proxy=proxy, headers=self._HEADERS
            )
        except Exception as e:
            if isinstance(e, HttpStatusError) and e.status == 403:
                try:
                    html = await self._http.get_text_via_jina(
                        self._HOT_URL, proxy=proxy, headers=self._HEADERS
                    )
                except Exception as je:
                    if isinstance(je, HttpStatusError) and je.status == 403:
                        raise SourceBlockedError(
                            "HTTP 403 (Cloudflare/anti-bot). "
                            "Provide a working proxy in plugin config or disable this source."
                        ) from je
                    raise
            else:
                raise
        soup = BeautifulSoup(html, "html.parser")

        items: list[HotItem] = []
        for card in soup.select(self._VIDEO_CARD_SELECTOR)[: max(limit * 3, limit)]:
            title_el = card.select_one(self._TITLE_SELECTOR)
            title = title_el.get_text(strip=True) if title_el else "无标题"

            link_el = card.find("a")
            href = link_el.get("href") if link_el else ""
            if not href:
                continue
            url = urljoin(self._BASE_URL, href)

            img_el = card.find("img")
            img_src = img_el.get("src") if img_el else ""
            if img_src:
                if self._RE_PROTOCOL_RELATIVE.match(img_src):
                    img_src = "https:" + img_src
                elif img_src.startswith("/"):
                    img_src = urljoin(self._BASE_URL, img_src)

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=url,
                    cover_url=img_src,
                    stars=None,
                    views=None,
                )
            )
            if len(items) >= limit:
                break

        return items

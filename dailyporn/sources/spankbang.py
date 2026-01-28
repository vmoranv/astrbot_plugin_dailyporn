from __future__ import annotations

import re

from ..models import HotItem
from ..services.http import HttpService, HttpStatusError
from .base import BaseSource, SourceBlockedError
from .tube_common import parse_tube_list


class SpankBangSource(BaseSource):
    source_id = "spankbang"
    display_name = "SpankBang"
    sections = {"real"}

    _BASE_URL = "https://spankbang.com"
    _HOT_URLS = [
        f"{_BASE_URL}/trending",
        f"{_BASE_URL}/trending_videos",
        f"{_BASE_URL}/",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _LINK_PATTERNS = [
        re.compile(r"^/[^/]+/video/[^/]+", re.IGNORECASE),
        re.compile(r"/[^/]+/video/[^/]+", re.IGNORECASE),
    ]

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._fetch_first(proxy)
        return parse_tube_list(
            html,
            base_url=self._BASE_URL,
            source_id=self.source_id,
            section=section,
            link_patterns=self._LINK_PATTERNS,
            limit=limit,
        )

    async def _fetch_first(self, proxy: str) -> str:
        last_err: Exception | None = None
        for url in self._HOT_URLS:
            try:
                return await self._http.get_text(
                    url, proxy=proxy, headers=self._HEADERS
                )
            except Exception as e:
                last_err = e
                if isinstance(e, HttpStatusError) and e.status == 403:
                    try:
                        return await self._http.get_text_via_jina(
                            url, proxy=proxy, headers=self._HEADERS
                        )
                    except Exception as je:
                        last_err = je
                        continue
                continue
        if last_err:
            if isinstance(last_err, HttpStatusError) and last_err.status == 403:
                raise SourceBlockedError(
                    "HTTP 403 (Cloudflare/anti-bot). "
                    "Provide a working proxy in plugin config or disable this source."
                )
            raise last_err
        raise RuntimeError("no url")

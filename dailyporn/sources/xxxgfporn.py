import re

from ..models import HotItem
from ..services.http import HttpService
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

        url = f"{self._ROOT_URL}/most-viewed/"
        html = await self._http.get_text(url, proxy=proxy, headers=self._HEADERS)
        return parse_tube_list(
            html,
            base_url=self._ROOT_URL,
            source_id=self.source_id,
            section=section,
            link_patterns=self._LINK_PATTERNS,
            limit=limit,
        )

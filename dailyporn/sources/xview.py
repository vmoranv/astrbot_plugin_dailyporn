from __future__ import annotations

import json
import re
from xml.etree import ElementTree as ET

from ..models import HotItem
from ..services.http import HttpService
from .base import BaseSource


class XViewSource(BaseSource):
    source_id = "xview"
    display_name = "XView"
    sections = {"real"}

    _BASE_URL = "https://secure.xview.tv"
    _FEED_URL = f"{_BASE_URL}/feed/latest/"

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "agreeterms=1; age_verified=1",
    }

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        xml_text = await self._http.get_text(
            self._FEED_URL, proxy=proxy, headers=self._HEADERS
        )
        try:
            root = ET.fromstring(xml_text or "")
        except Exception:
            return []

        items: list[HotItem] = []
        for it in root.findall(".//item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or ""
            cover = ""
            m = re.search(r"<img[^>]+src=\"([^\"]+)\"", desc, re.IGNORECASE)
            if m:
                cover = (m.group(1) or "").strip()

            if not link:
                continue
            stars = None
            views = None
            try:
                detail_html = await self._http.get_text(
                    link,
                    proxy=proxy,
                    headers={
                        "User-Agent": self._HEADERS.get("User-Agent", "Mozilla/5.0")
                    },
                )
                stars, views = self._extract_chaturbate_counts(detail_html)
            except Exception:
                pass

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title or link,
                    url=link,
                    cover_url=cover,
                    stars=stars,
                    views=views,
                )
            )
            if len(items) >= limit:
                break

        return items

    @staticmethod
    def _extract_chaturbate_counts(html: str) -> tuple[int | None, int | None]:
        # Example:
        # window.initialRoomDossier = "{\\u0022num_viewers\\u0022: 1266, ...}";
        m = re.search(
            r"window\.initialRoomDossier\s*=\s*\"(.*?)\"\s*;",
            html or "",
            re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return None, None

        raw = (m.group(1) or "").strip()
        try:
            decoded = raw.encode("utf-8").decode("unicode_escape")
            data = json.loads(decoded)
        except Exception:
            return None, None

        viewers = data.get("num_viewers")
        if isinstance(viewers, bool):
            viewers = None
        if isinstance(viewers, (int, float)):
            viewers = int(viewers)
        else:
            viewers = None

        # Chaturbate pages don't reliably expose follower/vote counts in HTML; use
        # live viewer count for both metrics as a popularity proxy.
        return viewers, viewers

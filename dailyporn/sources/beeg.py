from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from .base import BaseSource
from .tube_common import extract_counts, extract_img_url, extract_title


class BeegSource(BaseSource):
    source_id = "beeg"
    display_name = "Beeg"
    sections = {"real"}

    _BASE_URL = "https://beeg.com"
    _STORE_API = "https://store.externulls.com/facts/tag"
    _HOT_URLS = [
        f"{_BASE_URL}/",
    ]

    # "Hot" tag id from Beeg frontend config
    _HOT_TAG_ID = 21868

    _JSON_HEADERS = {"Accept": "application/json"}
    _HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html"}

    _RE_VIDEO_PATH = re.compile(r"^/(-?\d{6,})$")
    _RE_DURATION = re.compile(r"\b(\d{1,2}:\d{2})(?::\d{2})?\b")

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        # Prefer parsing the actual homepage cards so URLs/metrics match what users see.
        for hot_url in self._HOT_URLS:
            try:
                html = await self._http.get_text(hot_url, proxy=proxy, headers=self._HEADERS)
            except Exception:
                continue
            items = self._parse_home(html, limit=limit, section=section)
            if items:
                return items

        # Fallback: legacy externulls store API (may return stale/404 ids).
        params = {
            "limit": max(10, int(limit)),
            "offset": 0,
            "id": self._HOT_TAG_ID,
        }
        url = f"{self._STORE_API}?{urlencode(params)}"

        text = await self._http.get_text(url, proxy=proxy, headers=self._JSON_HEADERS)
        try:
            data = json.loads(text)
        except Exception:
            data = []

        items: list[HotItem] = []
        seen: set[str] = set()

        for entry in data or []:
            if not isinstance(entry, dict):
                continue

            facts = entry.get("fc_facts")
            if not isinstance(facts, list) or not facts:
                continue
            fact = facts[0]
            if not isinstance(fact, dict):
                continue

            public_id = self._find_public_id(entry) or self._find_public_id(fact)

            file = entry.get("file") if isinstance(entry.get("file"), dict) else {}
            file_id = str(file.get("id") or "").strip()
            if not file_id:
                continue

            title = ""
            fdata = file.get("data")
            if isinstance(fdata, list):
                for d in fdata:
                    if not isinstance(d, dict):
                        continue
                    if str(d.get("cd_column") or "").strip() == "sf_name":
                        title = str(d.get("cd_value") or "").strip()
                        if title:
                            break
                if not title:
                    for d in fdata:
                        if isinstance(d, dict):
                            title = str(d.get("cd_value") or "").strip()
                            if title:
                                break

            if not title:
                title = f"Beeg {public_id or file_id}"

            thumb_idx = 0
            thumbs = fact.get("fc_thumbs")
            if isinstance(thumbs, list) and thumbs:
                try:
                    thumb_idx = int(thumbs[0])
                except Exception:
                    thumb_idx = 0

            if not public_id:
                continue
            page_url = f"{self._BASE_URL}/{public_id}"
            if page_url in seen:
                continue
            seen.add(page_url)

            cover_url = f"https://thumbs.externulls.com/videos/{file_id}/{thumb_idx}.webp?size=480x270"

            stars = fact.get("reactions_count_unreg")
            stars = stars if isinstance(stars, int) else None

            views = fact.get("fc_st_views")
            views = views if isinstance(views, int) else None

            meta = {}
            duration = file.get("fl_duration")
            if isinstance(duration, int) and duration > 0:
                meta["duration"] = duration

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=page_url,
                    cover_url=cover_url,
                    stars=stars,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

    def _parse_home(self, html: str, *, limit: int, section: str) -> list[HotItem]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[HotItem] = []
        seen: set[str] = set()

        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            m = self._RE_VIDEO_PATH.match(href)
            if not m:
                continue

            url = f"{self._BASE_URL}{href}"
            if url in seen:
                continue
            seen.add(url)

            img = a.find("img")
            cover = extract_img_url(img)
            if cover and cover.startswith("//"):
                cover = "https:" + cover
            if cover and cover.startswith("/"):
                cover = self._BASE_URL + cover

            title = extract_title(a, img) or url

            # Try to use the nearest card/container text for metrics.
            container = a
            for _ in range(4):
                if container and container.parent:
                    container = container.parent
                if container and container.get_text(strip=True):
                    break
            text = container.get_text(" ", strip=True) if container else ""
            stars, views = extract_counts(text)

            meta: dict[str, object] = {}
            durations = []
            for dm in self._RE_DURATION.findall(text):
                sec = self._parse_duration_seconds(dm)
                if sec:
                    durations.append(sec)
            if durations:
                meta["duration"] = max(durations)

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

    @staticmethod
    def _parse_duration_seconds(s: str) -> int | None:
        s = (s or "").strip()
        if not s:
            return None
        parts = s.split(":")
        try:
            nums = [int(x) for x in parts]
        except Exception:
            return None
        if len(nums) == 2:
            mm, ss = nums
            return mm * 60 + ss
        if len(nums) == 3:
            hh, mm, ss = nums
            return hh * 3600 + mm * 60 + ss
        return None

    @staticmethod
    def _find_public_id(obj: object) -> str | None:
        # Try to locate a beeg public id like "-0351016920609936" from nested dict/list.
        if isinstance(obj, dict):
            for v in obj.values():
                found = BeegSource._find_public_id(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = BeegSource._find_public_id(v)
                if found:
                    return found
        elif isinstance(obj, str):
            s = obj.strip()
            if re.fullmatch(r"-\d{10,}", s):
                return s
        return None

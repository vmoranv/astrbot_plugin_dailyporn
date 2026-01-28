from __future__ import annotations

import json
from urllib.parse import urlencode

from ..models import HotItem
from ..services.http import HttpService
from .base import BaseSource


class BeegSource(BaseSource):
    source_id = "beeg"
    display_name = "Beeg"
    sections = {"real"}

    _BASE_URL = "https://beeg.com"
    _STORE_API = "https://store.externulls.com/facts/tag"

    # "Hot" tag id from Beeg frontend config
    _HOT_TAG_ID = 21868

    _JSON_HEADERS = {"Accept": "application/json"}

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

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

            fact_id = str(fact.get("id") or "").strip()
            if not fact_id:
                continue

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
                title = f"Beeg {fact_id}"

            thumb_idx = 0
            thumbs = fact.get("fc_thumbs")
            if isinstance(thumbs, list) and thumbs:
                try:
                    thumb_idx = int(thumbs[0])
                except Exception:
                    thumb_idx = 0

            page_url = f"{self._BASE_URL}/{fact_id}"
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

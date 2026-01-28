from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from .base import BaseSource
from .tube_common import extract_counts, extract_img_url, extract_title


class MissAVSource(BaseSource):
    source_id = "missav"
    display_name = "MissAV"
    sections = {"real"}

    _BASE_URL = "https://missav.ws/en/"
    _BASE_HOST = "client-rapi-missav.recombee.com"
    _DATABASE_ID = "missav-default"
    _PUBLIC_TOKEN = "Ikkg568nlM51RHvldlPvc2GzZPE9R4XGzaH9Qj4zK9npbbbTly1gj9K4mgRn0QlV"

    _SCRAPE_BASES = [
        "https://missav.mrst.one",
        "https://missav.ws",
    ]
    _HOT_PATHS = [
        "/en/today-hot",
        "/en/weekly-hot",
        "/en/monthly-hot",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _RE_VIDEO = re.compile(r"^/en/[a-z0-9]+-\d+$", re.IGNORECASE)

    _JSON_HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://missav.ws/",
    }

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        items = await self._fetch_hot_scrape(limit=max(1, int(limit)), proxy=proxy)
        if items:
            return items[: max(1, int(limit))]

        return await self._fetch_hot_recombee(limit=max(1, int(limit)), proxy=proxy)

    async def _fetch_hot_scrape(self, *, limit: int, proxy: str) -> list[HotItem]:
        for base in self._SCRAPE_BASES:
            for path in self._HOT_PATHS:
                url = base + path
                try:
                    html = await self._http.get_text(
                        url, proxy=proxy, headers=self._HEADERS
                    )
                except Exception:
                    continue

                soup = BeautifulSoup(html or "", "html.parser")
                items: list[HotItem] = []
                seen: set[str] = set()

                for a in soup.find_all("a", href=True):
                    href = (a.get("href") or "").strip()
                    if not href:
                        continue

                    href_path = href
                    if href_path.startswith(base):
                        href_path = href_path[len(base) :]
                    if not href_path.startswith("/"):
                        continue
                    if not self._RE_VIDEO.match(href_path):
                        continue

                    full_url = urljoin(base, href_path)
                    if full_url in seen:
                        continue
                    seen.add(full_url)

                    best = None
                    best_len = -1
                    cur = a
                    for _ in range(6):
                        cur = getattr(cur, "parent", None)
                        if cur is None:
                            break
                        name = getattr(cur, "name", "")
                        if name in {"html", "body"}:
                            break
                        if name not in {"article", "div", "li", "section"}:
                            continue
                        txt = cur.get_text(" ", strip=True)
                        if len(txt) > best_len:
                            best = cur
                            best_len = len(txt)

                    container = best or a.parent
                    img = (
                        a.find("img")
                        or (container.find("img") if container else None)
                        or a.find("source")
                        or (container.find("source") if container else None)
                    )

                    title = extract_title(a, img) or full_url
                    cover = extract_img_url(img)
                    if cover and not cover.startswith("http"):
                        cover = urljoin(base, cover)

                    text = container.get_text(" ", strip=True) if container else ""
                    stars, views = extract_counts(text)

                    items.append(
                        HotItem(
                            source=self.source_id,
                            section="real",
                            title=title,
                            url=full_url,
                            cover_url=cover,
                            stars=stars,
                            views=views,
                        )
                    )
                    if len(items) >= limit:
                        return items

        return []

    async def _fetch_hot_recombee(self, *, limit: int, proxy: str) -> list[HotItem]:
        path = f"/recomms/users/{quote('anonymous', safe='')}/items/"
        body: dict[str, Any] = {
            "count": max(10, int(limit)),
            "cascadeCreate": True,
            "returnProperties": True,
        }

        signed_path = self._sign_path(path)
        url = f"https://{self._BASE_HOST}{signed_path}"
        data = await self._http.post_json(
            url, json_body=body, proxy=proxy, headers=self._JSON_HEADERS
        )

        items: list[HotItem] = []
        for rec in data.get("recomms") or []:
            if not isinstance(rec, dict):
                continue

            vid = str(rec.get("id") or "").strip()
            if not vid:
                continue

            values = rec.get("values") if isinstance(rec.get("values"), dict) else {}
            title = (
                str(values.get("title_en") or "").strip()
                or str(values.get("title") or "").strip()
                or str(values.get("title_zh") or "").strip()
                or vid
            )

            page_url = urljoin(self._BASE_URL, vid)
            cover = f"https://fourhoi.com/{vid}/cover-t.jpg"

            meta = {}
            duration = values.get("duration")
            if isinstance(duration, int) and duration > 0:
                meta["duration"] = duration
            released_at = values.get("released_at")
            if released_at:
                meta["released_at"] = released_at
            actresses = values.get("actresses")
            if isinstance(actresses, list) and actresses:
                meta["actresses"] = actresses[:10]

            stars = None
            views = None
            for base in self._SCRAPE_BASES:
                try:
                    detail_url = urljoin(base + "/en/", vid)
                    detail_html = await self._http.get_text(
                        detail_url, proxy=proxy, headers=self._HEADERS
                    )
                    soup = BeautifulSoup(detail_html or "", "html.parser")
                    s = soup.get_text(" ", strip=True)
                    stars, views = extract_counts(s)
                    if stars is not None and views is not None:
                        page_url = detail_url
                        break
                except Exception:
                    continue

            items.append(
                HotItem(
                    source=self.source_id,
                    section="real",
                    title=title,
                    url=page_url,
                    cover_url=cover,
                    stars=stars,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

    def _sign_path(self, path: str) -> str:
        ts = int(time.time())
        unsigned = f"/{self._DATABASE_ID}{path}"
        if "?" in unsigned:
            unsigned += f"&frontend_timestamp={ts}"
        else:
            unsigned += f"?frontend_timestamp={ts}"

        signature = hmac.new(
            self._PUBLIC_TOKEN.encode("utf-8"),
            unsigned.encode("utf-8"),
            hashlib.sha1,
        ).hexdigest()
        return unsigned + f"&frontend_sign={signature}"

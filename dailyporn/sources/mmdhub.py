from __future__ import annotations

import html as _html
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource


class MmdHubSource(BaseSource):
    source_id = "mmdhub"
    display_name = "MMDHub"
    sections = {"3d"}

    _ROOT_URL = "https://www.mmdhub.net"
    _HOT_URLS = [
        f"{_ROOT_URL}/videos/top?type=today",
        f"{_ROOT_URL}/videos/top?type=this_week",
        f"{_ROOT_URL}/videos/top",
    ]

    _RE_WATCH = re.compile(r'/en/watch/([^"\'<>\\s]+)\.html', re.IGNORECASE)
    _RE_TITLE_META = re.compile(
        r'property="og:title"\s+content="([^"]+)"', re.IGNORECASE
    )
    _RE_TITLE_H1 = re.compile(r"<h1[^>]*>([^<]+)</h1>", re.IGNORECASE)
    _RE_TITLE_TAG = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
    _RE_THUMB = re.compile(r'property="og:image"\s+content="([^"]+)"', re.IGNORECASE)
    _RE_VIEWS = re.compile(r"(\d[\d,]*)\s*(?:views?|次观看|播放)", re.IGNORECASE)
    _RE_LIKES_DATA = re.compile(r'data-likes="(\d+)"', re.IGNORECASE)
    _RE_DISLIKES_DATA = re.compile(r'data-dislikes="(\d+)"', re.IGNORECASE)
    _RE_PUBLISHED_ON = re.compile(
        r"(?i)\bPublished\s+on\s*(\d{4}/\d{2}/\d{2})\b"
    )

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        list_html = ""
        last_err: Exception | None = None
        for hot_url in self._HOT_URLS:
            try:
                list_html = await self._http.get_text(hot_url, proxy=proxy)
                break
            except Exception as e:
                last_err = e
                continue
        if not list_html and last_err is not None:
            raise last_err

        slugs: list[str] = []
        for slug in self._RE_WATCH.findall(list_html):
            if slug not in slugs:
                slugs.append(slug)
            if len(slugs) >= max(limit, 8):
                break

        items: list[HotItem] = []
        for slug in slugs:
            # Keep '%' to avoid double-encoding already-escaped slugs.
            url = f"{self._ROOT_URL}/en/watch/{quote(slug, safe='%')}.html"
            try:
                html = await self._http.get_text(url, proxy=proxy)
            except Exception:
                continue

            soup = BeautifulSoup(html or "", "html.parser")

            title = ""
            meta_title = soup.find("meta", attrs={"property": "og:title"})
            if meta_title and meta_title.get("content"):
                title = str(meta_title.get("content") or "")
            if not title:
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(" ", strip=True)
            if not title:
                t = soup.find("title")
                if t:
                    title = t.get_text(" ", strip=True)
            title = (
                _html.unescape(title or slug)
                .replace(" - MMDHub", "")
                .replace(" | MMDHub", "")
                .strip()
            )

            thumb = ""
            og_img = soup.find("meta", attrs={"property": "og:image"})
            if og_img and og_img.get("content"):
                thumb = str(og_img.get("content") or "").strip()
            if thumb and not thumb.startswith("http"):
                thumb = urljoin(self._ROOT_URL, thumb)

            views = None
            views_el = soup.find(id="video-views-count")
            if views_el:
                views = parse_compact_int(views_el.get_text(" ", strip=True))
            if views is None:
                views = parse_compact_int(self._extract_first(html, [self._RE_VIEWS]))

            likes = None
            dislikes = None
            likes_bar = soup.find(id="likes-bar")
            if likes_bar:
                likes = parse_compact_int(str(likes_bar.get("data-likes") or ""))
                dislikes = parse_compact_int(str(likes_bar.get("data-dislikes") or ""))
            if likes is None:
                likes = parse_compact_int(self._extract_first(html, [self._RE_LIKES_DATA]))
            if dislikes is None:
                dislikes = parse_compact_int(
                    self._extract_first(html, [self._RE_DISLIKES_DATA])
                )

            meta: dict[str, object] = {}
            if dislikes is not None:
                meta["dislikes"] = dislikes
            published_on = self._extract_first(html, [self._RE_PUBLISHED_ON])
            if published_on:
                meta["published_on"] = published_on

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=url,
                    cover_url=thumb,
                    stars=likes,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content)
            if m:
                return (m.group(1) or "").strip()
        return None

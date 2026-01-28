from __future__ import annotations

import re

from bs4 import BeautifulSoup

from typing import Any

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int, parse_percent_int
from .base import BaseSource


class ThreeDPornDudeSource(BaseSource):
    source_id = "3dporndude"
    display_name = "3DPornDude"
    sections = {"3d"}

    _ROOT_URL = "https://3dporndude.com"
    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    _HOT_URLS = [
        f"{_ROOT_URL}/most-popular/",
        f"{_ROOT_URL}/top-rated/",
        f"{_ROOT_URL}/",
    ]

    _LINK_PATTERNS = [
        re.compile(r"/video/\d+/", re.IGNORECASE),
    ]

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        list_html = await self._fetch_first(proxy)
        items = self._parse_list(list_html, limit=limit, section=section)

        # This site shows rating% on list pages; detail pages contain real
        # like/dislike counts and a more accurate view counter. Prefer detail.
        enriched: list[HotItem] = []
        for it in items:
            try:
                detail_html = await self._http.get_text(
                    it.url, proxy=proxy, headers=self._HEADERS
                )
            except Exception:
                enriched.append(it)
                continue

            likes, views, extra_meta = self._parse_detail_stats(detail_html)
            meta = dict(it.meta) if isinstance(it.meta, dict) else {}
            meta.update(extra_meta)

            enriched.append(
                HotItem(
                    source=it.source,
                    section=it.section,
                    title=it.title,
                    url=it.url,
                    cover_url=it.cover_url,
                    stars=likes if likes is not None else it.stars,
                    views=views if views is not None else it.views,
                    meta=meta,
                )
            )
        return enriched

    async def _fetch_first(self, proxy: str) -> str:
        last_err: Exception | None = None
        for url in self._HOT_URLS:
            try:
                return await self._http.get_text(
                    url, proxy=proxy, headers=self._HEADERS
                )
            except Exception as e:
                last_err = e
        if last_err:
            raise last_err
        raise RuntimeError("no url")

    def _parse_list(self, html: str, *, limit: int, section: str) -> list[HotItem]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[HotItem] = []
        seen: set[str] = set()

        for card in soup.select("div.thumb-itm"):
            a = card.select_one("a[href]")
            href = (a.get("href") or "").strip() if a else ""
            if not href or not any(p.search(href) for p in self._LINK_PATTERNS):
                continue
            if href in seen:
                continue
            seen.add(href)

            title = (a.get("title") or "").strip()
            if not title:
                t = card.select_one(".title")
                title = (t.get_text(" ", strip=True) if t else "").strip()

            img = card.select_one("img")
            cover = ""
            if img:
                cover = (
                    (img.get("data-original") or "")
                    or (img.get("data-webp") or "")
                    or (img.get("src") or "")
                ).strip()

            duration = ""
            dur_el = card.select_one(".time")
            if dur_el:
                duration = (dur_el.get_text(strip=True) or "").strip()

            quality = ""
            q_el = card.select_one(".qualtiy")
            if q_el:
                quality = (q_el.get_text(strip=True) or "").strip()

            views = None
            rating_percent = None
            for ti in card.select(".thumb-bottom-videos .thumb-item"):
                txt = (ti.get_text(" ", strip=True) or "").strip()
                if not txt:
                    continue
                if ti.select_one(".icon-eye"):
                    views = parse_compact_int(txt)
                elif ti.select_one(".icon-like"):
                    rating_percent = parse_percent_int(txt)

            meta: dict[str, object] = {}
            if duration:
                meta["duration"] = duration
            if quality:
                meta["quality"] = quality
            if rating_percent is not None:
                meta["rating_percent"] = rating_percent

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title or href,
                    url=href,
                    cover_url=cover,
                    stars=rating_percent,
                    views=views,
                    meta=meta,
                )
            )
            if len(items) >= limit:
                break

        return items

    def _parse_detail_stats(
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, Any]]:
        soup = BeautifulSoup(html or "", "html.parser")

        likes: int | None = None
        dislikes: int | None = None
        views: int | None = None

        # Likes/dislikes are shown as plain numbers inside the vote buttons.
        like_btn = soup.select_one("a.rate-like")
        if like_btn:
            likes = parse_compact_int(like_btn.get_text(" ", strip=True))

        dislike_btn = soup.select_one("a.rate-dislike")
        if dislike_btn:
            dislikes = parse_compact_int(dislike_btn.get_text(" ", strip=True))

        # Views appear in the "count-item" list with an eye icon.
        for ci in soup.select(".count-item"):
            if ci.select_one(".icon-eye"):
                views = parse_compact_int(ci.get_text(" ", strip=True))
                break
        if views is None:
            m = re.search(r"(?i)\b(\d[\d,.]*[KMB]?)\s*views?\b", html or "")
            if m:
                views = parse_compact_int(m.group(1))

        if likes is None:
            m = re.search(r"(?is)rate-like[^>]*>.*?(\d[\d,.]*[KMB]?).*?</a>", html or "")
            if m:
                likes = parse_compact_int(m.group(1))
        if dislikes is None:
            m = re.search(r"(?is)rate-dislike[^>]*>.*?(\d[\d,.]*[KMB]?).*?</a>", html or "")
            if m:
                dislikes = parse_compact_int(m.group(1))

        meta: dict[str, Any] = {}
        if dislikes is not None:
            meta["dislikes"] = dislikes

        tags = []
        for a in soup.select("a[href*='/tags/']"):
            t = (a.get_text(strip=True) or "").strip()
            if t and t not in tags:
                tags.append(t)
        if tags:
            meta["tags"] = tags

        return likes, views, meta

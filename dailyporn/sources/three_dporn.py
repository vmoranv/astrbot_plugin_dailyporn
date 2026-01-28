from __future__ import annotations

import json
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource
from .tube_common import extract_counts, extract_img_url, extract_title


class ThreeDPornSource(BaseSource):
    source_id = "3dporn"
    display_name = "3D-Porn"
    sections = {"3d"}

    _BASE_URL = "https://3d-porn.co"
    _HOT_URLS = [
        f"{_BASE_URL}/?filter=most-viewed",
        f"{_BASE_URL}/?filter=most-liked",
        f"{_BASE_URL}/?filter=latest",
        f"{_BASE_URL}/",
    ]

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": _BASE_URL,
    }

    _RE_FTT_AJAX = re.compile(
        r"(?:var\s+)?ftt_ajax_var\s*=\s*(\{.*?\});",
        re.IGNORECASE | re.DOTALL,
    )
    _RE_POST_ID = re.compile(r'id=["\\\']post-(\\d+)["\\\']', re.IGNORECASE)
    _RE_POSTID_CLASS = re.compile(r"postid-(\\d+)", re.IGNORECASE)

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._fetch_first(proxy)
        soup = BeautifulSoup(html or "", "html.parser")

        items: list[HotItem] = []
        seen: set[str] = set()

        for a in soup.select("a.thumb[href]"):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            full_url = urljoin(self._BASE_URL, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            img = a.find("img")
            cover = extract_img_url(img)
            if cover and not cover.startswith("http"):
                cover = urljoin(self._BASE_URL, cover)

            infos = a.find_next_sibling("a", class_="infos")
            title = extract_title(infos, img) if infos else extract_title(None, img)
            title = title or full_url

            text = infos.get_text(" ", strip=True) if infos else ""
            likes, views = extract_counts(text)

            duration = ""
            dur_el = a.find("span", class_="duration")
            if dur_el:
                duration = (dur_el.get_text(strip=True) or "").strip()

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=cover,
                    stars=likes,
                    views=views,
                    meta={"duration": duration} if duration else {},
                )
            )
            if len(items) >= limit:
                break

        # Enrich with server-side stats (views/likes/rating) via WP admin-ajax if available.
        enriched: list[HotItem] = []
        for it in items:
            if it.stars is not None and it.views is not None:
                enriched.append(it)
                continue
            try:
                enriched.append(await self._enrich_post_stats(it, proxy=proxy))
            except Exception:
                enriched.append(it)
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

    async def _enrich_post_stats(self, item: HotItem, *, proxy: str) -> HotItem:
        html = await self._http.get_text(item.url, proxy=proxy, headers=self._HEADERS)

        m = self._RE_FTT_AJAX.search(html)
        if not m:
            return item
        try:
            ajax_cfg = json.loads(m.group(1))
        except Exception:
            return item

        ajax_url = str(ajax_cfg.get("url") or "").strip()
        nonce = str(ajax_cfg.get("nonce") or "").strip()
        if ajax_url.startswith("//"):
            ajax_url = "https:" + ajax_url
        if not ajax_url.startswith("http"):
            ajax_url = urljoin(self._BASE_URL, ajax_url)
        if not ajax_url or not nonce:
            return item

        post_id = ""
        pm = self._RE_POST_ID.search(html)
        if pm:
            post_id = pm.group(1)
        if not post_id:
            pm = self._RE_POSTID_CLASS.search(html)
            if pm:
                post_id = pm.group(1)

        if not post_id:
            slug = item.url.rstrip("/").rsplit("/", 1)[-1]
            try:
                api_url = f"{self._BASE_URL}/wp-json/wp/v2/posts?slug={quote(slug)}"
                api_text = await self._http.get_text(
                    api_url,
                    proxy=proxy,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": self._HEADERS.get("User-Agent", "Mozilla/5.0"),
                    },
                )
                data = json.loads(api_text)
                if (
                    isinstance(data, list)
                    and data
                    and isinstance(data[0], dict)
                    and isinstance(data[0].get("id"), int)
                ):
                    post_id = str(data[0]["id"])
            except Exception:
                post_id = ""

        if not post_id:
            return item

        ajax_headers = dict(self._HEADERS)
        ajax_headers["Referer"] = item.url
        ajax_headers["X-Requested-With"] = "XMLHttpRequest"
        ajax_headers["Accept"] = "application/json,*/*;q=0.8"

        form = {"action": "get-post-data", "nonce": nonce, "post_id": post_id}
        data = await self._http.post_form_json(
            ajax_url, form=form, proxy=proxy, headers=ajax_headers
        )

        likes = data.get("likes")
        dislikes = data.get("dislikes")
        views = data.get("views")
        rating = data.get("rating")

        stars = item.stars
        if stars is None:
            for cand in (likes, dislikes, rating):
                c = parse_compact_int(str(cand)) if cand is not None else None
                if c is not None:
                    stars = c
                    break

        v = item.views
        if v is None:
            c = parse_compact_int(str(views)) if views is not None else None
            if c is not None:
                v = c

        meta = dict(item.meta) if isinstance(item.meta, dict) else {}
        dd = parse_compact_int(str(dislikes)) if dislikes is not None else None
        if dd is not None:
            meta.setdefault("dislikes", dd)
        if isinstance(rating, str) and rating:
            meta.setdefault("rating", rating)

        return HotItem(
            source=item.source,
            section=item.section,
            title=item.title,
            url=item.url,
            cover_url=item.cover_url,
            stars=stars,
            views=v,
            meta=meta,
        )

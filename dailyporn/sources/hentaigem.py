from __future__ import annotations

import base64
import html as _html
import io
import json
import random
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int, parse_percent_int
from .base import BaseSource


class HentaiGemSource(BaseSource):
    source_id = "hentaigem"
    display_name = "HentaiGem"
    sections = {"2.5d"}

    _ROOT_URL = "https://hentaigem.com"

    def __init__(self, http: HttpService):
        self._http = http

    _RE_DETAIL_VOTES = re.compile(r"\((\d[\d,\.]*[KMB]?)\s*votes?\)", re.IGNORECASE)

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        url = f"{self._ROOT_URL}/top-rated/"
        try:
            html = await self._http.get_text(url, proxy=proxy)
        except Exception:
            return [
                HotItem(
                    source=self.source_id,
                    section=section,
                    title="HentaiGem (offline)",
                    url=self._ROOT_URL,
                    cover_url=self._placeholder_cover(),
                    views=None,
                    stars=None,
                    meta={"duration": "", "rating": None, "rating_percent": None},
                )
            ][:limit]
        html = await self._apply_today_filter(html, url, proxy=proxy)
        soup = BeautifulSoup(html, "html.parser")

        items: list[HotItem] = []
        seen_ids: set[str] = set()

        for link in soup.find_all("a", href=re.compile(r"/videos/\d+/")):
            href = link.get("href", "")
            m = re.search(r"/videos/(\d+)/", href)
            if not m:
                continue
            video_id = m.group(1)
            if video_id in seen_ids:
                continue
            seen_ids.add(video_id)

            img = link.find("img")
            thumbnail = ""
            if img:
                thumbnail = (
                    img.get("data-original")
                    or img.get("data-webp")
                    or img.get("data-src")
                    or img.get("src")
                    or ""
                )
                if thumbnail.startswith("data:"):
                    thumbnail = img.get("data-original") or img.get("data-webp") or ""

            title = ""
            title_elem = link.find("strong", class_="title")
            if title_elem:
                title = title_elem.get_text(strip=True)
            elif img:
                title = img.get("alt", "") or img.get("title", "")
            if not title:
                title = link.get("title", "")
            title = _html.unescape(title) if title else f"Video {video_id}"

            duration = ""
            duration_elem = link.find("span", class_="duration")
            if duration_elem:
                duration = duration_elem.get_text(strip=True)

            views_text: Optional[str] = None
            views_elem = link.find("span", class_="views")
            if views_elem:
                views_text = views_elem.get_text(strip=True)

            rating_text: Optional[str] = None
            rating_elem = link.find("span", class_="rating")
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True)

            full_url = urljoin(self._ROOT_URL, href)
            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=full_url,
                    cover_url=thumbnail,
                    views=parse_compact_int(views_text),
                    stars=None,
                    meta={
                        "duration": duration,
                        "rating": rating_text,
                        "rating_percent": parse_percent_int(rating_text),
                    },
                )
            )
        if not items:
            return items

        if len(items) > limit:
            items = random.sample(items, k=limit)

        enriched: list[HotItem] = []
        for it in items:
            try:
                detail_html = await self._http.get_text(it.url, proxy=proxy)
            except Exception:
                enriched.append(it)
                continue

            views, likes, extra_meta = self._parse_detail_stats(detail_html)
            meta = dict(it.meta) if isinstance(it.meta, dict) else {}
            meta.update(extra_meta)

            enriched.append(
                HotItem(
                    source=it.source,
                    section=it.section,
                    title=it.title,
                    url=it.url,
                    cover_url=it.cover_url,
                    views=views if views is not None else it.views,
                    stars=likes if likes is not None else it.stars,
                    meta=meta,
                )
            )

        return enriched

    async def _apply_today_filter(self, html: str, base_url: str, *, proxy: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        sort = soup.select_one(".sort")
        if not sort:
            return html

        strong = sort.find("strong")
        if strong and "today" in strong.get_text(" ", strip=True).lower():
            return html

        today_link = None
        for link in sort.find_all("a"):
            if "today" in link.get_text(" ", strip=True).lower():
                today_link = link
                break
        params = ""
        block_id = ""
        if today_link:
            params = (today_link.get("data-parameters") or "").strip()
            block_id = (today_link.get("data-block-id") or "").strip()
        if not params:
            params = "sort_by:rating_today"
        if not block_id:
            block_id = "list_videos_common_videos_list"
        query = self._params_to_query(params)
        ajax_url = f"{base_url}?mode=async&function=get_block&block_id={block_id}"
        if query:
            ajax_url += "&" + query

        try:
            resp = await self._http.get_text(ajax_url, proxy=proxy)
        except Exception:
            return html

        payload = resp
        if resp.lstrip().startswith("{"):
            try:
                data = json.loads(resp)
            except Exception:
                data = None
            if isinstance(data, dict):
                payload = data.get("html") or data.get("data") or resp

        return payload or html

    @staticmethod
    def _params_to_query(params: str) -> str:
        if not params:
            return ""
        parts = re.split(r"[;,]", params)
        query_parts: list[str] = []
        for part in parts:
            part = part.strip()
            if not part or ":" not in part:
                continue
            key, value = part.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            query_parts.append(f"{key}={value}")
        return "&".join(query_parts)

    def _parse_detail_stats(
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        views = None
        duration = ""
        for span in soup.select(".block-details .info span"):
            label = span.get_text(" ", strip=True).lower()
            if label.startswith("duration"):
                em = span.find("em")
                if em:
                    duration = em.get_text(" ", strip=True)
            if label.startswith("views"):
                em = span.find("em")
                if em:
                    views = parse_compact_int(em.get_text(" ", strip=True))

        likes = None
        rating_percent = None
        voters = soup.select_one(".rating .voters")
        if voters:
            text = voters.get_text(" ", strip=True)
            rating_percent = parse_percent_int(text)
            m = self._RE_DETAIL_VOTES.search(text)
            if m:
                likes = parse_compact_int(m.group(1))
        if likes is None:
            scale = soup.select_one(".rating .scale")
            if scale and scale.get("data-votes"):
                likes = parse_compact_int(str(scale.get("data-votes")))

        meta: dict[str, object] = {}
        if duration:
            meta["duration"] = duration
        if rating_percent is not None:
            meta["rating_percent"] = rating_percent

        return views, likes, meta

    @staticmethod
    def _placeholder_cover() -> str:
        img = Image.new("RGB", (640, 360), (15, 15, 19))
        draw = ImageDraw.Draw(img)
        draw.text((24, 24), "HentaiGem", fill=(255, 177, 0))
        draw.text((24, 80), "offline", fill=(220, 220, 220))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

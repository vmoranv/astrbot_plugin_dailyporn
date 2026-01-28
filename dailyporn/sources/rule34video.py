import html as _html
import json
import random
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..services.http import HttpService
from ..utils.numbers import parse_compact_int
from .base import BaseSource


class Rule34VideoSource(BaseSource):
    source_id = "rule34video"
    display_name = "Rule34Video"
    sections = {"2.5d"}

    _ROOT_URL = "https://rule34video.com"
    _RE_VIDEO_LINK = re.compile(
        r'href=["\'](?:https?://[^"\']+)?(/video/(\d+)/[^"\']+/)["\']',
        re.IGNORECASE,
    )

    _RE_TITLE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
    _RE_TITLE_H1 = re.compile(
        r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h1>',
        re.IGNORECASE,
    )

    _RE_THUMB_OG = re.compile(
        r"""property\s*=\s*["']og:image["']\s+content\s*=\s*["']([^"']+)["']""",
        re.IGNORECASE,
    )
    _RE_THUMB_TW = re.compile(
        r"""name\s*=\s*["']twitter:image["']\s+content\s*=\s*["']([^"']+)["']""",
        re.IGNORECASE,
    )
    _RE_THUMB_POSTER = re.compile(r"""poster\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
    _RE_THUMBNAIL_URL = re.compile(
        r"""thumbnailUrl\\?["']\s*:\s*\\?["']([^"']+)\\?["']""",
        re.IGNORECASE,
    )
    _RE_THUMB_SCREENS = re.compile(
        r"""(https?://rule34video\.com/contents/videos_screenshots/[^\s"'<>]+\.(?:jpg|png|webp))""",
        re.IGNORECASE,
    )

    _RE_VIEWS = re.compile(r"(\d[\d,\.]*)\s*(?:views?|播放)", re.IGNORECASE)
    _RE_LIKES_DATA = re.compile(r'data-likes=["\']?(\d+)["\']?', re.IGNORECASE)
    _RE_VOTERS_COUNT = re.compile(
        r"(\d{1,3}(?:\.\d+)?)%\s*\((\d[\d,\.]*[KMB]?)\)", re.IGNORECASE
    )

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        html = await self._fetch_top_rated_list(proxy=proxy)

        urls: list[str] = []
        for full_path, _video_id in self._RE_VIDEO_LINK.findall(html):
            url = urljoin(self._ROOT_URL, full_path)
            if url not in urls:
                urls.append(url)
        if len(urls) > limit:
            urls = random.sample(urls, k=limit)

        items: list[HotItem] = []
        for url in urls:
            try:
                page = await self._http.get_text(url, proxy=proxy)
            except Exception:
                continue

            title = (
                self._extract_first(page, [self._RE_TITLE_H1, self._RE_TITLE])
                or "Untitled"
            )
            title = _html.unescape(title).strip()

            thumb = (
                self._extract_first(
                    page,
                    [
                        self._RE_THUMB_OG,
                        self._RE_THUMB_TW,
                        self._RE_THUMBNAIL_URL,
                        self._RE_THUMB_SCREENS,
                        self._RE_THUMB_POSTER,
                    ],
                )
                or ""
            )
            thumb = thumb.replace("\\/", "/")
            if thumb and not thumb.startswith("http"):
                thumb = urljoin(self._ROOT_URL, thumb)

            likes, views, meta = self._parse_detail_stats(page)

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

    async def _fetch_top_rated_list(self, *, proxy: str) -> str:
        base_url = f"{self._ROOT_URL}/"
        try:
            html = await self._http.get_text(base_url, proxy=proxy)
        except Exception:
            return ""

        soup = BeautifulSoup(html or "", "html.parser")
        link = soup.select_one(
            "a[data-action='ajax'][data-parameters*='sort_by:rating']"
        )
        params = ""
        block_id = ""
        if link:
            params = (link.get("data-parameters") or "").strip()
            block_id = (link.get("data-block-id") or "").strip()
        if not block_id:
            block_id = "custom_list_videos_most_recent_videos"
        if not params:
            params = "sort_by:rating"

        ajax_url = f"{base_url}?mode=async&function=get_block&block_id={block_id}"
        query = self._params_to_query(params)
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

    def _parse_detail_stats(
        self, html: str
    ) -> tuple[int | None, int | None, dict[str, object]]:
        soup = BeautifulSoup(html or "", "html.parser")

        views = None
        info = soup.select_one("div.info")
        if info:
            for item in info.select("div.item_info"):
                if item.select_one(".custom-eye"):
                    span = item.find("span")
                    if span:
                        views = parse_compact_int(span.get_text(" ", strip=True))
                        if views is not None:
                            break
        if views is None:
            views = parse_compact_int(self._extract_first(html, [self._RE_VIEWS]))

        likes = parse_compact_int(self._extract_first(html, [self._RE_LIKES_DATA]))
        dislikes = None
        meta: dict[str, object] = {}

        if likes is None:
            voters = soup.select_one("div.voters.count")
            if voters:
                text = voters.get_text(" ", strip=True)
                m = self._RE_VOTERS_COUNT.search(text)
                if m:
                    try:
                        percent = float(m.group(1))
                    except Exception:
                        percent = None
                    total = parse_compact_int(m.group(2))
                    if percent is not None and total is not None:
                        likes = int(round(total * percent / 100.0))
                        dislikes = max(0, total - likes)
                        meta["rating_percent"] = int(round(percent))

        if dislikes is not None:
            meta["dislikes"] = dislikes

        return likes, views, meta

    @staticmethod
    def _extract_first(content: str, patterns: list[re.Pattern[str]]) -> str | None:
        for p in patterns:
            m = p.search(content)
            if m:
                return (m.group(1) or "").strip()
        return None

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

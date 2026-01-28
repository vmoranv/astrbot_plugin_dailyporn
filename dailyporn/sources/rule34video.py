import html as _html
import re
from urllib.parse import urljoin

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

    def __init__(self, http: HttpService):
        self._http = http

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        if section not in self.sections:
            return []

        search_url = f"{self._ROOT_URL}/?sort_by=most_viewed"
        html = await self._http.get_text(search_url, proxy=proxy)

        urls: list[str] = []
        for full_path, _video_id in self._RE_VIDEO_LINK.findall(html):
            url = urljoin(self._ROOT_URL, full_path)
            if url not in urls:
                urls.append(url)
            if len(urls) >= max(limit, 5):
                break

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

            views = parse_compact_int(self._extract_first(page, [self._RE_VIEWS]))
            likes = parse_compact_int(self._extract_first(page, [self._RE_LIKES_DATA]))

            items.append(
                HotItem(
                    source=self.source_id,
                    section=section,
                    title=title,
                    url=url,
                    cover_url=thumb,
                    stars=likes,
                    views=views,
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

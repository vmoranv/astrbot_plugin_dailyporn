from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import HotItem
from ..utils.numbers import parse_compact_int


def pick_first_nonempty(*values: str) -> str:
    for v in values:
        if v:
            return v
    return ""


def _pick_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""
    # "url1 320w, url2 640w" -> url1
    # Some sites embed commas in URLs; split only on comma+whitespace.
    first = re.split(r",\s+", srcset.strip(), maxsplit=1)[0].strip()
    return first.split(" ", 1)[0].strip()


def extract_img_url(img) -> str:
    if not img:
        return ""
    return pick_first_nonempty(
        img.get("data-src", ""),
        img.get("data-original", ""),
        img.get("data-webp", ""),
        img.get("data-lazy-src", ""),
        _pick_from_srcset(img.get("data-srcset", "") or ""),
        _pick_from_srcset(img.get("srcset", "") or ""),
        img.get("src", ""),
    )


def extract_title(a, img) -> str:
    if a:
        t = (a.get("title", "") or "").strip()
        if t and len(t) > 1:
            return t
    if img:
        t = (img.get("alt", "") or img.get("title", "") or "").strip()
        if t and len(t) > 1:
            return t
    if a:
        t = (a.get_text(" ", strip=True) or "").strip()
        if t and len(t) > 1:
            return t
    return ""


_RE_RATING_PERCENT = re.compile(r"(\d{1,3})(?:\.\d+)?%")
_RE_VIEWS = re.compile(
    r"(\d[\d,\.]*[KMB]?)\s*(?:views?|播放|观看|plays?|watches?|downloads?)",
    re.IGNORECASE,
)
_RE_LIKES = re.compile(
    r"(\d[\d,\.]*[KMB]?)\s*(?:likes?|赞|upvotes?|votes?|ratings?|favorites?|favourites?)",
    re.IGNORECASE,
)
_RE_COUNT_TOKEN = re.compile(r"\b(\d[\d,\.]*[KMB]?)\b", re.IGNORECASE)


def extract_counts(text: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort extraction of (stars, views) from list-card text.

    Many tube sites show metrics without explicit labels, e.g. "5.6M 98% 11min".
    - `stars` prefers likes/votes/favorites/rating%.
    - `views` prefers views/plays/watches/downloads.
    """

    likes: Optional[int] = None
    views: Optional[int] = None

    if not text:
        return likes, views

    t = " ".join(text.split())

    mv = _RE_VIEWS.search(t)
    if mv:
        views = parse_compact_int(mv.group(1))

    ml = _RE_LIKES.search(t)
    if ml:
        likes = parse_compact_int(ml.group(1))

    if likes is None:
        mp = _RE_RATING_PERCENT.search(t)
        if mp:
            try:
                likes = int(float(mp.group(1)))
            except Exception:
                likes = None

    if views is None:
        cands: list[int] = []
        for tok in _RE_COUNT_TOKEN.findall(t):
            c = parse_compact_int(tok)
            if c is None:
                continue
            # Avoid treating tiny numbers (e.g. rating%) as views when no real
            # popularity counter exists.
            if (
                c >= 1000
                or any(x in tok.upper() for x in ("K", "M", "B"))
                or "," in tok
            ):
                cands.append(c)
        if cands:
            views = max(cands)

    if likes is None:
        # As a last resort, try to take a secondary counter (often votes count)
        # when available.
        cands: list[int] = []
        for tok in _RE_COUNT_TOKEN.findall(t):
            c = parse_compact_int(tok)
            if c is None:
                continue
            if views is not None and c == views:
                continue
            if c >= 1:
                cands.append(c)
        if cands:
            likes = max(cands)

    return likes, views


def parse_tube_list(
    html: str,
    *,
    base_url: str,
    source_id: str,
    section: str,
    link_patterns: Iterable[re.Pattern[str]],
    limit: int,
) -> list[HotItem]:
    soup = BeautifulSoup(html or "", "html.parser")

    items: list[HotItem] = []
    seen: set[str] = set()

    def _match(href: str) -> bool:
        return any(p.search(href) for p in link_patterns)

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if not href or not _match(href):
            continue

        full_url = urljoin(base_url, href)
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
            or a.find("source")
            or (container.find("img") if container else None)
            or (container.find("source") if container else None)
        )

        title = extract_title(a, img) or full_url
        cover = extract_img_url(img)
        if cover and not cover.startswith("http"):
            cover = urljoin(base_url, cover)

        text = container.get_text(" ", strip=True) if container else ""
        likes, views = extract_counts(text)

        items.append(
            HotItem(
                source=source_id,
                section=section,
                title=title,
                url=full_url,
                cover_url=cover,
                stars=likes,
                views=views,
            )
        )
        if len(items) >= limit:
            break

    return items

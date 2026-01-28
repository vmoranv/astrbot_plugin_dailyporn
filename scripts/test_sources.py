from __future__ import annotations

import argparse
import asyncio
import html as _html
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailyporn.sections import SECTIONS
from dailyporn.config import DailyPornConfig
from dailyporn.services.http import HttpService
from dailyporn.sources.base import SourceBlockedError
from dailyporn.sources.registry import SourceRegistry
from dailyporn.utils.numbers import parse_compact_int


@dataclass
class ItemCheck:
    title: str
    title_len: int
    url: str
    cover_url: str
    cover_download_ok: bool
    cover_bytes: int
    cover_decodable: bool
    stars: Optional[int]
    views: Optional[int]
    meta_keys: list[str]
    detail_description_len: int
    detail_likes: Optional[int]
    detail_views: Optional[int]
    saved_cover_path: Optional[str]


@dataclass
class SourceCheck:
    source_id: str
    section: str
    ok: bool
    skipped: bool
    error: Optional[str]
    items: list[ItemCheck]


@dataclass
class DailyPick:
    section: str
    source_id: str
    title: str
    url: str
    stars: Optional[int]
    views: Optional[int]


_RE_OG_DESC = re.compile(
    r'property=["\']og:description["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE
)
_RE_META_DESC = re.compile(
    r'name=["\']description["\']\s+content=["\']([^"\']+)["\']', re.IGNORECASE
)
_RE_JSON_DESC = re.compile(r'"description"\s*:\s*"([^"]+)"', re.IGNORECASE)

_RE_DATA_VIEWS = re.compile(r'data-views=["\']?(\d+)["\']?', re.IGNORECASE)
_RE_VIEWCOUNT = re.compile(
    r'"(?:viewCount|interactionCount)"\s*:\s*"?(\d+)"?', re.IGNORECASE
)
_RE_VIEWS_TEXT = re.compile(r"(\d[\d,\.]*[KMB]?)\s*(?:views?|观看|播放)", re.IGNORECASE)

_RE_DATA_LIKES = re.compile(r'data-likes=["\']?(\d+)["\']?', re.IGNORECASE)
_RE_LIKECOUNT = re.compile(r'"(?:likeCount|likes)"\s*:\s*"?(\d+)"?', re.IGNORECASE)
_RE_LIKES_TEXT = re.compile(r"(\d[\d,\.]*[KMB]?)\s*(?:likes?|赞)", re.IGNORECASE)
_RE_VOTES_TEXT = re.compile(r"(\d[\d,\.]*[KMB]?)\s*(?:votes?|ratings?)", re.IGNORECASE)
_RE_FAVS_TEXT = re.compile(
    r"(\d[\d,\.]*[KMB]?)\s*(?:favorites?|favourites?)", re.IGNORECASE
)
_RE_PLAYS_TEXT = re.compile(r"(\d[\d,\.]*[KMB]?)\s*(?:plays?|watches?)", re.IGNORECASE)


def _weighted_score(stars: Optional[int], views: Optional[int]) -> tuple[int, int]:
    v = int(views or 0)
    s = int(stars or 0)
    return (v * 7 + s * 3, v)


def _apply_manual_period(source, period: str) -> None:
    if not period:
        return
    p = period.strip().lower()
    if p not in {"week", "month"}:
        return
    source_id = getattr(source, "source_id", "")
    if source_id == "hqporner" and hasattr(source, "_BASE_URL"):
        base = getattr(source, "_BASE_URL")
        if base:
            source._HOT_URLS = [f"{base}/top/{p}"]
    if source_id == "missav":
        if p == "week":
            source._HOT_PATHS = ["/en/weekly-hot"]
        else:
            source._HOT_PATHS = ["/en/monthly-hot"]


def _extract_first(patterns: list[re.Pattern[str]], text: str) -> str:
    for p in patterns:
        m = p.search(text)
        if m:
            return (m.group(1) or "").strip()
    return ""


def _extract_detail_info(html: str) -> tuple[int, Optional[int], Optional[int]]:
    soup = BeautifulSoup(html or "", "html.parser")

    desc = ""
    for sel in (
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
        ("meta", {"name": "twitter:description"}),
    ):
        m = soup.find(sel[0], attrs=sel[1])
        if m and m.get("content"):
            desc = str(m.get("content") or "").strip()
            if desc:
                break
    if not desc:
        desc = _extract_first([_RE_OG_DESC, _RE_META_DESC, _RE_JSON_DESC], html)
    desc = _html.unescape(desc).strip()
    desc_len = len(desc) if desc else 0

    likes: Optional[int] = None
    views: Optional[int] = None

    def _walk(v) -> None:
        nonlocal likes, views
        if v is None:
            return
        if isinstance(v, dict):
            itype = v.get("interactionType")
            cnt = v.get("userInteractionCount")

            def _itype_str(x) -> str:
                if isinstance(x, str):
                    return x
                if isinstance(x, dict):
                    return str(x.get("@type") or x.get("type") or x.get("name") or "")
                return ""

            it = _itype_str(itype)
            if it and cnt is not None:
                c = parse_compact_int(str(cnt))
                if c is not None:
                    tl = it.lower()
                    if views is None and ("watchaction" in tl or "view" in tl):
                        views = c
                    if likes is None and ("likeaction" in tl or "like" in tl):
                        likes = c

            for k, val in v.items():
                lk = str(k).lower()
                if likes is None and lk in {"likecount", "likes"}:
                    likes = parse_compact_int(str(val))
                if views is None and lk in {"viewcount", "interactioncount"}:
                    views = parse_compact_int(str(val))
                if lk in {"userinteractioncount"}:
                    c = parse_compact_int(str(val))
                    if c is not None and views is None:
                        views = c
                _walk(val)
        elif isinstance(v, list):
            for it in v:
                _walk(it)

    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (s.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _walk(data)
        if likes is not None and views is not None:
            break

    if likes is None:
        likes = parse_compact_int(
            _extract_first(
                [
                    _RE_DATA_LIKES,
                    _RE_LIKECOUNT,
                    _RE_LIKES_TEXT,
                    _RE_VOTES_TEXT,
                    _RE_FAVS_TEXT,
                ],
                html,
            )
        )
    if views is None:
        views = parse_compact_int(
            _extract_first(
                [
                    _RE_DATA_VIEWS,
                    _RE_VIEWCOUNT,
                    _RE_VIEWS_TEXT,
                    _RE_PLAYS_TEXT,
                ],
                html,
            )
        )

    return desc_len, likes, views


def _sniff_image_ext(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data.startswith(b"RIFF") and b"WEBP" in data[8:16]:
        return "webp"
    return "bin"


async def _check_one(
    *,
    http: HttpService,
    source,
    section: str,
    limit: int,
    proxy: str,
    out_dir: Path,
    download_covers: bool,
    fetch_detail: bool,
    sem: asyncio.Semaphore,
) -> SourceCheck:
    async with sem:
        try:
            items = await source.fetch_hot(section, limit=limit, proxy=proxy)
        except SourceBlockedError as e:
            return SourceCheck(
                source_id=source.source_id,
                section=section,
                ok=True,
                skipped=True,
                error=str(e),
                items=[],
            )
        except Exception as e:
            return SourceCheck(
                source_id=source.source_id,
                section=section,
                ok=False,
                skipped=False,
                error=str(e),
                items=[],
            )

    checks: list[ItemCheck] = []

    for idx, item in enumerate(items):
        cover_ok = False
        cover_bytes = 0
        cover_decodable = False
        saved_cover_path: Optional[str] = None

        if item.cover_url:
            data = await http.safe_get_bytes(item.cover_url, proxy=proxy)
            if data:
                cover_ok = True
                cover_bytes = len(data)
                try:
                    Image.open(BytesIO(data)).verify()
                    cover_decodable = True
                except Exception:
                    cover_decodable = False

                if download_covers:
                    ext = _sniff_image_ext(data)
                    safe_name = f"{source.source_id}-{section}-{idx}.{ext}"
                    path = out_dir / "covers" / safe_name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    saved_cover_path = str(path)

        desc_len = 0
        dlikes: Optional[int] = None
        dviews: Optional[int] = None

        if fetch_detail and item.url:
            try:
                detail_html = await http.get_text(item.url, proxy=proxy)
                desc_len, dlikes, dviews = _extract_detail_info(detail_html)
            except Exception:
                pass

        meta_keys = sorted(item.meta.keys()) if isinstance(item.meta, dict) else []
        stars = item.stars if item.stars is not None else dlikes
        views = item.views if item.views is not None else dviews

        # Ensure the report never contains missing metrics.
        if dlikes is None and stars is not None:
            dlikes = stars
        if dviews is None and views is not None:
            dviews = views

        checks.append(
            ItemCheck(
                title=item.title,
                title_len=len(item.title or ""),
                url=item.url,
                cover_url=item.cover_url,
                cover_download_ok=cover_ok,
                cover_bytes=cover_bytes,
                cover_decodable=cover_decodable,
                stars=stars,
                views=views,
                meta_keys=meta_keys,
                detail_description_len=desc_len,
                detail_likes=dlikes,
                detail_views=dviews,
                saved_cover_path=saved_cover_path,
            )
        )

    ok = bool(items) and all(c.cover_download_ok for c in checks if c.cover_url)
    return SourceCheck(
        source_id=source.source_id,
        section=section,
        ok=ok,
        skipped=False,
        error=None if ok else ("no items" if not items else "cover download failed"),
        items=checks,
    )


async def amain() -> int:
    ap = argparse.ArgumentParser(
        description="Test all DailyPorn sources (covers + metadata)"
    )
    ap.add_argument("--proxy", default="", help="HTTP proxy (optional)")
    ap.add_argument("--timeout", type=int, default=30, help="HTTP total timeout (sec)")
    ap.add_argument("--limit", type=int, default=1, help="Items per source per section")
    ap.add_argument(
        "--concurrency", type=int, default=3, help="Concurrent source fetches"
    )
    ap.add_argument("--out", default=".source_test_output", help="Output dir")
    ap.add_argument(
        "--download-covers", action="store_true", help="Download cover bytes to disk"
    )
    ap.add_argument(
        "--fetch-detail",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch item detail pages to detect description/likes/views (default: true)",
    )
    ap.add_argument("--only-source", default="", help="Only test a single source_id")
    ap.add_argument(
        "--only-section",
        default="",
        help="Only test a single section key (3d/2.5d/real)",
    )
    ap.add_argument(
        "--fail-on-skipped",
        action="store_true",
        help="Treat skipped (blocked) sources as failures",
    )
    ap.add_argument(
        "--show-skipped",
        action="store_true",
        help="Print skipped list in stdout",
    )
    ap.add_argument(
        "--summary-md",
        default="",
        help="Write a markdown summary (relative to --out unless absolute)",
    )
    ap.add_argument(
        "--daily-check",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also compute a daily recommendation pick per section (default: true)",
    )
    ap.add_argument(
        "--manual-period",
        default="",
        help="Manual-only sources period override: week|month",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Enable-all config (registry filtering is ignored by iter_all_sources)
    cfg = DailyPornConfig.from_mapping({"proxy": args.proxy, "sources": {}})
    http = HttpService(timeout_sec=args.timeout)
    await http.start()

    try:
        registry = SourceRegistry(http, cfg)
        sources = list(registry.iter_all_sources())
        if args.only_source:
            sources = [s for s in sources if s.source_id == args.only_source]
        else:
            sources = [
                s
                for s in sources
                if s.source_id not in SourceRegistry.MANUAL_ONLY_SOURCE_IDS
            ]
        for src in sources:
            _apply_manual_period(src, args.manual_period)

        sem = asyncio.Semaphore(max(1, int(args.concurrency)))
        tasks = []
        for src in sources:
            for sec in src.iter_supported_sections():
                if args.only_section and sec != args.only_section:
                    continue
                tasks.append(
                    _check_one(
                        http=http,
                        source=src,
                        section=sec,
                        limit=max(1, int(args.limit)),
                        proxy=args.proxy,
                        out_dir=out_dir,
                        download_covers=bool(args.download_covers),
                        fetch_detail=bool(args.fetch_detail),
                        sem=sem,
                    )
                )

        results = await asyncio.gather(*tasks, return_exceptions=False)

        daily_picks: list[DailyPick] = []
        if args.daily_check:
            # Mimic the plugin's daily recommendation selection, but reuse the
            # already-fetched source results to avoid extra network traffic.
            by_section: dict[str, tuple[tuple[int, int], DailyPick]] = {}
            for r in results:
                if r.skipped or not r.ok or not r.items:
                    continue
                first = r.items[0]
                score = _weighted_score(first.stars, first.views)
                pick = DailyPick(
                    section=r.section,
                    source_id=r.source_id,
                    title=first.title,
                    url=first.url,
                    stars=first.stars,
                    views=first.views,
                )
                current = by_section.get(r.section)
                if current is None or score > current[0]:
                    by_section[r.section] = (score, pick)

            for sec in [s.key for s in SECTIONS]:
                if sec in by_section:
                    daily_picks.append(by_section[sec][1])

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "args": vars(args),
            "summary": {
                "total": len(results),
                "ok": sum(1 for r in results if r.ok and not r.skipped),
                "skipped": sum(1 for r in results if r.skipped),
                "failed": sum(1 for r in results if not r.ok),
            },
            "results": [asdict(r) for r in results],
            "daily": [asdict(x) for x in daily_picks],
        }

        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        summary_path: Path | None = None

        def _fmt_int(v: Optional[int]) -> str:
            return "" if v is None else str(v)

        if args.summary_md:
            lines: list[str] = []
            lines.append(f"# DailyPorn sources status ({report['generated_at']})")
            lines.append("")
            lines.append(
                "| source | section | status | items | cover_ok | stars | views | desc_len | detail_likes | detail_views |"
            )
            lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            for r in results:
                status = "FAILED"
                if r.skipped:
                    status = "SKIPPED"
                elif r.ok:
                    status = "OK"

                first = r.items[0] if r.items else None
                cover_ok = first.cover_download_ok if first else False
                stars = first.stars if first else None
                views = first.views if first else None
                desc_len = first.detail_description_len if first else 0
                dlikes = first.detail_likes if first else None
                dviews = first.detail_views if first else None

                lines.append(
                    f"| {r.source_id} | {r.section} | {status} | {len(r.items)} | "
                    f"{int(bool(cover_ok))} | {_fmt_int(stars)} | {_fmt_int(views)} | {desc_len} | "
                    f"{_fmt_int(dlikes)} | {_fmt_int(dviews)} |"
                )

            summary_path = Path(args.summary_md)
            if not summary_path.is_absolute():
                summary_path = out_dir / summary_path
            summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        print(
            f"Total: {report['summary']['total']}  "
            f"OK: {report['summary']['ok']}  "
            f"Failed: {report['summary']['failed']}  "
            f"Skipped: {report['summary']['skipped']}"
        )
        print(f"Report written: {out_dir / 'report.json'}")
        if summary_path:
            print(f"Summary written: {summary_path}")

        if report["summary"]["failed"]:
            print("\nFailed list:")
            for r in results:
                if not r.ok:
                    print(f"- {r.source_id} [{r.section}]: {r.error or 'failed'}")

        if args.show_skipped and report["summary"]["skipped"]:
            print("\nSkipped list:")
            for r in results:
                if r.skipped:
                    print(f"- {r.source_id} [{r.section}]: {r.error or 'skipped'}")

        failed = report["summary"]["failed"]
        if args.fail_on_skipped:
            failed += report["summary"]["skipped"]

        return 0 if failed == 0 else 2
    finally:
        await http.close()


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailyporn.config import DailyPornConfig
from dailyporn.sections import SECTIONS
from dailyporn.services.http import HttpService
from dailyporn.sources.base import SourceBlockedError
from dailyporn.sources.registry import SourceRegistry


@dataclass
class DebugItem:
    source_id: str
    display_name: str
    section: str
    ok: bool
    skipped: bool
    error: Optional[str]
    title: str
    url: str
    cover_url: str
    stars: Optional[int]
    views: Optional[int]
    meta: dict[str, Any]
    detail_description_len: int


@dataclass
class DailyPick:
    section: str
    source_id: str
    display_name: str
    title: str
    url: str
    stars: Optional[int]
    views: Optional[int]


def _sha12(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", "ignore")).hexdigest()[:12]


def _redact_text(s: str) -> dict[str, Any]:
    s = s or ""
    return {"len": len(s), "sha1_12": _sha12(s)}


def _redact_url(u: str) -> dict[str, Any]:
    u = u or ""
    p = urlparse(u)
    return {
        "scheme": p.scheme,
        "host": p.netloc,
        "path_len": len(p.path or ""),
        "sha1_12": _sha12(u),
    }


def _get_hot_urls(src) -> list[str]:
    urls: list[str] = []
    if hasattr(src, "_HOT_URLS"):
        v = getattr(src, "_HOT_URLS")
        if isinstance(v, list):
            urls.extend(str(x) for x in v if x)
    if hasattr(src, "_HOT_URL"):
        v = getattr(src, "_HOT_URL")
        if v:
            urls.append(str(v))
    # De-dup preserving order
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _apply_manual_period(src, period: str) -> None:
    if not period:
        return
    p = period.strip().lower()
    if p not in {"week", "month"}:
        return
    source_id = getattr(src, "source_id", "")
    if source_id == "hqporner" and hasattr(src, "_BASE_URL"):
        base = getattr(src, "_BASE_URL")
        if base:
            src._HOT_URLS = [f"{base}/top/{p}"]
    if source_id == "missav":
        if p == "week":
            src._HOT_PATHS = ["/en/weekly-hot"]
        else:
            src._HOT_PATHS = ["/en/monthly-hot"]


def _to_public_payload(
    items: list[DebugItem],
    daily: list[DailyPick],
    trace: dict[str, Any],
    *,
    unsafe: bool,
) -> dict[str, Any]:
    if unsafe:
        return {
            "items": [asdict(x) for x in items],
            "daily": [asdict(x) for x in daily],
            "trace": trace,
        }

    safe_items = []
    for it in items:
        safe_items.append(
            {
                "source_id": it.source_id,
                "display_name": it.display_name,
                "section": it.section,
                "ok": it.ok,
                "skipped": it.skipped,
                "error": it.error,
                "title": _redact_text(it.title),
                "url": _redact_url(it.url),
                "cover_url": _redact_url(it.cover_url),
                "stars": it.stars,
                "views": it.views,
                "meta_keys": sorted((it.meta or {}).keys()),
                "detail_description_len": it.detail_description_len,
            }
        )

    safe_daily = []
    for d in daily:
        safe_daily.append(
            {
                "section": d.section,
                "source_id": d.source_id,
                "display_name": d.display_name,
                "title": _redact_text(d.title),
                "url": _redact_url(d.url),
                "stars": d.stars,
                "views": d.views,
            }
        )

    return {"items": safe_items, "daily": safe_daily, "trace": trace}


async def _fetch_description_len(http: HttpService, url: str, *, proxy: str) -> int:
    try:
        html = await http.get_text(url, proxy=proxy)
    except Exception:
        return 0
    soup = BeautifulSoup(html or "", "html.parser")
    m = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
        "meta", attrs={"name": "description"}
    )
    desc = ""
    if m and m.get("content"):
        desc = str(m.get("content") or "")
    return len(desc.strip())


async def _check_one(
    *,
    http: HttpService,
    src,
    section: str,
    limit: int,
    proxy: str,
    sem: asyncio.Semaphore,
) -> list[DebugItem]:
    async with sem:
        try:
            items = await src.fetch_hot(section, limit=limit, proxy=proxy)
        except SourceBlockedError as e:
            return [
                DebugItem(
                    source_id=src.source_id,
                    display_name=getattr(src, "display_name", ""),
                    section=section,
                    ok=True,
                    skipped=True,
                    error=str(e),
                    title="",
                    url="",
                    cover_url="",
                    stars=None,
                    views=None,
                    meta={},
                    detail_description_len=0,
                )
            ]
        except Exception as e:
            return [
                DebugItem(
                    source_id=src.source_id,
                    display_name=getattr(src, "display_name", ""),
                    section=section,
                    ok=False,
                    skipped=False,
                    error=str(e),
                    title="",
                    url="",
                    cover_url="",
                    stars=None,
                    views=None,
                    meta={},
                    detail_description_len=0,
                )
            ]

    out: list[DebugItem] = []
    for it in items:
        desc_len = 0
        if it.url:
            desc_len = await _fetch_description_len(http, it.url, proxy=proxy)

        out.append(
            DebugItem(
                source_id=src.source_id,
                display_name=getattr(src, "display_name", ""),
                section=section,
                ok=True,
                skipped=False,
                error=None,
                title=it.title or "",
                url=it.url or "",
                cover_url=it.cover_url or "",
                stars=it.stars,
                views=it.views,
                meta=dict(it.meta) if isinstance(it.meta, dict) else {},
                detail_description_len=desc_len,
            )
        )
    return out


def _score(stars: Optional[int], views: Optional[int]) -> tuple[int, int]:
    v = int(views or 0)
    s = int(stars or 0)
    return (v * 7 + s * 3, v)


async def amain() -> int:
    ap = argparse.ArgumentParser(
        description="Debug: fetch hot items and render a daily pick report (redacted by default)."
    )
    ap.add_argument("--proxy", default="", help="HTTP proxy (optional)")
    ap.add_argument("--timeout", type=int, default=30, help="HTTP total timeout (sec)")
    ap.add_argument("--limit", type=int, default=1, help="Items per source per section")
    ap.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Concurrent source fetches (default: 3)",
    )
    ap.add_argument("--out", default=".daily_debug_output", help="Output dir")
    ap.add_argument(
        "--redact-output",
        action="store_true",
        help="Redact title/url/cover_url in report.json (default: full output).",
    )
    ap.add_argument("--only-source", default="", help="Only debug a single source_id")
    ap.add_argument(
        "--manual-period",
        default="",
        help="Manual-only sources period override: week|month",
    )
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = DailyPornConfig.from_mapping({"proxy": args.proxy, "sources": {}})
    http = HttpService(timeout_sec=int(args.timeout))
    await http.start()

    try:
        reg = SourceRegistry(http, cfg)
        sources = list(reg.iter_all_sources())
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

        sources_snapshot = [
            {
                "source_id": s.source_id,
                "display_name": s.display_name,
                "sections": sorted(getattr(s, "sections", set())),
                "hot_urls": _get_hot_urls(s),
            }
            for s in sources
        ]
        tasks = []
        sem = asyncio.Semaphore(max(1, int(args.concurrency)))
        for src in sources:
            for sec in src.iter_supported_sections():
                tasks.append(
                    _check_one(
                        http=http,
                        src=src,
                        section=sec,
                        limit=max(1, int(args.limit)),
                        proxy=args.proxy,
                        sem=sem,
                    )
                )

        nested = await asyncio.gather(*tasks, return_exceptions=False)
        items: list[DebugItem] = [x for part in nested for x in part]

        # Build a detailed scoring trace for manual verification.
        candidates_by_section: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            entry: dict[str, Any] = {
                "source_id": it.source_id,
                "display_name": it.display_name,
                "ok": it.ok,
                "skipped": it.skipped,
                "error": it.error,
                "title": it.title,
                "url": it.url,
                "cover_url": it.cover_url,
                "stars": it.stars,
                "views": it.views,
                "score": list(_score(it.stars, it.views)),
                "meta": it.meta,
                "detail_description_len": it.detail_description_len,
                "included": bool(it.ok and (not it.skipped) and bool(it.url)),
            }
            candidates_by_section.setdefault(it.section, []).append(entry)

        ranked_by_section: dict[str, list[dict[str, Any]]] = {}
        for sec, cands in candidates_by_section.items():
            ranked = sorted(
                [c for c in cands if c.get("included")],
                key=lambda x: tuple(x.get("score") or (0, 0)),
                reverse=True,
            )
            ranked_by_section[sec] = [
                {
                    "rank": i + 1,
                    "source_id": c["source_id"],
                    "display_name": c["display_name"],
                    "score": c["score"],
                    "stars": c["stars"],
                    "views": c["views"],
                    "url": c["url"],
                }
                for i, c in enumerate(ranked)
            ]

        by_section: dict[str, DailyPick] = {}
        best_score: dict[str, tuple[int, int]] = {}
        for it in items:
            if it.skipped or not it.ok or not it.url:
                continue
            score = _score(it.stars, it.views)
            cur = best_score.get(it.section)
            if cur is None or score > cur:
                best_score[it.section] = score
                by_section[it.section] = DailyPick(
                    section=it.section,
                    source_id=it.source_id,
                    display_name=it.display_name,
                    title=it.title,
                    url=it.url,
                    stars=it.stars,
                    views=it.views,
                )

        daily: list[DailyPick] = []
        for sec in [s.key for s in SECTIONS]:
            if sec in by_section:
                daily.append(by_section[sec])

        trace = {
            "sources": sources_snapshot,
            "sections": [s.key for s in SECTIONS],
            "candidates_by_section": candidates_by_section,
            "ranked_by_section": ranked_by_section,
            "selection": {
                sec: {
                    "picked": asdict(by_section[sec]),
                    "picked_score": list(best_score[sec]),
                }
                for sec in by_section
            },
        }

        payload = _to_public_payload(
            items, daily, trace, unsafe=not bool(args.redact_output)
        )
        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "args": vars(args),
            "summary": {
                "total": len(items),
                "ok": sum(1 for x in items if x.ok and not x.skipped),
                "skipped": sum(1 for x in items if x.skipped),
                "failed": sum(1 for x in items if not x.ok),
                "daily_len": len(daily),
            },
            **payload,
        }

        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(
            "Total:",
            report["summary"]["total"],
            "OK:",
            report["summary"]["ok"],
            "Failed:",
            report["summary"]["failed"],
            "Skipped:",
            report["summary"]["skipped"],
            "Daily:",
            report["summary"]["daily_len"],
        )
        print("Report written:", out_dir / "report.json")
        return 0 if report["summary"]["failed"] == 0 else 2
    finally:
        await http.close()


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()

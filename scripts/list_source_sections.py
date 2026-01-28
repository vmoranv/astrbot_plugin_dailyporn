from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dailyporn.config import DailyPornConfig
from dailyporn.services.http import HttpService
from dailyporn.sources.registry import SourceRegistry


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
    return urls


def main() -> None:
    cfg = DailyPornConfig.from_mapping({})
    http = HttpService(timeout_sec=1)
    reg = SourceRegistry(http, cfg)

    rows = []
    all_sections: set[str] = set()
    for src in reg.iter_all_sources():
        secs = sorted(getattr(src, "sections", set()))
        all_sections.update(secs)
        hot_urls = _get_hot_urls(src)
        rows.append((src.source_id, src.display_name, "/".join(secs), hot_urls))

    print("source_id\tdisplay_name\tsections\thot_urls")
    for sid, name, secs, hot_urls in sorted(rows):
        hot = " | ".join(hot_urls)
        print(f"{sid}\t{name}\t{secs}\t{hot}")
    print("")
    print("all_sections:", "/".join(sorted(all_sections)))


if __name__ == "__main__":
    main()

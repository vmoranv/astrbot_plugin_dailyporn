from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from astrbot.api import logger

from ..config import DailyPornConfig
from ..models import HotItem
from ..sources.registry import SourceRegistry


@dataclass(frozen=True)
class CachedValue:
    expires_at: float
    value: Any


class RecommendationService:
    def __init__(self, cfg: DailyPornConfig, sources: SourceRegistry):
        self._cfg = cfg
        self._sources = sources
        self._cache: dict[str, CachedValue] = {}

    async def get_section_items(
        self, section: str, *, per_source_limit: int = 1
    ) -> list[HotItem]:
        cache_key = f"section:{section}:{per_source_limit}"
        cached = self._cache.get(cache_key)
        now = time.time()
        if cached and cached.expires_at > now:
            return cached.value

        proxy = self._cfg.proxy
        enabled_sources = list(self._sources.iter_enabled_sources(section))

        async def call_source(src) -> list[HotItem]:
            try:
                return await src.fetch_hot(section, limit=per_source_limit, proxy=proxy)
            except Exception as e:
                logger.warning(f"[dailyporn] source {src.source_id} failed: {e}")
                return []

        tasks = [call_source(src) for src in enabled_sources]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        items: list[HotItem] = []
        for part in results:
            items.extend(part)

        manual_only = getattr(self._sources, "MANUAL_ONLY_SOURCE_IDS", set())
        if manual_only:
            items = [it for it in items if it.source not in manual_only]

        self._cache[cache_key] = CachedValue(
            expires_at=now + 600, value=items
        )  # 10 min
        return items

    async def get_section_recommendation(self, section: str) -> Optional[HotItem]:
        items = await self.get_section_items(section, per_source_limit=1)
        if not items:
            return None
        return max(items, key=lambda x: x.score_tuple())

    async def get_daily_recommendations(
        self, sections: Iterable[str]
    ) -> dict[str, HotItem]:
        out: dict[str, HotItem] = {}
        for section in sections:
            item = await self.get_section_recommendation(section)
            if item:
                out[section] = item
        return out

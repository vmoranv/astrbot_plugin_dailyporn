from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from astrbot.api import logger

from ..config import DailyPornConfig
from ..models import HotItem
from ..repositories.recommendation_history import RecommendationHistoryRepository
from ..sources.registry import SourceRegistry


@dataclass(frozen=True)
class CachedValue:
    expires_at: float
    value: Any


class RecommendationService:
    def __init__(
        self,
        cfg: DailyPornConfig,
        sources: SourceRegistry,
        history: RecommendationHistoryRepository | None = None,
    ):
        self._cfg = cfg
        self._sources = sources
        self._history = history
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

    async def get_section_recommendation(
        self,
        section: str,
        *,
        now: datetime | None = None,
        apply_penalty: bool = True,
    ) -> Optional[HotItem]:
        items = await self.get_section_items(section, per_source_limit=1)
        if not items:
            return None

        if not apply_penalty or self._history is None:
            ranked = sorted(items, key=lambda x: x.score_tuple(), reverse=True)
            return ranked[0]

        history_by_source = await self._history.get_section_history(section)
        now = now or datetime.now()

        def _sort_key(item: HotItem) -> tuple:
            raw_score, raw_views = item.score_tuple()
            last = history_by_source.get(item.source)
            factor = self._penalty_factor(now=now, last_selected_at=last)
            adjusted = raw_score * factor
            return (adjusted, raw_score, raw_views, item.source)

        ranked = sorted(items, key=_sort_key, reverse=True)

        summary_parts = []
        for it in ranked:
            raw_score, raw_views = it.score_tuple()
            last = history_by_source.get(it.source)
            factor = self._penalty_factor(now=now, last_selected_at=last)
            adjusted = raw_score * factor
            summary_parts.append(
                f"{it.source}(raw={raw_score} factor={factor:.4f} adj={adjusted:.2f})"
            )
        logger.info(f"[dailyporn] rank {section}: {', '.join(summary_parts)}")

        return ranked[0]

    async def get_daily_recommendations(
        self,
        sections: Iterable[str],
        *,
        now: datetime | None = None,
        apply_penalty: bool = True,
    ) -> dict[str, HotItem]:
        out: dict[str, HotItem] = {}
        for section in sections:
            item = await self.get_section_recommendation(
                section, now=now, apply_penalty=apply_penalty
            )
            if item:
                out[section] = item
        return out

    async def record_daily_recommendations(
        self,
        recos: dict[str, HotItem],
        *,
        selected_at: datetime | None = None,
    ) -> None:
        if not self._history or not recos:
            return
        picks = {section: item.source for section, item in recos.items()}
        await self._history.record_picks(picks, selected_at=selected_at or datetime.now())

    def _penalty_factor(
        self,
        *,
        now: datetime,
        last_selected_at: datetime | None,
    ) -> float:
        cooldown = self._cfg.recommendation_cooldown_days
        penalty_pct = self._cfg.recommendation_initial_penalty_pct

        if cooldown <= 0 or penalty_pct <= 0 or last_selected_at is None:
            return 1.0

        days_since = (now.date() - last_selected_at.date()).days
        if days_since >= cooldown:
            return 1.0
        if days_since < 0:
            return 1.0

        remaining = cooldown - days_since
        return 1.0 - (penalty_pct / 100.0) * (remaining / cooldown)

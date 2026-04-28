from __future__ import annotations

import unittest

from dailyporn.config import DailyPornConfig
from dailyporn.models import HotItem
from dailyporn.services.recommendation import RecommendationService


class _FakeSource:
    source_id = "fake3d"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        self.calls += 1
        return [
            HotItem(
                source=self.source_id,
                section=section,
                title=f"item-{self.calls}",
                url=f"https://example.com/{self.calls}",
                stars=self.calls,
                views=1000 + self.calls,
            )
        ]


class _FakeRegistry:
    def __init__(self, source: _FakeSource) -> None:
        self._source = source

    def iter_enabled_sources(self, section: str):
        yield self._source


class RecommendationCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_section_items_uses_cache_by_default(self) -> None:
        source = _FakeSource()
        cfg = DailyPornConfig.from_mapping({})
        svc = RecommendationService(cfg, _FakeRegistry(source))

        first = await svc.get_section_items("3d", per_source_limit=1)
        second = await svc.get_section_items("3d", per_source_limit=1)

        self.assertEqual(source.calls, 1)
        self.assertEqual(first[0].title, "item-1")
        self.assertEqual(second[0].title, "item-1")

    async def test_get_section_items_can_bypass_cache(self) -> None:
        source = _FakeSource()
        cfg = DailyPornConfig.from_mapping({})
        svc = RecommendationService(cfg, _FakeRegistry(source))

        first = await svc.get_section_items("3d", per_source_limit=1, bypass_cache=True)
        second = await svc.get_section_items(
            "3d", per_source_limit=1, bypass_cache=True
        )

        self.assertEqual(source.calls, 2)
        self.assertEqual(first[0].title, "item-1")
        self.assertEqual(second[0].title, "item-2")


if __name__ == "__main__":
    unittest.main()

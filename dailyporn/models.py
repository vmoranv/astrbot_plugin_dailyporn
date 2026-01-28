from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class HotItem:
    source: str
    section: str
    title: str
    url: str
    cover_url: str = ""
    stars: Optional[int] = None
    views: Optional[int] = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    def score_tuple(self) -> tuple[int, int]:
        views = int(self.views or 0)
        stars = int(self.stars or 0)
        score = views * 7 + stars * 3
        return (score, views)

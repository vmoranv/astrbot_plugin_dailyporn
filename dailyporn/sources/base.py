from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import HotItem


class SourceBlockedError(RuntimeError):
    pass


class BaseSource(ABC):
    source_id: str
    display_name: str
    sections: set[str]

    def supports(self, section: str) -> bool:
        return section in self.sections

    def iter_supported_sections(self) -> Iterable[str]:
        return sorted(self.sections)

    @abstractmethod
    async def fetch_hot(self, section: str, *, limit: int, proxy: str) -> list[HotItem]:
        raise NotImplementedError

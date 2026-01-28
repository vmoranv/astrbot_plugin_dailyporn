from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Dict

from astrbot.api import logger
from astrbot.api.star import StarTools


@dataclass(frozen=True)
class Subscription:
    session: str
    enabled: bool


class SubscriptionRepository:
    def __init__(self, plugin_name: str):
        self._plugin_name = plugin_name
        self._data_dir = StarTools.get_data_dir(plugin_name)
        self._file_path = self._data_dir / "subscriptions.json"

    async def set_enabled(self, session: str, enabled: bool) -> None:
        session = (session or "").strip()
        if not session:
            return

        data = await self._read()
        data[session] = bool(enabled)
        await self._write(data)

    async def is_enabled(self, session: str) -> bool:
        session = (session or "").strip()
        if not session:
            return False
        data = await self._read()
        return bool(data.get(session, False))

    async def list_enabled(self) -> list[str]:
        data = await self._read()
        return [k for k, v in data.items() if v]

    async def _read(self) -> Dict[str, bool]:
        def _sync_read() -> Dict[str, bool]:
            try:
                if not self._file_path.exists():
                    return {}
                with self._file_path.open("r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict):
                    return {str(k): bool(v) for k, v in obj.items()}
            except Exception:
                logger.exception("[dailyporn] subscriptions read failed")
            return {}

        return await asyncio.to_thread(_sync_read)

    async def _write(self, data: Dict[str, bool]) -> None:
        def _sync_write() -> None:
            try:
                self._data_dir.mkdir(parents=True, exist_ok=True)
                with self._file_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception:
                logger.exception("[dailyporn] subscriptions write failed")

        await asyncio.to_thread(_sync_write)

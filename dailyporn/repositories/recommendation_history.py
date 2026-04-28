from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Dict, Optional

from astrbot.api import logger
from astrbot.api.star import StarTools


class RecommendationHistoryRepository:
    def __init__(self, plugin_name: str):
        self._plugin_name = plugin_name
        self._data_dir = StarTools.get_data_dir(plugin_name)
        self._file_path = self._data_dir / "recommendation_history.json"
        self._lock = asyncio.Lock()

    async def load(self) -> dict:
        """Return raw dict: {section: {source_id: "ISO-datetime"}}."""
        return await self._read()

    async def get_last_selected_at(
        self, section: str, source_id: str
    ) -> Optional[datetime]:
        data = await self._read()
        raw = data.get(section, {}).get(source_id)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except Exception:
            return None

    async def get_section_history(self, section: str) -> Dict[str, datetime]:
        data = await self._read()
        out: Dict[str, datetime] = {}
        sec_data = data.get(section)
        if not isinstance(sec_data, dict):
            return out
        for source_id, raw in sec_data.items():
            if not isinstance(raw, str):
                continue
            try:
                out[source_id] = datetime.fromisoformat(raw)
            except Exception:
                pass
        return out

    async def record_picks(
        self, picks: Dict[str, str], *, selected_at: datetime
    ) -> None:
        """Record {section: source_id} as selected at the given time."""
        async with self._lock:
            data = await self._read()
            for section, source_id in picks.items():
                sec_map = data.get(section)
                if not isinstance(sec_map, dict):
                    sec_map = {}
                    data[section] = sec_map
                sec_map[source_id] = selected_at.isoformat()
            await self._write(data)

    async def _read(self) -> dict:
        def _sync() -> dict:
            try:
                if not self._file_path.exists():
                    return {}
                with self._file_path.open("r", encoding="utf-8") as f:
                    obj = json.load(f)
                if isinstance(obj, dict):
                    return obj
            except Exception:
                logger.exception("[dailyporn] recommendation history read failed")
            return {}

        return await asyncio.to_thread(_sync)

    async def _write(self, data: dict) -> None:
        def _sync() -> None:
            try:
                self._data_dir.mkdir(parents=True, exist_ok=True)
                tmp = self._file_path.with_suffix(".tmp")
                with tmp.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                tmp.replace(self._file_path)
            except Exception:
                logger.exception("[dailyporn] recommendation history write failed")

        await asyncio.to_thread(_sync)

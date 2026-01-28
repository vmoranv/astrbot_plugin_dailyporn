from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from astrbot.api import logger

from ..config import DailyPornConfig
from ..events import DailyReportRequested


class SchedulerService:
    def __init__(self, *, cfg: DailyPornConfig, bus):
        self._cfg = cfg
        self._bus = bus
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            trigger = _next_trigger_time(self._cfg.trigger_time)
            sleep_seconds = max(5, (trigger - datetime.now()).total_seconds())
            logger.info(
                f"[dailyporn] next report at {trigger} (in {int(sleep_seconds)}s)"
            )
            await asyncio.sleep(sleep_seconds)
            self._bus.publish(DailyReportRequested(reason="schedule"))


def _next_trigger_time(trigger_time: str) -> datetime:
    now = datetime.now()
    hour, minute = _parse_hhmm(trigger_time)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def _parse_hhmm(value: str) -> tuple[int, int]:
    s = (value or "").strip()
    try:
        parts = s.split(":")
        if len(parts) != 2:
            raise ValueError
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
        return hour, minute
    except Exception:
        return 9, 0

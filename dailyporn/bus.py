from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable, DefaultDict, Type

from astrbot.api import logger


Handler = Callable[[Any], Awaitable[None]]


class EventBus:
    def __init__(self):
        self._handlers: DefaultDict[Type[Any], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: Type[Any], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        handlers = list(self._handlers.get(type(event), []))
        if not handlers:
            return

        for h in handlers:
            task = asyncio.create_task(h(event))
            task.add_done_callback(self._log_task_error)

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("[dailyporn] event handler error")

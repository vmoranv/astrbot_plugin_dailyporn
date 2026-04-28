from __future__ import annotations

import unittest
from types import SimpleNamespace

from dailyporn.events import DailyReportRequested
from main import DailyPornPlugin


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[DailyReportRequested] = []

    def publish(self, event: DailyReportRequested) -> None:
        self.events.append(event)


class _FakeEvent:
    def __init__(self, session: str = "test-session") -> None:
        self.unified_msg_origin = session

    def plain_result(self, text: str) -> str:
        return text


class ManualTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_dailyporn_test_publishes_manual_report(self) -> None:
        plugin = object.__new__(DailyPornPlugin)
        plugin.app = SimpleNamespace(bus=_FakeBus())
        event = _FakeEvent()

        responses = [
            item async for item in DailyPornPlugin.dailyporn(plugin, event, "test")
        ]

        self.assertEqual(responses, ["正在生成日报…"])
        self.assertEqual(len(plugin.app.bus.events), 1)
        published = plugin.app.bus.events[0]
        self.assertEqual(published.reason, "manual")
        self.assertEqual(published.target_sessions, ["test-session"])


if __name__ == "__main__":
    unittest.main()

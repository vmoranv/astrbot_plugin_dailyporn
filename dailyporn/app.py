from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from astrbot.api.star import Context

from .bus import EventBus
from .config import DailyPornConfig
from .repositories.subscriptions import SubscriptionRepository
from .services.http import HttpService
from .services.images import ImageService
from .services.render import RenderService
from .services.recommendation import RecommendationService
from .services.report import ReportService
from .services.scheduler import SchedulerService
from .sources.registry import SourceRegistry

HtmlRenderFn = Callable[..., Awaitable[Any]]


class DailyPornApp:
    def __init__(
        self,
        *,
        context: Context,
        raw_config: dict,
        plugin_name: str,
        html_render: Optional[HtmlRenderFn] = None,
    ):
        self.cfg = DailyPornConfig.from_mapping(raw_config)
        self.bus = EventBus()
        self.http = HttpService(timeout_sec=30)

        self.subscriptions = SubscriptionRepository(plugin_name=plugin_name)
        self.sources = SourceRegistry(self.http, self.cfg)
        self.recommendations = RecommendationService(self.cfg, self.sources)
        self.images = ImageService(
            plugin_name=plugin_name, cfg=self.cfg, http=self.http
        )
        self.renderer = RenderService(
            cfg=self.cfg,
            images=self.images,
            html_render=html_render,
            templates_dir=Path(__file__).resolve().parents[1] / "templates",
        )
        self.report = ReportService(
            context=context,
            cfg=self.cfg,
            bus=self.bus,
            subscriptions=self.subscriptions,
            recommendations=self.recommendations,
            images=self.images,
            renderer=self.renderer,
        )
        self.scheduler = SchedulerService(cfg=self.cfg, bus=self.bus)

    async def start(self) -> None:
        await self.http.start()
        self.report.register()
        self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()
        await self.http.close()

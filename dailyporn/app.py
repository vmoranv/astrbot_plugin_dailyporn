from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from astrbot.api import logger
from astrbot.api.star import Context
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .bus import EventBus
from .config import DailyPornConfig
from .repositories.subscriptions import SubscriptionRepository
from .repositories.recommendation_history import RecommendationHistoryRepository
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
        self.recommendation_history = RecommendationHistoryRepository(
            plugin_name=plugin_name
        )
        self.recommendations = RecommendationService(
            self.cfg, self.sources, history=self.recommendation_history
        )
        self.images = ImageService(
            plugin_name=plugin_name, cfg=self.cfg, http=self.http
        )
        render_dir = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / plugin_name
            / "cache"
            / "renders"
        )
        self.renderer = RenderService(
            cfg=self.cfg,
            images=self.images,
            html_render=html_render,
            templates_dir=Path(__file__).resolve().parents[1] / "templates",
            render_dir=render_dir,
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
        logger.info(
            "[dailyporn] render settings: "
            f"delivery_mode={self.cfg.delivery_mode} "
            f"backend={self.cfg.render_backend} "
            f"send_mode={self.cfg.render_send_mode} "
            f"template={self.cfg.render_template_name}"
        )
        await self.http.start()
        self.report.register()
        self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()
        await self.http.close()

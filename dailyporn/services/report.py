from __future__ import annotations

from datetime import datetime

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.star import Context

from ..config import DailyPornConfig
from ..events import DailyReportRequested
from ..repositories.subscriptions import SubscriptionRepository
from ..sections import SECTIONS, section_display
from .images import ImageService
from .render import RenderService
from .recommendation import RecommendationService


class ReportService:
    def __init__(
        self,
        *,
        context: Context,
        cfg: DailyPornConfig,
        bus,
        subscriptions: SubscriptionRepository,
        recommendations: RecommendationService,
        images: ImageService,
        renderer: RenderService | None,
    ):
        self._context = context
        self._cfg = cfg
        self._bus = bus
        self._subscriptions = subscriptions
        self._reco = recommendations
        self._images = images
        self._renderer = renderer

    def register(self) -> None:
        self._bus.subscribe(DailyReportRequested, self._on_daily_report)

    async def _on_daily_report(self, event: DailyReportRequested) -> None:
        try:
            targets = event.target_sessions or await self._subscriptions.list_enabled()
            if not targets:
                return

            sections = [s.key for s in SECTIONS]
            recos = await self._reco.get_daily_recommendations(sections)
            if recos:
                summary = ", ".join(
                    f"{section_display(k)}:{v.source}({v.stars or 0}/{v.views or 0})"
                    for k, v in recos.items()
                )
                logger.info(f"[dailyporn] daily picks: {summary}")

            for session in targets:
                await self._send_daily(session, recos, reason=event.reason)
        except Exception:
            logger.exception("[dailyporn] report failed")

    async def _send_daily(self, session: str, recos: dict, *, reason: str) -> None:
        if recos:
            summary = ", ".join(
                f"{section_display(k)}:{v.source}(score={v.score_tuple()[0]} stars={v.stars or 0} views={v.views or 0})"
                for k, v in recos.items()
            )
            logger.info(f"[dailyporn] render picks: {summary}")
        if self._cfg.delivery_mode == "html_image" and self._renderer is not None:
            image_ref = await self._renderer.render_daily(recos, reason=reason)
            if image_ref:
                try:
                    chain = MessageChain()
                    send_mode = (self._cfg.render_send_mode or "url").strip().lower()
                    if send_mode == "url":
                        if str(image_ref).startswith(("http://", "https://")):
                            chain.url_image(image_ref)
                        else:
                            chain.file_image(image_ref)
                    elif send_mode == "base64":
                        chain.base64_image(image_ref)
                    else:
                        chain.file_image(image_ref)
                    await self._context.send_message(session, chain)
                    return
                except Exception as e:
                    logger.warning(f"[dailyporn] send daily image failed: {e}")

        header = f"DailyPorn 日报 ({datetime.now().strftime('%Y-%m-%d %H:%M')}) 触发: {reason}"
        try:
            await self._context.send_message(session, MessageChain().message(header))
        except Exception as e:
            logger.warning(f"[dailyporn] send header failed: {e}")
            return

        for key, item in recos.items():
            title = item.title
            stars = item.stars if item.stars is not None else "-"
            views = item.views if item.views is not None else "-"

            text = (
                f"【{section_display(key)} 推荐】\n"
                f"来源: {item.source}\n"
                f"标题: {title}\n"
                f"star: {stars}  views: {views}\n"
                f"{item.url}"
            )
            chain = MessageChain().message(text)

            if item.cover_url:
                cover_path = await self._images.get_cover_path(item.cover_url)
                if cover_path:
                    chain.file_image(cover_path)

            try:
                await self._context.send_message(session, chain)
            except Exception as e:
                logger.warning(f"[dailyporn] send item failed: {e}")

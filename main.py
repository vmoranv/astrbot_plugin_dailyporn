from __future__ import annotations

import sys
from pathlib import Path

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dailyporn.app import DailyPornApp
from dailyporn.events import DailyReportRequested
from dailyporn.sections import SECTIONS, normalize_section, section_display


class DailyPornPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.app = DailyPornApp(
            context=context,
            raw_config=dict(config),
            plugin_name="astrbot_plugin_dailyporn",
            html_render=self.html_render,
        )

    async def initialize(self):
        await self.app.start()

    @filter.command("dailyporn")
    async def dailyporn(self, event: AstrMessageEvent, arg1: str = ""):
        """日报：/dailyporn on|off|test|<分区>"""
        session = event.unified_msg_origin
        sub = (arg1 or "").strip()
        sub_lower = sub.lower()

        if sub_lower == "on":
            await self.app.subscriptions.set_enabled(session, True)
            yield event.plain_result("已在当前群聊开启 DailyPorn 日报。")
            return

        if sub_lower == "off":
            await self.app.subscriptions.set_enabled(session, False)
            yield event.plain_result("已在当前群聊关闭 DailyPorn 日报。")
            return

        if sub_lower == "test":
            yield event.plain_result("正在生成日报…")
            self.app.bus.publish(
                DailyReportRequested(reason="manual", target_sessions=[session])
            )
            return

        # Manual-only sources (no reliable stats; disabled by default; never used in scheduled daily picks).
        if sub_lower in {"hqporner", "missav"}:
            async for r in self._send_manual_source(event, sub_lower):
                yield r
            return

        if not sub or sub_lower in {"help", "h", "?"}:
            yield event.plain_result(self._help_text())
            return

        section = normalize_section(sub)
        if section == "all":
            for sec in SECTIONS:
                async for r in self._send_section(event, sec.key):
                    yield r
            return

        if not section:
            yield event.plain_result(self._help_text())
            return

        async for r in self._send_section(event, section):
            yield r

    async def _send_manual_source(self, event: AstrMessageEvent, source_id: str):
        src = self.app.sources.get_source(source_id)
        if not src:
            yield event.plain_result(f"未知信息源：{source_id}")
            return

        # These sources are treated as "manual-only" and may not expose like/view counters.
        section = next(iter(getattr(src, "sections", {"real"})), "real")
        try:
            items = await src.fetch_hot(section, limit=1, proxy=self.app.cfg.proxy)
        except Exception as e:
            yield event.plain_result(f"[{source_id}] 抓取失败：{e}")
            return
        if not items:
            yield event.plain_result(f"[{source_id}] 暂无数据")
            return

        item = items[0]
        title = item.title or item.url

        meta = item.meta if isinstance(item.meta, dict) else {}
        meta_lines = []
        for k in ("released_at", "duration", "actresses", "tags", "rating", "rating_percent"):
            v = meta.get(k)
            if v is None or v == "" or v == []:
                continue
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v[:20])
            meta_lines.append(f"{k}: {v}")
        meta_text = "\n" + "\n".join(meta_lines) if meta_lines else ""

        text = f"【{item.source} 最新热榜】\n标题: {title}{meta_text}\n{item.url}"

        chain = []
        cover_path = (
            await self.app.images.get_cover_path(item.cover_url) if item.cover_url else None
        )
        if cover_path:
            chain.append(Comp.Image.fromFileSystem(cover_path))
        chain.append(Comp.Plain(text))
        yield event.chain_result(chain)

    async def _send_section(self, event: AstrMessageEvent, section: str):
        items = await self.app.recommendations.get_section_items(
            section, per_source_limit=1
        )
        if not items:
            yield event.plain_result(
                f"【{section_display(section)}】暂无数据（可能该分区未启用任何源）。"
            )
            return

        if self.app.cfg.delivery_mode == "html_image":
            image_path = await self.app.renderer.render_section(section, items)
            if image_path:
                yield event.chain_result([Comp.Image.fromFileSystem(image_path)])
                return

        yield event.plain_result(
            f"【{section_display(section)} 热门】共 {len(items)} 个源"
        )

        for item in items:
            stars = item.stars if item.stars is not None else "-"
            views = item.views if item.views is not None else "-"
            duration = (
                item.meta.get("duration", "") if isinstance(item.meta, dict) else ""
            )
            duration_text = f"\n时长: {duration}" if duration else ""

            text = (
                f"[{item.source}] {item.title}{duration_text}\n"
                f"star: {stars}  views: {views}\n"
                f"{item.url}"
            )

            chain = []
            cover_path = (
                await self.app.images.get_cover_path(item.cover_url)
                if item.cover_url
                else None
            )
            if cover_path:
                chain.append(Comp.Image.fromFileSystem(cover_path))
            chain.append(Comp.Plain(text))
            yield event.chain_result(chain)

    def _help_text(self) -> str:
        trigger_time = self.app.cfg.trigger_time
        enabled = [s for s in self.app.sources.list_sources() if s.enabled]
        enabled_text = (
            ", ".join(f"{s.display_name}" for s in enabled) if enabled else "（无）"
        )

        sections_text = " / ".join(f"{s.display}" for s in SECTIONS) + " / all"
        return (
            "DailyPorn 使用说明\n"
            f"- /dailyporn on|off：在当前群聊开关日报\n"
            f"- /dailyporn test：手动触发一次日报（仅当前群聊）\n"
            f"- /dailyporn <分区>：返回对应分区不同源最热门封面+信息\n"
            f"- /dailyporn hqporner|missav：手动抓取该源最新热榜（默认关闭，不参与定时推荐）\n"
            f"  分区: {sections_text}\n"
            f"\n当前配置：触发时间 {trigger_time} | 封面打码 {self.app.cfg.mosaic_level}\n"
            f"已启用源：{enabled_text}"
        )

    async def terminate(self):
        await self.app.stop()

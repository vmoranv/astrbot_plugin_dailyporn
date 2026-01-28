from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DailyPornConfig:
    trigger_time: str
    mosaic_level: int
    proxy: str
    delivery_mode: str
    render_template_name: str
    render_send_mode: str
    render_image_type: str
    render_quality: int
    render_full_page: bool
    render_omit_background: bool
    render_timeout_ms: int
    sources: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DailyPornConfig":
        trigger_time = str(raw.get("trigger_time", "09:00")).strip() or "09:00"
        try:
            mosaic_level = int(raw.get("mosaic_level", 60))
        except Exception:
            mosaic_level = 60
        mosaic_level = max(0, min(100, mosaic_level))

        proxy = str(raw.get("proxy", "")).strip()

        delivery_mode = (
            str(raw.get("delivery_mode", "html_image") or "html_image").strip().lower()
        )
        if delivery_mode not in {"html_image", "plain"}:
            delivery_mode = "html_image"

        render_template_name = str(
            raw.get("render_template_name", "pornhub") or "pornhub"
        ).strip()
        render_send_mode = (
            str(raw.get("render_send_mode", "url") or "url").strip().lower()
        )
        if render_send_mode not in {"file", "url", "base64"}:
            render_send_mode = "url"
        render_image_type = (
            str(raw.get("render_image_type", "png") or "png").strip().lower()
        )
        if render_image_type not in {"png", "jpeg"}:
            render_image_type = "png"

        try:
            render_quality = int(raw.get("render_quality", 82))
        except Exception:
            render_quality = 82
        render_quality = max(10, min(100, render_quality))

        render_full_page = bool(raw.get("render_full_page", True))
        render_omit_background = bool(raw.get("render_omit_background", False))
        try:
            render_timeout_ms = int(raw.get("render_timeout_ms", 20000))
        except Exception:
            render_timeout_ms = 20000
        render_timeout_ms = max(0, int(render_timeout_ms))

        sources = (
            raw.get("sources", {})
            if isinstance(raw.get("sources", {}), Mapping)
            else {}
        )

        return cls(
            trigger_time=trigger_time,
            mosaic_level=mosaic_level,
            proxy=proxy,
            delivery_mode=delivery_mode,
            render_template_name=render_template_name,
            render_send_mode=render_send_mode,
            render_image_type=render_image_type,
            render_quality=render_quality,
            render_full_page=render_full_page,
            render_omit_background=render_omit_background,
            render_timeout_ms=render_timeout_ms,
            sources=sources,
        )

    def is_source_enabled(self, source_id: str, default: bool = False) -> bool:
        key = f"enable_{source_id}"
        value = self.sources.get(key, default)
        return bool(value)

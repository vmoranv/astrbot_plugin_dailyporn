from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dailyporn.config import DailyPornConfig
from dailyporn.models import HotItem
from dailyporn.services.render import RenderService


class _FakeImages:
    async def get_cover_path(self, url: str) -> str | None:
        return None


class RenderServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_backend_does_not_call_html_render(self) -> None:
        calls = 0

        async def fake_html_render(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise RuntimeError("should not be called")

        cfg = DailyPornConfig.from_mapping(
            {
                "delivery_mode": "html_image",
                "render_backend": "local",
                "render_send_mode": "file",
            }
        )
        recos = {
            "3d": HotItem(
                source="3dporn",
                section="3d",
                title="test",
                url="https://example.com",
                stars=1,
                views=2,
            )
        }

        with tempfile.TemporaryDirectory() as tmp:
            svc = RenderService(
                cfg=cfg,
                images=_FakeImages(),
                html_render=fake_html_render,
                templates_dir=Path(tmp) / "templates",
                render_dir=Path(tmp) / "renders",
            )
            out = await svc.render_daily(recos, reason="manual")

        self.assertEqual(calls, 0)
        self.assertTrue(bool(out))

    async def test_missing_template_skips_remote_and_uses_local(self) -> None:
        calls = 0

        async def fake_html_render(*args, **kwargs):
            nonlocal calls
            calls += 1
            return "https://example.com/should-not-be-used.png"

        cfg = DailyPornConfig.from_mapping(
            {
                "delivery_mode": "html_image",
                "render_backend": "remote",
                "render_send_mode": "file",
            }
        )
        recos = {
            "3d": HotItem(
                source="3dporn",
                section="3d",
                title="test",
                url="https://example.com",
                stars=1,
                views=2,
            )
        }

        with tempfile.TemporaryDirectory() as tmp:
            svc = RenderService(
                cfg=cfg,
                images=_FakeImages(),
                html_render=fake_html_render,
                templates_dir=Path(tmp) / "missing_templates",
                render_dir=Path(tmp) / "renders",
            )
            out = await svc.render_daily(recos, reason="manual")
            self.assertTrue(bool(out))
            assert out is not None
            self.assertTrue(Path(out).exists())

        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()

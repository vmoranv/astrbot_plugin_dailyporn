from __future__ import annotations

import unittest
from unittest.mock import patch

from dailyporn.sources.three_dporn import ThreeDPornSource


class _FakeHttp:
    def __init__(self, list_html: str, detail_html_by_url: dict[str, str]) -> None:
        self._list_html = list_html
        self._detail_html_by_url = detail_html_by_url

    async def get_text(self, url: str, *, proxy: str = "", headers=None) -> str:
        if url in self._detail_html_by_url:
            return self._detail_html_by_url[url]
        return self._list_html


class ThreeDPornSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_hot_uses_candidate_pool_before_picking_limit_one(self) -> None:
        list_html = """
        <html><body>
          <a class="thumb" href="/first/">
            <img src="/first.jpg" alt="First" />
            <span class="duration">01:00</span>
          </a>
          <a class="infos">1,000 views 1 likes</a>
          <a class="thumb" href="/second/">
            <img src="/second.jpg" alt="Second" />
            <span class="duration">02:00</span>
          </a>
          <a class="infos">2,000 views 2 likes</a>
          <a class="thumb" href="/third/">
            <img src="/third.jpg" alt="Third" />
            <span class="duration">03:00</span>
          </a>
          <a class="infos">3,000 views 3 likes</a>
        </body></html>
        """
        detail_html = {
            "https://3d-porn.co/first/": '<script type="application/ld+json">{"@type":"VideoObject"}</script>',
            "https://3d-porn.co/second/": '<script type="application/ld+json">{"@type":"VideoObject"}</script>',
            "https://3d-porn.co/third/": '<script type="application/ld+json">{"@type":"VideoObject"}</script>',
        }
        source = ThreeDPornSource(_FakeHttp(list_html, detail_html))

        with patch("dailyporn.sources.three_dporn.random.shuffle") as shuffle:
            shuffle.side_effect = lambda seq: seq.reverse()
            items = await source.fetch_hot("3d", limit=1, proxy="")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://3d-porn.co/third/")
        self.assertEqual(items[0].title, "Third")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import base64
import pathlib
from urllib.parse import urlparse

import aiohttp

try:
    from astrbot.api import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("dailyporn.http")

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
}


class HttpStatusError(RuntimeError):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status}: {url}")
        self.status = status
        self.url = url


class HttpService:
    def __init__(self, *, timeout_sec: int = 30):
        self._timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session and not self._session.closed:
            return
        self._session = aiohttp.ClientSession(timeout=self._timeout, trust_env=True)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    @staticmethod
    def _merge_headers(headers: dict[str, str] | None) -> dict[str, str]:
        merged = dict(_DEFAULT_HEADERS)
        if headers:
            merged.update(headers)
        return merged

    async def get_text(
        self, url: str, *, proxy: str = "", headers: dict[str, str] | None = None
    ) -> str:
        await self.start()
        assert self._session is not None
        async with self._session.get(
            url,
            proxy=(proxy or None),
            headers=self._merge_headers(headers),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise HttpStatusError(resp.status, url)
            return await resp.text()

    async def get_bytes(
        self, url: str, *, proxy: str = "", headers: dict[str, str] | None = None
    ) -> bytes:
        await self.start()
        assert self._session is not None
        async with self._session.get(
            url,
            proxy=(proxy or None),
            headers=self._merge_headers(headers),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise HttpStatusError(resp.status, url)
            return await resp.read()

    async def post_json(
        self,
        url: str,
        *,
        json_body: dict,
        proxy: str = "",
        headers: dict[str, str] | None = None,
    ) -> dict:
        await self.start()
        assert self._session is not None
        merged_headers = self._merge_headers(headers)
        async with self._session.post(
            url,
            json=json_body,
            proxy=(proxy or None),
            headers=merged_headers,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise HttpStatusError(resp.status, url)
            return await resp.json(content_type=None)

    async def post_form_json(
        self,
        url: str,
        *,
        form: dict[str, str],
        proxy: str = "",
        headers: dict[str, str] | None = None,
    ) -> dict:
        await self.start()
        assert self._session is not None
        merged_headers = self._merge_headers(headers)
        async with self._session.post(
            url,
            data=form,
            proxy=(proxy or None),
            headers=merged_headers,
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                raise HttpStatusError(resp.status, url)
            try:
                return await resp.json(content_type=None)
            except Exception:
                text = await resp.text()
                raise RuntimeError(f"Non-JSON response: {text[:200]}")

    async def safe_get_bytes(
        self, url: str, *, proxy: str = "", headers: dict[str, str] | None = None
    ) -> bytes | None:
        if url.startswith("data:"):
            try:
                header, payload = url.split(",", 1)
                if ";base64" in header:
                    return base64.b64decode(payload)
                return payload.encode("utf-8")
            except Exception as e:
                logger.warning(f"[dailyporn] data url decode failed: {e}")
                return None

        if url.startswith("file://"):
            try:
                parsed = urlparse(url)
                path = pathlib.Path(parsed.path)
                if path.is_file():
                    return path.read_bytes()
            except Exception as e:
                logger.warning(f"[dailyporn] file url read failed: {e}")
                return None
        try:
            merged_headers = dict(headers or {})
            if "Referer" not in merged_headers:
                p = urlparse(url)
                if p.scheme and p.netloc:
                    merged_headers["Referer"] = f"{p.scheme}://{p.netloc}/"
            return await self.get_bytes(url, proxy=proxy, headers=merged_headers)
        except Exception as e:
            logger.warning(f"[dailyporn] download failed: {url} ({e})")
            return None

    async def get_text_via_jina(
        self,
        url: str,
        *,
        proxy: str = "",
        headers: dict[str, str] | None = None,
    ) -> str:
        """
        Fetch HTML via r.jina.ai as a lightweight fallback for sites that return
        HTTP 403/anti-bot to direct requests.
        """
        jina_url = f"https://r.jina.ai/{url}"
        merged_headers = dict(headers or {})
        merged_headers.setdefault("Accept", "text/plain,*/*;q=0.8")
        merged_headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        return await self.get_text(jina_url, proxy=proxy, headers=merged_headers)

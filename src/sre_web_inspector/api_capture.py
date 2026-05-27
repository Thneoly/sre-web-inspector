"""Lightweight in-memory API response capture for scraping tasks.

Captures JSON responses directly into a Python list, avoiding the
disk round-trip of JsonResponseSaverMiddleware.  Designed for
data-extraction workflows where you need to inspect API payloads
programmatically.

Usage::

    cap = ApiCapture()
    page.on("response", cap.handler)
    await page.goto("https://example.com")
    for entry in cap.responses:
        print(entry["url"], entry["data"].keys())
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from playwright.async_api import Response

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class ApiCapture:
    """Capture JSON API responses into an in-memory list.

    Attach ``handler`` as a Playwright ``response`` event listener.
    After navigation, read ``responses`` for the captured payloads.
    """

    def __init__(
        self,
        *,
        url_keywords: list[str] | None = None,
        url_exclude: list[str] | None = None,
        max_captures: int = 200,
    ) -> None:
        self.url_keywords = url_keywords or []
        self.url_exclude = url_exclude or []
        self.max_captures = max_captures
        self.responses: list[dict[str, Any]] = []
        self._scheduled = 0

    # -- event handler ---------------------------------------------------

    def handler(self, response: Response) -> None:
        """Playwright ``response`` event callback (synchronous wrapper)."""
        import asyncio

        try:
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct.lower():
                return

            url = response.url
            if self.url_keywords and not any(kw in url for kw in self.url_keywords):
                return
            if self.url_exclude and any(kw in url for kw in self.url_exclude):
                return
        except Exception:
            return

        if self._scheduled < self.max_captures:
            self._scheduled += 1
            asyncio.ensure_future(self._capture(response))

    # -- helpers ---------------------------------------------------------

    def attach(self, page: "Page") -> None:
        """Convenience: register handler on a Playwright Page."""
        page.on("response", self.handler)  # type: ignore[arg-type]

    def detach(self, page: "Page") -> None:
        """Convenience: remove handler from a Playwright Page."""
        try:
            page.remove_listener("response", self.handler)  # type: ignore[arg-type]
        except Exception:
            pass

    def clear(self) -> None:
        self.responses.clear()

    async def _capture(self, response: Response) -> None:
        try:
            data = await response.json()
            self.responses.append({
                "url": response.url,
                "status": response.status,
                "data": data,
            })
        except Exception:
            logger.debug("Failed to parse JSON from %s", response.url, exc_info=True)

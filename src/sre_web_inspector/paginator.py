"""Generic pagination helpers for scraping tasks.

Two common patterns:

1. **URL-based** — each page has a distinct URL (``?page=2``, ``?page=3``, …).
2. **Click-based** — a "next page" button is clicked to load more content
   via XHR without changing the URL.

Both return an async generator of ``(page_number, page)`` tuples.
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from playwright.async_api import Page

logger = logging.getLogger(__name__)


async def paginate_by_url(
    page_factory,  # Callable[[], Awaitable[Page]] — create a fresh page for each request
    url_template: str,
    *,
    start: int = 1,
    max_pages: int = 0,
    wait_for_network_idle: bool = True,
    idle_timeout: int = 15000,
    wait_ms: int = 500,
) -> AsyncIterator[tuple[int, Page]]:
    """Yield ``(page_num, page)`` for each URL in the sequence.

    Parameters
    ----------
    url_template:
        Must contain ``{page}``, e.g. ``"https://example.com?page={page}"``.
    max_pages:
        0 means iterate until an empty page or error is detected (hard cap
        at 500 to prevent runaway loops).
    """
    pg = start
    cap = max_pages if max_pages > 0 else 500
    while pg <= start + cap - 1:
        url = url_template.format(page=pg)
        page = await page_factory()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if wait_for_network_idle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=idle_timeout)
                except Exception:
                    pass
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)
            yield pg, page
        except Exception as exc:
            logger.warning("Failed to load page %d: %s", pg, exc)
            await page.close()
            break
        pg += 1


async def paginate_by_click(
    page: Page,
    *,
    next_selector: str = ".btn-next",
    max_clicks: int = 10,
    wait_for_network_idle: bool = True,
    idle_timeout: int = 10000,
    wait_ms: int = 1500,
) -> AsyncIterator[tuple[int, Page]]:
    """Yield ``(click_num, page)``, clicking *next_selector* each iteration.

    Stops when the button is missing, invisible, or disabled.  The first
    yield happens *before* any click (click 0 = initial page state).

    Parameters
    ----------
    next_selector:
        CSS selector for the "next page" button.
    max_clicks:
        Upper bound on how many clicks are attempted (safety limit).
    """
    for click_num in range(max_clicks + 1):
        yield click_num, page

        if click_num >= max_clicks:
            break

        try:
            btn = page.locator(next_selector).first
            if await btn.count() == 0:
                break
            disabled = await btn.get_attribute("disabled")
            if disabled is not None:
                break
            if not await btn.is_visible():
                break
            await btn.click()

            if wait_for_network_idle:
                try:
                    await page.wait_for_load_state("networkidle", timeout=idle_timeout)
                except Exception:
                    pass
            if wait_ms > 0:
                await page.wait_for_timeout(wait_ms)
        except Exception:
            logger.debug("Pagination ended at click %d", click_num)
            break

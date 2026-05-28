from __future__ import annotations

import logging
from collections.abc import Callable, Awaitable
from typing import TYPE_CHECKING

from playwright.async_api import BrowserContext

from sre_web_inspector.config_schema import LoginCheckConfig

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

PageFactory = Callable[[], Awaitable["Page"]]


class SessionChecker:
    async def is_logged_in(
        self,
        context: BrowserContext,
        page_factory: PageFactory,
        check_cfg: LoginCheckConfig | None,
    ) -> bool:
        if check_cfg is None or check_cfg.type == "none":
            return False

        try:
            if check_cfg.type == "selector":
                return await self._check_selector(page_factory, check_cfg)
            if check_cfg.type == "api":
                return await self._check_api(context, check_cfg)
            if check_cfg.type == "cookie":
                return await self._check_cookie(context, check_cfg)
            if check_cfg.type == "url_contains":
                return await self._check_url_contains(page_factory, check_cfg)
        except Exception:
            logger.debug("Session check failed", exc_info=True)

        return False

    async def _check_selector(
        self,
        page_factory: PageFactory,
        check_cfg: LoginCheckConfig,
    ) -> bool:
        page: Page = await page_factory()
        try:
            if check_cfg.url:
                await page.goto(check_cfg.url, wait_until="domcontentloaded", timeout=check_cfg.timeout)
            if check_cfg.selector:
                await page.wait_for_selector(check_cfg.selector, timeout=check_cfg.timeout)
                return True
            return False
        except Exception:
            return False
        finally:
            await page.close()

    async def _check_api(
        self,
        context: BrowserContext,
        check_cfg: LoginCheckConfig,
    ) -> bool:
        if not check_cfg.url:
            return False
        resp = await context.request.get(
            check_cfg.url,
            timeout=check_cfg.timeout,
        )
        if check_cfg.expect_status is not None:
            return resp.status == check_cfg.expect_status
        return resp.ok

    async def _check_cookie(
        self,
        context: BrowserContext,
        check_cfg: LoginCheckConfig,
    ) -> bool:
        cookies = await context.cookies()
        return any(c.get("name") == check_cfg.cookie_name for c in cookies)

    async def _check_url_contains(
        self,
        page_factory: PageFactory,
        check_cfg: LoginCheckConfig,
    ) -> bool:
        page: Page = await page_factory()
        try:
            if check_cfg.url:
                await page.goto(check_cfg.url, wait_until="domcontentloaded", timeout=check_cfg.timeout)
            return check_cfg.selector is not None and check_cfg.selector in page.url
        except Exception:
            return False
        finally:
            await page.close()

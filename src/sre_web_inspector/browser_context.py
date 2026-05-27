from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    BrowserType,
    Error as PlaywrightError,
    Page,
    Playwright,
    Request,
    Response,
)

logger = logging.getLogger(__name__)


class BrowserContextManager:
    """
    Playwright 异步浏览器上下文管理器。

    主要能力：
    - 使用 launch_persistent_context 持久化用户数据
    - 支持自定义 Chromium 可执行文件路径
    - 支持忽略 HTTPS 证书错误
    - 支持最大化窗口
    - 支持创建新页面
    - 支持保存 storage_state
    - 支持截图
    - 支持基础请求/响应监听
    - 支持优雅关闭 Playwright 资源
    """

    def __init__(
        self,
        *,
        exe_dir: Optional[Path | str] = None,
        browser_path: Optional[Path | str] = None,
        user_data_dir: Optional[Path | str] = None,
        headless: bool = False,
        slow_mo: int = 300,
        ignore_https_errors: bool = True,
        no_viewport: bool = True,
        start_maximized: bool = True,
        extra_args: Optional[list[str]] = None,
    ) -> None:
        self._exe_dir = Path(exe_dir) if exe_dir else Path(__file__).resolve().parent.parent

        self._browser_path = (
            Path(browser_path)
            if browser_path
            else self._exe_dir
            / "playwright_browsers"
            / "chromium-1217"
            / "chrome-win64"
            / "chrome.exe"
        )

        self._user_data_dir = (
            Path(user_data_dir)
            if user_data_dir
            else self._exe_dir / "user-data"
        )

        self._headless = headless
        self._slow_mo = slow_mo
        self._ignore_https_errors = ignore_https_errors
        self._no_viewport = no_viewport
        self._start_maximized = start_maximized
        self._extra_args = extra_args or []

        self._playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self._requests: list[dict[str, Any]] = []
        self._responses: list[dict[str, Any]] = []

    @property
    def exe_dir(self) -> Path:
        return self._exe_dir

    @property
    def browser_path(self) -> Path:
        return self._browser_path

    @property
    def user_data_dir(self) -> Path:
        return self._user_data_dir

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self._requests

    @property
    def responses(self) -> list[dict[str, Any]]:
        return self._responses

    def clear_network_records(self) -> None:
        """清空当前内存中的请求/响应记录，适合每个 page 巡检前重置。"""
        self._requests.clear()
        self._responses.clear()

    async def __aenter__(self) -> "BrowserContextManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if self.context is not None:
            return

        self._ensure_dirs()

        self._playwright = await async_playwright().start()
        browser_type: BrowserType = self._playwright.chromium

        args = self._build_browser_args()

        # 如果显式配置的 browser_path 存在，则使用内置浏览器；否则使用 Playwright 默认浏览器。
        executable_path = str(self._browser_path) if self._browser_path.exists() else None

        self.context = await browser_type.launch_persistent_context(
            user_data_dir=str(self._user_data_dir),
            executable_path=executable_path,
            headless=self._headless,
            slow_mo=self._slow_mo,
            ignore_https_errors=self._ignore_https_errors,
            no_viewport=self._no_viewport,
            args=args,
        )

        self._bind_context_events(self.context)
        self.page = await self.context.new_page()
        self._bind_page_events(self.page)

    async def close(self) -> None:
        if self.context is not None:
            try:
                await self.context.close()
            except PlaywrightError as e:
                logger.warning("Failed to close browser context: %s", e)
            finally:
                self.context = None
                self.page = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except PlaywrightError as e:
                logger.warning("Failed to stop playwright: %s", e)
            finally:
                self._playwright = None

    async def new_page(self) -> Page:
        context = self._require_context()
        page = await context.new_page()
        self._bind_page_events(page)
        return page

    async def goto(
        self,
        url: str,
        *,
        page: Optional[Page] = None,
        wait_until: str = "domcontentloaded",
        timeout: int = 60_000,
    ) -> Optional[Response]:
        target_page = page or self._require_page()
        return await target_page.goto(url, wait_until=wait_until, timeout=timeout)

    async def wait_for_timeout(self, ms: int, *, page: Optional[Page] = None) -> None:
        target_page = page or self._require_page()
        await target_page.wait_for_timeout(ms)

    async def screenshot(
        self,
        path: Path | str,
        *,
        page: Optional[Page] = None,
        full_page: bool = True,
    ) -> Path:
        target_page = page or self._require_page()
        screenshot_path = Path(path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        await target_page.screenshot(path=str(screenshot_path), full_page=full_page)
        return screenshot_path

    async def save_html(self, path: Path | str, *, page: Optional[Page] = None) -> Path:
        target_page = page or self._require_page()
        html_path = Path(path)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(await target_page.content(), encoding="utf-8")
        return html_path

    async def save_storage_state(self, path: Path | str) -> Path:
        context = self._require_context()
        storage_path = Path(path)
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(storage_path))
        return storage_path

    async def dump_network_records(self, path: Path | str) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"requests": self._requests, "responses": self._responses}
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path

    async def wait_for_response(self, predicate, *, page: Optional[Page] = None, timeout: int = 30_000) -> Response:
        target_page = page or self._require_page()
        if isinstance(predicate, str):
            url_part = predicate
            matcher = lambda response: url_part in response.url
        else:
            matcher = predicate
        return await target_page.wait_for_response(matcher, timeout=timeout)

    async def wait_for_request(self, predicate, *, page: Optional[Page] = None, timeout: int = 30_000) -> Request:
        target_page = page or self._require_page()
        if isinstance(predicate, str):
            url_part = predicate
            matcher = lambda request: url_part in request.url
        else:
            matcher = predicate
        return await target_page.wait_for_request(matcher, timeout=timeout)

    async def get_cookies(self) -> list[dict[str, Any]]:
        return await self._require_context().cookies()

    async def clear_cookies(self) -> None:
        await self._require_context().clear_cookies()

    async def evaluate(self, script: str, *, page: Optional[Page] = None, arg: Any = None) -> Any:
        return await (page or self._require_page()).evaluate(script, arg)

    async def content(self, *, page: Optional[Page] = None) -> str:
        return await (page or self._require_page()).content()

    async def title(self, *, page: Optional[Page] = None) -> str:
        return await (page or self._require_page()).title()

    def _ensure_dirs(self) -> None:
        self._user_data_dir.mkdir(parents=True, exist_ok=True)

    def _build_browser_args(self) -> list[str]:
        args: list[str] = []
        if self._start_maximized:
            args.append("--start-maximized")
        args.extend([
            "--disable-features=LocalNetworkAccessChecks,LocalNetworkAccessPermissionPrompt",
        ])
        args.extend(self._extra_args)
        return args

    def _bind_context_events(self, context: BrowserContext) -> None:
        context.on("page", self._on_new_page)

    def _bind_page_events(self, page: Page) -> None:
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("console", lambda msg: logger.info("Console: %s", msg.text))
        page.on("pageerror", lambda err: logger.warning("Page error: %s", err))

    def _on_new_page(self, page: Page) -> None:
        self._bind_page_events(page)

    def _on_request(self, request: Request) -> None:
        try:
            self._requests.append({
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
                "headers": dict(request.headers),
                "post_data": request.post_data,
            })
        except Exception as e:
            logger.warning("Failed to record request: %s", e)

    def _on_response(self, response: Response) -> None:
        try:
            self._responses.append({
                "url": response.url,
                "status": response.status,
                "status_text": response.status_text,
                "headers": dict(response.headers),
            })
        except Exception as e:
            logger.warning("Failed to record response: %s", e)

    def _require_context(self) -> BrowserContext:
        if self.context is None:
            raise RuntimeError("Browser context is not initialized")
        return self.context

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("Page is not initialized")
        return self.page

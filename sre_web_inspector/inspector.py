from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Request, Response

from .browser_context import BrowserContextManager
from .request_utils import safe_filename


class WebInspectionNode:
    def __init__(self, context_manager: BrowserContextManager) -> None:
        self.cm = context_manager

    async def inspect_page(
        self,
        url: str,
        *,
        page: Page | None = None,
        name: str | None = None,
        output_dir: str | Path = "outputs",
        screenshot: bool = True,
        save_html: bool = True,
        save_network: bool = True,
        wait_ms: int = 1000,
        timeout: int = 60_000,
    ) -> dict[str, Any]:
        """巡检单个页面。支持 page 专属网络记录，适合并发执行。"""
        target_page = page or self.cm.page
        if target_page is None:
            raise RuntimeError("Page is not initialized")

        local_requests: list[dict[str, Any]] = []
        local_responses: list[dict[str, Any]] = []

        def on_request(request: Request) -> None:
            local_requests.append(
                {
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "headers": dict(request.headers),
                    "post_data": request.post_data,
                }
            )

        def on_response(response: Response) -> None:
            local_responses.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "status_text": response.status_text,
                    "headers": dict(response.headers),
                }
            )

        if save_network:
            target_page.on("request", on_request)
            target_page.on("response", on_response)

        try:
            await self.cm.goto(url, page=target_page, timeout=timeout)
            if wait_ms > 0:
                await self.cm.wait_for_timeout(wait_ms, page=target_page)

            title = await self.cm.title(page=target_page)
            base_name = safe_filename(name or title or "page")
            output_dir = Path(output_dir)

            result: dict[str, Any] = {
                "name": name,
                "url": url,
                "title": title,
            }

            if screenshot:
                result["screenshot"] = str(
                    await self.cm.screenshot(
                        output_dir / "screenshots" / f"{base_name}.png",
                        page=target_page,
                    )
                )

            if save_html:
                result["html"] = str(
                    await self.cm.save_html(
                        output_dir / "html" / f"{base_name}.html",
                        page=target_page,
                    )
                )

            if save_network:
                network_path = output_dir / "network" / f"{base_name}.json"
                network_path.parent.mkdir(parents=True, exist_ok=True)
                network_path.write_text(
                    json.dumps(
                        {"requests": local_requests, "responses": local_responses},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                result["network"] = str(network_path)

            result["request_count"] = len(local_requests) if save_network else len(self.cm.requests)
            result["response_count"] = len(local_responses) if save_network else len(self.cm.responses)
            return result
        finally:
            # Playwright Python supports remove_listener on event emitters.
            if save_network:
                try:
                    target_page.remove_listener("request", on_request)
                    target_page.remove_listener("response", on_response)
                except Exception:
                    pass

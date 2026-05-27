from __future__ import annotations

from typing import Any

from playwright.async_api import BrowserContext


class ApiCollector:
    def __init__(self, context: BrowserContext) -> None:
        self.context = context

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.context.request.get(url, params=params, headers=headers)
        return await response.json()

    async def post_json(
        self,
        url: str,
        *,
        data: dict[str, Any] | list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.context.request.post(url, data=data, headers=headers)
        return await response.json()

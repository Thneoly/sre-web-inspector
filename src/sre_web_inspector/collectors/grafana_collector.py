from __future__ import annotations

from typing import Any

from playwright.async_api import BrowserContext


class GrafanaCollector:
    def __init__(self, context: BrowserContext, base_url: str) -> None:
        self.context = context
        self.base_url = base_url.rstrip("/")

    async def search_dashboards(self, *, query: str = "") -> Any:
        response = await self.context.request.get(
            f"{self.base_url}/api/search",
            params={"query": query},
        )
        return await response.json()

    async def get_dashboard_by_uid(self, uid: str) -> Any:
        response = await self.context.request.get(
            f"{self.base_url}/api/dashboards/uid/{uid}"
        )
        return await response.json()

    async def query_datasource(self, payload: dict[str, Any]) -> Any:
        response = await self.context.request.post(
            f"{self.base_url}/api/ds/query",
            data=payload,
        )
        return await response.json()

from __future__ import annotations

from typing import Any

from playwright.async_api import Page


class TableCollector:
    def __init__(self, page: Page) -> None:
        self.page = page

    async def collect_table(self, selector: str = "table") -> list[dict[str, Any]]:
        table = self.page.locator(selector).first()
        headers = await table.locator("thead tr th").all_text_contents()
        rows = table.locator("tbody tr")
        count = await rows.count()

        results: list[dict[str, Any]] = []
        for i in range(count):
            cells = await rows.nth(i).locator("td").all_text_contents()
            if headers and len(headers) == len(cells):
                results.append(dict(zip(headers, cells)))
            else:
                results.append({"cells": cells})
        return results

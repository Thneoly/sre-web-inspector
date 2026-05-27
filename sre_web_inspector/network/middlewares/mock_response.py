from __future__ import annotations

import json
from typing import Any

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall


class MockResponseMiddleware(RouteMiddleware):
    def __init__(
        self,
        *,
        body: Any,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {"content-type": "application/json"}

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        ctx.handled = True
        body = self.body
        if not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)
        return await ctx.route.fulfill(
            status=self.status,
            headers=self.headers,
            body=body,
        )

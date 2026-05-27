from __future__ import annotations

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall


class HeaderPatchMiddleware(RouteMiddleware):
    def __init__(
        self,
        *,
        set_headers: dict[str, str] | None = None,
        remove_headers: list[str] | None = None,
    ) -> None:
        self.set_headers = set_headers or {}
        self.remove_headers = {h.lower() for h in (remove_headers or [])}

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        ctx.headers = {
            key: value
            for key, value in ctx.headers.items()
            if key.lower() not in self.remove_headers
        }
        ctx.headers.update(self.set_headers)
        return await next_call()

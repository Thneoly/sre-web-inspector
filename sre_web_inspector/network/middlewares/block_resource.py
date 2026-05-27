from __future__ import annotations

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall


class BlockResourceMiddleware(RouteMiddleware):
    def __init__(self, *, resource_types: list[str] | None = None) -> None:
        self.resource_types = set(resource_types or ["image", "font", "media"])

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        if ctx.request.resource_type in self.resource_types:
            ctx.handled = True
            return await ctx.route.abort()
        return await next_call()

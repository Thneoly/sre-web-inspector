from __future__ import annotations

from typing import Any

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall
from ...request_utils import patch_url_query


class QueryParamPatchMiddleware(RouteMiddleware):
    def __init__(
        self,
        *,
        set_params: dict[str, Any] | None = None,
        remove_params: list[str] | None = None,
    ) -> None:
        self.set_params = set_params or {}
        self.remove_params = remove_params or []

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        ctx.url = patch_url_query(
            ctx.url,
            set_params=self.set_params,
            remove_params=self.remove_params,
        )
        return await next_call()

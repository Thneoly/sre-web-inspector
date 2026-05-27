from __future__ import annotations

import json
from typing import Any

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall
from ...request_utils import patch_json_body


class PostJsonPatchMiddleware(RouteMiddleware):
    def __init__(self, *, patch: dict[str, Any]) -> None:
        self.patch = patch

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        if ctx.method.upper() != "POST":
            return await next_call()

        content_type = ctx.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return await next_call()

        if not ctx.post_data:
            return await next_call()

        try:
            body = json.loads(ctx.post_data)
        except json.JSONDecodeError:
            return await next_call()

        body = patch_json_body(body, self.patch)
        ctx.post_data = json.dumps(body, ensure_ascii=False)
        return await next_call()

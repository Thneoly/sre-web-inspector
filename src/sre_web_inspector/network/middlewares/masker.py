from __future__ import annotations

from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall
from ...request_utils import mask_headers


class SensitiveMasker(RouteMiddleware):
    """
    对记录或后续处理中的敏感 header 做脱敏。
    注意：如果该 middleware 放在 route.continue_ 前，会改变真正请求的 header。
    通常建议仅在 recorder 内部脱敏，而不是实际修改请求。
    """

    def __init__(self, *, sensitive_keys: list[str] | None = None) -> None:
        self.sensitive_keys = sensitive_keys

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        ctx.headers = mask_headers(ctx.headers, self.sensitive_keys)
        return await next_call()

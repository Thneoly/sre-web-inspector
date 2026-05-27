from __future__ import annotations

import json
import time
from pathlib import Path

from ..contexts import RouteContext, RequestContext
from ..middleware import RouteMiddleware, RequestMiddleware, NextCall
from ...request_utils import mask_headers


class RouteRecorderMiddleware(RouteMiddleware):
    def __init__(
        self,
        *,
        output_dir: str | Path = "outputs/network",
        filename: str = "route_records.jsonl",
        mask_sensitive: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.mask_sensitive = mask_sensitive

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        headers = mask_headers(ctx.headers) if self.mask_sensitive else ctx.headers
        record = {
            "time": time.time(),
            "kind": "route",
            "method": ctx.method,
            "url": ctx.url,
            "headers": headers,
            "post_data": ctx.post_data,
            "metadata": ctx.metadata,
        }
        with (self.output_dir / self.filename).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return await next_call()


class RequestRecorderMiddleware(RequestMiddleware):
    def __init__(
        self,
        *,
        output_dir: str | Path = "outputs/network",
        filename: str = "request_records.jsonl",
        url_keywords: list[str] | None = None,
        mask_sensitive: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.filename = filename
        self.url_keywords = url_keywords or []
        self.mask_sensitive = mask_sensitive

    async def handle(self, ctx: RequestContext) -> None:
        if self.url_keywords and not any(k in ctx.url for k in self.url_keywords):
            return
        headers = mask_headers(ctx.headers) if self.mask_sensitive else ctx.headers
        record = {
            "time": time.time(),
            "kind": "request",
            "method": ctx.method,
            "url": ctx.url,
            "resource_type": ctx.resource_type,
            "headers": headers,
            "post_data": ctx.post_data,
            "metadata": ctx.metadata,
        }
        with (self.output_dir / self.filename).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..contexts import ResponseContext
from ..middleware import ResponseMiddleware


class JsonResponseSaverMiddleware(ResponseMiddleware):
    def __init__(
        self,
        *,
        output_dir: str | Path = "outputs/responses",
        url_keywords: list[str] | None = None,
        save_headers: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.url_keywords = url_keywords or []
        self.save_headers = save_headers

    async def handle(self, ctx: ResponseContext) -> None:
        if self.url_keywords and not any(keyword in ctx.url for keyword in self.url_keywords):
            return

        content_type = ctx.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return

        try:
            data = await ctx.response.json()
        except Exception:
            return

        name = hashlib.md5(ctx.url.encode("utf-8")).hexdigest()
        output_path = self.output_dir / f"{name}.json"

        payload = {
            "url": ctx.url,
            "status": ctx.status,
            "data": data,
        }
        if self.save_headers:
            payload["headers"] = ctx.headers

        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

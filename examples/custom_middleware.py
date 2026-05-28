"""
自定义 Middleware 示例 — 演示如何编写 Route / Request / Response 三种 middleware。

包含：
  1. TimingMiddleware (Route)     — 记录每个请求耗时，可设置慢请求阈值告警
  2. ApiBodyCapture (Request)      — 按 URL 关键词捕获 POST 请求体到内存
  3. ResponseValidator (Response)  — 检查 JSON 响应是否包含必需字段
  4. ResponseSizeGuard (Response)  — 响应体过大时告警

使用方式：
  # 直接用 Python 运行（纯编程方式）
  uv run python examples/custom_middleware.py

  # 在 YAML 中引用（需先在 factory 中注册，见文件末尾的说明）
  # 或通过编程方式在脚本中直接实例化
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from sre_web_inspector.network.contexts import RequestContext, ResponseContext, RouteContext
from sre_web_inspector.network.manager import NetworkMiddlewareManager
from sre_web_inspector.network.middleware import NextCall, RequestMiddleware, ResponseMiddleware, RouteMiddleware

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. 自定义 RouteMiddleware — 请求计时 + 慢请求告警
# ═══════════════════════════════════════════════════════════════════════════════

class TimingMiddleware(RouteMiddleware):
    """记录每个路由请求的耗时，超过阈值时发出 WARNING。

    RouteMiddleware 可以修改 ctx.url / ctx.headers / ctx.post_data，
    然后调用 await next_call() 将修改后的请求发出。
    不调用 next_call() = 拦截并"吃掉"请求（可用于 mock / block）。
    """

    def __init__(
        self,
        *,
        slow_threshold_ms: float = 3000,
        log_all: bool = False,
    ) -> None:
        self.slow_threshold_ms = slow_threshold_ms
        self.log_all = log_all

    async def handle(self, ctx: RouteContext, next_call: NextCall) -> Any:
        start = time.monotonic()
        try:
            result = await next_call()
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            if self.log_all:
                logger.info("request %s %s took %.0fms", ctx.method, ctx.url, elapsed_ms)
            if elapsed_ms > self.slow_threshold_ms:
                logger.warning(
                    "SLOW request: %s %s (%.0fms > %.0fms)",
                    ctx.method, ctx.url, elapsed_ms, self.slow_threshold_ms,
                )
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. 自定义 RouteMiddleware — 注入认证 token
# ═══════════════════════════════════════════════════════════════════════════════

class AuthTokenMiddleware(RouteMiddleware):
    """从环境变量或文件注入 Bearer token 到请求头。

    适用于需要动态 token 的场景（如 CI 中从 vault 读取）。
    优先级：env_token > file_token_path > 静态 token
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        header_name: str = "Authorization",
        token_prefix: str = "Bearer ",
    ) -> None:
        self._token = token
        self.header_name = header_name
        self.token_prefix = token_prefix

    def _get_token(self) -> str | None:
        # 示例：可扩展从文件或 vault 读取
        return self._token

    async def handle(self, ctx: RouteContext, next_call: NextCall) -> Any:
        token = self._get_token()
        if token:
            ctx.headers[self.header_name] = f"{self.token_prefix}{token}"
            logger.debug("injected %s header for %s, ctx.url=%s", self.header_name, ctx.url[:120])
        return await next_call()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. 自定义 RequestMiddleware — 按关键词捕获 POST 请求体
# ═══════════════════════════════════════════════════════════════════════════════

class ApiBodyCapture(RequestMiddleware):
    """监听所有 request 事件，匹配 URL 关键词时捕获 POST body 到内存列表。

    RequestMiddleware 的 handle(ctx) 是 fire-and-forget 的：
    不能修改 request，适合做日志 / 采集 / 告警。
    """

    def __init__(self, *, url_keywords: list[str] | None = None, max_captures: int = 200) -> None:
        self.url_keywords = url_keywords or []
        self.max_captures = max_captures
        self.captured: list[dict[str, Any]] = []

    async def handle(self, ctx: RequestContext) -> None:
        if self.url_keywords and not any(kw in ctx.url for kw in self.url_keywords):
            return
        if len(self.captured) >= self.max_captures:
            return
        self.captured.append({
            "url": ctx.url,
            "method": ctx.method,
            "resource_type": ctx.resource_type,
            "headers": ctx.headers,
            "post_data": ctx.post_data,
        })
        logger.debug("captured request body: %s %s", ctx.method, ctx.url[:120])

    def dump(self, filepath: str | Path) -> None:
        Path(filepath).write_text(
            json.dumps(self.captured, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. 自定义 ResponseMiddleware — 校验 JSON 响应是否包含必需字段
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseValidator(ResponseMiddleware):
    """检查 JSON 响应是否包含期望的顶层字段，缺失时输出 WARNING。

    ResponseMiddleware.handle(ctx) 可访问 ctx.response / ctx.url / ctx.status / ctx.headers。
    适合做 API 契约校验、变更检测。
    """

    def __init__(self, *, url_keywords: list[str] | None = None, required_fields: list[str] | None = None) -> None:
        self.url_keywords = url_keywords or []
        self.required_fields = required_fields or []

    async def handle(self, ctx: ResponseContext) -> None:
        if self.url_keywords and not any(kw in ctx.url for kw in self.url_keywords):
            return

        content_type = ctx.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return

        try:
            data = await ctx.response.json()
        except Exception:
            return

        if not isinstance(data, dict):
            return

        missing = [f for f in self.required_fields if f not in data]
        if missing:
            logger.warning(
                "Response validation: %s (status=%s) missing fields: %s",
                ctx.url[:120], ctx.status, missing,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. 自定义 ResponseMiddleware — 响应体大小守护
# ═══════════════════════════════════════════════════════════════════════════════

class ResponseSizeGuard(ResponseMiddleware):
    """当 JSON 响应超过阈值时告警，帮助发现意外的超大批次返回。"""

    def __init__(self, *, max_items: int = 1000, list_key: str | None = None) -> None:
        self.max_items = max_items
        self.list_key = list_key  # 如果响应是 {"items": [...]}，指定 list_key="items"

    async def handle(self, ctx: ResponseContext) -> None:
        content_type = ctx.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return

        try:
            data = await ctx.response.json()
        except Exception:
            return

        items = data.get(self.list_key, data) if self.list_key else data
        if isinstance(items, list) and len(items) > self.max_items:
            logger.warning(
                "Large response: %s returned %d items (limit=%d), status=%s",
                ctx.url[:120], len(items), self.max_items, ctx.status,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. 组装 & 使用示例
# ═══════════════════════════════════════════════════════════════════════════════

def build_custom_middleware_manager() -> NetworkMiddlewareManager:
    """
    构建一个包含自定义 middleware 的 NetworkMiddlewareManager。

    这是纯编程方式，不依赖 YAML / factory。
    """

    mgr = NetworkMiddlewareManager()

    # Route 级别 — 对匹配 URL pattern 的请求生效
    mgr.routes.add_route(
        pattern="**/*/api/*",
        middlewares=[
            TimingMiddleware(slow_threshold_ms=2000, log_all=True),
            AuthTokenMiddleware(token="my-static-token"),
        ],
        name="custom_api_pipeline",
    )

    # Route 级别 — 静态资源单独计时（宽松阈值）
    mgr.routes.add_route(
        pattern="**/*.png",
        middlewares=[TimingMiddleware(slow_threshold_ms=5000)],
        name="static_timing",
    )

    # Request 级别 — 采集 POST body
    body_capture = ApiBodyCapture(url_keywords=["/api/"], max_captures=100)
    mgr.requests.add(body_capture)

    # Response 级别 — 校验 + 大小守护
    mgr.responses.add(ResponseValidator(
        url_keywords=["/api/"],
        required_fields=["code", "data"],
    ))
    mgr.responses.add(ResponseSizeGuard(max_items=500, list_key="data"))

    return mgr


# ═══════════════════════════════════════════════════════════════════════════════
# 使用入口（可直接运行）
# ═══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    import asyncio

    from sre_web_inspector import BrowserContextManager

    async with BrowserContextManager(headless=False, slow_mo=200) as cm:
        mgr = build_custom_middleware_manager()
        await mgr.bind(cm.page)

        await cm.goto("https://example.com/pods")
        await asyncio.sleep(2)
        await cm.screenshot("outputs/screenshots/pods_custom_mw.png")

        # 打印捕获的 request body
        for cap_mw in mgr.requests.middlewares:
            if isinstance(cap_mw, ApiBodyCapture):
                print(f"captured {len(cap_mw.captured)} request bodies")
                if cap_mw.captured:
                    print(json.dumps(cap_mw.captured[:2], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    asyncio.run(main())


# ═══════════════════════════════════════════════════════════════════════════════
# YAML 集成说明
# ═══════════════════════════════════════════════════════════════════════════════
#
# 如果要在 YAML 配置中使用自定义 middleware，需要：
#
# 1. 在 factory.py 的 build_route_middleware / build_request_middleware /
#    build_response_middleware 中添加对应的 type 分支：
#
#    # 在 build_route_middleware() 中添加:
#    if typ == "timing":
#        return TimingMiddleware(
#            slow_threshold_ms=cfg.get("slow_threshold_ms", 3000),
#            log_all=cfg.get("log_all", False),
#        )
#    if typ == "auth_token":
#        return AuthTokenMiddleware(token=cfg.get("token"))
#
#    # 在 build_request_middleware() 中添加:
#    if typ == "api_body_capture":
#        return ApiBodyCapture(
#            url_keywords=cfg.get("url_keywords"),
#            max_captures=cfg.get("max_captures", 200),
#        )
#
#    # 在 build_response_middleware() 中添加:
#    if typ == "response_validator":
#        return ResponseValidator(
#            url_keywords=cfg.get("url_keywords"),
#            required_fields=cfg.get("required_fields", []),
#        )
#    if typ == "response_size_guard":
#        return ResponseSizeGuard(
#            max_items=cfg.get("max_items", 1000),
#            list_key=cfg.get("list_key"),
#        )
#
# 2. 然后在 network_middlewares YAML 中使用:
#
#    network_middlewares:
#      routes:
#        - pattern: "**/*/api/*"
#          middlewares:
#            - type: timing
#              slow_threshold_ms: 2000
#              log_all: true
#            - type: auth_token
#              token: "{{ sre_token }}"
#      responses:
#        - type: response_validator
#          url_keywords:
#            - /api/
#          required_fields:
#            - code
#            - data
#        - type: response_size_guard
#          max_items: 500
#          list_key: data

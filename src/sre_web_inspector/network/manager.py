from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from playwright.async_api import BrowserContext, Page, Route, Request, Response

from .contexts import RouteContext, RequestContext, ResponseContext
from .middleware import RouteMiddleware, RequestMiddleware, ResponseMiddleware

logger = logging.getLogger(__name__)


class RouteBindable(Protocol):
    async def route(self, url: str, handler, **kwargs): ...


class EventBindable(Protocol):
    def on(self, event: str, handler): ...


@dataclass(slots=True)
class RouteRule:
    pattern: str
    middlewares: list[RouteMiddleware]
    name: str | None = None


class RouteMiddlewareManager:
    def __init__(self) -> None:
        self._routes: list[RouteRule] = []

    @property
    def routes(self) -> list[RouteRule]:
        return self._routes

    def add_route(
        self,
        pattern: str,
        middlewares: list[RouteMiddleware],
        *,
        name: str | None = None,
    ) -> None:
        self._routes.append(RouteRule(pattern=pattern, middlewares=middlewares, name=name))

    async def bind_to_page(self, page: Page) -> None:
        await self._bind(page)

    async def bind_to_context(self, context: BrowserContext) -> None:
        await self._bind(context)

    # Backward-compatible alias.
    async def bind(self, page: Page) -> None:
        await self.bind_to_page(page)

    async def _bind(self, target: RouteBindable) -> None:
        for rule in self._routes:
            await target.route(rule.pattern, self._build_handler(rule.middlewares, rule.name))

    def _build_handler(self, middlewares: list[RouteMiddleware], route_name: str | None = None):
        async def handler(route: Route, request: Request):
            ctx = RouteContext(
                route=route,
                request=request,
                url=request.url,
                method=request.method,
                headers=dict(request.headers),
                post_data=request.post_data,
            )
            if route_name:
                ctx.metadata["route_name"] = route_name

            index = 0

            async def next_call():
                nonlocal index

                if index < len(middlewares):
                    middleware = middlewares[index]
                    index += 1
                    return await middleware.handle(ctx, next_call)

                if not ctx.handled:
                    ctx.handled = True
                    return await route.continue_(
                        url=ctx.url,
                        headers=ctx.headers,
                        post_data=ctx.post_data,
                    )

            return await next_call()

        return handler


class RequestMiddlewareManager:
    def __init__(self) -> None:
        self.middlewares: list[RequestMiddleware] = []

    def add(self, middleware: RequestMiddleware) -> None:
        self.middlewares.append(middleware)

    def bind_to_page(self, page: Page) -> None:
        self._bind(page)

    def bind_to_context(self, context: BrowserContext) -> None:
        self._bind(context)

    # Backward-compatible alias.
    def bind(self, page: Page) -> None:
        self.bind_to_page(page)

    def _bind(self, target: EventBindable) -> None:
        if not self.middlewares:
            return
        target.on("request", self._on_request)

    def _on_request(self, request: Request) -> None:
        asyncio.create_task(self._handle_request(request))

    async def _handle_request(self, request: Request) -> None:
        ctx = RequestContext(
            request=request,
            url=request.url,
            method=request.method,
            headers=dict(request.headers),
            post_data=request.post_data,
            resource_type=request.resource_type,
        )
        for middleware in self.middlewares:
            try:
                await middleware.handle(ctx)
            except Exception as e:
                logger.warning("Request middleware failed: %s", e)


class ResponseMiddlewareManager:
    def __init__(self) -> None:
        self.middlewares: list[ResponseMiddleware] = []

    def add(self, middleware: ResponseMiddleware) -> None:
        self.middlewares.append(middleware)

    def bind_to_page(self, page: Page) -> None:
        self._bind(page)

    def bind_to_context(self, context: BrowserContext) -> None:
        self._bind(context)

    # Backward-compatible alias.
    def bind(self, page: Page) -> None:
        self.bind_to_page(page)

    def _bind(self, target: EventBindable) -> None:
        if not self.middlewares:
            return
        target.on("response", self._on_response)

    def _on_response(self, response: Response) -> None:
        asyncio.create_task(self._handle_response(response))

    async def _handle_response(self, response: Response) -> None:
        ctx = ResponseContext(
            response=response,
            url=response.url,
            status=response.status,
            headers=dict(response.headers),
        )
        for middleware in self.middlewares:
            try:
                await middleware.handle(ctx)
            except Exception as e:
                logger.warning("Response middleware failed: %s", e)


class NetworkMiddlewareManager:
    """
    统一管理 route/request/response 三类 middleware。

    支持两种绑定范围：
    - bind_to_context(context): 绑定到整个 BrowserContext，对所有 page 生效。
    - bind_to_page(page): 只绑定到当前 page，适合单页面巡检规则。

    bind(page) 是旧版本兼容别名，等价于 bind_to_page(page)。
    """

    def __init__(self) -> None:
        self.routes = RouteMiddlewareManager()
        self.requests = RequestMiddlewareManager()
        self.responses = ResponseMiddlewareManager()

    async def bind_to_page(self, page: Page) -> None:
        await self.routes.bind_to_page(page)
        self.requests.bind_to_page(page)
        self.responses.bind_to_page(page)

    async def bind_to_context(self, context: BrowserContext) -> None:
        await self.routes.bind_to_context(context)
        self.requests.bind_to_context(context)
        self.responses.bind_to_context(context)

    # Backward-compatible alias.
    async def bind(self, page: Page) -> None:
        await self.bind_to_page(page)

    def extend(self, other: "NetworkMiddlewareManager") -> "NetworkMiddlewareManager":
        for rule in other.routes.routes:
            self.routes.add_route(rule.pattern, rule.middlewares, name=rule.name)
        for middleware in other.requests.middlewares:
            self.requests.add(middleware)
        for middleware in other.responses.middlewares:
            self.responses.add(middleware)
        return self

    @classmethod
    def merge(cls, *managers: "NetworkMiddlewareManager") -> "NetworkMiddlewareManager":
        merged = cls()
        for manager in managers:
            merged.extend(manager)
        return merged

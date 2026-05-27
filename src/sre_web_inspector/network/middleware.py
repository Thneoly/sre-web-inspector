from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from .contexts import RouteContext, RequestContext, ResponseContext


NextCall = Callable[[], Awaitable[Any]]


class RouteMiddleware(ABC):
    @abstractmethod
    async def handle(self, ctx: RouteContext, next_call: NextCall) -> Any:
        raise NotImplementedError


class RequestMiddleware(ABC):
    @abstractmethod
    async def handle(self, ctx: RequestContext) -> None:
        raise NotImplementedError


class ResponseMiddleware(ABC):
    @abstractmethod
    async def handle(self, ctx: ResponseContext) -> None:
        raise NotImplementedError

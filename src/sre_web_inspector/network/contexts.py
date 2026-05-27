from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Route, Request, Response


@dataclass
class RouteContext:
    route: Route
    request: Request
    url: str
    method: str
    headers: dict[str, str]
    post_data: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    handled: bool = False


@dataclass
class RequestContext:
    request: Request
    url: str
    method: str
    headers: dict[str, str]
    post_data: str | None
    resource_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseContext:
    response: Response
    url: str
    status: int
    headers: dict[str, str]
    metadata: dict[str, Any] = field(default_factory=dict)

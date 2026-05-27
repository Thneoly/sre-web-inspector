from __future__ import annotations

from copy import deepcopy
from typing import Any

from .manager import NetworkMiddlewareManager
from .middlewares import (
    QueryParamPatchMiddleware,
    PostJsonPatchMiddleware,
    HeaderPatchMiddleware,
    RouteRecorderMiddleware,
    RequestRecorderMiddleware,
    JsonResponseSaverMiddleware,
    BlockResourceMiddleware,
    MockResponseMiddleware,
)


def build_network_middleware_manager(config: dict[str, Any]) -> NetworkMiddlewareManager:
    """
    Backward-compatible builder.

    可传入完整配置：
        {"network_middlewares": {...}}

    也可直接传入 middleware section：
        {"routes": [...], "requests": [...], "responses": [...]}
    """
    section = config.get("network_middlewares", config) or {}
    return build_network_middleware_manager_from_section(section)


def build_network_middleware_manager_from_section(section: dict[str, Any] | None) -> NetworkMiddlewareManager:
    manager = NetworkMiddlewareManager()
    network_cfg = section or {}

    for route_cfg in network_cfg.get("routes", []) or []:
        pattern = route_cfg["pattern"]
        name = route_cfg.get("name")
        middlewares = []
        for mw_cfg in route_cfg.get("middlewares", []) or []:
            middlewares.append(build_route_middleware(mw_cfg))
        manager.routes.add_route(pattern, middlewares, name=name)

    for req_cfg in network_cfg.get("requests", []) or []:
        manager.requests.add(build_request_middleware(req_cfg))

    for resp_cfg in network_cfg.get("responses", []) or []:
        manager.responses.add(build_response_middleware(resp_cfg))

    return manager


def build_context_middleware_manager(config: dict[str, Any]) -> NetworkMiddlewareManager:
    return build_network_middleware_manager_from_section(config.get("context_middlewares", {}) or {})


def build_page_middleware_manager(config: dict[str, Any], page_cfg: dict[str, Any]) -> NetworkMiddlewareManager:
    """
    合并全局 page middleware 与单页 middleware。

    合并顺序：
    1. config.network_middlewares
    2. page_cfg.network_middlewares

    后绑定的规则不会覆盖前者，但如果 pattern 相同，Playwright 会按注册顺序匹配，
    因此建议单页规则 pattern 更精确。
    """
    global_page_manager = build_network_middleware_manager_from_section(
        config.get("network_middlewares", {}) or {}
    )
    page_manager = build_network_middleware_manager_from_section(
        page_cfg.get("network_middlewares", {}) or {}
    )
    return NetworkMiddlewareManager.merge(global_page_manager, page_manager)


def merge_middleware_sections(*sections: dict[str, Any] | None) -> dict[str, Any]:
    """
    配置层面的浅合并工具：routes/requests/responses 直接拼接。
    """
    merged: dict[str, Any] = {"routes": [], "requests": [], "responses": []}
    for section in sections:
        section = section or {}
        for key in ("routes", "requests", "responses"):
            merged[key].extend(deepcopy(section.get(key, []) or []))
    return merged


def build_route_middleware(cfg: dict[str, Any]):
    typ = cfg["type"]

    if typ == "query_param_patch":
        return QueryParamPatchMiddleware(
            set_params=cfg.get("set") or cfg.get("set_params") or {},
            remove_params=cfg.get("remove") or cfg.get("remove_params") or [],
        )

    if typ == "post_json_patch":
        return PostJsonPatchMiddleware(patch=cfg.get("patch") or {})

    if typ == "header_patch":
        return HeaderPatchMiddleware(
            set_headers=cfg.get("set") or cfg.get("set_headers") or {},
            remove_headers=cfg.get("remove") or cfg.get("remove_headers") or [],
        )

    if typ == "route_recorder":
        return RouteRecorderMiddleware(
            output_dir=cfg.get("output_dir", "outputs/network"),
            filename=cfg.get("filename", "route_records.jsonl"),
            mask_sensitive=cfg.get("mask_sensitive", True),
        )

    if typ == "block_resource":
        return BlockResourceMiddleware(resource_types=cfg.get("resource_types"))

    if typ == "mock_response":
        return MockResponseMiddleware(
            body=cfg.get("body", {}),
            status=cfg.get("status", 200),
            headers=cfg.get("headers"),
        )

    raise ValueError(f"Unknown route middleware type: {typ}")


def build_request_middleware(cfg: dict[str, Any]):
    typ = cfg["type"]

    if typ == "request_recorder":
        return RequestRecorderMiddleware(
            output_dir=cfg.get("output_dir", "outputs/network"),
            filename=cfg.get("filename", "request_records.jsonl"),
            url_keywords=cfg.get("url_keywords"),
            mask_sensitive=cfg.get("mask_sensitive", True),
        )

    raise ValueError(f"Unknown request middleware type: {typ}")


def build_response_middleware(cfg: dict[str, Any]):
    typ = cfg["type"]

    if typ == "json_response_saver":
        return JsonResponseSaverMiddleware(
            output_dir=cfg.get("output_dir", "outputs/responses"),
            url_keywords=cfg.get("url_keywords"),
            save_headers=cfg.get("save_headers", True),
        )

    raise ValueError(f"Unknown response middleware type: {typ}")

from __future__ import annotations

import json
from typing import Any

from playwright.async_api import Route, Request

from .request_utils import patch_url_query, patch_json_body


async def modify_get_request(
    route: Route,
    request: Request,
    *,
    set_params: dict[str, Any] | None = None,
    remove_params: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    new_url = patch_url_query(request.url, set_params=set_params, remove_params=remove_params)
    await route.continue_(url=new_url, headers=headers or request.headers)


async def modify_post_json_request(
    route: Route,
    request: Request,
    *,
    json_patch: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> None:
    raw = request.post_data or "{}"
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        await route.continue_()
        return

    new_body = patch_json_body(body, json_patch)
    await route.continue_(
        headers=headers or request.headers,
        post_data=json.dumps(new_body, ensure_ascii=False),
    )

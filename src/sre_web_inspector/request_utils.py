from __future__ import annotations

import copy
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def patch_url_query(
    url: str,
    *,
    set_params: dict[str, Any] | None = None,
    remove_params: list[str] | None = None,
) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))

    for key in remove_params or []:
        query.pop(key, None)

    for key, value in (set_params or {}).items():
        query[key] = str(value)

    new_query = urlencode(query, doseq=True)

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment,
    ))


def patch_json_body(body: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(body)
    result.update(patch)
    return result


def mask_headers(headers: dict[str, str], sensitive_keys: list[str] | None = None) -> dict[str, str]:
    keys = {k.lower() for k in (sensitive_keys or ["authorization", "cookie", "set-cookie", "x-api-key"])}
    return {k: ("***MASKED***" if k.lower() in keys else v) for k, v in headers.items()}


def safe_filename(name: str, max_len: int = 120) -> str:
    for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '&', '=', ' ']:
        name = name.replace(ch, "_")
    return name[:max_len] or "unnamed"

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"{{\s*([a-zA-Z0-9_.-]+)\s*}}")


def get_by_path(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return default
    return current


def render_value(value: Any, vars_map: Mapping[str, Any]) -> Any:
    """Render {{ var }} placeholders in strings, dicts, and lists.

    If a string is exactly one placeholder, the original value type is preserved.
    Example: "{{ page_size }}" can become int 200 instead of "200".
    """
    if isinstance(value, str):
        full = _VAR_RE.fullmatch(value)
        if full:
            var_name = full.group(1)
            found = get_by_path(vars_map, var_name, value)
            if found is value:
                logger.warning("Template variable not found: {{ %s }}, keeping placeholder", var_name)
            return found

        def repl(match: re.Match[str]) -> str:
            var_name = match.group(1)
            placeholder = match.group(0)
            found = get_by_path(vars_map, var_name, placeholder)
            if found is placeholder:
                logger.warning("Template variable not found: {{ %s }}, keeping placeholder", var_name)
            return str(found)

        return _VAR_RE.sub(repl, value)

    if isinstance(value, list):
        return [render_value(item, vars_map) for item in value]

    if isinstance(value, dict):
        return {key: render_value(val, vars_map) for key, val in value.items()}

    return value


def build_vars(config: Mapping[str, Any], extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    vars_map: dict[str, Any] = {}
    vars_map.update(config.get("vars", {}) or {})
    if extra:
        vars_map.update(extra)
    return vars_map

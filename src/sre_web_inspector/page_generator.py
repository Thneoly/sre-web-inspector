from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sre_web_inspector.template import render_value

logger = logging.getLogger(__name__)


def expand_page_generators(config: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    generators = config.get("page_generators") or []
    pages: list[dict[str, Any]] = []

    for gen in generators:
        gen_type = gen.get("type", "list")
        max_pages = gen.get("max_pages", 500)

        if gen_type == "ids":
            expanded = _expand_ids(gen, vars_map)
        elif gen_type == "list":
            expanded = _expand_list(gen, vars_map)
        else:
            logger.warning("Unsupported page generator type: %s, skipping", gen_type)
            continue

        if len(expanded) > max_pages:
            raise ValueError(
                f"Page generator '{gen.get('name')}' produced {len(expanded)} pages, "
                f"exceeding max_pages limit of {max_pages}"
            )

        pages.extend(expanded)

    return pages


def _expand_ids(gen: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    id_field = gen.get("id_field", "id")
    ids = gen.get("ids", [])

    list_gen = dict(gen)
    list_gen["type"] = "list"
    list_gen["values"] = [{id_field: val} for val in ids]
    list_gen.pop("id_field", None)
    list_gen.pop("ids", None)

    return _expand_list(list_gen, vars_map)


def _expand_list(gen: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    template = gen.get("template", {})
    values = gen.get("values", [])
    generator_name = gen.get("name", "unknown")

    pages: list[dict[str, Any]] = []

    for item in values:
        item_vars = {**vars_map, **item}

        # Deep copy the template so each page gets its own object
        page = render_value(deepcopy(template), item_vars)

        page.setdefault("_generated", True)
        page.setdefault("_generator", generator_name)

        pages.append(page)

    logger.info("Page generator '%s': expanded %d pages", generator_name, len(pages))
    return pages

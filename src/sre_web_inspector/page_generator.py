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
        elif gen_type == "csv":
            expanded = _expand_csv(gen, vars_map)
        elif gen_type == "json":
            expanded = _expand_json(gen, vars_map)
        elif gen_type == "xlsx":
            expanded = _expand_xlsx(gen, vars_map)
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


def _expand_csv(gen: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    import csv
    from pathlib import Path

    source = gen.get("source")
    if not source:
        raise ValueError("CSV page generator requires 'source' field")

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"CSV source file not found: {source_path}")

    template = gen.get("template", {})
    generator_name = gen.get("name", "unknown")

    with open(source_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []

        pages: list[dict[str, Any]] = []
        for row in reader:
            item_vars = {**vars_map, **row}
            page = render_value(deepcopy(template), item_vars)
            page.setdefault("_generated", True)
            page.setdefault("_generator", generator_name)
            pages.append(page)

    logger.info("Page generator '%s': expanded %d pages from %s", generator_name, len(pages), source)
    return pages


def _expand_json(gen: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    import json
    from pathlib import Path

    source = gen.get("source")
    if not source:
        raise ValueError("JSON page generator requires 'source' field")

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"JSON source file not found: {source_path}")

    template = gen.get("template", {})
    generator_name = gen.get("name", "unknown")
    items_path = gen.get("items_path")

    data = json.loads(source_path.read_text(encoding="utf-8"))

    if items_path:
        # 去掉 $ 前缀，按 . 分割路径
        path = items_path.lstrip("$").lstrip(".")
        if path:
            for part in path.split("."):
                if isinstance(data, dict) and part in data:
                    data = data[part]
                else:
                    raise ValueError(
                        f"items_path '{items_path}' not found in JSON (part '{part}' missing)"
                    )

    if not isinstance(data, list):
        raise ValueError(
            f"JSON source at items_path '{items_path or '$'}' must be a list, got {type(data).__name__}"
        )

    pages: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            row = item
        else:
            row = {"value": item}
        item_vars = {**vars_map, **row}
        page = render_value(deepcopy(template), item_vars)
        page.setdefault("_generated", True)
        page.setdefault("_generator", generator_name)
        pages.append(page)

    logger.info("Page generator '%s': expanded %d pages from %s", generator_name, len(pages), source)
    return pages


def _expand_xlsx(gen: dict[str, Any], vars_map: dict[str, Any]) -> list[dict[str, Any]]:
    from pathlib import Path

    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required for xlsx page generators. Install with: pip install openpyxl"
        )

    source = gen.get("source")
    if not source:
        raise ValueError("XLSX page generator requires 'source' field")

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"XLSX source file not found: {source_path}")

    template = gen.get("template", {})
    generator_name = gen.get("name", "unknown")
    sheet_name = gen.get("sheet_name")

    wb = openpyxl.load_workbook(source_path, read_only=True)
    try:
        ws = wb[sheet_name] if sheet_name else wb.active
        if ws is None:
            return []

        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return []

        headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]

        pages: list[dict[str, Any]] = []
        for row in rows[1:]:
            if all(c is None for c in row):
                continue
            row_dict = {
                headers[i]: (row[i] if i < len(row) and row[i] is not None else "")
                for i in range(len(headers))
            }
            item_vars = {**vars_map, **row_dict}
            page = render_value(deepcopy(template), item_vars)
            page.setdefault("_generated", True)
            page.setdefault("_generator", generator_name)
            pages.append(page)
    finally:
        wb.close()

    logger.info("Page generator '%s': expanded %d pages from %s", generator_name, len(pages), source)
    return pages

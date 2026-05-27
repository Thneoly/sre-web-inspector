from __future__ import annotations

import argparse
import asyncio
import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sre_web_inspector import BrowserContextManager, RequestReplayer
from sre_web_inspector.config_schema import AppConfig, HooksConfig, PageConfig, ReplayRequestConfig
from sre_web_inspector.hooks import run_hooks
from sre_web_inspector.reporter import write_html_report, write_json_report
from sre_web_inspector.inspector import WebInspectionNode
from sre_web_inspector.network.factory import (
    build_context_middleware_manager,
    build_page_middleware_manager,
)
from sre_web_inspector.retry import RetryPolicy, run_with_retry
from sre_web_inspector.run_context import RunContext
from sre_web_inspector.template import build_vars, render_value

logger = logging.getLogger(__name__)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge override into base. Lists are concatenated, dicts are merged recursively."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = result[key] + value
        else:
            result[key] = deepcopy(value)
    return result


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw


def load_and_validate_config(*paths: str | Path) -> tuple[AppConfig, dict[str, Any]]:
    merged: dict[str, Any] = {}
    for path in paths:
        raw = load_config(path)
        merged = deep_merge(merged, raw)
    rendered = render_value(merged, build_vars(merged))
    try:
        return AppConfig.model_validate(rendered), rendered
    except ValidationError as exc:
        raise SystemExit(f"Config validation failed:\n{exc}") from exc


def rewrite_output_dirs(obj: Any, run_output_dir: Path) -> Any:
    """Rewrite middleware output_dir values into outputs/runs/{run_id}/...

    - output_dir: outputs/responses/global -> {run}/responses/global
    - output_dir: outputs/network/pod_page -> {run}/network/pod_page
    - output_dir: responses/global -> {run}/responses/global
    - absolute paths are kept unchanged
    """
    if isinstance(obj, dict):
        new: dict[str, Any] = {}
        for key, value in obj.items():
            if key == "output_dir" and isinstance(value, str):
                path = Path(value)
                if path.is_absolute():
                    new[key] = value
                else:
                    parts = path.parts
                    if parts and parts[0] == "outputs":
                        new[key] = str(run_output_dir.joinpath(*parts[1:]))
                    else:
                        new[key] = str(run_output_dir / path)
            else:
                new[key] = rewrite_output_dirs(value, run_output_dir)
        return new
    if isinstance(obj, list):
        return [rewrite_output_dirs(item, run_output_dir) for item in obj]
    return obj


async def run_replay_requests(
    cm: BrowserContextManager,
    replay_configs: list[ReplayRequestConfig],
    *,
    output_dir: str | Path,
    namespace: str,
    default_retry: RetryPolicy,
    default_timeout: int,
) -> list[dict[str, Any]]:
    if cm.context is None:
        raise RuntimeError("Browser context is not initialized")

    output_dir = Path(output_dir)
    replayer = RequestReplayer(cm.context, output_dir=output_dir)
    results: list[dict[str, Any]] = []

    for item in replay_configs:
        method = item.method.upper()
        timeout = item.timeout or default_timeout
        retry_policy = RetryPolicy.from_config(
            item.retry.model_dump() if item.retry else None,
            default_times=default_retry.times,
            default_interval_ms=default_retry.interval_ms,
        )

        async def do_request():
            if method == "GET":
                return await replayer.get(
                    item.url,
                    name=item.name,
                    params=item.params,
                    headers=item.headers,
                    timeout=timeout,
                )
            if method == "POST" and item.body_type == "json":
                return await replayer.post_json(
                    item.url,
                    name=item.name,
                    data=item.data,
                    headers=item.headers,
                    timeout=timeout,
                )
            if method == "POST" and item.body_type == "form":
                return await replayer.post_form(
                    item.url,
                    name=item.name,
                    form=item.form,
                    headers=item.headers,
                    timeout=timeout,
                )
            if method == "PUT":
                return await replayer.put_json(
                    item.url,
                    name=item.name,
                    data=item.data,
                    headers=item.headers,
                    timeout=timeout,
                )
            if method == "PATCH":
                return await replayer.patch_json(
                    item.url,
                    name=item.name,
                    data=item.data,
                    headers=item.headers,
                    timeout=timeout,
                )
            if method == "DELETE":
                return await replayer.delete(
                    item.url,
                    name=item.name,
                    headers=item.headers,
                    timeout=timeout,
                )
            raise ValueError(f"Unsupported replay request: {item.model_dump()}")

        try:
            result = await run_with_retry(
                do_request,
                policy=retry_policy,
                name=f"replay:{namespace}.{item.name}",
            )
            results.append(
                {
                    "namespace": namespace,
                    "name": result.name,
                    "method": result.method,
                    "url": result.url,
                    "status": result.status,
                    "ok": 200 <= result.status < 400,
                    "output_path": str(result.output_path) if result.output_path else None,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Replay failed: namespace=%s name=%s error=%s", namespace, item.name, exc)
            results.append(
                {
                    "namespace": namespace,
                    "name": item.name,
                    "method": method,
                    "url": item.url,
                    "ok": False,
                    "error": str(exc),
                }
            )

    return results


async def create_wait_tasks(cm: BrowserContextManager, page, page_cfg: PageConfig) -> list[asyncio.Task]:
    tasks: list[asyncio.Task] = []

    for wait_cfg in page_cfg.wait_for_requests:
        keyword = wait_cfg.keyword
        timeout = wait_cfg.timeout
        name = wait_cfg.name or keyword
        task = asyncio.create_task(
            cm.wait_for_request(
                lambda r, keyword=keyword: keyword in r.url,
                page=page,
                timeout=timeout,
            ),
            name=f"wait_request:{name}",
        )
        tasks.append(task)

    for wait_cfg in page_cfg.wait_for_responses:
        keyword = wait_cfg.keyword
        status = wait_cfg.status
        timeout = wait_cfg.timeout
        name = wait_cfg.name or keyword
        task = asyncio.create_task(
            cm.wait_for_response(
                lambda r, keyword=keyword, status=status: (
                    keyword in r.url and (status is None or r.status == status)
                ),
                page=page,
                timeout=timeout,
            ),
            name=f"wait_response:{name}",
        )
        tasks.append(task)

    return tasks


async def consume_wait_tasks(tasks: list[asyncio.Task]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for task in tasks:
        try:
            item = await task
            if hasattr(item, "status"):
                results.append(
                    {
                        "name": task.get_name(),
                        "type": "response",
                        "url": item.url,
                        "status": item.status,
                        "ok": True,
                    }
                )
            else:
                results.append(
                    {
                        "name": task.get_name(),
                        "type": "request",
                        "url": item.url,
                        "method": item.method,
                        "ok": True,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("wait task failed: %s", exc)
            results.append({"name": task.get_name(), "type": "error", "ok": False, "error": str(exc)})
    return results


async def inspect_one_page(
    *,
    cm: BrowserContextManager,
    inspector: WebInspectionNode,
    app_cfg: AppConfig,
    raw_config: dict[str, Any],
    raw_page_cfg: dict[str, Any],
    page_cfg: PageConfig,
    run_ctx: RunContext,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        page_name = page_cfg.name or "page"
        page_output_dir = run_ctx.output_dir
        page = await cm.new_page()

        try:
            if page_cfg.lifecycle.clear_network_records:
                cm.clear_network_records()

            page_manager = build_page_middleware_manager(raw_config, raw_page_cfg)
            await page_manager.bind_to_page(page)

            retry_policy = RetryPolicy.from_config(
                page_cfg.retry.model_dump() if page_cfg.retry else None,
                default_times=app_cfg.runtime.retry.times,
                default_interval_ms=app_cfg.runtime.retry.interval_ms,
            )
            timeout = page_cfg.timeout or app_cfg.runtime.timeout

            pre_replays = await run_replay_requests(
                cm,
                page_cfg.pre_replay_requests,
                output_dir=page_output_dir / "replay" / page_name / "pre",
                namespace=f"{page_name}.pre",
                default_retry=retry_policy,
                default_timeout=timeout,
            )

            wait_tasks = await create_wait_tasks(cm, page, page_cfg)

            async def do_inspect():
                return await inspector.inspect_page(
                    page_cfg.url,
                    page=page,
                    name=page_name,
                    output_dir=page_output_dir,
                    screenshot=page_cfg.screenshot,
                    save_html=page_cfg.save_html,
                    save_network=page_cfg.save_network,
                    wait_ms=page_cfg.wait_ms,
                    timeout=timeout,
                )

            page_hooks = page_cfg.hooks
            if page_hooks and page_hooks.on_page_before_goto:
                await run_hooks(page_hooks.on_page_before_goto, env={
                    "SRE_RUN_ID": run_ctx.run_id,
                    "SRE_PAGE_NAME": page_name,
                    "SRE_PAGE_URL": page_cfg.url,
                })

            inspection = await run_with_retry(
                do_inspect,
                policy=retry_policy,
                name=f"inspect_page:{page_name}",
            )

            if page_hooks and page_hooks.on_page_after_load:
                await run_hooks(page_hooks.on_page_after_load, env={
                    "SRE_RUN_ID": run_ctx.run_id,
                    "SRE_PAGE_NAME": page_name,
                    "SRE_PAGE_URL": page_cfg.url,
                    "SRE_PAGE_TITLE": inspection.get("title", ""),
                })
            waits = await consume_wait_tasks(wait_tasks)

            replays = await run_replay_requests(
                cm,
                page_cfg.replay_requests,
                output_dir=page_output_dir / "replay" / page_name,
                namespace=page_name,
                default_retry=retry_policy,
                default_timeout=timeout,
            )

            return {
                "name": page_name,
                "url": page_cfg.url,
                "ok": True,
                "inspection": inspection,
                "pre_replays": pre_replays,
                "waits": waits,
                "replays": replays,
                "evidence": {
                    "screenshot": inspection.get("screenshot"),
                    "html": inspection.get("html"),
                    "network": inspection.get("network"),
                    "replay_dir": str(page_output_dir / "replay" / page_name),
                },
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Page inspection failed: %s", page_name)
            return {"name": page_name, "url": page_cfg.url, "ok": False, "error": str(exc)}
        finally:
            if page_cfg.lifecycle.close_after_inspection:
                await page.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", action="append", default=None, help="Config file(s), merged in order")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--page", default=None, help="Run only the named page(s), comma-separated")
    parser.add_argument("--list-pages", action="store_true", help="List page names from config and exit")
    parser.add_argument("--output-format", default="json,html", help="Output formats: json,html (comma-separated)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    config_paths = args.config or ["config/example.yaml"]

    app_cfg, rendered_config = load_and_validate_config(*config_paths)
    if args.validate_only:
        print("Config validation passed")
        return

    if args.list_pages:
        for page in app_cfg.pages:
            print(page.name or page.url)
        return

    run_ctx = RunContext.create(app_cfg.runtime.output_dir, app_cfg.runtime.run_id)
    rendered_config = rewrite_output_dirs(rendered_config, run_ctx.output_dir)
    logger.info("run_id=%s output_dir=%s", run_ctx.run_id, run_ctx.output_dir)

    browser_cfg = app_cfg.browser.model_dump(exclude_none=True)

    async with BrowserContextManager(**browser_cfg) as cm:
        if cm.context is None:
            raise RuntimeError("Browser context is not initialized")

        context_network_manager = build_context_middleware_manager(rendered_config)
        await context_network_manager.bind_to_context(cm.context)

        if app_cfg.hooks and app_cfg.hooks.on_browser_start:
            await run_hooks(app_cfg.hooks.on_browser_start, env={
                "SRE_RUN_ID": run_ctx.run_id,
                "SRE_OUTPUT_DIR": str(run_ctx.output_dir),
            })

        default_retry = RetryPolicy.from_config(app_cfg.runtime.retry.model_dump())
        global_replays = await run_replay_requests(
            cm,
            app_cfg.replay_requests,
            output_dir=run_ctx.output_dir / "replay" / "global",
            namespace="global",
            default_retry=default_retry,
            default_timeout=app_cfg.runtime.timeout,
        )

        inspector = WebInspectionNode(cm)
        semaphore = asyncio.Semaphore(app_cfg.runtime.concurrency)

        raw_pages = rendered_config.get("pages", []) or []

        # Filter pages when --page is specified
        page_filter: set[str] | None = None
        if args.page:
            page_filter = {p.strip() for p in args.page.split(",")}

        def _page_matches(name: str | None, url: str) -> bool:
            if page_filter is None:
                return True
            return (name or "") in page_filter or url in page_filter

        page_tasks = [
            asyncio.create_task(
                inspect_one_page(
                    cm=cm,
                    inspector=inspector,
                    app_cfg=app_cfg,
                    raw_config=rendered_config,
                    raw_page_cfg=raw_page_cfg,
                    page_cfg=page_cfg,
                    run_ctx=run_ctx,
                    semaphore=semaphore,
                )
            )
            for raw_page_cfg, page_cfg in zip(raw_pages, app_cfg.pages, strict=False)
            if _page_matches(page_cfg.name, page_cfg.url)
        ]
        page_results = await asyncio.gather(*page_tasks)

        if app_cfg.hooks and app_cfg.hooks.on_run_complete:
            await run_hooks(app_cfg.hooks.on_run_complete, env={
                "SRE_RUN_ID": run_ctx.run_id,
                "SRE_OUTPUT_DIR": str(run_ctx.output_dir),
                "SRE_ALL_OK": str(all(page.get("ok") for page in page_results)),
            })

        summary = {
            "kind": "WebInspectionRun",
            "run_id": run_ctx.run_id,
            "output_dir": str(run_ctx.output_dir),
            "ok": all(page.get("ok") for page in page_results),
            "global_replays": global_replays,
            "pages": page_results,
        }

        output_formats = {f.strip() for f in args.output_format.split(",")}

        if "json" in output_formats:
            json_path = write_json_report(summary, run_ctx.output_dir)
            logger.info("JSON report saved to %s", json_path)

        if "html" in output_formats:
            html_path = write_html_report(summary, run_ctx.output_dir)
            logger.info("HTML report saved to %s", html_path)

        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

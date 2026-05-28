"""
完整巡检流水线示例 — Middleware + Login + Page Inspection + Replay + Report。

演示从 YAML 配置加载到生成报告的完整流程：
  1. 加载并校验 YAML 配置（含 page_generators 展开）
  2. 启动 BrowserContext
  3. 绑定 context/network middleware（拦截/修改请求和响应）
  4. 执行 LoginFlow（可选）
  5. 并发巡检所有 pages
  6. 收集 evidence（screenshot, HTML, network, API 响应）
  7. 生成 JSON + HTML 报告

运行：
  uv run python examples/full_inspection.py

对比 YAML 方式：
  uv run python main.py --config config/example.yaml
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from sre_web_inspector import BrowserContextManager
from sre_web_inspector.config_schema import AppConfig
from sre_web_inspector.hooks import run_hooks
from sre_web_inspector.inspector import WebInspectionNode
from sre_web_inspector.network.factory import (
    build_context_middleware_manager,
    build_page_middleware_manager,
)
from sre_web_inspector.page_generator import expand_page_generators
from sre_web_inspector.reporter import write_html_report, write_json_report
from sre_web_inspector.request_replayer import RequestReplayer
from sre_web_inspector.retry import RetryPolicy, run_with_retry
from sre_web_inspector.run_context import RunContext
from sre_web_inspector.template import build_vars, render_value

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# 完整巡检流水线
# ═══════════════════════════════════════════════════════════════════════

async def run_full_inspection(config: dict) -> dict:
    """
    完整巡检流水线。

    等同于 main.py 的核心逻辑，适合在脚本中自定义流程。
    """
    # 1. 加载配置
    vars_map = build_vars(config)
    rendered_config = render_value(config, vars_map)
    app_config = AppConfig.model_validate(rendered_config)

    print(f"Config loaded: {len(app_config.pages)} static pages")
    if app_config.page_generators:
        print(f"  + {len(app_config.page_generators)} page generators")

    # 2. 展开 page_generators
    generated_pages = expand_page_generators(rendered_config, vars_map)
    all_pages = rendered_config.get("pages") or []
    if generated_pages:
        all_pages = all_pages + generated_pages
        print(f"  → {len(generated_pages)} generated pages")

    # 3. 创建 RunContext
    run_ctx = RunContext.create(
        base_output_dir=app_config.runtime.output_dir,
        run_id=app_config.runtime.run_id,
    )
    print(f"Run: {run_ctx.run_id}")

    # 4. 启动浏览器
    browser_cfg = app_config.browser.model_dump(exclude_none=True)
    async with BrowserContextManager(**browser_cfg) as cm:
        if cm.context is None:
            raise RuntimeError("Browser context not initialized")

        # 5. 绑定 context 级 middleware
        context_manager = build_context_middleware_manager(rendered_config)
        await context_manager.bind_to_context(cm.context)

        # 6. Login（如果配置了）
        if app_config.login and app_config.login.enabled:
            from sre_web_inspector.auth.login_flow import LoginFlow
            flow = LoginFlow(cm, app_config, run_ctx)
            result = await flow.run()
            print(f"Login: {result.reason or ('skipped (already logged in)' if result.skipped else 'ok')}")

        # 7. 全局 API replay
        replayer = RequestReplayer(cm.context, output_dir=run_ctx.output_dir / "replay" / "global")
        global_replay_results = []
        for req_cfg in app_config.replay_requests:
            result = await replayer.get(
                req_cfg.url,
                name=req_cfg.name,
                params=req_cfg.params,
                timeout=req_cfg.timeout or 60000,
            )
            global_replay_results.append(result)
            print(f"  Replay [{req_cfg.name}]: status={result.status}")

        # 8. 并发巡检所有 pages
        semaphore = asyncio.Semaphore(app_config.runtime.concurrency)
        inspector = WebInspectionNode(cm)

        async def inspect_one(page_cfg: dict) -> dict:
            async with semaphore:
                page = await cm.new_page()
                try:
                    page_manager = build_page_middleware_manager(rendered_config, page_cfg)
                    await page_manager.bind_to_page(page)

                    if page_cfg.get("hooks"):
                        hook_cfg = page_cfg["hooks"].get("on_page_before_goto")
                        if hook_cfg:
                            await run_hooks(hook_cfg, env={
                                "SRE_PAGE_NAME": page_cfg.get("name", ""),
                                "SRE_PAGE_URL": page_cfg.get("url", ""),
                            })

                    retry = RetryPolicy.from_config(page_cfg.get("retry"))

                    async def do_inspect():
                        return await inspector.inspect_page(
                            url=page_cfg["url"],
                            page=page,
                            name=page_cfg.get("name"),
                            screenshot=page_cfg.get("screenshot", True),
                            save_html=page_cfg.get("save_html", True),
                            save_network=page_cfg.get("save_network", True),
                            wait_ms=page_cfg.get("wait_ms", 1000),
                            timeout=page_cfg.get("timeout", 60000),
                        )

                    return await run_with_retry(do_inspect, policy=retry, name=page_cfg.get("name", "page"))
                except Exception as exc:
                    logger.warning("Page inspection failed: %s", exc)
                    return {"error": str(exc), "url": page_cfg.get("url", ""), "name": page_cfg.get("name")}
                finally:
                    if page_cfg.get("lifecycle", {}).get("close_after_inspection", True):
                        await page.close()

        tasks = [inspect_one(p) for p in all_pages]
        page_results: list[dict] = list(await asyncio.gather(*tasks))

        # 9. 收集结果（失败时返回 {"error": ..., "url": ..., "name": ...}）
        all_ok = all("error" not in r for r in page_results)
        pages_summary = []
        for r in page_results:
            pages_summary.append({
                "name": r.get("name", "unknown"),
                "url": r.get("url", ""),
                "ok": "error" not in r,
                "error": r.get("error"),
                "evidence": {
                    "screenshot": r.get("screenshot"),
                    "html": r.get("html"),
                    "network": r.get("network"),
                },
            })

        summary = {
            "kind": "WebInspectionRun",
            "run_id": run_ctx.run_id,
            "ok": all_ok,
            "output_dir": str(run_ctx.output_dir),
            "pages": pages_summary,
            "global_replays": [
                {"name": r.name, "method": r.method, "url": r.url, "status": r.status, "ok": r.status < 400}
                for r in global_replay_results
            ],
        }

        print(f"\nFinished: {'ALL OK' if all_ok else 'SOME FAILED'}")
        print(f"  Pages: {len(page_results)} ({sum(1 for r in page_results if 'error' not in r)} ok)")
        print(f"  Replays: {len(global_replay_results)}")
        print(f"  Output: {run_ctx.output_dir}")

        return summary


# ═══════════════════════════════════════════════════════════════════════
# Demo
# ═══════════════════════════════════════════════════════════════════════

async def main() -> None:
    """使用本地 echo 服务器演示完整流水线。"""
    import http.server
    import threading

    # 启动一个本地 HTTP 服务器模拟巡检目标
    class MockHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if "/api/" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok","path":"' + self.path.encode() + b'"}')
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Hello SRE</h1><div class='user-menu'>admin</div></body></html>")

    server = http.server.HTTPServer(("127.0.0.1", 0), MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    print(f"Mock server at {base_url}\n")

    config = {
        "vars": {"base_url": base_url},
        "runtime": {
            "output_dir": str(Path(tempfile.mkdtemp(prefix="sre_example_"))),
            "concurrency": 2,
            "timeout": 30000,
            "retry": {"times": 1, "interval_ms": 500},
        },
        "browser": {"headless": True, "slow_mo": 0},
        "context_middlewares": {
            "routes": [
                {
                    "name": "block_images",
                    "pattern": "**/*",
                    "middlewares": [{"type": "block_resource", "resource_types": ["image", "font"]}],
                }
            ]
        },
        "network_middlewares": {
            "responses": [
                {
                    "type": "json_response_saver",
                    "output_dir": "outputs/responses",
                    "url_keywords": ["/api/"],
                }
            ]
        },
        "replay_requests": [
            {"name": "status_check", "method": "GET", "url": "{{ base_url }}/api/status", "timeout": 10000},
        ],
        "page_generators": [
            {
                "name": "section_pages",
                "type": "list",
                "values": [{"section": "pods"}, {"section": "nodes"}, {"section": "services"}],
                "template": {
                    "name": "{{ section }}_page",
                    "url": "{{ base_url }}/{{ section }}",
                    "screenshot": True,
                    "save_html": True,
                    "save_network": True,
                    "wait_ms": 500,
                    "lifecycle": {"close_after_inspection": True},
                },
            }
        ],
        "pages": [
            {
                "name": "home",
                "url": "{{ base_url }}/",
                "screenshot": True,
                "save_html": True,
                "save_network": True,
                "wait_ms": 500,
            }
        ],
    }

    try:
        summary = await run_full_inspection(config)
    finally:
        server.shutdown()

    # 生成报告
    output_path = Path(summary["output_dir"])
    write_json_report(summary, output_path)
    html_path = write_html_report(summary, output_path)
    print(f"\nReport: {html_path}")
    print(f"  JSON: {output_path / 'run_result.json'}")
    print(f"  HTML: {html_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())

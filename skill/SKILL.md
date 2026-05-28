---
name: sre-web-inspector
description: SRE web inspection toolkit based on Playwright. Use when the user needs to write or debug YAML inspection configs, create custom network middlewares (route/request/response), analyze inspection output, add new collectors, or extend the replay/retry/template systems. Triggers include: "inspect a page", "add a middleware", "create a route modifier", "write a collector", "debug a config", "replay an API", "add a template variable", "set up retry", "generate a report".
---

# SRE Web Inspector

A Playwright-based toolkit for SRE web inspection, API replay, and evidence collection. Configured via YAML with Pydantic validation and `{{ var }}` template substitution.

## Commands

```bash
# Install
uv sync --extra dev
playwright install chromium

# Validate config only (no browser)
uv run python main.py --validate-only

# List pages in config
uv run python main.py --list-pages

# Run all pages
uv run python main.py --config config/example.yaml

# Merge multiple configs (later files override)
uv run python main.py --config base.yaml --config env/prod.yaml

# Run only specific pages
uv run python main.py --page pod_page
uv run python main.py --page "pod_page,grafana_page"

# Business collectors (datamarket)
uv run python run_lizhi.py                          # lizhi.shop software catalog
uv run python run_lizhi.py --max-pages 3 --no-headless
uv run python run_cninfo.py                         # cninfo announcements
uv run python run_cninfo.py --exchanges szse bj --max-clicks 5

# Tests
uv run pytest -v                                    # 249 tests
uv run pytest tests/test_template.py -v
```

## Architecture (quick reference)

```
src/
├── sre_web_inspector/            # Core library
│   ├── config_schema.py          # Pydantic v2 models (AppConfig root)
│   ├── browser_context.py        # BrowserContextManager (launch, nav, screenshot)
│   ├── inspector.py              # WebInspectionNode (per-page visit + evidence)
│   ├── page_generator.py         # expand_page_generators() — template-based page expansion
│   ├── request_replayer.py       # RequestReplayer (API calls reusing browser auth)
│   ├── template.py               # {{ var }} substitution, type-preserving
│   ├── retry.py                  # RetryPolicy + run_with_retry
│   ├── run_context.py            # outputs/runs/{run_id}/ directory creation
│   ├── hooks.py                  # Lifecycle hooks (shell commands)
│   ├── reporter.py               # HTML + JSON report generation (dual-format: inspection + generic)
│   ├── request_utils.py          # URL patch, JSON merge, header mask, safe filename
│   ├── route_modifier.py         # Playwright route modification helpers
│   ├── base_collector.py         # BaseCollector[T] — generic abstract base for business collectors
│   ├── api_capture.py            # ApiCapture — in-memory JSON response interception
│   ├── paginator.py              # paginate_by_url / paginate_by_click async generators
│   ├── auth/                     # Login subsystem
│   │   ├── login_flow.py         # LoginFlow orchestrator
│   │   ├── login_result.py       # LoginResult dataclass
│   │   ├── session_checker.py    # SessionChecker (5 check types)
│   │   └── strategies.py         # Manual/Form/Cookie login strategies
│   ├── collectors/               # ApiCollector, GrafanaCollector, TableCollector
│   └── network/                  # Middleware system
│       ├── contexts.py           # RouteContext, RequestContext, ResponseContext
│       ├── middleware.py          # Abstract base classes
│       ├── manager.py            # NetworkMiddlewareManager + binding logic
│       ├── factory.py            # Build managers from config dicts
│       └── middlewares/          # Built-in implementations
│           ├── query_param_patch.py
│           ├── post_json_patch.py
│           ├── header_patch.py
│           ├── block_resource.py
│           ├── mock_response.py
│           ├── recorders.py
│           ├── response_saver.py
│           └── masker.py
└── datamarket/                   # Business logic
    ├── lizhi_inspector.py        # lizhi.shop software scraper (extends BaseCollector)
    └── cninfo_collector.py       # cninfo announcement collector (extends BaseCollector)
main.py                           # CLI entry, orchestration pipeline
run_lizhi.py                      # lizhi.shop entry point
run_cninfo.py                     # cninfo entry point
config/                           # YAML config files
tests/                            # pytest (249 tests)
```

## Core pipeline

```
YAML files → deep_merge → render_value({{ vars }}) → expand_page_generators → Pydantic validate
  → RunContext(outputs/runs/{run_id}/) → rewrite_output_dirs
  → BrowserContextManager.start (launch_persistent_context)
  → bind context_middlewares → LoginFlow (check session → login strategy)
  → global replay_requests
  → for each page (concurrent, semaphore-gated):
      new_page → bind merged middlewares → pre_replay_requests
      → hooks.on_page_before_goto → goto → wait → hooks.on_page_after_load
      → replay_requests → collect screenshot/HTML/network
  → hooks.on_run_complete → write run_result.json + run_result.html
```

## Middleware system

Three layers, each with a context dataclass and abstract base class:

| Layer    | Context         | Binding API              | Can short-circuit? |
|----------|-----------------|--------------------------|--------------------|
| Route    | `RouteContext`  | `page.route(pattern)`    | Yes (skip next_call)|
| Request  | `RequestContext`| `page.on("request")`     | No                 |
| Response | `ResponseContext`| `page.on("response")`    | No                 |

**Route middlewares** form a chain. Call `await next_call()` to pass control to the next middleware. Don't call it to short-circuit (abort, fulfill, or consume the request).

**Binding scopes** (broadest to narrowest):
1. `context_middlewares` → entire BrowserContext
2. `network_middlewares` (top-level) → default for all pages
3. `pages[].network_middlewares` → merged on top of global defaults (lists concatenated)

**Programmatic registration**: `inspector.add_response_middleware(mw)` registers a `ResponseMiddleware` instance that applies to all subsequent `inspect_page` calls.

### Creating a custom route middleware

```python
# src/sre_web_inspector/network/middlewares/my_middleware.py
from ..contexts import RouteContext
from ..middleware import RouteMiddleware, NextCall

class MyMiddleware(RouteMiddleware):
    def __init__(self, *, custom_option: str = "default"):
        self.custom_option = custom_option

    async def handle(self, ctx: RouteContext, next_call: NextCall):
        # ctx.url, ctx.method, ctx.headers, ctx.post_data are mutable
        if some_condition(ctx):
            ctx.handled = True
            return await ctx.route.abort()  # or ctx.route.fulfill(...)
        return await next_call()
```

Then register it in `src/sre_web_inspector/network/factory.py` in `build_route_middleware()`.

### Creating a custom response middleware

```python
from ..contexts import ResponseContext
from ..middleware import ResponseMiddleware

class MyResponseMiddleware(ResponseMiddleware):
    async def handle(self, ctx: ResponseContext) -> None:
        # ctx.url, ctx.status, ctx.headers, ctx.response are available
        if "application/json" in ctx.headers.get("content-type", ""):
            data = await ctx.response.json()
            # process data...
```

## Business collector patterns

### BaseCollector[T] — abstract base

Eliminates ~70% boilerplate. Subclass and implement `collect()`:

```python
from dataclasses import dataclass
from typing import Any
from sre_web_inspector.base_collector import BaseCollector

@dataclass
class MyItem:
    name: str
    value: int
    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}

class MyCollector(BaseCollector[MyItem]):
    async def collect(self) -> list[MyItem]:
        page = self.cm.page
        await page.goto("https://example.com")
        self.results = [MyItem("a", 1), MyItem("b", 2)]
        return self.results

# save_results handles dedup, JSON, HTML report in one call:
summary = collector.save_results(
    kind="MyCollection",
    filename="my_results.json",
    dedup_key=lambda item: item.name,
    api_captures=capture.responses,
    source="https://example.com",
)
```

Auto-provided attributes: `self.cm`, `self.inspector`, `self.run_ctx`, `self.retry_policy`, `self.timeout`, `self.output_dir`.

### ApiCapture — in-memory JSON capture

Lightweight, no disk round-trip. Uses a synchronous `_scheduled` counter to prevent over-scheduling:

```python
from sre_web_inspector.api_capture import ApiCapture

cap = ApiCapture(url_keywords=["/api/data"], url_exclude=["/analytics/"], max_captures=200)
cap.attach(page)
await page.goto("https://example.com")
# cap.responses = [{"url": "...", "status": 200, "data": {...}}, ...]
cap.detach(page)
```

### Paginator — two async generator patterns

```python
from sre_web_inspector.paginator import paginate_by_url, paginate_by_click

# URL increment: creates a new page per URL
async for pg_num, page in paginate_by_url(new_page, "https://x.com?page={page}", start=1, max_pages=10):
    extract_data(page)
    await page.close()

# Click button: reuses one page, auto-detects disabled state
async for click_num, page in paginate_by_click(page, next_selector=".btn-next", max_clicks=10):
    extract_data(page)  # click_num=0 is first page (before clicking)
```

### SPA-aware inspect_page

```python
await self.inspector.inspect_page(
    url,
    page=page,
    wait_for_network_idle=True,           # wait for XHR/fetch to settle
    wait_for_selector='a[href*="id"]',    # wait for specific DOM element
    wait_ms=1000,
)
```

## Config patterns

### Variable substitution

- `{{ var }}` in strings, supports dot-path: `{{ nested.key }}`
- Fullmatch placeholders preserve original type: `"{{ count }}"` with `count: 200` → `int` 200
- Missing variables log a warning and keep the placeholder text

### Retry inheritance

Global defaults → page-level override → replay-level override. Each level can override `times` and `interval_ms`.

### Output directory layout

```
outputs/runs/{run_id}/
├── screenshots/{page_name}.png
├── html/{page_name}.html
├── network/{page_name}.json
├── responses/{md5_hash}.json
├── login/                     # Login evidence (screenshots, storage_state)
│   ├── login_before.png
│   ├── login_after.png
│   └── storage_state.json
├── replay/
│   ├── global/{name}.json
│   └── {page_name}/
│       ├── pre/{name}.json
│       └── {name}.json
├── run_result.json
└── run_result.html
```

Middleware `output_dir` values with relative paths are rewritten into the run directory at startup.

### Hook configuration

```yaml
hooks:
  on_browser_start:
    commands:
      - "echo 'Browser ready: $SRE_RUN_ID'"
      - "curl -X POST https://hooks.slack.com/... -d '{\"text\":\"Inspection started\"}'"
    timeout: 30

pages:
  - name: my_page
    url: https://example.com
    hooks:
      on_page_before_goto:
        commands:
          - "echo 'Opening $SRE_PAGE_URL'"
      on_page_after_load:
        commands:
          - "echo 'Loaded: $SRE_PAGE_TITLE'"
```

Environment variables available: `SRE_RUN_ID`, `SRE_OUTPUT_DIR`, `SRE_PAGE_NAME`, `SRE_PAGE_URL`, `SRE_PAGE_TITLE`, `SRE_ALL_OK`.

## Debugging checklist

1. **Config won't validate**: Run `uv run python main.py --validate-only`. Check Pydantic error messages for field name and constraint.
2. **Template variable not replaced**: Look for `WARNING:sre_web_inspector.template` log lines. Check that the var name in `vars:` matches exactly.
3. **Page timeout**: Increase `timeout` or set `wait_ms` lower. Check network connectivity from the browser context.
4. **Middleware not firing**: Check the URL `pattern` glob. Patterns are Playwright route patterns (e.g., `**/*/api/pods*`). Use `--list-pages` to verify the page is configured.
5. **Replay fails**: Check `run_result.json` → `global_replays` or `pages[].replays` for error messages. Verify the browser context has valid auth cookies.
6. **Output directory empty**: Middleware `output_dir` is rewritten at startup. Relative paths go into `outputs/runs/{run_id}/`. Check `run_result.json` for the actual output paths.
7. **ApiCapture over-scheduling**: The `_scheduled` counter is incremented synchronously in `handler()` before `ensure_future`. This prevents race conditions where all loop iterations pass the capacity check before any async task completes.

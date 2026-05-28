# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

SRE web inspection toolkit built on Playwright (Python, async). Drives a Chromium browser to visit pages, intercept/modify network requests, replay API calls, and collect evidence (screenshots, HTML snapshots, network traces, API responses). Configured via YAML with Pydantic validation and `{{ var }}` template substitution.

Source lives under `src/`. Core library in `src/sre_web_inspector/`. Business logic in `src/datamarket/`.

## Commands

```bash
# Install
uv sync --extra dev
playwright install chromium

# Run an inspection
uv run python main.py --config config/example.yaml

# Validate config only (no browser)
uv run python main.py --validate-only

# List configured pages
uv run python main.py --list-pages

# Run only specific pages
uv run python main.py --page pod_page

# Merge multiple configs
uv run python main.py --config base.yaml --config env/prod.yaml

# Business scrapers
uv run python run_lizhi.py --no-headless --max-pages 2
uv run python run_cninfo.py --exchanges szse bj --max-clicks 3

# Tests
uv run pytest -v
uv run pytest tests/test_template.py -v
```

## Architecture

### Source layout

```
src/
├── sre_web_inspector/       # Core library
│   ├── config_schema.py     # Pydantic v2 models (AppConfig root)
│   ├── browser_context.py   # BrowserContextManager (launch, nav, screenshot)
│   ├── inspector.py         # WebInspectionNode (per-page visit + evidence, SPA-aware)
│   ├── base_collector.py    # BaseCollector[T] abstract class for data-collection tasks
│   ├── api_capture.py       # ApiCapture — in-memory JSON response interception
│   ├── paginator.py         # paginate_by_url / paginate_by_click async generators
│   ├── page_generator.py    # expand_page_generators() — template-based page expansion
│   ├── request_replayer.py  # RequestReplayer (API calls reusing browser auth)
│   ├── template.py          # {{ var }} substitution, type-preserving
│   ├── retry.py             # RetryPolicy + run_with_retry
│   ├── run_context.py       # outputs/runs/{run_id}/ directory creation
│   ├── hooks.py             # Lifecycle hooks (shell commands)
│   ├── reporter.py          # HTML + JSON report (generic + WebInspectionRun)
│   ├── request_utils.py     # URL patch, JSON merge, header mask
│   ├── route_modifier.py    # Playwright route modification helpers
│   ├── auth/                # Login subsystem
│   │   ├── login_flow.py    # LoginFlow orchestrator
│   │   ├── login_result.py  # LoginResult dataclass
│   │   ├── session_checker.py  # SessionChecker (5 check types)
│   │   └── strategies.py    # Manual/Form/Cookie login strategies
│   ├── collectors/          # ApiCollector, GrafanaCollector, TableCollector
│   └── network/             # Middleware system
│       ├── contexts.py      # RouteContext, RequestContext, ResponseContext
│       ├── middleware.py     # Abstract base classes
│       ├── manager.py       # NetworkMiddlewareManager + binding logic
│       ├── factory.py       # Build managers from config dicts
│       └── middlewares/     # Built-in implementations
└── datamarket/              # Business logic
    ├── lizhi_inspector.py   # Lizhi.shop product catalog scraper
    └── cninfo_collector.py  # Cninfo announcement collector (深市/沪市/北交所)
tests/                       # pytest (314 tests)
main.py                      # CLI entry point (YAML-driven inspection)
run_lizhi.py                 # CLI entry point (lizhi.shop scraper)
run_cninfo.py                # CLI entry point (cninfo announcement scraper)
config/                      # YAML config files
examples/                    # Runnable example scripts

### Examples

```bash
uv run python examples/page_generation.py    # Page generators demo
uv run python examples/login_flow.py         # Login flow patterns
uv run python examples/hooks_lifecycle.py    # Lifecycle hooks
uv run python examples/full_inspection.py    # Complete end-to-end pipeline
uv run python examples/custom_middleware.py  # Custom middleware
```

### Entry point (`main.py`)

1. Loads YAML config(s), deep-merges them, expands `page_generators` into concrete pages, renders `{{ var }}` templates, validates with Pydantic (`AppConfig`)
2. Creates a `RunContext` → `outputs/runs/{run_id}/` with subdirectories
3. Rewrites relative `output_dir` paths in middleware config to point into the run directory
4. Launches `BrowserContextManager` (persistent context via `launch_persistent_context`)
5. Runs `on_browser_start` hooks, binds `context_middlewares` to the BrowserContext
6. Runs `LoginFlow` (if `login.enabled`): check session → execute login strategy → handle on_failure
7. Runs global `replay_requests` (API calls reusing browser auth context)
8. For each page in `pages[]`, concurrently (gated by `asyncio.Semaphore`):
   - Creates a new Page, binds merged middleware (global `network_middlewares` + page-specific `network_middlewares`)
   - Runs `on_page_before_goto` hook → `pre_replay_requests` → opens page → waits → runs `replay_requests` → `on_page_after_load` hook
   - Collects screenshots, HTML, network JSON, replay results
9. Runs `on_run_complete` hook, writes `run_result.json` and `run_result.html`

### Key components for business code

**`BaseCollector[T]`** (`base_collector.py`) — Abstract base for data-collection classes. Provides:
- Standard `__init__(cm, run_ctx, retry_policy, timeout)` and `output_dir` property
- `save_results(kind, filename, dedup_key, api_captures, **extra)` — dedup, JSON dump, HTML+JSON reports
- `_dedup(items, key)` — deduplication helper

**`ApiCapture`** (`api_capture.py`) — In-memory JSON response interception:
- `cap = ApiCapture(url_keywords=["/api/"], max_captures=200)`
- `cap.attach(page)` / `cap.detach(page)` — register/remove event listener
- `cap.responses` — `list[dict]` with `url`, `status`, `data` keys

**`Paginator`** (`paginator.py`) — Two pagination patterns:
- `paginate_by_url(page_factory, url_template="{page}", start=1, max_pages=0)` — URL-based
- `paginate_by_click(page, next_selector=".btn-next", max_clicks=10)` — click-based
- Both are async generators yielding `(page_num, page)` tuples

**`WebInspectionNode`** (`inspector.py`) — SPA-aware page inspection:
- `inspect_page(url, wait_for_network_idle=True, wait_for_selector="...")` — two new SPA params
- `add_response_middleware(mw)` — register `ResponseMiddleware` instances from code

**`Reporter`** (`reporter.py`) — Dual-format HTML rendering:
- `kind: "WebInspectionRun"` → inspection-specific layout (backward-compatible)
- Any other `kind` → generic key-value summary + items table

### Middleware system

Three layers, each with a context dataclass and abstract base class:

| Level | Interface | Binding | Context |
|-------|-----------|---------|---------|
| Route | `RouteMiddleware.handle(ctx, next_call)` | URL pattern → `page.route()` | `RouteContext` (mutable url/headers/post_data) |
| Request | `RequestMiddleware.handle(ctx)` | `page.on("request")` | `RequestContext` (read-only) |
| Response | `ResponseMiddleware.handle(ctx)` | `page.on("response")` | `ResponseContext` (read-only) |

Route middlewares form a chain (call `next_call()` to continue, skip it to short-circuit). Built-in route middlewares: `QueryParamPatch`, `PostJsonPatch`, `HeaderPatch`, `BlockResource`, `MockResponse`, `RouteRecorder`, `SensitiveMasker`. Request middlewares: `RequestRecorder`. Response middlewares: `JsonResponseSaver`.

Response middlewares can also be registered programmatically via `WebInspectionNode.add_response_middleware()` — no YAML config needed.

### Middleware binding scopes

Three levels, from broadest to narrowest:
1. `context_middlewares` — bound to `BrowserContext`, affects every page
2. `network_middlewares` (top-level) — default page middleware, inherited by all pages
3. `pages[].network_middlewares` — page-specific, merged on top of global defaults (routes/requests/responses lists are concatenated)

### Config variable flow

```
YAML files → deep_merge → render_value(raw, build_vars(raw)) → expand_page_generators → AppConfig.model_validate → rewrite_output_dirs
```

`rewrite_output_dirs` patches relative `output_dir` paths inside middleware config to point into `outputs/runs/{run_id}/`.

### Page generators

`page_generators` 从 YAML 内联数据或外部文件批量生成 pages。变量来自顶层 `vars:` 块 + 每行数据的字段。

**`type: ids`** — 内联 ID 列表：

```yaml
page_generators:
  - name: pod_pages
    type: ids
    id_field: pod
    ids: [pod-a, pod-b]
    template:
      name: "pod_{{ pod }}"
      url: "{{ base_url }}/k8s/{{ namespace }}/pods/{{ pod }}"
```

**`type: list`** — 内联 dict 列表：

```yaml
page_generators:
  - name: env_pages
    type: list
    values:
      - {env: dev, region: us}
      - {env: prod, region: eu}
    template:
      name: "{{ env }}-dashboard"
      url: "{{ base_url }}/{{ region }}/{{ env }}/dashboard"
```

**`type: csv`** — 从 CSV 文件读取（首行为列名），支持 BOM：

```yaml
page_generators:
  - name: resource_pages
    type: csv
    source: config/resources.csv
    max_pages: 500
    template:
      name: "resource_{{ resource_id }}"
      url: "{{ base_url }}/ids/{{ resource_id }}/query"
```

**`type: json`** — 从 JSON 文件读取，可选 `items_path` 定位数组：

```yaml
# JSON 根为数组：[{"id":"1001"}, {"id":"1002"}]
page_generators:
  - name: pod_pages
    type: json
    source: config/pods.json
    template:
      name: "pod_{{ id }}"
      url: "{{ base_url }}/pods/{{ id }}"

# JSON 嵌套路径：{"data":{"items":[...]}}
page_generators:
  - name: dashboard_pages
    type: json
    source: config/dashboards.json
    items_path: "$.data.items"    # 或 "data.items"
    template:
      name: "dashboard_{{ uid }}"
      url: "{{ grafana_url }}/d/{{ uid }}"
```

**`type: xlsx`** — 从 Excel 文件读取（首行为列名），可选 `sheet_name`：

```yaml
page_generators:
  - name: middleware_pages
    type: xlsx
    source: config/middleware.xlsx
    sheet_name: instances         # 可选，默认为第一个 sheet
    max_pages: 200
    template:
      name: "mw_{{ instance_id }}"
      url: "{{ base_url }}/middleware/{{ instance_id }}/metrics"
```

所有类型共用 `max_pages` 上限检查（默认 500）。CSV/JSON/Excel 的 `source` 路径相对于执行 `main.py` 的工作目录。

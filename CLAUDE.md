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
│   ├── request_replayer.py  # RequestReplayer (API calls reusing browser auth)
│   ├── template.py          # {{ var }} substitution, type-preserving
│   ├── retry.py             # RetryPolicy + run_with_retry
│   ├── run_context.py       # outputs/runs/{run_id}/ directory creation
│   ├── hooks.py             # Lifecycle hooks (shell commands)
│   ├── reporter.py          # HTML + JSON report (generic + WebInspectionRun)
│   ├── request_utils.py     # URL patch, JSON merge, header mask
│   ├── route_modifier.py    # Playwright route modification helpers
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
tests/                       # pytest (141 tests)
main.py                      # CLI entry point (YAML-driven inspection)
run_lizhi.py                 # CLI entry point (lizhi.shop scraper)
run_cninfo.py                # CLI entry point (cninfo announcement scraper)
config/                      # YAML config files
```

### Entry point (`main.py`)

1. Loads YAML config(s), deep-merges them, renders `{{ var }}` templates, validates with Pydantic (`AppConfig`)
2. Creates a `RunContext` → `outputs/runs/{run_id}/` with subdirectories
3. Rewrites relative `output_dir` paths in middleware config to point into the run directory
4. Launches `BrowserContextManager` (persistent context via `launch_persistent_context`)
5. Runs `on_browser_start` hooks, binds `context_middlewares` to the BrowserContext
6. Runs global `replay_requests` (API calls reusing browser auth context)
7. For each page in `pages[]`, concurrently (gated by `asyncio.Semaphore`):
   - Creates a new Page, binds merged middleware (global `network_middlewares` + page-specific `network_middlewares`)
   - Runs `on_page_before_goto` hook → `pre_replay_requests` → opens page → waits → runs `replay_requests` → `on_page_after_load` hook
   - Collects screenshots, HTML, network JSON, replay results
8. Runs `on_run_complete` hook, writes `run_result.json` and `run_result.html`

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
YAML files → deep_merge → render_value(raw, build_vars(raw)) → AppConfig.model_validate → rewrite_output_dirs
```

`rewrite_output_dirs` patches relative `output_dir` paths inside middleware config to point into `outputs/runs/{run_id}/`.

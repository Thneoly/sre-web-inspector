# SRE Web Inspector Advanced

Playwright 驱动的 SRE 网页巡检、接口重放与证据留存工具包。支持 YAML 配置、Pydantic 校验、`{{ var }}` 模板变量替换。

## 安装

```bash
uv sync --extra dev
playwright install chromium
```

## 运行

### YAML 巡检模式

```bash
# 运行巡检
uv run python main.py --config config/example.yaml

# 只校验配置
uv run python main.py --validate-only

# 合并多份配置
uv run python main.py --config base.yaml --config env/prod.yaml

# 只运行指定页面
uv run python main.py --page pod_page
```

### 业务采集器（datamarket）

```bash
# 采集 lizhi.shop 全部软件产品
uv run python run_lizhi.py --no-headless --max-pages 2

# 采集巨潮资讯网（深市/沪市/北交所）公告
uv run python run_cninfo.py --exchanges szse bj --max-clicks 3

# 查看参数
uv run python run_lizhi.py --help
uv run python run_cninfo.py --help
```

## 核心组件

### BaseCollector[T] — 数据采集基类

所有业务采集器的抽象基类，提供标准生命周期：

```python
from sre_web_inspector.base_collector import BaseCollector

class MyCollector(BaseCollector[MyItem]):
    async def collect(self) -> list[MyItem]:
        # 实现采集逻辑
        self.results = [...]
        return self.results

# 使用：save_results 自动处理去重、JSON 写入、HTML 报告
summary = collector.save_results(
    kind="MyCollection",
    filename="my_results.json",
    dedup_key=lambda item: item.id,
    api_captures=capture.responses,
    source="https://example.com",
)
```

### ApiCapture — 内存级 API 响应拦截

无需写磁盘，直接将 JSON 响应捕获到内存列表：

```python
from sre_web_inspector.api_capture import ApiCapture

cap = ApiCapture(url_keywords=["/api/"], max_captures=200)
cap.attach(page)
await page.goto("https://example.com")
# cap.responses = [{"url": ..., "status": 200, "data": {...}}, ...]
cap.detach(page)
```

### Paginator — 翻页工具

两种模式覆盖所有常见翻页场景：

```python
# URL 递增模式
from sre_web_inspector.paginator import paginate_by_url
async for pg, page in paginate_by_url(new_page, "https://x.com?page={page}", start=1, max_pages=10):
    # 每页一个独立的 Page

# 点击按钮模式
from sre_web_inspector.paginator import paginate_by_click
async for click_num, page in paginate_by_click(page, next_selector=".btn-next", max_clicks=10):
    # 共用一个 Page，自动检测按钮 disabled 状态
```

### WebInspectionNode — SPA 感知巡检

```python
# 原参数仍可用；新增 SPA 参数：
await inspector.inspect_page(
    url,
    wait_for_network_idle=True,        # 等待 XHR/fetch 完成
    wait_for_selector='a[href*="id"]',  # 等待特定 DOM 元素
)
# 也支持从代码注册 ResponseMiddleware
inspector.add_response_middleware(my_response_middleware)
```

### Reporter — 泛型 HTML 报告

`render_report()` 根据 `kind` 自动选择渲染方式：
- `"WebInspectionRun"` → 巡检专用布局（截图、HTML、网络证据卡片）
- 其他 → 通用 key-value 摘要 + items 表格

## 输出结构

```
outputs/runs/{run_id}/
├── screenshots/
├── html/
├── network/
├── responses/
├── replay/
│   ├── global/
│   └── {page_name}/
├── run_result.json
├── run_result.html
└── {business_data}.json      # 业务采集器输出的数据文件
```

## 核心配置片段

```yaml
vars:
  base_url: https://example.com
  namespace: default

runtime:
  output_dir: outputs
  concurrency: 2
  timeout: 60000
  retry:
    times: 2
    interval_ms: 1000

replay_requests:
  - name: current_user
    method: GET
    url: "{{ base_url }}/api/current-user"

pages:
  - name: pod_page
    url: "{{ base_url }}/pods"
    lifecycle:
      close_after_inspection: true
    replay_requests:
      - name: pod_list
        method: GET
        url: "{{ base_url }}/api/pods"
        params:
          namespace: "{{ namespace }}"
```

## 中间件系统

三层架构，各有独立的 context 和抽象基类：

| 层 | 接口 | Context | 可短路？ |
|---|------|---------|---------|
| Route | `RouteMiddleware.handle(ctx, next_call)` | `RouteContext` | 是 |
| Request | `RequestMiddleware.handle(ctx)` | `RequestContext` | 否 |
| Response | `ResponseMiddleware.handle(ctx)` | `ResponseContext` | 否 |

绑定范围（由宽到窄）：
1. `context_middlewares` → 整个 BrowserContext
2. `network_middlewares` → 所有 page 默认继承
3. `pages[].network_middlewares` → 当前 page 专属

也可以通过代码注册：`inspector.add_response_middleware(mw)`。

## 测试

```bash
uv run pytest -v          # 全部 141 个测试
uv run pytest tests/test_base_collector.py -v
```

## 现有业务代码

| 采集器 | 入口 | 目标 |
|--------|------|------|
| `lizhi_inspector.py` | `run_lizhi.py` | lizhi.shop 全部软件产品（约 378 款） |
| `cninfo_collector.py` | `run_cninfo.py` | 巨潮资讯网公告：深市主板/创业板/沪市主板/科创板/北交所 |

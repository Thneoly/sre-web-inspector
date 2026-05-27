# usage.md

## 1. 基本运行

```bash
python main.py --config config/example.yaml
```

校验配置：

```bash
python main.py --config config/example.yaml --validate-only
```

## 2. 业务采集器

### lizhi.shop 软件采集

```bash
# 采集所有分页（共 ~19 页，378 款软件）
uv run python run_lizhi.py

# 限制页数
uv run python run_lizhi.py --max-pages 3

# 显示浏览器窗口、截图
uv run python run_lizhi.py --no-headless --screenshot

# 自定义重试
uv run python run_lizhi.py --retry-times 3 --retry-interval 2000
```

### cninfo 公告采集

```bash
# 采集全部交易所
uv run python run_cninfo.py

# 只采集指定交易所
uv run python run_cninfo.py --exchanges szse bj

# 限制翻页次数
uv run python run_cninfo.py --max-clicks 5

# 显示浏览器窗口
uv run python run_cninfo.py --no-headless
```

## 3. 变量替换

配置中的字符串支持 `{{ var }}`：

```yaml
vars:
  base_url: https://example.com
  namespace: default
  page_size: 200

pages:
  - name: pod_page
    url: "{{ base_url }}/pods"
    replay_requests:
      - name: pod_full_list
        method: GET
        url: "{{ base_url }}/api/pods"
        params:
          namespace: "{{ namespace }}"
          pageSize: "{{ page_size }}"
```

如果整个字符串就是一个变量，例如 `"{{ page_size }}"`，会保留原始类型，如整数 `200`。

## 4. run_id 输出目录

默认每次运行输出到：

```text
outputs/runs/{run_id}/
```

可以指定固定 run_id：

```yaml
runtime:
  output_dir: outputs
  run_id: debug-001
```

输出包括：

```text
screenshots/
html/
network/
responses/
replay/
run_result.json
run_result.html
```

## 5. retry 与 timeout

全局默认：

```yaml
runtime:
  timeout: 60000
  retry:
    times: 2
    interval_ms: 1000
```

page 覆盖：

```yaml
pages:
  - name: pod_page
    url: https://example.com/pods
    timeout: 30000
    retry:
      times: 3
      interval_ms: 2000
```

replay 覆盖：

```yaml
replay_requests:
  - name: current_user
    method: GET
    url: https://example.com/api/current-user
    timeout: 30000
    retry:
      times: 2
      interval_ms: 1000
```

## 6. 并发控制

```yaml
runtime:
  concurrency: 2
```

每个 page 会创建独立 `Page`，并绑定自己的 page-scoped middleware。截图、HTML、network 会保存到同一个 run 目录下。

## 7. Page 生命周期

```yaml
pages:
  - name: pod_page
    url: https://example.com/pods
    lifecycle:
      close_after_inspection: true
      clear_network_records: true
```

- `close_after_inspection`: 巡检后关闭当前 page。
- `clear_network_records`: 巡检前清空 BrowserContextManager 的全局内存记录。

## 8. 全局 replay

```yaml
replay_requests:
  - name: current_user
    method: GET
    url: "{{ base_url }}/api/current-user"
```

输出到：

```text
outputs/runs/{run_id}/replay/global/current_user.json
```

## 9. Page 级 replay

```yaml
pages:
  - name: pod_page
    url: "{{ base_url }}/pods"

    pre_replay_requests:
      - name: pod_options
        method: GET
        url: "{{ base_url }}/api/pod-options"

    replay_requests:
      - name: pod_full_list
        method: GET
        url: "{{ base_url }}/api/pods"
        params:
          pageSize: 200
```

输出到：

```text
outputs/runs/{run_id}/replay/pod_page/pre/pod_options.json
outputs/runs/{run_id}/replay/pod_page/pod_full_list.json
```

## 10. Middleware scope

```yaml
context_middlewares:
  routes: []

network_middlewares:
  requests: []
  responses: []

pages:
  - name: pod_page
    network_middlewares:
      routes: []
      responses: []
```

- `context_middlewares`: 绑定到 BrowserContext。
- `network_middlewares`: 所有 page 默认继承。
- `pages[].network_middlewares`: 当前 page 专属。

也可以通过代码注册 ResponseMiddleware：

```python
inspector.add_response_middleware(my_middleware)
```

## 11. 配置校验

配置启动时会用 Pydantic 校验。如果字段类型错误，例如：

```yaml
runtime:
  concurrency: 0
```

会直接报错，因为并发数必须 `>= 1`。

## 12. 编写业务采集代码

### 继承 BaseCollector

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
        # ... extract data ...
        self.results = [MyItem("a", 1), MyItem("b", 2)]
        return self.results
```

BaseCollector 自动提供：
- `self.cm` / `self.inspector` / `self.run_ctx` / `self.retry_policy`
- `self.output_dir` (Path)
- `save_results(kind=..., filename=..., dedup_key=...)` — 去重、JSON、HTML 报告一步完成

### 使用 ApiCapture 拦截 API 响应

```python
from sre_web_inspector.api_capture import ApiCapture

cap = ApiCapture(url_keywords=["/api/data"], max_captures=200)
cap.attach(page)
await page.goto("https://example.com")
# cap.responses 现在包含匹配的 JSON 响应
cap.detach(page)

# 传给 save_results 保存到磁盘
collector.save_results(kind="MyCollect", api_captures=cap.responses)
```

### 使用 Paginator 翻页

```python
from sre_web_inspector.paginator import paginate_by_click, paginate_by_url

# 方式 1: 点击"下一页"按钮
async for click_num, page in paginate_by_click(page, next_selector=".btn-next", max_clicks=10):
    # click_num=0 是第一页（点击前），之后每点一次递增
    extract_data(page)

# 方式 2: URL 递增
async def new_page(): return await cm.new_page()
async for pg_num, page in paginate_by_url(new_page, "https://x.com?page={page}", start=1, max_pages=5):
    extract_data(page)
    await page.close()
```

### 使用 WebInspectionNode 的 SPA 参数

```python
await self.inspector.inspect_page(
    url,
    page=page,
    wait_for_network_idle=True,           # 等待 XHR/fetch 完成
    wait_for_selector='a[href*="id"]',    # 等待特定元素
    wait_ms=1000,
)
```

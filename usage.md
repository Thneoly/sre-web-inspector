# usage.md

## 1. 基本运行

```bash
python main.py --config config/example.yaml
```

校验配置：

```bash
python main.py --config config/example.yaml --validate-only
```

## 2. 变量替换

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

## 3. run_id 输出目录

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
```

## 4. retry 与 timeout

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

## 5. 并发控制

```yaml
runtime:
  concurrency: 2
```

每个 page 会创建独立 `Page`，并绑定自己的 page-scoped middleware。截图、HTML、network 会保存到同一个 run 目录下。

## 6. Page 生命周期

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

## 7. 全局 replay

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

## 8. Page 级 replay

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

## 9. Middleware scope

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

## 10. 配置校验

配置启动时会用 Pydantic 校验。如果字段类型错误，例如：

```yaml
runtime:
  concurrency: 0
```

会直接报错，因为并发数必须 `>= 1`。

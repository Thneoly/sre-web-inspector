# SRE Web Inspector Advanced

这是一个面向 SRE 网页巡检、接口重放和证据留存的 Playwright 工具包。

本版新增能力：

1. `replay_requests` 支持全局和 page 级配置。
2. 支持 `{{ var }}` 变量替换。
3. 支持 retry / timeout 策略。
4. 支持多 page 并发巡检。
5. 支持 page 生命周期策略。
6. 使用 Pydantic 做配置 Schema 校验。
7. 每次运行按 `run_id` 输出到 `outputs/runs/{run_id}/`。

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

或开发态：

```bash
uv pip install -e .
```

## 运行

```bash
python main.py --config config/example.yaml
```

只校验配置：

```bash
python main.py --config config/example.yaml --validate-only
```

## 输出结构

```text
outputs/runs/{run_id}/
├── screenshots/
├── html/
├── network/
├── responses/
├── replay/
│   ├── global/
│   ├── pod_page/
│   └── grafana_page/
└── run_result.json
```

## 核心配置片段

```yaml
vars:
  base_url: https://example.com
  namespace: default
  page_size: 200

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
      clear_network_records: true
    replay_requests:
      - name: pod_full_list
        method: GET
        url: "{{ base_url }}/api/pods"
        params:
          namespace: "{{ namespace }}"
          pageSize: "{{ page_size }}"
```

## 注意

- `context_middlewares` 绑定到整个 BrowserContext。
- `network_middlewares` 是所有 page 默认继承的 page 级 middleware。
- `pages[].network_middlewares` 只绑定到当前 page。
- `pages[].pre_replay_requests` 在页面打开前执行。
- `pages[].replay_requests` 在页面打开后执行。
- replay 底层复用 `BrowserContext.request`，语义上归属于 page。

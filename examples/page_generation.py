"""
Page Generator 示例 — 从内联数据 / CSV / JSON / Excel 批量生成页面。

演示五种 page_generators type：
  - ids:   内联 ID 列表
  - list:  内联 dict 列表
  - csv:   从 CSV 文件读取（首行为列名）
  - json:  从 JSON 文件读取（支持 items_path 定位数组）
  - xlsx:  从 Excel 文件读取（可选 sheet_name）

运行方式：
  # 先生成示例数据文件，再导入验证
  uv run python examples/page_generation.py

  # 或在 YAML 配置中使用（推荐方式），见文件末尾的 YAML 示例。
"""

from __future__ import annotations

import json
from pathlib import Path

from sre_web_inspector.config_schema import AppConfig
from sre_web_inspector.page_generator import expand_page_generators


def demo_ids_generator() -> None:
    """type: ids — 内联 ID 列表，适合 pod/服务/实例名等。"""
    config = {
        "vars": {"base_url": "https://k8s.example.com", "namespace": "prod"},
        "page_generators": [
            {
                "name": "pod_pages",
                "type": "ids",
                "id_field": "pod",
                "ids": ["pod-a", "pod-b", "pod-c"],
                "template": {
                    "name": "pod_{{ pod }}",
                    "url": "{{ base_url }}/k8s/{{ namespace }}/pods/{{ pod }}",
                    "screenshot": True,
                },
            }
        ],
    }
    pages = expand_page_generators(config, config["vars"])
    print(f"[ids] expanded {len(pages)} pages:")
    for p in pages:
        print(f"  {p['name']:20s} → {p['url']}")


def demo_list_generator() -> None:
    """type: list — 内联 dict 列表，每项可含多个字段。"""
    config = {
        "vars": {"base_url": "https://monitor.example.com"},
        "page_generators": [
            {
                "name": "dashboard_pages",
                "type": "list",
                "values": [
                    {"env": "prod", "uid": "abc123"},
                    {"env": "staging", "uid": "def456"},
                    {"env": "dev", "uid": "ghi789"},
                ],
                "template": {
                    "name": "{{ env }}-dashboard",
                    "url": "{{ base_url }}/d/{{ uid }}/{{ env }}-overview",
                    "save_html": False,
                },
            }
        ],
    }
    pages = expand_page_generators(config, config["vars"])
    print(f"\n[list] expanded {len(pages)} pages:")
    for p in pages:
        print(f"  {p['name']:22s} → {p['url']}")


def demo_csv_generator(tmp_dir: Path) -> None:
    """type: csv — 从 CSV 文件读取，首行为列名。"""
    csv_path = tmp_dir / "resources.csv"
    csv_path.write_text(
        "resource_id,system_name,env\n"
        "1001,HIS,prod\n"
        "1002,LIS,prod\n"
        "1003,EMR,staging\n",
        encoding="utf-8",
    )

    config = {
        "vars": {"base_url": "https://sre.example.com"},
        "page_generators": [
            {
                "name": "resource_pages",
                "type": "csv",
                "source": str(csv_path),
                "template": {
                    "name": "resource_{{ resource_id }}",
                    "url": "{{ base_url }}/systems/{{ system_name }}/{{ resource_id }}?env={{ env }}",
                },
            }
        ],
    }
    pages = expand_page_generators(config, config["vars"])
    print(f"\n[csv] expanded {len(pages)} pages from {csv_path.name}:")
    for p in pages:
        print(f"  {p['name']:24s} → {p['url']}")


def demo_json_generator(tmp_dir: Path) -> None:
    """type: json — 从 JSON 文件读取，可选 items_path 定位数组。"""

    # 场景 1：JSON 根为数组
    json_path = tmp_dir / "pods.json"
    json_path.write_text(json.dumps([
        {"name": "redis-master", "cluster": "prod-1"},
        {"name": "redis-slave", "cluster": "prod-2"},
    ]), encoding="utf-8")

    config = {
        "vars": {"base_url": "https://k8s.example.com"},
        "page_generators": [
            {
                "name": "pod_json",
                "type": "json",
                "source": str(json_path),
                "template": {
                    "name": "{{ name }}",
                    "url": "{{ base_url }}/pods/{{ name }}?cluster={{ cluster }}",
                },
            }
        ],
    }
    pages = expand_page_generators(config, config["vars"])
    print(f"\n[json] expanded {len(pages)} pages from {json_path.name}:")
    for p in pages:
        print(f"  {p['name']:20s} → {p['url']}")

    # 场景 2：JSON 嵌套路径
    json_path2 = tmp_dir / "nested.json"
    json_path2.write_text(json.dumps({
        "status": "ok",
        "data": {"items": [
            {"uid": "dashboard-a", "title": "System Overview"},
            {"uid": "dashboard-b", "title": "Redis Metrics"},
        ]},
    }), encoding="utf-8")

    config2 = {
        "vars": {"grafana_url": "https://grafana.example.com"},
        "page_generators": [
            {
                "name": "grafana_dashboards",
                "type": "json",
                "source": str(json_path2),
                "items_path": "$.data.items",
                "template": {
                    "name": "{{ title }}",
                    "url": "{{ grafana_url }}/d/{{ uid }}",
                },
            }
        ],
    }
    pages2 = expand_page_generators(config2, config2["vars"])
    print(f"\n[json nested] expanded {len(pages2)} pages from {json_path2.name}:")
    for p in pages2:
        print(f"  {p['name']:22s} → {p['url']}")


def demo_xlsx_generator(tmp_dir: Path) -> None:
    """type: xlsx — 从 Excel 文件读取，首行为列名。需要 openpyxl。"""
    try:
        import openpyxl
    except ImportError:
        print("\n[xlsx] skipped — openpyxl not installed")
        return

    xlsx_path = tmp_dir / "middleware.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["instance_id", "type", "host", "port"])
    ws.append(["mw-001", "Redis", "10.0.1.10", "6379"])
    ws.append(["mw-002", "Kafka", "10.0.1.20", "9092"])
    ws.append(["mw-003", "MySQL", "10.0.1.30", "3306"])
    wb.save(str(xlsx_path))

    config = {
        "vars": {"base_url": "https://sre.example.com"},
        "page_generators": [
            {
                "name": "middleware_pages",
                "type": "xlsx",
                "source": str(xlsx_path),
                "template": {
                    "name": "{{ type }}_{{ instance_id }}",
                    "url": "{{ base_url }}/middleware/{{ instance_id }}/metrics?host={{ host }}:{{ port }}",
                },
            }
        ],
    }
    pages = expand_page_generators(config, config["vars"])
    print(f"\n[xlsx] expanded {len(pages)} pages from {xlsx_path.name}:")
    for p in pages:
        print(f"  {p['name']:22s} → {p['url']}")


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        demo_ids_generator()
        demo_list_generator()
        demo_csv_generator(tmp)
        demo_json_generator(tmp)
        demo_xlsx_generator(tmp)

    print("\n── 以下是 YAML 配置中使用 page_generators 的示例 ──\n")
    print(YAML_EXAMPLES)


YAML_EXAMPLES = r"""
# ═══════════════════════════════════════════════════════════════════════
# YAML 配置示例
# ═══════════════════════════════════════════════════════════════════════

vars:
  base_url: https://k8s.example.com
  namespace: prod
  grafana_url: https://grafana.example.com

# ── ids 类型 ──────────────────────────────────────────────────────────
page_generators:
  - name: pod_pages
    type: ids
    id_field: pod
    ids: [pod-a, pod-b, pod-c]
    max_pages: 100
    template:
      name: "pod_{{ pod }}"
      url: "{{ base_url }}/k8s/{{ namespace }}/pods/{{ pod }}"
      screenshot: true
      network_middlewares:
        responses:
          - type: json_response_saver
            url_keywords: [/api/pods]

  # ── list 类型 ─────────────────────────────────────────────────────
  - name: dashboard_pages
    type: list
    values:
      - {env: prod, uid: abc123}
      - {env: staging, uid: def456}
    template:
      name: "{{ env }}-dashboard"
      url: "{{ grafana_url }}/d/{{ uid }}"

  # ── csv 类型 ──────────────────────────────────────────────────────
  - name: system_pages
    type: csv
    source: config/systems.csv
    template:
      name: "system_{{ system_id }}"
      url: "{{ base_url }}/systems/{{ system_id }}/health"

  # ── json 类型 ─────────────────────────────────────────────────────
  - name: resource_pages
    type: json
    source: config/resources.json
    items_path: "$.items"
    template:
      name: "resource_{{ id }}"
      url: "{{ base_url }}/resources/{{ id }}"

  # ── xlsx 类型 ─────────────────────────────────────────────────────
  - name: middleware_pages
    type: xlsx
    source: config/middleware.xlsx
    sheet_name: prod
    template:
      name: "{{ type }}_{{ instance_id }}"
      url: "{{ base_url }}/middleware/{{ instance_id }}"

# 生成的 pages 与静态 pages 合并后执行巡检
pages:
  - name: home
    url: "{{ base_url }}/home"
    screenshot: true
"""

if __name__ == "__main__":
    main()

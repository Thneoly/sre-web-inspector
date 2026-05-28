"""
Hooks 生命周期示例 — 在巡检关键节点执行 Shell 命令。

四个生命周期节点：
  1. on_browser_start   — 浏览器启动后
  2. on_page_before_goto — 每个页面打开前
  3. on_page_after_load  — 每个页面加载后
  4. on_run_complete     — 巡检结束

可用环境变量：
  SRE_RUN_ID, SRE_OUTPUT_DIR, SRE_PAGE_NAME,
  SRE_PAGE_URL, SRE_PAGE_TITLE, SRE_ALL_OK

运行：
  uv run python examples/hooks_lifecycle.py
"""

from __future__ import annotations

import asyncio
import logging

from sre_web_inspector.hooks import HookConfig, run_hooks

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# YAML 配置示例中的 hooks 用法
# ═══════════════════════════════════════════════════════════════════════

YAML_HOOKS_EXAMPLES = r"""
# ── 全局 hooks（作用于整个巡检生命周期）───────────────────────────────
hooks:
  on_browser_start:
    commands:
      - "echo 'Browser ready: run_id=$SRE_RUN_ID'"
      - "curl -s -X POST https://hooks.slack.com/xxx -d '{\"text\":\"巡检开始: $SRE_RUN_ID\"}' || true"
    timeout: 10

  on_run_complete:
    commands:
      - "echo 'Run complete: $SRE_RUN_ID, all_ok=$SRE_ALL_OK'"
      - |
        if [ "$SRE_ALL_OK" = "false" ]; then
          echo "有页面失败，发送告警..."
        fi
    timeout: 30

# ── 页面级 hooks（作用于单个 page）────────────────────────────────────
pages:
  - name: critical_page
    url: "{{ base_url }}/critical"
    hooks:
      on_page_before_goto:
        commands:
          - "echo 'Opening $SRE_PAGE_NAME: $SRE_PAGE_URL'"
      on_page_after_load:
        commands:
          - |
            echo "Loaded $SRE_PAGE_NAME: title=$SRE_PAGE_TITLE"
            # 用外部工具对截图做二次处理
            # convert outputs/runs/$SRE_RUN_ID/screenshots/$SRE_PAGE_NAME.png \\
            #   -resize 50% outputs/runs/$SRE_RUN_ID/screenshots/$SRE_PAGE_NAME_thumb.png
"""


# ═══════════════════════════════════════════════════════════════════════
# 编程方式使用 hooks
# ═══════════════════════════════════════════════════════════════════════

async def demo_run_hooks() -> None:
    """演示直接调用 run_hooks API。"""

    # 模拟通知
    await run_hooks(
        HookConfig(
            commands=[
                "echo 'Starting inspection...'",
                "echo Branch: $(git branch --show-current 2>/dev/null || echo N/A)",
            ],
            timeout=30,
        ),
        env={"SRE_RUN_ID": "demo-001", "SRE_OUTPUT_DIR": "/tmp/sre-demo"},
    )

    # 模拟成功完成
    await run_hooks(
        HookConfig(
            commands=[
                "echo 'Done: run_id=$SRE_RUN_ID, all_ok=$SRE_ALL_OK'",
            ],
            timeout=10,
        ),
        env={"SRE_RUN_ID": "demo-001", "SRE_ALL_OK": "true"},
    )


async def demo_hook_failure() -> None:
    """演示 hook 命令失败时的行为（非零退出码不会中断流程）。"""

    print("\n--- 下面的警告是预期行为 ---")
    await run_hooks(
        HookConfig(
            commands=[
                "echo 'This command succeeds'",
                "exit 1",  # fails but doesn't stop the flow
                "echo 'This also runs despite the failure above'",
            ],
            timeout=10,
        ),
    )
    print("--- 警告结束 ---")


async def main() -> None:
    await demo_run_hooks()
    await demo_hook_failure()
    print("\n" + YAML_HOOKS_EXAMPLES)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())

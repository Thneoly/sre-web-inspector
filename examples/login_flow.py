"""
Login 流程示例 — 手动 / 表单 / Cookie 三种登录模式。

演示：
  1. Manual login — 打开登录页，人工扫码/输密码，框架等待成功标志
  2. Form login  — 自动填写用户名密码，点击提交
  3. Cookie login — 直接注入 Cookie，无需打开页面
  4. Session checker — 启动前先检查是否已登录，已登录则跳过
  5. Login evidence — 登录前后截图 + 保存 storage_state

编程方式使用 LoginFlow：

    flow = LoginFlow(cm, app_config, run_ctx)
    result = await flow.run()
    if not result.success:
        raise RuntimeError(f"Login failed: {result.reason}")

YAML 方式（推荐）见文件末尾的完整配置示例。

运行：
  uv run python examples/login_flow.py
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from sre_web_inspector.auth.login_flow import LoginFlow
from sre_web_inspector.auth.login_result import LoginResult
from sre_web_inspector.auth.session_checker import SessionChecker
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.config_schema import (
    AppConfig,
    CookieLoginConfig,
    FormLoginConfig,
    LoginCheckConfig,
    LoginConfig,
    ManualLoginConfig,
)
from sre_web_inspector.run_context import RunContext

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# 构建 LoginConfig 的辅助函数
# ═══════════════════════════════════════════════════════════════════════

def build_manual_login_config(login_url: str) -> LoginConfig:
    """手动登录：打开登录页，等待用户完成登录后检测成功标志。"""
    return LoginConfig(
        enabled=True,
        mode="manual",
        login_url=login_url,
        on_failure="stop",
        check=LoginCheckConfig(
            type="selector",
            url=f"{login_url}/../home",
            selector=".user-avatar, .user-menu, [data-testid='user-info']",
            timeout=10000,
        ),
        manual=ManualLoginConfig(
            wait_timeout=120000,  # 给用户 2 分钟完成登录
            success_selector=".user-avatar, .user-menu",
        ),
    )


def build_form_login_config(login_url: str, username: str, password: str) -> LoginConfig:
    """表单登录：自动填写并提交登录表单。"""
    return LoginConfig(
        enabled=True,
        mode="form",
        login_url=login_url,
        on_failure="stop",
        check=LoginCheckConfig(
            type="api",
            url=f"{login_url}/../api/current-user",
            expect_status=200,
            timeout=10000,
        ),
        form=FormLoginConfig(
            username_selector="#username, input[name='username'], input[type='email']",
            password_selector="#password, input[name='password']",
            submit_selector="button[type='submit'], input[type='submit']",
            username=username,
            password=password,
            after_submit={
                "wait_for_url_contains": "/dashboard",
                "timeout": 15000,
            },
        ),
    )


def build_cookie_login_config(cookies: list[dict]) -> LoginConfig:
    """Cookie 登录：直接注入 Cookie 到 BrowserContext。"""
    return LoginConfig(
        enabled=True,
        mode="cookie",
        on_failure="continue",
        check=LoginCheckConfig(
            type="cookie",
            cookie_name=cookies[0]["name"] if cookies else "token",
            timeout=5000,
        ),
        cookie=CookieLoginConfig(cookies=cookies),
    )


# ═══════════════════════════════════════════════════════════════════════
# 编程方式使用 LoginFlow
# ═══════════════════════════════════════════════════════════════════════

async def demo_login_flow_programmatic() -> None:
    """
    演示直接使用 LoginFlow API。

    注意：这个示例需要真实的登录页面，默认不会实际执行。
    把 SKIP_DEMO 设为 False 并设置实际 URL 即可测试。
    """
    SKIP_DEMO = True
    if SKIP_DEMO:
        print("[demo_login_flow] 跳过（需要真实登录页，设 SKIP_DEMO=False 启用）")
        return

    app_config = AppConfig.model_validate({
        "runtime": {"concurrency": 1, "timeout": 60000},
        "browser": {"headless": False, "slow_mo": 200},
        "login": {
            "enabled": True,
            "mode": "form",
            "login_url": "https://your-site.example.com/login",
            "on_failure": "stop",
            "check": {
                "type": "api",
                "url": "https://your-site.example.com/api/current-user",
                "expect_status": 200,
            },
            "form": {
                "username_selector": "input[name='username']",
                "password_selector": "input[name='password']",
                "submit_selector": "button[type='submit']",
                "username": "admin",
                "password": "your-password",
                "after_submit": {"wait_for_url_contains": "/dashboard", "timeout": 15000},
            },
            "evidence": {
                "screenshot_before": True,
                "screenshot_after": True,
                "save_storage_state": True,
            },
        },
        "pages": [],
    })

    run_ctx = RunContext.create(base_output_dir="outputs")

    async with BrowserContextManager(
        headless=False,
        slow_mo=200,
        user_data_dir="./user-data",
    ) as cm:
        flow = LoginFlow(cm, app_config, run_ctx)
        result = await flow.run()

        print(f"Login result: success={result.success}, mode={result.mode}")
        print(f"  skipped={result.skipped}, reason={result.reason}")
        if result.evidence:
            for key, path in result.evidence.items():
                print(f"  evidence.{key}: {path}")

        if not result.success:
            raise RuntimeError(f"Login failed: {result.reason}")

        # 登录成功，继续巡检...
        print("Login OK, ready to inspect pages.")


# ═══════════════════════════════════════════════════════════════════════
# SessionChecker 独立使用示例
# ═══════════════════════════════════════════════════════════════════════

async def demo_session_checker() -> None:
    """
    演示独立使用 SessionChecker — 不通过 LoginFlow。

    适合在自定义脚本中判断是否已登录。
    """
    SKIP_DEMO = True
    if SKIP_DEMO:
        print("[demo_session_checker] 跳过（需要真实环境，设 SKIP_DEMO=False 启用）")
        return

    async with BrowserContextManager(
        headless=False,
        user_data_dir="./user-data",
    ) as cm:
        checker = SessionChecker()

        async def new_page():
            return await cm.new_page()

        # 检查 1：URL 是否包含特定文本
        check1 = LoginCheckConfig(type="url_contains", url="https://example.com/home", selector="dashboard")
        logged_in_1 = await checker.is_logged_in(cm.context, new_page, check1)
        print(f"url_contains check: {logged_in_1}")

        # 检查 2：页面是否出现用户菜单
        check2 = LoginCheckConfig(type="selector", url="https://example.com/home", selector=".user-menu")
        logged_in_2 = await checker.is_logged_in(cm.context, new_page, check2)
        print(f"selector check: {logged_in_2}")

        # 检查 3：API 是否返回 200
        check3 = LoginCheckConfig(type="api", url="https://example.com/api/me", expect_status=200)
        logged_in_3 = await checker.is_logged_in(cm.context, new_page, check3)
        print(f"api check: {logged_in_3}")

        # 检查 4：Cookie 是否存在
        check4 = LoginCheckConfig(type="cookie", cookie_name="auth_token")
        logged_in_4 = await checker.is_logged_in(cm.context, new_page, check4)
        print(f"cookie check: {logged_in_4}")


# ═══════════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════════

async def main() -> None:
    await demo_login_flow_programmatic()
    await demo_session_checker()
    print("\n" + YAML_EXAMPLE)


YAML_EXAMPLE = r"""
# ═══════════════════════════════════════════════════════════════════════
# YAML 配置中的 login 示例
# ═══════════════════════════════════════════════════════════════════════

# ── 手动登录（适合 SSO / 扫码 / 验证码场景）──────────────────────────
login:
  enabled: true
  mode: manual
  login_url: "{{ base_url }}/login"
  on_failure: stop
  check:
    type: selector
    url: "{{ base_url }}/home"
    selector: ".user-avatar"
    timeout: 10000
  manual:
    wait_timeout: 120000          # 给用户 2 分钟完成登录
    success_selector: ".user-avatar"
  evidence:
    screenshot_before: true
    screenshot_after: true
    save_storage_state: true

# ── 表单登录（适合有用户名/密码的系统）─────────────────────────────────
login:
  enabled: true
  mode: form
  login_url: "{{ base_url }}/login"
  on_failure: stop
  check:
    type: api
    url: "{{ base_url }}/api/current-user"
    expect_status: 200
  form:
    username_selector: "input[name='username']"
    password_selector: "input[name='password']"
    submit_selector: "button[type='submit']"
    username: "admin"
    password: "{{ LOGIN_PASSWORD }}"          # 从环境变量读取
    after_submit:
      wait_for_selector: ".dashboard-content"
      timeout: 15000
  evidence:
    screenshot_before: false
    screenshot_after: true
    save_storage_state: true

# ── Cookie 登录（适合已有 token / CI 环境）────────────────────────────
login:
  enabled: true
  mode: cookie
  on_failure: continue           # Cookie 过期仍继续，页面报错时手动处理
  check:
    type: cookie
    cookie_name: auth_token
  cookie:
    cookies:
      - name: auth_token
        value: "{{ AUTH_TOKEN }}"              # 从环境变量或 vars 注入
        domain: ".example.com"
        path: "/"
        httpOnly: true
        secure: true
      - name: session_id
        value: "{{ SESSION_ID }}"
        domain: ".example.com"
        path: "/"
  evidence:
    save_storage_state: true     # 保存登录后的 storage_state 供下次复用
"""

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())

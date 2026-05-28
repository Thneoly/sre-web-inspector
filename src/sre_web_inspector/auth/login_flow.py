from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sre_web_inspector.auth.login_result import LoginResult
from sre_web_inspector.auth.session_checker import SessionChecker
from sre_web_inspector.auth.strategies import build_login_strategy

if TYPE_CHECKING:
    from sre_web_inspector.browser_context import BrowserContextManager
    from sre_web_inspector.config_schema import AppConfig
    from sre_web_inspector.run_context import RunContext


logger = logging.getLogger(__name__)


class LoginFlow:
    def __init__(
        self,
        cm: BrowserContextManager,
        config: AppConfig,
        run_context: RunContext,
    ):
        self._cm = cm
        self._config = config
        self._run_ctx = run_context
        self._checker = SessionChecker()

    async def run(self) -> LoginResult:
        login_cfg = self._config.login
        if login_cfg is None or not login_cfg.enabled:
            return LoginResult(enabled=False, success=True)

        # Check if already logged in
        if login_cfg.check is not None and login_cfg.check.type != "none":
            page_factory = self._cm.new_page
            already = await self._checker.is_logged_in(
                self._cm.context,
                page_factory,
                login_cfg.check,
            )
            if already:
                logger.info("Session already valid, skipping login")
                return LoginResult(
                    enabled=True,
                    mode=login_cfg.mode,
                    skipped=True,
                    success=True,
                )

        # Prepare output dir for login evidence
        evidence_dir: Path | None = None
        if login_cfg.evidence and (
            login_cfg.evidence.screenshot_before
            or login_cfg.evidence.screenshot_after
            or login_cfg.evidence.save_storage_state
        ):
            evidence_dir = self._run_ctx.output_dir / "login"
            evidence_dir.mkdir(parents=True, exist_ok=True)

        strategy = build_login_strategy(login_cfg.mode)

        if login_cfg.mode == "cookie":
            result = await strategy.login(self._cm.context, login_cfg.cookie)
        else:
            page = await self._cm.new_page()
            try:
                if login_cfg.mode == "manual":
                    result = await strategy.login(
                        page, login_cfg, login_cfg.manual, login_cfg.evidence, evidence_dir
                    )
                elif login_cfg.mode == "form":
                    result = await strategy.login(
                        page, login_cfg, login_cfg.form, login_cfg.evidence, evidence_dir
                    )
                else:
                    raise ValueError(f"Unsupported login mode: {login_cfg.mode}")
            finally:
                await page.close()

        if not result.success and login_cfg.on_failure == "stop":
            raise RuntimeError(f"Login failed: {result.reason}")

        logger.info(
            "Login result: enabled=%s mode=%s skipped=%s success=%s",
            result.enabled,
            result.mode,
            result.skipped,
            result.success,
        )
        return result

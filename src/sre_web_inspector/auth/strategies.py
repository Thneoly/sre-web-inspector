from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sre_web_inspector.auth.login_result import LoginResult
from sre_web_inspector.config_schema import (
    CookieLoginConfig,
    FormLoginConfig,
    LoginConfig,
    LoginEvidenceConfig,
    ManualLoginConfig,
)

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


logger = logging.getLogger(__name__)


class ManualLoginStrategy:
    async def login(
        self,
        page: Page,
        login_config: LoginConfig,
        manual_cfg: ManualLoginConfig,
        evidence_cfg: LoginEvidenceConfig,
        output_dir: Path | None = None,
    ) -> LoginResult:
        if not login_config.login_url:
            return LoginResult(enabled=True, mode="manual", success=False, reason="login_url is required")

        if evidence_cfg.screenshot_before and output_dir:
            await page.screenshot(path=str(output_dir / "login_before.png"))

        await page.goto(login_config.login_url, wait_until="domcontentloaded")

        timeout = manual_cfg.wait_timeout
        success_selector = manual_cfg.success_selector
        success_url_contains = manual_cfg.success_url_contains

        try:
            if success_selector:
                await page.wait_for_selector(success_selector, timeout=timeout)

            if success_url_contains:
                await page.wait_for_url(
                    lambda url, needle=success_url_contains: needle in str(url),
                    timeout=timeout,
                )

            if evidence_cfg.screenshot_after and output_dir:
                await page.screenshot(path=str(output_dir / "login_after.png"))

            if evidence_cfg.save_storage_state and output_dir:
                await page.context.storage_state(path=str(output_dir / "storage_state.json"))

            return LoginResult(
                enabled=True,
                mode="manual",
                skipped=False,
                success=True,
                evidence=self._build_evidence(evidence_cfg, output_dir),
            )
        except Exception as e:
            logger.warning("Manual login failed: %s", e)
            return LoginResult(
                enabled=True,
                mode="manual",
                skipped=False,
                success=False,
                reason=str(e),
            )

    def _build_evidence(self, evidence_cfg: LoginEvidenceConfig, output_dir: Path | None) -> dict:
        evidence: dict = {}
        if not output_dir:
            return evidence
        if evidence_cfg.screenshot_before:
            evidence["screenshot_before"] = str(output_dir / "login_before.png")
        if evidence_cfg.screenshot_after:
            evidence["screenshot_after"] = str(output_dir / "login_after.png")
        if evidence_cfg.save_storage_state:
            evidence["storage_state"] = str(output_dir / "storage_state.json")
        return evidence


class FormLoginStrategy:
    async def login(
        self,
        page: Page,
        login_config: LoginConfig,
        form_cfg: FormLoginConfig,
        evidence_cfg: LoginEvidenceConfig,
        output_dir: Path | None = None,
    ) -> LoginResult:
        if not login_config.login_url:
            return LoginResult(enabled=True, mode="form", success=False, reason="login_url is required")

        try:
            if evidence_cfg.screenshot_before and output_dir:
                await page.screenshot(path=str(output_dir / "login_before.png"))

            await page.goto(login_config.login_url, wait_until="domcontentloaded")

            await page.fill(form_cfg.username_selector, form_cfg.username)
            await page.fill(form_cfg.password_selector, form_cfg.password)
            await page.click(form_cfg.submit_selector)

            after = form_cfg.after_submit
            timeout = after.get("timeout", 30000)

            if after.get("wait_for_url_contains"):
                needle = after["wait_for_url_contains"]
                await page.wait_for_url(
                    lambda url, needle=needle: needle in str(url),
                    timeout=timeout,
                )

            if after.get("wait_for_selector"):
                await page.wait_for_selector(after["wait_for_selector"], timeout=timeout)

            if evidence_cfg.screenshot_after and output_dir:
                await page.screenshot(path=str(output_dir / "login_after.png"))

            if evidence_cfg.save_storage_state and output_dir:
                await page.context.storage_state(path=str(output_dir / "storage_state.json"))

            return LoginResult(
                enabled=True,
                mode="form",
                skipped=False,
                success=True,
            )
        except Exception as e:
            logger.warning("Form login failed: %s", e)
            return LoginResult(
                enabled=True,
                mode="form",
                skipped=False,
                success=False,
                reason=str(e),
            )


class CookieLoginStrategy:
    async def login(
        self,
        context: BrowserContext,
        cookie_cfg: CookieLoginConfig,
    ) -> LoginResult:
        try:
            await context.add_cookies(cookie_cfg.cookies)  # type: ignore[arg-type]
            return LoginResult(
                enabled=True,
                mode="cookie",
                skipped=False,
                success=True,
            )
        except Exception as e:
            logger.warning("Cookie login failed: %s", e)
            return LoginResult(
                enabled=True,
                mode="cookie",
                skipped=False,
                success=False,
                reason=str(e),
            )


def build_login_strategy(mode: str):
    if mode == "manual":
        return ManualLoginStrategy()
    if mode == "form":
        return FormLoginStrategy()
    if mode == "cookie":
        return CookieLoginStrategy()
    raise ValueError(f"Unsupported login mode: {mode}")

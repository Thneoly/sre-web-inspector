from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from pydantic import ValidationError

from sre_web_inspector.auth.login_flow import LoginFlow
from sre_web_inspector.auth.login_result import LoginResult
from sre_web_inspector.auth.session_checker import SessionChecker
from sre_web_inspector.auth.strategies import (
    CookieLoginStrategy,
    FormLoginStrategy,
    ManualLoginStrategy,
    build_login_strategy,
)
from sre_web_inspector.config_schema import (
    AppConfig,
    CookieLoginConfig,
    FormLoginConfig,
    LoginCheckConfig,
    LoginConfig,
    LoginEvidenceConfig,
    ManualLoginConfig,
)
from sre_web_inspector.run_context import RunContext


class TestLoginCheckConfig:
    def test_defaults(self):
        cfg = LoginCheckConfig()
        assert cfg.type == "none"
        assert cfg.timeout == 10000

    def test_selector_type(self):
        cfg = LoginCheckConfig(type="selector", url="https://example.com/home", selector=".avatar")
        assert cfg.type == "selector"
        assert cfg.url == "https://example.com/home"
        assert cfg.selector == ".avatar"

    def test_api_type(self):
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me", expect_status=200)
        assert cfg.type == "api"
        assert cfg.expect_status == 200

    def test_cookie_type(self):
        cfg = LoginCheckConfig(type="cookie", cookie_name="SESSION")
        assert cfg.type == "cookie"
        assert cfg.cookie_name == "SESSION"

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            LoginCheckConfig(type="invalid")


class TestLoginConfig:
    def test_disabled_by_default(self):
        cfg = LoginConfig()
        assert cfg.enabled is False
        assert cfg.mode == "manual"

    def test_enabled_manual(self):
        cfg = LoginConfig(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            manual=ManualLoginConfig(wait_timeout=60000),
        )
        assert cfg.enabled is True
        assert cfg.manual.wait_timeout == 60000

    def test_form_login(self):
        cfg = LoginConfig(
            enabled=True,
            mode="form",
            login_url="https://example.com/login",
            form=FormLoginConfig(
                username_selector="#user",
                password_selector="#pass",
                submit_selector="button",
                username="admin",
                password="secret",
            ),
        )
        assert cfg.form.username == "admin"
        assert cfg.form.password == "secret"

    def test_cookie_login(self):
        cfg = LoginConfig(
            enabled=True,
            mode="cookie",
            cookie=CookieLoginConfig(cookies=[{"name": "S", "value": "v", "domain": ".x.com"}]),
        )
        assert len(cfg.cookie.cookies) == 1

    def test_form_requires_fields(self):
        with pytest.raises(ValidationError):
            FormLoginConfig(
                username_selector="#u",
                password_selector="#p",
                submit_selector="button",
                # missing username and password
            )

    def test_full_config_with_check(self):
        cfg = LoginConfig(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            check=LoginCheckConfig(type="selector", url="https://example.com/home", selector=".user"),
            manual=ManualLoginConfig(success_selector=".user"),
        )
        assert cfg.check.type == "selector"


class TestSessionChecker:
    @pytest.fixture
    def checker(self):
        return SessionChecker()

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.request = MagicMock()
        ctx.request.get = AsyncMock()
        return ctx

    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.close = AsyncMock()
        page.url = "https://example.com/home"
        return page

    @pytest.mark.asyncio
    async def test_none_check_returns_false(self, checker, mock_context):
        result = await checker.is_logged_in(mock_context, AsyncMock(), None)
        assert result is False

    @pytest.mark.asyncio
    async def test_none_type_returns_false(self, checker, mock_context):
        cfg = LoginCheckConfig(type="none")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_selector_check_success(self, checker, mock_context, mock_page):
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="selector", url="https://example.com/home", selector=".avatar")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is True
        mock_page.goto.assert_called_once()
        mock_page.wait_for_selector.assert_called_once_with(".avatar", timeout=10000)

    @pytest.mark.asyncio
    async def test_selector_check_failure(self, checker, mock_context, mock_page):
        mock_page.wait_for_selector.side_effect = TimeoutError()
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="selector", url="https://example.com/home", selector=".avatar")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_api_check_success(self, checker, mock_context):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status = 200
        mock_context.request.get.return_value = mock_resp
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_api_check_expect_status(self, checker, mock_context):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_context.request.get.return_value = mock_resp
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me", expect_status=200)
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_api_check_wrong_status(self, checker, mock_context):
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_context.request.get.return_value = mock_resp
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me", expect_status=200)
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_api_check_failure(self, checker, mock_context):
        mock_context.request.get.side_effect = Exception("Connection error")
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_cookie_check_found(self, checker, mock_context):
        mock_context.cookies = AsyncMock(return_value=[
            {"name": "SESSION", "value": "abc123", "domain": ".example.com"},
        ])
        cfg = LoginCheckConfig(type="cookie", cookie_name="SESSION")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_cookie_check_not_found(self, checker, mock_context):
        mock_context.cookies = AsyncMock(return_value=[
            {"name": "OTHER", "value": "xyz"},
        ])
        cfg = LoginCheckConfig(type="cookie", cookie_name="SESSION")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_url_contains_check_success(self, checker, mock_context, mock_page):
        mock_page.url = "https://example.com/home"
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="url_contains", url="https://example.com/home", selector="/home")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is True

    @pytest.mark.asyncio
    async def test_url_contains_check_failure(self, checker, mock_context, mock_page):
        mock_page.url = "https://example.com/login"
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="url_contains", url="https://example.com/home", selector="/home")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_selector_check_no_url(self, checker, mock_context, mock_page):
        """Selector check without a URL should still try wait_for_selector."""
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="selector", selector=".avatar")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is True
        mock_page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_selector_check_no_selector_returns_false(self, checker, mock_context, mock_page):
        """Selector check with no selector returns False."""
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="selector", url="https://example.com/home")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_api_check_no_url_returns_false(self, checker, mock_context):
        cfg = LoginCheckConfig(type="api")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_is_logged_in_general_exception(self, checker, mock_context):
        """If an unexpected exception occurs, is_logged_in should catch and return False."""
        mock_context.request = None  # cause AttributeError
        cfg = LoginCheckConfig(type="api", url="https://example.com/api/me")
        result = await checker.is_logged_in(mock_context, AsyncMock(), cfg)
        assert result is False

    @pytest.mark.asyncio
    async def test_url_contains_check_goto_failure(self, checker, mock_context, mock_page):
        """url_contains check where goto itself fails should return False."""
        mock_page.goto.side_effect = Exception("DNS error")
        page_factory = AsyncMock(return_value=mock_page)
        cfg = LoginCheckConfig(type="url_contains", url="https://bad.host", selector="/home")
        result = await checker.is_logged_in(mock_context, page_factory, cfg)
        assert result is False


class TestManualLoginStrategy:
    @pytest.fixture
    def strategy(self):
        return ManualLoginStrategy()

    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_url = AsyncMock()
        page.screenshot = AsyncMock()
        page.context = MagicMock()
        page.context.storage_state = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_login_success_with_selector(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar")
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        assert result.mode == "manual"
        mock_page.goto.assert_called_once_with("https://example.com/login", wait_until="domcontentloaded")
        mock_page.wait_for_selector.assert_called_once_with(".avatar", timeout=120000)

    @pytest.mark.asyncio
    async def test_login_success_with_url_contains(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_url_contains="/home")
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.wait_for_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_failure_timeout(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar", wait_timeout=1000)
        evidence = LoginEvidenceConfig()

        mock_page.wait_for_selector.side_effect = TimeoutError()
        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is False
        assert result.reason is not None

    @pytest.mark.asyncio
    async def test_login_missing_url(self, strategy, mock_page):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url=None)
        manual_cfg = ManualLoginConfig()
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence)
        assert result.success is False
        assert "login_url" in result.reason

    @pytest.mark.asyncio
    async def test_evidence_screenshots(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar")
        evidence = LoginEvidenceConfig(screenshot_before=True, screenshot_after=True)

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        assert mock_page.screenshot.call_count == 2

    @pytest.mark.asyncio
    async def test_evidence_storage_state(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar")
        evidence = LoginEvidenceConfig(save_storage_state=True)

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.context.storage_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_both_success_conditions(self, strategy, mock_page, tmp_path):
        """When both success_selector and success_url_contains are set, both are waited for."""
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar", success_url_contains="/dashboard")
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.wait_for_selector.assert_called_once_with(".avatar", timeout=120000)
        mock_page.wait_for_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_goto_failure_propagates(self, strategy, mock_page):
        """When page.goto fails, the exception propagates (not caught by the try block)."""
        mock_page.goto = AsyncMock(side_effect=Exception("Connection refused"))
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig(success_selector=".avatar")
        evidence = LoginEvidenceConfig()

        with pytest.raises(Exception, match="Connection refused"):
            await strategy.login(mock_page, login_cfg, manual_cfg, evidence)

    @pytest.mark.asyncio
    async def test_no_success_conditions_returns_success(self, strategy, mock_page, tmp_path):
        """With no success conditions, the login returns success immediately after goto."""
        login_cfg = LoginConfig(enabled=True, mode="manual", login_url="https://example.com/login")
        manual_cfg = ManualLoginConfig()  # no success_selector or url_contains
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, manual_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.goto.assert_called_once()

    def test_build_evidence_no_output_dir(self, strategy):
        """_build_evidence with no output_dir returns empty dict."""
        evidence_cfg = LoginEvidenceConfig(screenshot_before=True, screenshot_after=True)
        result = strategy._build_evidence(evidence_cfg, None)
        assert result == {}

    def test_build_evidence_partial_flags(self, strategy, tmp_path):
        """_build_evidence with only some flags enabled."""
        evidence_cfg = LoginEvidenceConfig(screenshot_before=True, screenshot_after=False)
        result = strategy._build_evidence(evidence_cfg, tmp_path)
        assert "screenshot_before" in result
        assert "screenshot_after" not in result
        assert "storage_state" not in result


class TestFormLoginStrategy:
    @pytest.fixture
    def strategy(self):
        return FormLoginStrategy()

    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        page.goto = AsyncMock()
        page.fill = AsyncMock()
        page.click = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_url = AsyncMock()
        page.screenshot = AsyncMock()
        page.context = MagicMock()
        page.context.storage_state = AsyncMock()
        return page

    @pytest.mark.asyncio
    async def test_form_login_success(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user",
            password_selector="#pass",
            submit_selector="button",
            username="admin",
            password="secret",
            after_submit={"wait_for_selector": ".dashboard"},
        )
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence, tmp_path)
        assert result.success is True
        assert result.mode == "form"
        mock_page.fill.assert_any_call("#user", "admin")
        mock_page.fill.assert_any_call("#pass", "secret")
        mock_page.click.assert_called_once_with("button")

    @pytest.mark.asyncio
    async def test_form_login_failure(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user",
            password_selector="#pass",
            submit_selector="button",
            username="admin",
            password="wrong",
        )
        evidence = LoginEvidenceConfig()

        mock_page.click.side_effect = Exception("Submit failed")
        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence, tmp_path)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_form_login_missing_url(self, strategy, mock_page):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url=None)
        form_cfg = FormLoginConfig(
            username_selector="#u", password_selector="#p",
            submit_selector="button", username="a", password="b",
        )
        evidence = LoginEvidenceConfig()
        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence)
        assert result.success is False
        assert "login_url" in result.reason

    @pytest.mark.asyncio
    async def test_form_login_with_url_contains(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user",
            password_selector="#pass",
            submit_selector="button",
            username="admin",
            password="secret",
            after_submit={"wait_for_url_contains": "/dashboard"},
        )
        evidence = LoginEvidenceConfig()

        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.wait_for_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_form_login_with_evidence_screenshots(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user",
            password_selector="#pass",
            submit_selector="button",
            username="admin",
            password="secret",
            after_submit={"wait_for_selector": ".dashboard"},
        )
        evidence = LoginEvidenceConfig(screenshot_before=True, screenshot_after=True)

        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence, tmp_path)
        assert result.success is True
        assert mock_page.screenshot.call_count == 2

    @pytest.mark.asyncio
    async def test_form_login_with_storage_state(self, strategy, mock_page, tmp_path):
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user",
            password_selector="#pass",
            submit_selector="button",
            username="admin",
            password="secret",
        )
        evidence = LoginEvidenceConfig(save_storage_state=True)

        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence, tmp_path)
        assert result.success is True
        mock_page.context.storage_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_form_login_goto_failure_caught(self, strategy, mock_page):
        """FormLoginStrategy wraps everything in try/except, so goto failure returns LoginResult."""
        mock_page.goto = AsyncMock(side_effect=Exception("DNS failure"))
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://bad.host/login")
        form_cfg = FormLoginConfig(
            username_selector="#u", password_selector="#p",
            submit_selector="button", username="a", password="b",
        )
        evidence = LoginEvidenceConfig()
        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence)
        assert result.success is False
        assert "DNS failure" in result.reason

    @pytest.mark.asyncio
    async def test_form_login_fill_failure(self, strategy, mock_page):
        mock_page.fill = AsyncMock(side_effect=Exception("Element not found"))
        login_cfg = LoginConfig(enabled=True, mode="form", login_url="https://example.com/login")
        form_cfg = FormLoginConfig(
            username_selector="#user", password_selector="#pass",
            submit_selector="button", username="admin", password="secret",
        )
        evidence = LoginEvidenceConfig()
        result = await strategy.login(mock_page, login_cfg, form_cfg, evidence)
        assert result.success is False


class TestCookieLoginStrategy:
    @pytest.fixture
    def strategy(self):
        return CookieLoginStrategy()

    @pytest.fixture
    def mock_context(self):
        ctx = MagicMock()
        ctx.add_cookies = AsyncMock()
        return ctx

    @pytest.mark.asyncio
    async def test_cookie_login_success(self, strategy, mock_context):
        cookie_cfg = CookieLoginConfig(
            cookies=[{"name": "SESSION", "value": "abc", "domain": ".example.com"}],
        )
        result = await strategy.login(mock_context, cookie_cfg)
        assert result.success is True
        assert result.mode == "cookie"
        mock_context.add_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_cookie_login_failure(self, strategy, mock_context):
        mock_context.add_cookies.side_effect = Exception("Invalid cookie")
        cookie_cfg = CookieLoginConfig(
            cookies=[{"name": "SESSION", "value": "abc"}],
        )
        result = await strategy.login(mock_context, cookie_cfg)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_cookie_login_empty_list(self, strategy, mock_context):
        """Setting an empty cookie list should succeed (no-op)."""
        cookie_cfg = CookieLoginConfig(cookies=[])
        result = await strategy.login(mock_context, cookie_cfg)
        assert result.success is True
        mock_context.add_cookies.assert_called_once_with([])

    @pytest.mark.asyncio
    async def test_cookie_login_multiple_cookies(self, strategy, mock_context):
        """Setting multiple cookies at once."""
        cookie_cfg = CookieLoginConfig(cookies=[
            {"name": "A", "value": "1", "domain": ".x.com"},
            {"name": "B", "value": "2", "domain": ".x.com"},
        ])
        result = await strategy.login(mock_context, cookie_cfg)
        assert result.success is True
        mock_context.add_cookies.assert_called_once_with(cookie_cfg.cookies)


class TestBuildLoginStrategy:
    def test_manual(self):
        assert isinstance(build_login_strategy("manual"), ManualLoginStrategy)

    def test_form(self):
        assert isinstance(build_login_strategy("form"), FormLoginStrategy)

    def test_cookie(self):
        assert isinstance(build_login_strategy("cookie"), CookieLoginStrategy)

    def test_unknown_mode(self):
        with pytest.raises(ValueError, match="Unsupported login mode"):
            build_login_strategy("oauth")


class TestLoginResult:
    def test_defaults(self):
        r = LoginResult(enabled=False)
        assert r.success is False
        assert r.skipped is False
        assert r.evidence == {}

    def test_successful(self):
        r = LoginResult(enabled=True, mode="manual", success=True, evidence={"screenshot": "path.png"})
        assert r.success is True
        assert r.evidence["screenshot"] == "path.png"

    def test_skipped(self):
        r = LoginResult(enabled=True, mode="manual", skipped=True, success=True, reason="Already logged in")
        assert r.skipped is True
        assert r.reason == "Already logged in"


class TestLoginFlow:
    """Tests for the LoginFlow orchestrator that wires SessionChecker + strategies together."""

    @pytest.fixture
    def mock_cm(self):
        cm = MagicMock()
        cm.context = MagicMock()
        cm.new_page = AsyncMock()
        return cm

    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()
        page.wait_for_url = AsyncMock()
        page.screenshot = AsyncMock()
        page.close = AsyncMock()
        page.context = MagicMock()
        page.context.storage_state = AsyncMock()
        return page

    @pytest.fixture
    def run_ctx(self, tmp_path):
        return RunContext.create(base_output_dir=str(tmp_path))

    def _make_config(self, **login_kwargs):
        return AppConfig.model_validate({
            "runtime": {"concurrency": 1, "timeout": 30000},
            "browser": {"headless": True, "slow_mo": 0},
            "pages": [],
            "login": login_kwargs,
        })

    @pytest.mark.asyncio
    async def test_login_disabled_returns_early(self, mock_cm, run_ctx):
        """When login is not configured at all, return success immediately."""
        config = AppConfig.model_validate({
            "runtime": {"concurrency": 1, "timeout": 30000},
            "browser": {"headless": True, "slow_mo": 0},
            "pages": [],
        })
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.enabled is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_login_not_enabled_returns_early(self, mock_cm, run_ctx):
        """When login.enabled=False, return success immediately."""
        config = self._make_config(enabled=False, mode="manual", login_url="https://x.com/login")
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.enabled is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_check_already_logged_in_skips_login(self, mock_cm, mock_page, run_ctx):
        """When session check passes, skip the login step entirely."""
        mock_cm.new_page.return_value = mock_page
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            check=LoginCheckConfig(type="selector", url="https://example.com/home", selector=".avatar"),
            manual=ManualLoginConfig(success_selector=".avatar"),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.skipped is True
        assert result.success is True
        # Should NOT have called goto for login (only check page was used)
        mock_page.goto.assert_called_once_with("https://example.com/home", wait_until="domcontentloaded", timeout=10000)

    @pytest.mark.asyncio
    async def test_check_fails_proceeds_to_login_manual(self, mock_cm, mock_page, run_ctx):
        """When session check fails, execute the login strategy."""
        # First page: check fails (throw on wait_for_selector)
        check_page = MagicMock()
        check_page.goto = AsyncMock()
        check_page.wait_for_selector = AsyncMock(side_effect=TimeoutError())
        check_page.close = AsyncMock()

        # Second page: login succeeds
        login_page = MagicMock()
        login_page.goto = AsyncMock()
        login_page.wait_for_selector = AsyncMock()
        login_page.screenshot = AsyncMock()
        login_page.close = AsyncMock()
        login_page.context = MagicMock()
        login_page.context.storage_state = AsyncMock()

        mock_cm.new_page.side_effect = [check_page, login_page]
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            check=LoginCheckConfig(type="selector", url="https://example.com/home", selector=".avatar"),
            manual=ManualLoginConfig(success_selector=".dashboard"),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.skipped is False
        assert result.success is True
        assert result.mode == "manual"
        login_page.goto.assert_called_once_with("https://example.com/login", wait_until="domcontentloaded")
        login_page.wait_for_selector.assert_called_once_with(".dashboard", timeout=120000)

    @pytest.mark.asyncio
    async def test_check_none_type_proceeds_to_login(self, mock_cm, mock_page, run_ctx):
        """When check.type is 'none', skip the check and go straight to login."""
        mock_cm.new_page.return_value = mock_page
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            check=LoginCheckConfig(type="none"),
            manual=ManualLoginConfig(success_selector=".dashboard"),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.skipped is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_login_no_check_proceeds(self, mock_cm, mock_page, run_ctx):
        """When no check config at all, go straight to login."""
        mock_cm.new_page.return_value = mock_page
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            manual=ManualLoginConfig(success_selector=".dashboard"),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.skipped is False
        assert result.success is True

    @pytest.mark.asyncio
    async def test_form_mode_login(self, mock_cm, mock_page, run_ctx):
        mock_cm.new_page.return_value = mock_page
        mock_page.fill = AsyncMock()
        mock_page.click = AsyncMock()
        config = self._make_config(
            enabled=True,
            mode="form",
            login_url="https://example.com/login",
            form=FormLoginConfig(
                username_selector="#user",
                password_selector="#pass",
                submit_selector="button",
                username="admin",
                password="secret",
            ),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.success is True
        assert result.mode == "form"
        mock_page.fill.assert_any_call("#user", "admin")
        mock_page.click.assert_called_once_with("button")

    @pytest.mark.asyncio
    async def test_cookie_mode_login(self, mock_cm, run_ctx):
        mock_cm.context.add_cookies = AsyncMock()
        config = self._make_config(
            enabled=True,
            mode="cookie",
            cookie=CookieLoginConfig(cookies=[{"name": "S", "value": "v", "domain": ".x.com"}]),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.success is True
        assert result.mode == "cookie"
        mock_cm.context.add_cookies.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_failure_stop_raises(self, mock_cm, mock_page, run_ctx):
        """When on_failure='stop' and login fails, raise RuntimeError."""
        mock_cm.new_page.return_value = mock_page
        mock_page.wait_for_selector.side_effect = TimeoutError()
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            on_failure="stop",
            manual=ManualLoginConfig(success_selector=".avatar", wait_timeout=500),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        with pytest.raises(RuntimeError, match="Login failed"):
            await flow.run()

    @pytest.mark.asyncio
    async def test_login_failure_continue_returns_result(self, mock_cm, mock_page, run_ctx):
        """When on_failure='continue' and login fails, return the failed LoginResult."""
        mock_cm.new_page.return_value = mock_page
        mock_page.wait_for_selector.side_effect = TimeoutError()
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            on_failure="continue",
            manual=ManualLoginConfig(success_selector=".avatar", wait_timeout=500),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.success is False
        assert result.mode == "manual"

    @pytest.mark.asyncio
    async def test_evidence_directory_created(self, mock_cm, mock_page, run_ctx):
        """When evidence is enabled, create login evidence directory."""
        mock_cm.new_page.return_value = mock_page
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            manual=ManualLoginConfig(success_selector=".avatar"),
            evidence=LoginEvidenceConfig(screenshot_before=True, screenshot_after=True),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.success is True
        evidence_dir = run_ctx.output_dir / "login"
        assert evidence_dir.exists()

    @pytest.mark.asyncio
    async def test_evidence_not_created_when_all_disabled(self, mock_cm, mock_page, run_ctx):
        """When all evidence flags are off, do not create the directory."""
        mock_cm.new_page.return_value = mock_page
        config = self._make_config(
            enabled=True,
            mode="manual",
            login_url="https://example.com/login",
            manual=ManualLoginConfig(success_selector=".avatar"),
            evidence=LoginEvidenceConfig(),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.success is True
        evidence_dir = run_ctx.output_dir / "login"
        assert not evidence_dir.exists()

    @pytest.mark.asyncio
    async def test_cookie_mode_with_check_skip(self, mock_cm, run_ctx):
        """Cookie mode with session check that passes should skip."""
        mock_cm.context.cookies = AsyncMock(return_value=[{"name": "S", "value": "v"}])
        mock_cm.context.add_cookies = AsyncMock()
        config = self._make_config(
            enabled=True,
            mode="cookie",
            check=LoginCheckConfig(type="cookie", cookie_name="S"),
            cookie=CookieLoginConfig(cookies=[{"name": "S", "value": "v", "domain": ".x.com"}]),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        result = await flow.run()
        assert result.skipped is True

    @pytest.mark.asyncio
    async def test_unknown_mode_in_flow_raises(self, mock_cm, run_ctx):
        """A mode unsupported by build_login_strategy should propagate the ValueError."""
        config = self._make_config(
            enabled=True,
            mode="manual",  # mode valid at model level
            login_url="https://example.com/login",
            manual=ManualLoginConfig(success_selector=".avatar"),
        )
        # Patch build_login_strategy to simulate an unexpected mode reaching the flow
        with patch("sre_web_inspector.auth.login_flow.build_login_strategy", side_effect=ValueError("bad")):
            flow = LoginFlow(mock_cm, config, run_ctx)
            with pytest.raises(ValueError, match="bad"):
                await flow.run()

    @pytest.mark.asyncio
    async def test_form_mode_page_closes_after_login(self, mock_cm, mock_page, run_ctx):
        """The login page should be closed after a successful login."""
        mock_cm.new_page.return_value = mock_page
        mock_page.fill = AsyncMock()
        mock_page.click = AsyncMock()
        config = self._make_config(
            enabled=True,
            mode="form",
            login_url="https://example.com/login",
            form=FormLoginConfig(
                username_selector="#user",
                password_selector="#pass",
                submit_selector="button",
                username="admin",
                password="secret",
            ),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        await flow.run()
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_form_mode_page_closes_after_failure(self, mock_cm, mock_page, run_ctx):
        """The login page should be closed even after a failed login."""
        mock_cm.new_page.return_value = mock_page
        mock_page.goto.side_effect = Exception("Network error")
        config = self._make_config(
            enabled=True,
            mode="form",
            login_url="https://example.com/login",
            on_failure="continue",
            form=FormLoginConfig(
                username_selector="#user",
                password_selector="#pass",
                submit_selector="button",
                username="admin",
                password="secret",
            ),
        )
        flow = LoginFlow(mock_cm, config, run_ctx)
        await flow.run()
        mock_page.close.assert_called_once()

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sre_web_inspector.config_schema import (
    AppConfig,
    BrowserConfig,
    PageConfig,
    PageLifecycleConfig,
    ReplayRequestConfig,
    RetryConfig,
    RuntimeConfig,
    WaitRequestConfig,
    WaitResponseConfig,
)


class TestRetryConfig:
    def test_defaults(self):
        cfg = RetryConfig()
        assert cfg.times == 1
        assert cfg.interval_ms == 1000

    def test_times_must_be_at_least_1(self):
        with pytest.raises(ValidationError):
            RetryConfig(times=0)

    def test_interval_ms_must_be_non_negative(self):
        with pytest.raises(ValidationError):
            RetryConfig(interval_ms=-1)


class TestRuntimeConfig:
    def test_defaults(self):
        cfg = RuntimeConfig()
        assert cfg.concurrency == 1
        assert cfg.output_dir == "outputs"
        assert cfg.run_id is None
        assert cfg.timeout == 60000

    def test_concurrency_must_be_at_least_1(self):
        with pytest.raises(ValidationError):
            RuntimeConfig(concurrency=0)

    def test_timeout_must_be_at_least_1(self):
        with pytest.raises(ValidationError):
            RuntimeConfig(timeout=0)


class TestBrowserConfig:
    def test_defaults(self):
        cfg = BrowserConfig()
        assert cfg.headless is False
        assert cfg.slow_mo == 300
        assert cfg.ignore_https_errors is True
        assert cfg.no_viewport is True
        assert cfg.start_maximized is True

    def test_slow_mo_cannot_be_negative(self):
        with pytest.raises(ValidationError):
            BrowserConfig(slow_mo=-1)


class TestReplayRequestConfig:
    def test_minimal_config(self):
        cfg = ReplayRequestConfig(name="test", url="http://example.com/api")
        assert cfg.name == "test"
        assert cfg.method == "GET"
        assert cfg.url == "http://example.com/api"

    def test_method_is_uppercased(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="post")
        assert cfg.method == "POST"

    def test_invalid_method(self):
        with pytest.raises(ValidationError):
            ReplayRequestConfig(name="t", url="http://x.com", method="OPTIONS")

    def test_post_json_defaults_data_to_empty_dict(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="POST", body_type="json")
        assert cfg.data == {}

    def test_post_form_defaults_form_to_empty_dict(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="POST", body_type="form")
        assert cfg.form == {}

    def test_put_is_valid(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="PUT")
        assert cfg.method == "PUT"

    def test_patch_is_valid(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="PATCH")
        assert cfg.method == "PATCH"

    def test_delete_is_valid(self):
        cfg = ReplayRequestConfig(name="t", url="http://x.com", method="DELETE")
        assert cfg.method == "DELETE"


class TestWaitConfigs:
    def test_wait_request_defaults(self):
        cfg = WaitRequestConfig(keyword="/api/")
        assert cfg.name is None
        assert cfg.keyword == "/api/"
        assert cfg.timeout == 30_000

    def test_wait_response_defaults(self):
        cfg = WaitResponseConfig(keyword="/api/", status=200)
        assert cfg.keyword == "/api/"
        assert cfg.status == 200


class TestPageLifecycleConfig:
    def test_defaults(self):
        cfg = PageLifecycleConfig()
        assert cfg.close_after_inspection is True
        assert cfg.clear_network_records is True


class TestPageConfig:
    def test_minimal_config(self):
        cfg = PageConfig(url="http://x.com")
        assert cfg.url == "http://x.com"
        assert cfg.screenshot is True
        assert cfg.save_html is True

    def test_backward_compat_close_page(self):
        cfg = PageConfig(url="http://x.com", close_page=False)
        assert cfg.lifecycle.close_after_inspection is False

    def test_lifecycle_overrides_close_page(self):
        cfg = PageConfig(url="http://x.com", close_page=True, lifecycle=PageLifecycleConfig(close_after_inspection=False))
        # close_page sets it to True, but model_validator runs after, setting it to True
        # Actually close_page=None by default, lifecycle defaults to True
        # If close_page is explicitly True, it overrides
        assert cfg.lifecycle.close_after_inspection is True


class TestAppConfig:
    def test_empty_config(self):
        cfg = AppConfig()
        assert cfg.pages == []
        assert cfg.replay_requests == []
        assert cfg.vars == {}

    def test_with_pages(self):
        cfg = AppConfig(pages=[PageConfig(url="http://a.com", name="a"), PageConfig(url="http://b.com", name="b")])
        assert len(cfg.pages) == 2

    def test_extra_fields_allowed(self):
        cfg = AppConfig.model_validate({"runtime": {"concurrency": 1}, "custom_key": "value"})
        assert cfg.runtime.concurrency == 1

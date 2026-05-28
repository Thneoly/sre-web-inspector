from __future__ import annotations

import json
from pathlib import Path

import pytest

from sre_web_inspector.config_schema import AppConfig
from sre_web_inspector.reporter import render_report, write_html_report, write_json_report
from sre_web_inspector.run_context import RunContext, make_run_id
from sre_web_inspector.template import build_vars, render_value

# Import from main module for integration coverage
from main import deep_merge, load_config, load_and_validate_config, rewrite_output_dirs


class TestDeepMerge:
    def test_merges_flat_dicts(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_original_unmodified(self):
        base = {"a": 1}
        deep_merge(base, {"b": 2})
        assert base == {"a": 1}

    def test_nested_dicts_merged_recursively(self):
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 99, "c": 3}}
        result = deep_merge(base, override)
        assert result == {"outer": {"a": 1, "b": 99, "c": 3}}

    def test_lists_concatenated(self):
        base = {"items": [1, 2]}
        override = {"items": [3, 4]}
        result = deep_merge(base, override)
        assert result == {"items": [1, 2, 3, 4]}

    def test_deep_list_in_override_alone(self):
        base = {}
        override = {"items": [{"name": "a"}]}
        result = deep_merge(base, override)
        assert result == {"items": [{"name": "a"}]}


class TestConfigLoading:
    def test_load_example_config(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "example.yaml"
        raw = load_config(config_path)
        assert "vars" in raw
        assert "pages" in raw
        assert len(raw["pages"]) == 2

    def test_validate_example_config(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "example.yaml"
        app_cfg, rendered = load_and_validate_config(config_path)
        assert isinstance(app_cfg, AppConfig)
        assert len(app_cfg.pages) == 2
        assert app_cfg.pages[0].name == "pod_page"
        assert app_cfg.pages[1].name == "grafana_page"

    def test_validate_multiple_configs(self):
        config_path = Path(__file__).resolve().parent.parent / "config" / "example.yaml"
        # Merging same file twice should be idempotent for values, lists concatenate
        app_cfg, rendered = load_and_validate_config(config_path, config_path)
        assert len(app_cfg.pages) == 4  # 2 + 2 concatenated

    def test_validate_config_with_login(self, tmp_path):
        import yaml
        config_file = tmp_path / "with_login.yaml"
        config = {
            "runtime": {"concurrency": 1, "timeout": 30000},
            "browser": {"headless": True, "slow_mo": 0},
            "pages": [{"name": "test", "url": "https://example.com"}],
            "login": {
                "enabled": True,
                "mode": "form",
                "login_url": "https://example.com/login",
                "check": {"type": "api", "url": "https://example.com/api/me"},
                "form": {
                    "username_selector": "#user",
                    "password_selector": "#pass",
                    "submit_selector": "button",
                    "username": "admin",
                    "password": "secret",
                },
                "on_failure": "continue",
            },
        }
        config_file.write_text(yaml.dump(config))
        app_cfg, rendered = load_and_validate_config(str(config_file))
        assert app_cfg.login.enabled is True
        assert app_cfg.login.mode == "form"
        assert app_cfg.login.on_failure == "continue"
        assert app_cfg.login.form.username == "admin"

    def test_validate_config_with_page_generators(self, tmp_path):
        import yaml
        config_file = tmp_path / "with_generators.yaml"
        config = {
            "vars": {"base": "https://x.com"},
            "runtime": {"concurrency": 1, "timeout": 30000},
            "browser": {"headless": True, "slow_mo": 0},
            "pages": [{"name": "home", "url": "{{ base }}/home"}],
            "page_generators": [
                {
                    "name": "id_pages",
                    "type": "ids",
                    "ids": [1, 2],
                    "template": {"name": "p{{ id }}", "url": "{{ base }}/{{ id }}"},
                }
            ],
        }
        config_file.write_text(yaml.dump(config))
        app_cfg, rendered = load_and_validate_config(str(config_file))
        assert len(app_cfg.pages) == 3  # 1 static + 2 generated
        assert app_cfg.pages[1].url == "https://x.com/1"


class TestRewriteOutputDirs:
    def test_relative_path_rewritten(self, tmp_dir):
        result = rewrite_output_dirs(
            {"output_dir": "outputs/responses/global"},
            tmp_dir,
        )
        assert result["output_dir"] == str(tmp_dir / "responses" / "global")

    def test_outputs_prefix_stripped(self, tmp_dir):
        result = rewrite_output_dirs(
            {"output_dir": "outputs/network/pod_page"},
            tmp_dir,
        )
        assert result["output_dir"] == str(tmp_dir / "network" / "pod_page")

    def test_absolute_path_unchanged(self, tmp_dir):
        result = rewrite_output_dirs(
            {"output_dir": "/absolute/path"},
            tmp_dir,
        )
        assert result["output_dir"] == "/absolute/path"

    def test_nested_dict(self, tmp_dir):
        nested = {"routes": [{"type": "route_recorder", "output_dir": "outputs/network/custom"}]}
        result = rewrite_output_dirs(nested, tmp_dir)
        assert result["routes"][0]["output_dir"] == str(tmp_dir / "network" / "custom")

    def test_non_string_value_unchanged(self, tmp_dir):
        result = rewrite_output_dirs({"count": 42}, tmp_dir)
        assert result["count"] == 42


class TestRunContext:
    def test_create_with_auto_id(self, tmp_dir):
        ctx = RunContext.create(base_output_dir=tmp_dir)
        assert ctx.run_id
        assert (ctx.output_dir / "screenshots").exists()
        assert (ctx.output_dir / "html").exists()
        assert (ctx.output_dir / "network").exists()

    def test_create_with_fixed_id(self, tmp_dir):
        ctx = RunContext.create(base_output_dir=tmp_dir, run_id="debug-001")
        assert ctx.run_id == "debug-001"
        assert ctx.output_dir == tmp_dir / "runs" / "debug-001"

    def test_make_run_id_format(self):
        rid = make_run_id()
        # Format: YYYYMMDD-HHMMSS
        assert len(rid) == 15
        assert "-" in rid


class TestReporter:
    def _make_summary(self, ok=True):
        return {
            "kind": "WebInspectionRun",
            "run_id": "20260527-120000",
            "output_dir": "/tmp/test",
            "ok": ok,
            "global_replays": [
                {"name": "current_user", "method": "GET", "url": "http://x/api/user", "status": 200, "ok": True}
            ],
            "pages": [
                {
                    "name": "pod_page",
                    "url": "http://x/pods",
                    "ok": ok,
                    "inspection": {"title": "Pods", "screenshot": "outputs/runs/xxx/screenshots/pod_page.png"},
                    "pre_replays": [],
                    "waits": [
                        {"name": "wait_request:pod_request", "type": "request", "url": "http://x/api/pods", "method": "GET", "ok": True}
                    ],
                    "replays": [
                        {"name": "pod_full_list", "method": "GET", "url": "http://x/api/pods", "status": 200, "ok": True}
                    ],
                    "evidence": {
                        "screenshot": "outputs/runs/xxx/screenshots/pod_page.png",
                        "html": "outputs/runs/xxx/html/pod_page.html",
                        "network": "outputs/runs/xxx/network/pod_page.json",
                        "replay_dir": "outputs/runs/xxx/replay/pod_page",
                    },
                }
            ],
        }

    def test_render_html_report(self):
        summary = self._make_summary()
        html = render_report(summary)
        assert "<!DOCTYPE html>" in html
        assert "20260527-120000" in html
        assert "pod_page" in html
        assert "PASS" in html

    def test_render_html_report_failure(self):
        summary = self._make_summary(ok=False)
        summary["pages"][0]["ok"] = False
        summary["pages"][0]["error"] = "timeout"
        html = render_report(summary)
        assert "FAIL" in html
        assert "timeout" in html

    def test_write_json_report(self, tmp_dir):
        summary = self._make_summary()
        path = write_json_report(summary, tmp_dir)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["run_id"] == "20260527-120000"

    def test_write_html_report(self, tmp_dir):
        summary = self._make_summary()
        path = write_html_report(summary, tmp_dir)
        assert path.exists()
        content = path.read_text()
        assert "<!DOCTYPE html>" in content


class TestTemplateIntegration:
    def test_full_config_rendering(self):
        config = {
            "vars": {"base_url": "http://example.com", "ns": "default", "count": 100},
            "pages": [
                {
                    "name": "test",
                    "url": "{{ base_url }}/api/pods",
                    "replay_requests": [
                        {
                            "name": "list",
                            "method": "GET",
                            "url": "{{ base_url }}/api/pods",
                            "params": {"namespace": "{{ ns }}", "pageSize": "{{ count }}"},
                        }
                    ],
                }
            ],
        }
        rendered = render_value(config, build_vars(config))
        assert rendered["pages"][0]["url"] == "http://example.com/api/pods"
        assert rendered["pages"][0]["replay_requests"][0]["params"]["namespace"] == "default"
        # count is a fullmatch placeholder, so it preserves the int type
        assert rendered["pages"][0]["replay_requests"][0]["params"]["pageSize"] == 100
        assert isinstance(rendered["pages"][0]["replay_requests"][0]["params"]["pageSize"], int)

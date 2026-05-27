from __future__ import annotations

import logging

import pytest

from sre_web_inspector.template import build_vars, get_by_path, render_value


class TestGetByPath:
    def test_simple_key(self):
        assert get_by_path({"a": 1}, "a") == 1

    def test_nested_key(self):
        data = {"a": {"b": {"c": 42}}}
        assert get_by_path(data, "a.b.c") == 42

    def test_missing_key_returns_default(self):
        assert get_by_path({"a": 1}, "b", "fallback") == "fallback"

    def test_missing_nested_returns_default(self):
        assert get_by_path({"a": {"b": 1}}, "a.x.y", None) is None

    def test_non_mapping_intermediate(self):
        data = {"a": 1}
        assert get_by_path(data, "a.b", "default") == "default"


class TestRenderValue:
    def test_no_template_returns_unchanged(self):
        assert render_value("hello world", {}) == "hello world"

    def test_single_var_replaced(self):
        assert render_value("hello {{ name }} world", {"name": "Alice"}) == "hello Alice world"

    def test_fullmatch_preserves_type_int(self):
        result = render_value("{{ count }}", {"count": 200})
        assert result == 200
        assert isinstance(result, int)

    def test_fullmatch_preserves_type_bool(self):
        result = render_value("{{ flag }}", {"flag": True})
        assert result is True

    def test_fullmatch_preserves_type_list(self):
        result = render_value("{{ items }}", {"items": [1, 2, 3]})
        assert result == [1, 2, 3]

    def test_multiple_vars_in_string(self):
        result = render_value("{{ a }}/{{ b }}", {"a": "foo", "b": "bar"})
        assert result == "foo/bar"

    def test_nested_var_path(self):
        result = render_value("{{ db.host }}:{{ db.port }}", {"db": {"host": "localhost", "port": 5432}})
        assert result == "localhost:5432"

    def test_non_string_passthrough(self):
        assert render_value(42, {}) == 42
        assert render_value(True, {}) is True
        assert render_value(None, {}) is None

    def test_dict_recursive(self):
        result = render_value({"url": "{{ base }}/api", "num": "{{ n }}"}, {"base": "http://x", "n": 1})
        assert result == {"url": "http://x/api", "num": 1}

    def test_list_recursive(self):
        result = render_value(["{{ a }}", "static", "{{ b }}"], {"a": "x", "b": "y"})
        assert result == ["x", "static", "y"]

    def test_missing_var_warns_and_keeps_placeholder(self, caplog):
        caplog.set_level(logging.WARNING)
        result = render_value("{{ no_such_var }}/api", {})
        assert "{{ no_such_var }}/api" == result
        assert "no_such_var" in caplog.text

    def test_missing_var_fullmatch_warns(self, caplog):
        caplog.set_level(logging.WARNING)
        result = render_value("{{ no_such_var }}", {})
        assert "no_such_var" in caplog.text
        assert result == "{{ no_such_var }}"

    def test_whitespace_in_braces(self):
        result = render_value("{{   key   }}", {"key": "val"})
        assert result == "val"

    def test_special_chars_in_varname(self):
        result = render_value("{{ api.key-name }}", {"api": {"key-name": "found"}})
        assert result == "found"


class TestBuildVars:
    def test_extracts_vars_section(self):
        config = {"vars": {"a": 1, "b": 2}}
        result = build_vars(config)
        assert result == {"a": 1, "b": 2}

    def test_merges_extra(self):
        config = {"vars": {"a": 1}}
        result = build_vars(config, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_extra_overrides_vars(self):
        config = {"vars": {"a": 1}}
        result = build_vars(config, {"a": 99})
        assert result == {"a": 99}

    def test_no_vars_section(self):
        result = build_vars({})
        assert result == {}

from __future__ import annotations

from sre_web_inspector.request_utils import (
    mask_headers,
    patch_json_body,
    patch_url_query,
    safe_filename,
)


class TestPatchUrlQuery:
    def test_set_single_param(self):
        result = patch_url_query("http://example.com/api", set_params={"page": "1"})
        assert result == "http://example.com/api?page=1"

    def test_set_multiple_params(self):
        result = patch_url_query("http://example.com/api", set_params={"a": "1", "b": "2"})
        assert "a=1" in result
        assert "b=2" in result

    def test_override_existing_param(self):
        result = patch_url_query("http://example.com/api?page=1", set_params={"page": "10"})
        assert "page=10" in result

    def test_remove_param(self):
        result = patch_url_query("http://example.com/api?page=1&sort=asc", remove_params=["page"])
        assert "page=1" not in result
        assert "sort=asc" in result

    def test_set_and_remove_together(self):
        result = patch_url_query("http://example.com/api?old=1", set_params={"new": "2"}, remove_params=["old"])
        assert "old=1" not in result
        assert "new=2" in result

    def test_url_with_fragment(self):
        result = patch_url_query("http://example.com/api#section", set_params={"a": "1"})
        assert result.endswith("#section")
        assert "a=1" in result

    def test_no_changes(self):
        result = patch_url_query("http://example.com/api")
        assert result == "http://example.com/api"


class TestPatchJsonBody:
    def test_add_key(self):
        result = patch_json_body({"a": 1}, {"b": 2})
        assert result == {"a": 1, "b": 2}

    def test_override_key(self):
        result = patch_json_body({"a": 1}, {"a": 99})
        assert result == {"a": 99}

    def test_empty_body(self):
        result = patch_json_body({}, {"x": "y"})
        assert result == {"x": "y"}

    def test_original_unmodified(self):
        original = {"a": 1}
        result = patch_json_body(original, {"b": 2})
        assert original == {"a": 1}
        assert result == {"a": 1, "b": 2}


class TestMaskHeaders:
    def test_masks_default_sensitive_keys(self):
        headers = {"Authorization": "Bearer token123", "Content-Type": "application/json", "Cookie": "session=abc"}
        result = mask_headers(headers)
        assert result["Authorization"] == "***MASKED***"
        assert result["Cookie"] == "***MASKED***"
        assert result["Content-Type"] == "application/json"

    def test_case_insensitive(self):
        headers = {"authorization": "Bearer xyz", "AUTHORIZATION": "Bearer abc"}
        result = mask_headers(headers)
        assert result["authorization"] == "***MASKED***"
        assert result["AUTHORIZATION"] == "***MASKED***"

    def test_custom_sensitive_keys(self):
        headers = {"X-API-Key": "secret", "X-Request-Id": "123"}
        result = mask_headers(headers, sensitive_keys=["x-request-id"])
        assert result["X-Request-Id"] == "***MASKED***"
        assert result["X-API-Key"] == "secret"

    def test_empty_headers(self):
        assert mask_headers({}) == {}


class TestSafeFilename:
    def test_removes_special_chars(self):
        result = safe_filename("hello:world*test?query<data>")
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert "<" not in result
        assert ">" not in result

    def test_replaces_spaces(self):
        result = safe_filename("my file name")
        assert " " not in result
        assert result == "my_file_name"

    def test_truncates_long_names(self):
        long_name = "a" * 200
        result = safe_filename(long_name, max_len=120)
        assert len(result) == 120

    def test_empty_name_returns_unnamed(self):
        assert safe_filename("") == "unnamed"

    def test_common_url_chars(self):
        result = safe_filename("https://example.com/api/pods?namespace=default&pageSize=200")
        assert "/" not in result
        assert "&" not in result
        assert "=" not in result
        assert "?" not in result

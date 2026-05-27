"""Tests for ApiCapture in-memory response capture."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from sre_web_inspector.api_capture import ApiCapture


def _make_mock_response(url: str, content_type: str, json_data: dict) -> MagicMock:
    """Build a mock Playwright Response object."""
    resp = MagicMock()
    resp.url = url
    resp.headers = {"content-type": content_type}
    resp.status = 200
    resp.json = AsyncMock(return_value=json_data)
    return resp


class TestApiCaptureHandlerSync:
    """Handler tests that do NOT require an event loop."""

    def test_skips_non_json(self) -> None:
        cap = ApiCapture()
        resp = _make_mock_response("https://x.com/page", "text/html", {})
        cap.handler(resp)
        assert len(cap.responses) == 0

    def test_skips_no_content_type(self) -> None:
        cap = ApiCapture()
        resp = MagicMock()
        resp.url = "https://x.com/api"
        resp.headers = {}
        cap.handler(resp)
        assert len(cap.responses) == 0

    def test_url_keyword_filter_no_event_loop(self) -> None:
        """Handler with url_keywords skips non-matching before ensure_future."""
        cap = ApiCapture(url_keywords=["/api/"])
        resp_bad = _make_mock_response("https://x.com/static/config.json", "application/json", {"b": 2})
        cap.handler(resp_bad)
        assert len(cap.responses) == 0

    def test_url_exclude_filter_no_event_loop(self) -> None:
        cap = ApiCapture(url_exclude=["/analytics/"])
        resp_bad = _make_mock_response("https://x.com/analytics/track", "application/json", {"b": 2})
        cap.handler(resp_bad)
        assert len(cap.responses) == 0

    def test_max_captures_limit_reached(self) -> None:
        """When limit is reached, ensure_future is not called."""
        cap = ApiCapture(max_captures=2)
        cap._scheduled = 2  # simulate already-full state
        resp = _make_mock_response("https://x.com/api/3", "application/json", {"i": 3})
        cap.handler(resp)
        assert cap._scheduled == 2  # unchanged, no new schedule


class TestApiCaptureHandlerAsync:
    """Handler tests that need an event loop."""

    @pytest.mark.asyncio
    async def test_accepts_json_response(self) -> None:
        cap = ApiCapture()
        resp = _make_mock_response(
            "https://api.example.com/v1/data",
            "application/json; charset=utf-8",
            {"results": [1, 2, 3]},
        )
        cap.handler(resp)
        # Let the scheduled task run
        await asyncio.sleep(0.05)

        assert len(cap.responses) == 1
        assert cap.responses[0]["url"] == "https://api.example.com/v1/data"
        assert cap.responses[0]["data"] == {"results": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_url_keyword_filter_matching(self) -> None:
        cap = ApiCapture(url_keywords=["/api/"])
        resp = _make_mock_response("https://x.com/api/data", "application/json", {"a": 1})
        cap.handler(resp)
        await asyncio.sleep(0.05)
        assert len(cap.responses) == 1

    @pytest.mark.asyncio
    async def test_url_exclude_filter_matching(self) -> None:
        cap = ApiCapture(url_exclude=["/analytics/"])
        resp = _make_mock_response("https://x.com/api/data", "application/json", {"a": 1})
        cap.handler(resp)
        await asyncio.sleep(0.05)
        assert len(cap.responses) == 1

    @pytest.mark.asyncio
    async def test_max_captures(self) -> None:
        cap = ApiCapture(max_captures=2)
        for i in range(5):
            resp = _make_mock_response(f"https://x.com/api/{i}", "application/json", {"i": i})
            cap.handler(resp)
        await asyncio.sleep(0.05)
        assert len(cap.responses) <= 2


class TestApiCaptureHelpers:
    def test_clear(self) -> None:
        cap = ApiCapture()
        cap.responses.append({"url": "x", "data": {}})
        cap.clear()
        assert cap.responses == []

    def test_detach_does_not_raise(self) -> None:
        cap = ApiCapture()
        mock_page = MagicMock()
        cap.detach(mock_page)

    def test_attach_registers_handler(self) -> None:
        cap = ApiCapture()
        mock_page = MagicMock()
        cap.attach(mock_page)
        mock_page.on.assert_called_once_with("response", cap.handler)

"""Tests for BaseCollector abstract base class."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from sre_web_inspector.base_collector import BaseCollector, DEFAULT_RETRY
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.run_context import RunContext


# -- test fixtures & stubs ---------------------------------------------------

@dataclass
class _FakeItem:
    name: str
    value: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}


class _FakeCollector(BaseCollector[_FakeItem]):
    """Minimal concrete collector for testing BaseCollector."""

    async def collect(self) -> list[_FakeItem]:
        self.results = [
            _FakeItem("a", 1),
            _FakeItem("b", 2),
            _FakeItem("a", 1),  # duplicate
        ]
        return self.results


class _FakeCollectorNoToDict(BaseCollector[dict[str, Any]]):
    """Collector whose items are plain dicts (no to_dict)."""

    async def collect(self) -> list[dict[str, Any]]:
        self.results = [{"x": 1}, {"x": 2}]
        return self.results

    @staticmethod
    def _item_to_dict(item: dict[str, Any]) -> dict[str, Any]:
        return item


@pytest.fixture
def run_ctx(tmp_path: Path) -> RunContext:
    return RunContext.create(base_output_dir=str(tmp_path))


@pytest.fixture
def collector(run_ctx: RunContext) -> _FakeCollector:
    # We don't actually need a browser for these tests.
    cm = object()  # type: ignore[assignment]
    return _FakeCollector(cm, run_ctx=run_ctx)


# -- tests -------------------------------------------------------------------


class TestBaseCollectorDefaults:
    def test_default_retry_policy(self) -> None:
        assert DEFAULT_RETRY.times == 3
        assert DEFAULT_RETRY.interval_ms == 2000

    def test_output_dir_is_run_ctx_output_dir(self, collector: _FakeCollector) -> None:
        assert collector.output_dir == collector.run_ctx.output_dir

    def test_results_initially_empty(self, collector: _FakeCollector) -> None:
        assert collector.results == []


class TestSaveResults:
    async def test_save_creates_json_file(self, collector: _FakeCollector) -> None:
        await collector.collect()
        summary = collector.save_results(kind="TestCollection")

        assert summary["kind"] == "TestCollection"
        assert summary["total"] == 3  # before dedup

        json_path = collector.output_dir / "results.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_dedup_removes_duplicates(self, collector: _FakeCollector) -> None:
        await collector.collect()
        summary = collector.save_results(
            kind="TestCollection", dedup_key=lambda item: item.name,
        )

        assert summary["total"] == 2
        names = [i["name"] for i in summary["items"]]
        assert names == ["a", "b"]

    async def test_save_writes_html_report(self, collector: _FakeCollector) -> None:
        await collector.collect()
        collector.save_results(kind="TestCollection")
        html_path = collector.output_dir / "run_result.html"
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "TestCollection" in content

    async def test_save_writes_json_report(self, collector: _FakeCollector) -> None:
        await collector.collect()
        collector.save_results(kind="TestCollection")
        json_path = collector.output_dir / "run_result.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["kind"] == "TestCollection"

    async def test_custom_filename(self, collector: _FakeCollector) -> None:
        await collector.collect()
        collector.save_results(kind="T", filename="custom.json")
        assert (collector.output_dir / "custom.json").exists()

    async def test_api_captures_saved(self, collector: _FakeCollector) -> None:
        await collector.collect()
        caps = [{"url": "http://x", "data": {"a": 1}}]
        collector.save_results(kind="T", api_captures=caps)
        api_path = collector.output_dir / "api_captures.json"
        assert api_path.exists()
        data = json.loads(api_path.read_text(encoding="utf-8"))
        assert len(data) == 1

    async def test_custom_api_filename(self, collector: _FakeCollector) -> None:
        await collector.collect()
        collector.save_results(kind="T", api_captures=[{"u": "x"}], api_filename="x.json")
        assert (collector.output_dir / "x.json").exists()

    async def test_extra_summary_keys(self, collector: _FakeCollector) -> None:
        await collector.collect()
        summary = collector.save_results(kind="T", extra_key=42, source="test")
        assert summary["extra_key"] == 42
        assert summary["source"] == "test"

    async def test_items_key_overridable(self, collector: _FakeCollector) -> None:
        await collector.collect()
        collector.save_results(kind="T")
        data = json.loads((collector.output_dir / "results.json").read_text(encoding="utf-8"))
        # Default is "items" but _FakeCollector doesn't override
        assert "items" in data

    async def test_item_to_dict_fallback(self, run_ctx: RunContext) -> None:
        c = _FakeCollectorNoToDict(object(), run_ctx=run_ctx)  # type: ignore[arg-type]
        await c.collect()
        summary = c.save_results(kind="T")
        assert summary["items"] == [{"x": 1}, {"x": 2}]


class TestDedup:
    def test_no_key_returns_copy(self) -> None:
        items = [1, 2, 3, 2]
        assert BaseCollector._dedup(items, None) == [1, 2, 3, 2]

    def test_with_key_removes_duplicates(self) -> None:
        items = ["aa", "bb", "aa", "cc"]
        result = BaseCollector._dedup(items, key=lambda x: x)
        assert result == ["aa", "bb", "cc"]

    def test_empty_list(self) -> None:
        assert BaseCollector._dedup([], key=lambda x: x) == []

    def test_all_unique(self) -> None:
        items = [{"id": 1}, {"id": 2}, {"id": 3}]
        result = BaseCollector._dedup(items, key=lambda x: str(x["id"]))
        assert len(result) == 3


class TestMakeSummary:
    def test_make_summary_minimal(self, collector: _FakeCollector) -> None:
        s = collector._make_summary()
        assert s["kind"] == "WebInspectionRun"
        assert s["run_id"] == collector.run_ctx.run_id
        assert s["ok"] is True
        assert s["pages"] == []
        assert s["global_replays"] == []

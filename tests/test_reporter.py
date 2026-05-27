"""Tests for reporter (HTML + JSON report generation)."""
from __future__ import annotations

import json
from pathlib import Path

from sre_web_inspector.reporter import (
    render_report,
    write_html_report,
    write_json_report,
)


class TestRenderInspectionReport:
    def test_basic_inspection_report(self) -> None:
        summary = {
            "kind": "WebInspectionRun",
            "run_id": "test-123",
            "ok": True,
            "output_dir": "/tmp/test",
            "global_replays": [],
            "pages": [],
        }
        html = render_report(summary)
        assert "SRE Inspection Report" in html
        assert "test-123" in html
        assert "PASS" in html

    def test_inspection_with_failure(self) -> None:
        summary = {
            "kind": "WebInspectionRun",
            "run_id": "fail-1",
            "ok": False,
            "global_replays": [],
            "pages": [],
        }
        html = render_report(summary)
        assert "FAIL" in html

    def test_inspection_with_pages(self) -> None:
        summary = {
            "kind": "WebInspectionRun",
            "run_id": "r1",
            "ok": True,
            "global_replays": [],
            "pages": [
                {
                    "name": "home",
                    "url": "https://example.com",
                    "ok": True,
                    "evidence": {
                        "screenshot": "/tmp/s.png",
                        "html": "/tmp/h.html",
                        "network": "/tmp/n.json",
                        "replay_dir": "",
                    },
                    "replays": [],
                    "pre_replays": [],
                    "waits": [],
                }
            ],
        }
        html = render_report(summary)
        assert "home" in html
        assert "https://example.com" in html
        assert "PASS" in html

    def test_inspection_with_replays(self) -> None:
        summary = {
            "kind": "WebInspectionRun",
            "run_id": "r2",
            "ok": True,
            "global_replays": [
                {"name": "login", "method": "POST", "url": "/api/login", "ok": True, "status": 200},
            ],
            "pages": [
                {
                    "name": "p1", "url": "/", "ok": True, "evidence": {},
                    "replays": [
                        {"name": "fetch", "method": "GET", "url": "/api/data", "ok": False, "error": "timeout"},
                    ],
                    "pre_replays": [],
                    "waits": [],
                }
            ],
        }
        html = render_report(summary)
        assert "login" in html
        assert "POST" in html
        assert "fetch" in html
        assert "timeout" in html


class TestRenderGenericReport:
    def test_generic_with_items(self) -> None:
        summary = {
            "kind": "TestCollection",
            "run_id": "g1",
            "ok": True,
            "total": 2,
            "source": "https://example.com",
            "items": [
                {"name": "alpha", "count": 10},
                {"name": "beta", "count": 20},
            ],
        }
        html = render_report(summary)
        assert "TestCollection Report" in html
        assert "alpha" in html
        assert "beta" in html
        assert "10" in html
        assert "Summary" in html
        assert "Items (2)" in html

    def test_generic_without_items(self) -> None:
        summary = {
            "kind": "EmptyCollect",
            "run_id": "g2",
            "ok": False,
            "total": 0,
            "source": "https://x.com",
        }
        html = render_report(summary)
        assert "EmptyCollect Report" in html
        assert "FAIL" in html
        assert "total" in html

    def test_generic_no_kind(self) -> None:
        summary = {"run_id": "nokind", "ok": True}
        html = render_report(summary)
        assert "Collection Report" in html

    def test_generic_items_with_urls(self) -> None:
        summary = {
            "kind": "Test",
            "run_id": "u1",
            "ok": True,
            "items": [
                {"name": "x", "url": "https://example.com/page"},
            ],
        }
        html = render_report(summary)
        assert 'href="https://example.com/page"' in html


class TestWriteJsonReport:
    def test_writes_json(self, tmp_path: Path) -> None:
        summary = {"kind": "Test", "run_id": "j1", "ok": True}
        path = write_json_report(summary, tmp_path)
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["kind"] == "Test"


class TestWriteHtmlReport:
    def test_writes_html(self, tmp_path: Path) -> None:
        summary = {"kind": "Test", "run_id": "h1", "ok": True}
        path = write_html_report(summary, tmp_path)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "<html" in content

"""Tests for CninfoCollector and related components."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datamarket.cninfo_collector import (
    BASE_URL,
    Announcement,
    CninfoCollector,
    run_cninfo_collector,
)
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.retry import RetryPolicy
from sre_web_inspector.run_context import RunContext


class TestAnnouncement:
    def test_defaults(self):
        ann = Announcement()
        assert ann.sec_code == ""
        assert ann.sec_name == ""
        assert ann.title == ""
        assert ann.announcement_time == ""
        assert ann.exchange == ""
        assert ann.pdf_url == ""
        assert ann.announcement_id == ""

    def test_to_dict(self):
        ann = Announcement(
            sec_code="000001", sec_name="平安银行", title="关于xxx的公告",
            announcement_time="2025-01-15", exchange="深市主板",
            pdf_url="https://example.com/pdf", announcement_id="12345",
        )
        d = ann.to_dict()
        assert d["sec_code"] == "000001"
        assert d["sec_name"] == "平安银行"
        assert d["title"] == "关于xxx的公告"
        assert d["announcement_time"] == "2025-01-15"
        assert d["exchange"] == "深市主板"
        assert d["pdf_url"] == "https://example.com/pdf"
        assert d["announcement_id"] == "12345"


class TestParseRow:
    def test_parse_full_row(self):
        href = "/new/disclosure/detail?stockCode=000001&announcementId=12345&announcementTime=2025-01-15"
        text = "平安银行 关于xxx的公告"
        ann = CninfoCollector._parse_row(href, text)
        assert ann is not None
        assert ann.sec_code == "000001"
        assert ann.announcement_id == "12345"
        assert ann.announcement_time == "2025-01-15"

    def test_parse_row_no_href_params(self):
        href = "/some/page"
        text = "000002 万科A 公告标题"
        ann = CninfoCollector._parse_row(href, text)
        assert ann is not None
        assert ann.sec_code == "000002"

    def test_parse_row_date_in_text(self):
        href = "/page"
        text = "2025-01-15 万科A 公告标题"
        ann = CninfoCollector._parse_row(href, text)
        assert ann is not None
        assert ann.announcement_time == "2025-01-15"

    def test_parse_row_short_text(self):
        href = "/page"
        ann = CninfoCollector._parse_row(href, "x")
        assert ann is None

    def test_parse_row_empty_text(self):
        ann = CninfoCollector._parse_row("/page", "")
        assert ann is None

    def test_parse_row_full_url(self):
        href = f"{BASE_URL}/new/disclosure/detail?announcementId=abc"
        text = "测试公告"
        ann = CninfoCollector._parse_row(href, text)
        assert ann is not None
        assert ann.announcement_id == "abc"
        assert ann.title == "测试公告"

    def test_parse_row_single_token_as_title(self):
        ann = CninfoCollector._parse_row("/page", "000001")
        assert ann is not None
        assert ann.sec_code == "000001"
        assert ann.title == "000001"

    def test_parse_row_too_short_title(self):
        ann = CninfoCollector._parse_row("/page", "x")
        assert ann is None


class TestParseApiItem:
    def test_parse_basic_item(self):
        item = {
            "announcementId": "123", "announcementTitle": "公告标题",
            "secCode": "000001", "secName": "公司A",
            "announcementTime": 1700000000000, "adjunctUrl": "/pdf/123",
        }
        ann = CninfoCollector._parse_api_item(item)
        assert ann is not None
        assert ann.announcement_id == "123"
        assert ann.title == "公告标题"
        assert ann.sec_code == "000001"
        assert ann.sec_name == "公司A"
        assert ann.announcement_time != ""

    def test_parse_api_item_alternate_keys(self):
        item = {
            "id": "456", "title": "Alt",
            "stockCode": "000002", "stockName": "B公司",
            "publishDate": 0, "pdfUrl": "https://x.com/pdf",
        }
        ann = CninfoCollector._parse_api_item(item)
        assert ann is not None
        assert ann.announcement_id == "456"
        assert ann.sec_code == "000002"
        assert ann.sec_name == "B公司"

    def test_parse_api_item_no_title(self):
        ann = CninfoCollector._parse_api_item({"id": "1"})
        assert ann is None

    def test_parse_api_item_string_time(self):
        ann = CninfoCollector._parse_api_item({"title": "T", "announcementTime": "2025-01-15"})
        assert ann is not None
        assert ann.announcement_time == "2025-01-15"


class TestExtractFromApiResponses:
    def test_classified_announcements_structure(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())
        collector.api_capture.responses = [
            {"url": f"{BASE_URL}/api", "status": 200, "data": {
                "classifiedAnnouncements": [
                    [{"announcementId": "1", "announcementTitle": "公告1", "secCode": "000001"}],
                    [{"announcementId": "2", "announcementTitle": "公告2", "secCode": "000002"}],
                ],
            }},
        ]
        results = collector._extract_from_api_responses()
        assert len(results) == 2

    def test_generic_fallback(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())
        collector.api_capture.responses = [
            {"url": f"{BASE_URL}/api", "status": 200, "data": {
                "records": [{"announcementId": "3", "announcementTitle": "公告3"}],
            }},
        ]
        results = collector._extract_from_api_responses()
        assert len(results) == 1
        assert results[0].announcement_id == "3"

    def test_empty_responses(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())
        results = collector._extract_from_api_responses()
        assert results == []

    def test_data_list_fallback(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())
        collector.api_capture.responses = [
            {"url": f"{BASE_URL}/api", "status": 200, "data": [
                {"announcementId": "5", "announcementTitle": "公告5"},
            ]},
        ]
        results = collector._extract_from_api_responses()
        assert len(results) == 1


class TestExtractFromDom:
    @pytest.mark.asyncio
    async def test_extract_from_dom_with_rows(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())

        mock_row = MagicMock()
        mock_row.get_attribute = AsyncMock(return_value="/detail?announcementId=abc&stockCode=000001")
        mock_row.text_content = AsyncMock(return_value="公司A 公告标题")

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=1)
        mock_locator.nth = MagicMock(return_value=mock_row)
        mock_page.locator = MagicMock(return_value=mock_locator)

        results = await collector._extract_from_dom(mock_page)
        assert len(results) == 1
        assert results[0].announcement_id == "abc"
        assert results[0].sec_code == "000001"

    @pytest.mark.asyncio
    async def test_extract_from_dom_empty(self):
        cm = MagicMock(spec=BrowserContextManager)
        collector = CninfoCollector(cm, run_ctx=RunContext.create())

        mock_page = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count = AsyncMock(return_value=0)
        mock_page.locator = MagicMock(return_value=mock_locator)

        results = await collector._extract_from_dom(mock_page)
        assert results == []


class TestCollectOneExchange:
    @pytest.mark.asyncio
    async def test_collect_single_exchange(self):
        cm = MagicMock(spec=BrowserContextManager)
        cm.context = MagicMock()
        run_ctx = RunContext.create()
        collector = CninfoCollector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)

        mock_page = MagicMock()
        collector.api_capture.responses = [
            {"url": f"{BASE_URL}/api", "status": 200, "data": {
                "classifiedAnnouncements": [
                    [{"announcementId": "1", "announcementTitle": "公告1", "secCode": "000001"}],
                ],
            }},
        ]

        with patch.object(collector.inspector, "inspect_page", new_callable=AsyncMock):
            async def _mock_paginator(*_args, **_kwargs):
                yield 0, mock_page
            with patch("datamarket.cninfo_collector.paginate_by_click", side_effect=_mock_paginator):
                mock_page.locator = MagicMock()
                mock_locator = MagicMock()
                mock_locator.count = AsyncMock(return_value=0)
                mock_page.locator.return_value = mock_locator

                results = await collector._collect_one_exchange(
                    "深市主板", "szseMain", mock_page, max_clicks=1,
                    screenshot=False, save_html=False, save_network=False,
                )
                assert len(results) == 1
                assert results[0].exchange == "深市主板"


class TestCollectorInit:
    def test_init(self):
        cm = MagicMock(spec=BrowserContextManager)
        run_ctx = RunContext.create()
        collector = CninfoCollector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)
        assert collector.api_capture is not None
        assert "classifiedAnnouncements" in collector.api_capture.url_keywords
        assert ".png" in collector.api_capture.url_exclude

    def test_items_key(self):
        assert CninfoCollector._items_key() == "announcements"


class TestSaveResults:
    def test_save_results_with_exchange_breakdown(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        run_ctx = RunContext.create(base_output_dir=str(tmp_path), run_id="test-001")
        collector = CninfoCollector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1))
        collector.results = [
            Announcement(sec_code="000001", title="公告1", exchange="深市主板", announcement_id="1"),
            Announcement(sec_code="000002", title="公告2", exchange="深市主板", announcement_id="2"),
            Announcement(sec_code="600001", title="公告3", exchange="沪市主板", announcement_id="3"),
        ]
        collector.api_capture.responses = []

        summary = collector.save_results()
        assert summary["kind"] == "CninfoAnnouncementCollection"
        assert summary["total"] == 3
        assert summary["by_exchange"]["深市主板"] == 2
        assert summary["by_exchange"]["沪市主板"] == 1
        assert "exchanges" in summary


class TestRunCninfoCollector:
    @pytest.mark.asyncio
    async def test_run_with_hooks(self, tmp_path):
        with patch("datamarket.cninfo_collector.BrowserContextManager") as mock_bcm_cls:
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_cm.context = MagicMock()
            mock_cm.new_page = AsyncMock()
            mock_bcm_cls.return_value = mock_cm

            with patch("datamarket.cninfo_collector.CninfoCollector.collect", new_callable=AsyncMock) as mock_collect:
                mock_collect.return_value = []
                products, summary = await run_cninfo_collector(
                    headless=True, output_dir=str(tmp_path), exchanges=["szse"], max_clicks=1,
                    screenshot=False, save_html=False, save_network=False,
                    hook_start=["echo start"], hook_complete=["echo done"],
                )
                assert products == []
                assert summary["kind"] == "CninfoAnnouncementCollection"


class TestApiCaptureIntegration:
    @pytest.mark.asyncio
    async def test_api_capture_keywords_and_excludes(self):
        cm = MagicMock(spec=BrowserContextManager)
        run_ctx = RunContext.create()
        collector = CninfoCollector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1))
        assert len(collector.api_capture.url_keywords) > 0
        assert len(collector.api_capture.url_exclude) > 0
        assert collector.api_capture.max_captures == 500

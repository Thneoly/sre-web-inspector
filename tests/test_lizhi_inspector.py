"""Tests for LizhiInspector collector and related components."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datamarket.lizhi_inspector import (
    BASE_URL,
    LizhiInspector,
    SoftwareInfo,
    run_lizhi_inspector,
)
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.retry import RetryPolicy
from sre_web_inspector.run_context import RunContext


class TestSoftwareInfo:
    def test_defaults(self):
        item = SoftwareInfo(name="Test", url="https://example.com")
        assert item.name == "Test"
        assert item.url == "https://example.com"
        assert item.price == ""
        assert item.original_price == ""
        assert item.description == ""
        assert item.image_url == ""
        assert item.platforms == []
        assert item.product_type == ""

    def test_to_dict(self):
        item = SoftwareInfo(
            name="App", url="https://example.com/app",
            price="99", original_price="199",
            description="A great app", image_url="https://img.example.com/app.png",
            platforms=["macOS", "Windows"], product_type="product",
        )
        d = item.to_dict()
        assert d["name"] == "App"
        assert d["url"] == "https://example.com/app"
        assert d["price"] == "99"
        assert d["original_price"] == "199"
        assert d["description"] == "A great app"
        assert d["image_url"] == "https://img.example.com/app.png"
        assert d["platforms"] == ["macOS", "Windows"]
        assert d["product_type"] == "product"


class TestLizhiInspectorInit:
    def test_inspector_initialized(self):
        cm = MagicMock(spec=BrowserContextManager)
        run_ctx = RunContext.create(base_output_dir="/tmp/test")
        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)
        assert inspector.cm is cm
        assert inspector.run_ctx is run_ctx
        assert inspector.api_capture is not None
        assert inspector.api_capture.url_keywords == ["/api/", "/graphql"]
        assert inspector.results == []

    def test_items_key(self):
        assert LizhiInspector._items_key() == "products"


class TestExtractProducts:
    @pytest.mark.asyncio
    async def test_extract_products_empty_page(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=[])
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_returns_none(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=None)
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_returns_dict(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value={"a": 1})
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_exception(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("eval failed"))
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_success(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        raw = [
            {"name": "App", "url": f"{BASE_URL}/products/app", "price": "99",
             "original_price": "199", "description": "desc", "image_url": "img.png",
             "platforms": ["macOS"], "product_type": "product"},
        ]
        mock_page.evaluate = AsyncMock(return_value=raw)
        result = await inspector._extract_products(mock_page)
        assert len(result) == 1
        assert result[0]["name"] == "App"


class TestGetPageInfo:
    @pytest.mark.asyncio
    async def test_get_page_info_success(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value={"total": 378, "maxPage": 19, "expectedPages": 19})
        info = await inspector._get_page_info(mock_page)
        assert info["total"] == 378
        assert info["expectedPages"] == 19

    @pytest.mark.asyncio
    async def test_get_page_info_exception(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=Exception("eval failed"))
        info = await inspector._get_page_info(mock_page)
        assert info == {"total": 0, "maxPage": 1}

    @pytest.mark.asyncio
    async def test_get_page_info_returns_list(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=[1, 2, 3])
        info = await inspector._get_page_info(mock_page)
        assert info == {"total": 0, "maxPage": 1}


class TestScrapeListingPage:
    @pytest.mark.asyncio
    async def test_scrape_page_success(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        cm.context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(return_value=[
            {"name": "App", "url": f"{BASE_URL}/products/app", "price": "99",
             "original_price": "", "description": "", "image_url": "",
             "platforms": [], "product_type": "product"},
        ])
        cm.page = mock_page

        run_ctx = RunContext.create(base_output_dir=str(tmp_path), run_id="test-001")
        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)

        with patch.object(inspector.inspector, "inspect_page", new_callable=AsyncMock) as mock_inspect:
            results = await inspector.scrape_listing_page(
                1, page=mock_page, screenshot=False, save_html=False, save_network=False,
            )
            assert len(results) == 1
            assert results[0].name == "App"
            mock_inspect.assert_called_once()


class TestCollect:
    @pytest.mark.asyncio
    async def test_collect_single_page(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        cm.context = MagicMock()
        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=[
            [{"name": "App", "url": f"{BASE_URL}/products/app", "price": "10",
              "original_price": "", "description": "", "image_url": "",
              "platforms": [], "product_type": "product"}],
            {"total": 20, "maxPage": 1, "expectedPages": 1},
        ])
        cm.page = mock_page
        cm.new_page = AsyncMock()
        cm.clear_network_records = MagicMock()

        run_ctx = RunContext.create(base_output_dir=str(tmp_path), run_id="test-001")
        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)

        with patch.object(inspector.inspector, "inspect_page", new_callable=AsyncMock):
            with patch("datamarket.lizhi_inspector.paginate_by_url", AsyncMock(return_value=__import__("types").SimpleNamespace(
                __aiter__=lambda s: s,
                __anext__=AsyncMock(side_effect=StopAsyncIteration),
            ))):
                results = await inspector.collect(start_page=1, max_pages=0, screenshot=False, save_html=False, save_network=False)
                assert len(results) >= 1
                assert results[0].name == "App"


class TestSaveResults:
    def test_save_results_includes_api_captures(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        run_ctx = RunContext.create(base_output_dir=str(tmp_path), run_id="test-001")
        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1))
        inspector.results = [SoftwareInfo(name="App", url="https://example.com/app")]
        inspector.api_capture.responses = [{"url": "https://example.com/api/products", "status": 200, "data": {"items": []}}]

        summary = inspector.save_results(kind="TestScrape", dedup_key=lambda p: p.url, api_captures=inspector.api_capture.responses)
        assert summary["kind"] == "TestScrape"
        assert summary["total"] == 1

        api_file = tmp_path / "runs" / "test-001" / "api_captures.json"
        assert api_file.exists()
        data = json.loads(api_file.read_text())
        assert len(data) == 1
        assert data[0]["url"] == "https://example.com/api/products"


class TestRunLizhiInspector:
    @pytest.mark.asyncio
    async def test_run_with_hooks(self, tmp_path):
        with patch("datamarket.lizhi_inspector.BrowserContextManager") as mock_bcm_cls:
            mock_cm = MagicMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_cm)
            mock_cm.__aexit__ = AsyncMock(return_value=None)
            mock_cm.context = MagicMock()
            mock_page = MagicMock()
            mock_page.evaluate = AsyncMock(side_effect=[
                [],
                {"total": 0, "maxPage": 1, "expectedPages": 1},
            ])
            mock_cm.page = mock_page
            mock_cm.new_page = AsyncMock()
            mock_cm.clear_network_records = MagicMock()
            mock_bcm_cls.return_value = mock_cm

            with patch("datamarket.lizhi_inspector.LizhiInspector.collect", new_callable=AsyncMock) as mock_collect:
                mock_collect.return_value = []
                products, summary = await run_lizhi_inspector(
                    headless=True, output_dir=str(tmp_path), max_pages=1,
                    save_html=False, save_network=False,
                    hook_start=["echo start"], hook_complete=["echo done"],
                )
                assert products == []
                assert summary["kind"] == "LizhiShopScrape"


class TestErrorResilience:
    @pytest.mark.asyncio
    async def test_page_failure_does_not_lose_results(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        cm.context = MagicMock()
        cm.clear_network_records = MagicMock()
        cm.new_page = AsyncMock()

        mock_page = MagicMock()
        mock_page.evaluate = AsyncMock(side_effect=[
            [{"name": "App1", "url": f"{BASE_URL}/p1", "price": "10",
              "original_price": "", "description": "", "image_url": "",
              "platforms": [], "product_type": "product"}],
            {"total": 40, "maxPage": 2, "expectedPages": 2},
        ])
        cm.page = mock_page

        run_ctx = RunContext.create(base_output_dir=str(tmp_path), run_id="test-001")
        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=RetryPolicy(times=1), timeout=10000)

        # First page succeeds via scrape_listing_page. paginate_by_url raises
        # to simulate second page failure.
        with patch.object(inspector.inspector, "inspect_page", new_callable=AsyncMock):
            with patch("datamarket.lizhi_inspector.paginate_by_url", side_effect=RuntimeError("page2 failed")):
                results = await inspector.collect(
                    start_page=1, max_pages=0, screenshot=False,
                    save_html=False, save_network=False,
                )
                # Results from first page are preserved even though second page failed
                assert len(results) == 1
                assert results[0].name == "App1"

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


# -- locator mock helpers -----------------------------------------------

def _make_card_locator(cards: list[MagicMock]) -> MagicMock:
    """Return a mock locator whose .all() yields product card elements."""
    loc = MagicMock()
    loc.all = AsyncMock(return_value=cards)
    return loc


def _make_card(href: str, text: str, imgs: list[MagicMock] | None = None) -> MagicMock:
    """Create a mock product card <a> element."""
    card = MagicMock()
    card.get_attribute = AsyncMock(return_value=href)
    card.text_content = AsyncMock(return_value=text)
    img_loc = MagicMock()
    img_loc.all = AsyncMock(return_value=imgs or [])
    card.locator = MagicMock(return_value=img_loc)
    return card


def _make_img(src: str) -> MagicMock:
    """Create a mock <img> element."""
    img = MagicMock()
    img.get_attribute = AsyncMock(return_value=src)
    return img


def _make_body_locator(text: str) -> MagicMock:
    """Return a mock body locator with inner_text()."""
    loc = MagicMock()
    loc.inner_text = AsyncMock(return_value=text)
    return loc


def _make_pagination_locator(texts: list[str]) -> MagicMock:
    """Return a mock locator whose .all() yields pagination link elements."""
    links = []
    for t in texts:
        link = MagicMock()
        link.text_content = AsyncMock(return_value=t)
        links.append(link)
    loc = MagicMock()
    loc.all = AsyncMock(return_value=links)
    return loc


# -- page.locator dispatcher --------------------------------------------

def _make_page_locator(cards_loc=None, body_loc=None, pagination_loc=None):
    """Return a mock for page.locator that dispatches by selector."""
    def _dispatch(selector: str) -> MagicMock:
        if 'href^="/products/"' in selector or 'href^="/p/"' in selector:
            return cards_loc or _make_card_locator([])
        if selector == "body":
            return body_loc or _make_body_locator("")
        if "pagination" in selector:
            return pagination_loc or _make_pagination_locator([])
        return MagicMock()
    return MagicMock(side_effect=_dispatch)


class TestExtractProducts:
    @pytest.mark.asyncio
    async def test_extract_products_empty_page(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([]))
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_locator_failure(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.locator = MagicMock(side_effect=Exception("DOM error"))
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_card_failure_skips(self):
        """A single card that raises during extraction should be skipped."""
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        bad_card = MagicMock()
        bad_card.get_attribute = AsyncMock(side_effect=Exception("broken card"))
        good_card = _make_card("/products/app", "App ￥99", imgs=[])

        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([bad_card, good_card]))
        result = await inspector._extract_products(mock_page)
        assert len(result) == 1
        assert result[0]["name"] == "App"

    @pytest.mark.asyncio
    async def test_extract_products_skips_empty_href(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        card = _make_card("", "Some text", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([card]))
        result = await inspector._extract_products(mock_page)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_products_dedup_by_href(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        card1 = _make_card("/products/app", "App ￥99", imgs=[])
        card2 = _make_card("/products/app", "App Dup ￥149", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([card1, card2]))
        result = await inspector._extract_products(mock_page)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_extract_products_success(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        img = _make_img("https://img.example.com/app.png")
        platform_img = _make_img("https://img.example.com/icon-windows.svg")
        card = _make_card(
            "/products/app",
            "1. App - A great tool ￥99 ￥199",
            imgs=[img, platform_img],
        )

        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([card]))
        result = await inspector._extract_products(mock_page)
        assert len(result) == 1
        assert result[0]["name"] == "App"
        assert result[0]["url"] == f"{BASE_URL}/products/app"
        assert result[0]["price"] == "99"
        assert result[0]["original_price"] == "199"
        assert result[0]["description"] == "A great tool"
        assert result[0]["image_url"] == "https://img.example.com/app.png"
        assert "Windows" in result[0]["platforms"]
        assert result[0]["product_type"] == "product"

    @pytest.mark.asyncio
    async def test_extract_products_bundle_type(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        card = _make_card("/p/bundle1", "Bundle Deal ￥299", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([card]))
        result = await inspector._extract_products(mock_page)
        assert len(result) == 1
        assert result[0]["product_type"] == "bundle"

    @pytest.mark.asyncio
    async def test_extract_products_skips_short_name(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())

        card = _make_card("/products/x", "X", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = MagicMock(return_value=_make_card_locator([card]))
        result = await inspector._extract_products(mock_page)
        assert result == []


class TestGetPageInfo:
    @pytest.mark.asyncio
    async def test_get_page_info_success(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()

        mock_page.locator = _make_page_locator(
            body_loc=_make_body_locator("共 378 件商品"),
            pagination_loc=_make_pagination_locator(["1", "2", "...", "19"]),
        )

        info = await inspector._get_page_info(mock_page)
        assert info["total"] == 378
        assert info["maxPage"] == 19
        assert info["expectedPages"] == 19

    @pytest.mark.asyncio
    async def test_get_page_info_body_failure(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()
        mock_page.locator = MagicMock(side_effect=Exception("locator error"))

        info = await inspector._get_page_info(mock_page)
        assert info == {"total": 0, "maxPage": 1}

    @pytest.mark.asyncio
    async def test_get_page_info_no_pagination_links(self):
        cm = MagicMock(spec=BrowserContextManager)
        inspector = LizhiInspector(cm, run_ctx=RunContext.create())
        mock_page = MagicMock()

        mock_page.locator = _make_page_locator(
            body_loc=_make_body_locator("共 15 件商品"),
            pagination_loc=_make_pagination_locator([]),
        )

        info = await inspector._get_page_info(mock_page)
        assert info["total"] == 15
        assert info["maxPage"] == 1
        assert info["expectedPages"] == 1  # ceil(15/20) = 1


class TestScrapeListingPage:
    @pytest.mark.asyncio
    async def test_scrape_page_success(self, tmp_path):
        cm = MagicMock(spec=BrowserContextManager)
        cm.context = MagicMock()
        mock_page = MagicMock()
        card = _make_card("/products/app", "App ￥99", imgs=[])
        mock_page.locator = MagicMock(return_value=_make_card_locator([card]))
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
        cm.clear_network_records = MagicMock()
        cm.new_page = AsyncMock()

        card = _make_card("/products/app", "App ￥10", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = _make_page_locator(
            cards_loc=_make_card_locator([card]),
            body_loc=_make_body_locator("共 20 件商品"),
            pagination_loc=_make_pagination_locator(["1"]),
        )
        cm.page = mock_page

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

        card = _make_card("/p1", "App1 ￥10", imgs=[])
        mock_page = MagicMock()
        mock_page.locator = _make_page_locator(
            cards_loc=_make_card_locator([card]),
            body_loc=_make_body_locator("共 40 件商品"),
            pagination_loc=_make_pagination_locator(["1", "2"]),
        )
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

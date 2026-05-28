"""Lizhi.shop scraper built on sre_web_inspector infrastructure.

Uses:
- BrowserContextManager for browser lifecycle
- WebInspectionNode for page navigation + evidence collection
- Playwright native locators for DOM extraction (no injected JS)
- ApiCapture for in-memory JSON response interception
- RequestReplayer for direct API calls with browser auth
- RunContext for organized output directories
- run_with_retry for robust page visits
- run_hooks for lifecycle notifications
- reporter for JSON/HTML output
- template.render_value for URL construction
- paginate_by_url for multi-page iteration
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Locator, Page

from sre_web_inspector.api_capture import ApiCapture
from sre_web_inspector.base_collector import BaseCollector
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.hooks import HookConfig, run_hooks
from sre_web_inspector.paginator import paginate_by_url
from sre_web_inspector.request_replayer import RequestReplayer
from sre_web_inspector.retry import RetryPolicy, run_with_retry
from sre_web_inspector.run_context import RunContext
from sre_web_inspector.template import render_value

logger = logging.getLogger(__name__)

BASE_URL = "https://lizhi.shop"

_PLATFORM_MAP = {
    "apple": "macOS",
    "appstore": "iOS",
    "windows": "Windows",
    "android": "Android",
    "linux": "Linux",
    "web_app": "Web",
}

_PRICE_RE = re.compile(r"￥([\d,.]+)")
_PRODUCT_CARD_SELECTOR = 'a[href^="/products/"], a[href^="/p/"]'


@dataclass
class SoftwareInfo:
    """Structured product data extracted from listing pages."""

    name: str
    url: str
    price: str = ""
    original_price: str = ""
    description: str = ""
    image_url: str = ""
    platforms: list[str] = field(default_factory=list)
    product_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "price": self.price,
            "original_price": self.original_price,
            "description": self.description,
            "image_url": self.image_url,
            "platforms": self.platforms,
            "product_type": self.product_type,
        }


class LizhiInspector(BaseCollector[SoftwareInfo]):
    """Scrape lizhi.shop using sre_web_inspector components."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api_capture = ApiCapture(
            url_keywords=["/api/", "/graphql"],
            url_exclude=[".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff"],
            max_captures=500,
        )
        self.replayer: RequestReplayer | None = None

    async def _extract_products(self, page: Page) -> list[dict[str, Any]]:
        """Extract product cards from DOM using Playwright native locators."""
        try:
            cards = await page.locator(_PRODUCT_CARD_SELECTOR).all()
        except Exception:
            logger.warning("DOM extraction failed: could not locate product cards", exc_info=True)
            return []

        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        for card in cards:
            try:
                href = (await card.get_attribute("href")) or ""
                if not href or href in seen:
                    continue
                seen.add(href)

                text_raw = (await card.text_content()) or ""
                text = " ".join(text_raw.split())

                imgs = await card.locator("img").all()

                image_url = ""
                if imgs:
                    image_url = (await imgs[0].get_attribute("src")) or ""

                platforms = await self._detect_platforms(imgs)

                prices = _PRICE_RE.findall(text)
                price = prices[0] if prices else ""
                original_price = prices[1] if len(prices) > 1 else ""

                price_idx = text.index("￥") if "￥" in text else -1
                name_desc = text[:price_idx].strip() if price_idx > 0 else text

                name = name_desc
                description = ""
                sep = ""
                if " - " in name_desc:
                    sep = " - "
                elif " — " in name_desc:
                    sep = " — "
                if sep:
                    parts = name_desc.split(sep, 1)
                    name = parts[0].strip()
                    description = parts[1].strip() if len(parts) > 1 else ""

                name = re.sub(r"^\d+\.\s*", "", name).strip()
                if len(name) < 2:
                    continue

                product_type = "bundle" if href.startswith("/p/") else "product"
                full_url = BASE_URL + href

                results.append({
                    "name": name,
                    "url": full_url,
                    "price": price,
                    "original_price": original_price,
                    "description": description,
                    "image_url": image_url,
                    "platforms": platforms,
                    "product_type": product_type,
                })
            except Exception:
                logger.debug("Failed to extract product card", exc_info=True)
                continue

        return results

    @staticmethod
    async def _detect_platforms(imgs: list[Locator]) -> list[str]:
        """Detect platform labels from image src keywords (images beyond the first)."""
        platforms: list[str] = []
        for img in imgs[1:]:
            src = ((await img.get_attribute("src")) or "").lower()
            for key, label in _PLATFORM_MAP.items():
                if key in src and label not in platforms:
                    platforms.append(label)
        return platforms

    async def _get_page_info(self, page: Page) -> dict[str, Any]:
        """Extract pagination info from DOM using Playwright native locators."""
        try:
            body_text = await page.locator("body").inner_text()
        except Exception:
            return {"total": 0, "maxPage": 1}

        match = re.search(r"共\s*(\d+)\s*件商品", body_text)
        total = int(match.group(1)) if match else 0

        max_page = 1
        try:
            pagination_links = await page.locator(
                '.pagination a, [class*="pagination"] a, nav a[href*="page="]'
            ).all()
            for link in pagination_links:
                try:
                    num = int((await link.text_content()).strip())
                    if num > max_page:
                        max_page = num
                except (ValueError, TypeError):
                    continue
        except Exception:
            logger.debug("Could not extract pagination links", exc_info=True)

        expected_pages = math.ceil(total / 20) if total > 0 else max_page
        return {"total": total, "maxPage": max_page, "expectedPages": expected_pages}

    async def _replay_api(
        self,
        url: str,
        *,
        name: str = "api_replay",
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Replay an API call using browser auth context.  Non-blocking on failure."""
        if self.replayer is None:
            if self.cm.context is None:
                return []
            self.replayer = RequestReplayer(
                self.cm.context,
                output_dir=self.output_dir / "replay",
                save_response=True,
            )
        try:
            result = await self.replayer.get(url, name=name, params=params)
            if isinstance(result.data, dict):
                for key in ("data", "results", "products", "items", "records"):
                    if key in result.data and isinstance(result.data[key], list):
                        return result.data[key]
                if "data" in result.data and isinstance(result.data["data"], list):
                    return result.data["data"]
                return [result.data] if result.data else []
            if isinstance(result.data, list):
                return result.data
            return []
        except Exception:
            logger.debug("API replay failed for %s", url, exc_info=True)
            return []

    async def scrape_listing_page(
        self,
        page_num: int,
        *,
        page: Page | None = None,
        screenshot: bool = False,
        save_html: bool = True,
        save_network: bool = True,
    ) -> list[SoftwareInfo]:
        url = render_value(
            "{{ base_url }}/products?page={{ page_num }}",
            {"base_url": BASE_URL, "page_num": page_num},
        )
        name = f"listing_page_{page_num:03d}"

        target_page = page or self.cm.page
        if target_page is None:
            raise RuntimeError("Page not initialized")

        self.api_capture.attach(target_page)

        async def do_scrape():
            await self.inspector.inspect_page(
                url,
                page=target_page,
                name=name,
                output_dir=self.output_dir,
                screenshot=screenshot or (page_num == 1),
                save_html=save_html,
                save_network=save_network,
                wait_ms=500,
                timeout=self.timeout,
                wait_for_network_idle=True,
                wait_for_selector='a[href^="/products/"], a[href^="/p/"]',
            )

            raw_products = await self._extract_products(target_page)
            return [SoftwareInfo(**p) for p in raw_products]

        try:
            return await run_with_retry(
                do_scrape,
                policy=self.retry_policy,
                name=f"scrape_page_{page_num}",
            )
        finally:
            self.api_capture.detach(target_page)

    async def collect(
        self,
        *,
        start_page: int = 1,
        max_pages: int = 0,
        screenshot: bool = False,
        save_html: bool = True,
        save_network: bool = True,
    ) -> list[SoftwareInfo]:
        """Scrape all product listing pages."""
        page = self.cm.page
        if page is None:
            raise RuntimeError("Page not initialized")

        # Visit first page to get total count
        logger.info("Fetching page %d to determine total pages...", start_page)
        try:
            products = await self.scrape_listing_page(
                start_page, page=page, screenshot=screenshot,
                save_html=save_html, save_network=save_network,
            )
            self.results.extend(products)
        except Exception:
            logger.warning("First page failed; trying to continue", exc_info=True)

        page_info = await self._get_page_info(page)
        total_pages = page_info.get("expectedPages", 1) or page_info.get("maxPage", 1)
        logger.info("Total products: %d, estimated pages: %d", page_info.get("total", 0), total_pages)

        if max_pages > 0:
            total_pages = min(total_pages, start_page + max_pages - 1)

        if total_pages <= start_page:
            return self.results

        # Remaining pages via paginate_by_url
        async def _new_page():
            return await self.cm.new_page()

        try:
            async for pg, new_page in paginate_by_url(
                _new_page,
                f"{BASE_URL}/products?page={{page}}",
                start=start_page + 1,
                max_pages=total_pages - start_page,
            ):
                try:
                    self.cm.clear_network_records()
                    products = await self.scrape_listing_page(
                        pg, page=new_page, screenshot=screenshot,
                        save_html=save_html, save_network=save_network,
                    )
                    self.results.extend(products)
                    logger.info("Page %d/%d: %d products (total: %d)", pg, total_pages, len(products), len(self.results))
                except Exception:
                    logger.warning("Page %d failed, continuing", pg, exc_info=True)
                finally:
                    await new_page.close()
        except Exception:
            logger.warning("Pagination failed, returning partial results", exc_info=True)

        # Try API replay as complementary data source
        try:
            api_products = await self._replay_api(
                f"{BASE_URL}/api/products",
                name="products_api",
                params={"page": 1, "pageSize": 20},
            )
            if api_products:
                logger.info("API replay returned %d products", len(api_products))
        except Exception:
            logger.debug("API replay not available", exc_info=True)

        return self.results

    # -- BaseCollector hooks -----------------------------------------------

    @staticmethod
    def _items_key() -> str:
        return "products"


async def run_lizhi_inspector(
    *,
    headless: bool = True,
    output_dir: str = "outputs",
    start_page: int = 1,
    max_pages: int = 0,
    screenshot: bool = False,
    save_html: bool = True,
    save_network: bool = True,
    user_data_dir: str | None = None,
    retry_times: int = 2,
    retry_interval_ms: int = 1000,
    timeout: int = 30000,
    hook_start: list[str] | None = None,
    hook_complete: list[str] | None = None,
) -> tuple[list[SoftwareInfo], dict[str, Any]]:
    browser_kwargs: dict[str, Any] = {
        "headless": headless,
        "slow_mo": 200,
        "ignore_https_errors": True,
        "no_viewport": True,
        "start_maximized": True,
    }
    if user_data_dir:
        browser_kwargs["user_data_dir"] = user_data_dir

    async with BrowserContextManager(**browser_kwargs) as cm:
        retry = RetryPolicy(times=retry_times, interval_ms=retry_interval_ms)
        run_ctx = RunContext.create(base_output_dir=output_dir)

        if hook_start:
            await run_hooks(
                HookConfig(commands=hook_start),
                env={"SRE_RUN_ID": run_ctx.run_id, "SRE_OUTPUT_DIR": str(run_ctx.output_dir)},
            )

        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=retry, timeout=timeout)
        products = await inspector.collect(
            start_page=start_page, max_pages=max_pages,
            screenshot=screenshot, save_html=save_html, save_network=save_network,
        )
        summary = inspector.save_results(
            kind="LizhiShopScrape",
            dedup_key=lambda p: p.url,
            api_captures=inspector.api_capture.responses,
            source=BASE_URL,
        )

        if hook_complete:
            await run_hooks(
                HookConfig(commands=hook_complete),
                env={
                    "SRE_RUN_ID": run_ctx.run_id,
                    "SRE_OUTPUT_DIR": str(run_ctx.output_dir),
                    "SRE_TOTAL": str(len(products)),
                },
            )

        return products, summary

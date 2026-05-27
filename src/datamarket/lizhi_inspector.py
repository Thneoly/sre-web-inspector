"""Lizhi.shop scraper built on sre_web_inspector infrastructure.

Uses:
- BrowserContextManager for browser lifecycle
- WebInspectionNode for page navigation + evidence collection
- RunContext for organized output directories
- run_with_retry for robust page visits
- reporter for JSON/HTML output
- template.render_value for URL construction
- paginate_by_url for multi-page iteration
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

from sre_web_inspector.base_collector import BaseCollector
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.paginator import paginate_by_url
from sre_web_inspector.retry import RetryPolicy, run_with_retry
from sre_web_inspector.run_context import RunContext
from sre_web_inspector.template import render_value

logger = logging.getLogger(__name__)

BASE_URL = "https://lizhi.shop"


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


_EXTRACT_SCRIPT = r"""
(() => {
    const BASE = 'https://lizhi.shop';
    const platformMap = {
        'apple': 'macOS', 'appstore': 'iOS', 'windows': 'Windows',
        'android': 'Android', 'linux': 'Linux', 'web_app': 'Web'
    };

    const cards = document.querySelectorAll('a[href^="/products/"], a[href^="/p/"]');
    const seen = new Set();
    const results = [];

    for (const card of cards) {
        const href = card.getAttribute('href') || '';
        if (seen.has(href)) continue;
        seen.add(href);

        const text = (card.textContent || '').replace(/\s+/g, ' ').trim();
        const imgs = card.querySelectorAll('img');

        let imageUrl = '';
        if (imgs.length > 0) {
            imageUrl = imgs[0].getAttribute('src') || '';
        }

        const platforms = [];
        for (let i = 1; i < imgs.length; i++) {
            const src = (imgs[i].getAttribute('src') || '').toLowerCase();
            for (const [key, label] of Object.entries(platformMap)) {
                if (src.includes(key)) platforms.push(label);
            }
        }

        const priceMatches = [...text.matchAll(/￥([\d,.]+)/g)];
        const price = priceMatches.length > 0 ? priceMatches[0][1] : '';
        const originalPrice = priceMatches.length > 1 ? priceMatches[1][1] : '';

        const priceIdx = text.indexOf('￥');
        const nameDesc = priceIdx > 0 ? text.substring(0, priceIdx).trim() : text;

        let name = nameDesc;
        let description = '';
        const sep = nameDesc.includes(' - ') ? ' - ' : (nameDesc.includes(' — ') ? ' — ' : '');
        if (sep) {
            const parts = nameDesc.split(sep);
            name = parts[0].trim();
            description = parts.slice(1).join(sep).trim();
        }

        name = name.replace(/^\d+\.\s*/, '').trim();
        if (name.length < 2) continue;

        const productType = href.startsWith('/p/') ? 'bundle' : 'product';
        const fullUrl = BASE + href;

        results.push({
            name, url: fullUrl, price, original_price: originalPrice,
            description, image_url: imageUrl, platforms, product_type: productType
        });
    }
    return results;
})()
"""

_PAGE_INFO_SCRIPT = r"""
(() => {
    const header = document.body.textContent || '';
    const match = header.match(/共\s*(\d+)\s*件商品/);
    const total = match ? parseInt(match[1]) : 0;

    const pageLinks = document.querySelectorAll('.pagination a, [class*="pagination"] a, nav a[href*="page="]');
    let maxPage = 1;
    for (const link of pageLinks) {
        const num = parseInt(link.textContent.trim());
        if (!isNaN(num) && num > maxPage) maxPage = num;
    }

    return { total, maxPage, expectedPages: Math.ceil(total / 20) };
})()
"""


class LizhiInspector(BaseCollector[SoftwareInfo]):
    """Scrape lizhi.shop using sre_web_inspector components."""

    async def _extract_products(self, page: Page) -> list[dict[str, Any]]:
        try:
            raw = await page.evaluate(_EXTRACT_SCRIPT)
            return raw if isinstance(raw, list) else []
        except Exception:
            logger.warning("DOM extraction failed", exc_info=True)
            return []

    async def _get_page_info(self, page: Page) -> dict[str, Any]:
        try:
            info = await page.evaluate(_PAGE_INFO_SCRIPT)
            return info if isinstance(info, dict) else {"total": 0, "maxPage": 1}
        except Exception:
            return {"total": 0, "maxPage": 1}

    async def scrape_listing_page(
        self,
        page_num: int,
        *,
        page: Page | None = None,
        screenshot: bool = False,
    ) -> list[SoftwareInfo]:
        url = render_value(
            "{{ base_url }}/products?page={{ page_num }}",
            {"base_url": BASE_URL, "page_num": page_num},
        )
        name = f"listing_page_{page_num:03d}"

        async def do_scrape():
            target_page = page or self.cm.page
            if target_page is None:
                raise RuntimeError("Page not initialized")

            await self.inspector.inspect_page(
                url,
                page=target_page,
                name=name,
                output_dir=self.output_dir,
                screenshot=screenshot,
                save_html=False,
                save_network=False,
                wait_ms=500,
                timeout=self.timeout,
                wait_for_network_idle=True,
            )

            raw_products = await self._extract_products(target_page)
            return [SoftwareInfo(**p) for p in raw_products]

        return await run_with_retry(
            do_scrape,
            policy=self.retry_policy,
            name=f"scrape_page_{page_num}",
        )

    async def collect(
        self,
        *,
        start_page: int = 1,
        max_pages: int = 0,
        screenshot: bool = False,
    ) -> list[SoftwareInfo]:
        """Scrape all product listing pages."""
        page = self.cm.page
        if page is None:
            raise RuntimeError("Page not initialized")

        # Visit first page to get total count
        logger.info("Fetching page %d to determine total pages...", start_page)
        products = await self.scrape_listing_page(start_page, page=page, screenshot=screenshot)
        self.results.extend(products)

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

        async for pg, new_page in paginate_by_url(
            _new_page,
            f"{BASE_URL}/products?page={{page}}",
            start=start_page + 1,
            max_pages=total_pages - start_page,
        ):
            try:
                products = await self.scrape_listing_page(pg, page=new_page, screenshot=screenshot)
                self.results.extend(products)
                logger.info("Page %d/%d: %d products (total: %d)", pg, total_pages, len(products), len(self.results))
            finally:
                await new_page.close()

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
    user_data_dir: str | None = None,
    retry_times: int = 2,
    retry_interval_ms: int = 1000,
    timeout: int = 30000,
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

        inspector = LizhiInspector(cm, run_ctx=run_ctx, retry_policy=retry, timeout=timeout)
        products = await inspector.collect(start_page=start_page, max_pages=max_pages, screenshot=screenshot)
        summary = inspector.save_results(kind="LizhiShopScrape", dedup_key=lambda p: p.url)
        return products, summary

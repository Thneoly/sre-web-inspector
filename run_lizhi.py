#!/usr/bin/env python3
"""Scrape all software products from lizhi.shop using sre_web_inspector stack.

Components used:
  - BrowserContextManager  → browser lifecycle
  - WebInspectionNode      → page navigation + evidence (screenshot, HTML, network)
  - RunContext             → outputs/runs/{run_id}/ organized output
  - RetryPolicy            → run_with_retry for robust page visits
  - reporter               → JSON + HTML report generation
  - template.render_value  → URL construction with {{ var }} substitution
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from datamarket.lizhi_inspector import run_lizhi_inspector


async def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape lizhi.shop product catalog")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=0, help="Max pages (0=all)")
    parser.add_argument("--screenshot", action="store_true", help="Take page screenshots")
    parser.add_argument("--user-data-dir", default=None)
    parser.add_argument("--retry-times", type=int, default=2)
    parser.add_argument("--retry-interval", type=int, default=1000)
    parser.add_argument("--timeout", type=int, default=30000)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    products, summary = await run_lizhi_inspector(
        headless=not args.no_headless,
        output_dir=args.output_dir,
        start_page=args.start_page,
        max_pages=args.max_pages,
        screenshot=args.screenshot,
        user_data_dir=args.user_data_dir,
        retry_times=args.retry_times,
        retry_interval_ms=args.retry_interval,
        timeout=args.timeout,
    )

    print(f"\nTotal products: {len(products)}")
    print(f"Run ID: {summary['run_id']}")
    print(f"Output: {summary.get('output_dir', args.output_dir)}")

    # Platform breakdown
    platforms: dict[str, int] = {}
    for p in products:
        for plat in p.platforms:
            platforms[plat] = platforms.get(plat, 0) + 1
        if not p.platforms:
            platforms["(unspecified)"] = platforms.get("(unspecified)", 0) + 1

    print("\nBy platform:")
    for plat, count in sorted(platforms.items(), key=lambda x: -x[1]):
        print(f"  {plat}: {count}")

    # Price range
    prices = []
    for p in products:
        try:
            prices.append(float(p.price.replace(",", "")))
        except (ValueError, AttributeError):
            pass
    if prices:
        print(f"\nPrice range: ￥{min(prices):.2f} ~ ￥{max(prices):.2f}")

    # Product type breakdown
    product_count = sum(1 for p in products if p.product_type == "product")
    bundle_count = sum(1 for p in products if p.product_type == "bundle")
    if bundle_count:
        print(f"Products: {product_count}, Bundles: {bundle_count}")


if __name__ == "__main__":
    asyncio.run(main())

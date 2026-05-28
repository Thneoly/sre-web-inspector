#!/usr/bin/env python3
"""Scrape announcements from cninfo.com.cn (巨潮资讯网) using sre_web_inspector.

Covers all exchanges: 深市主板, 创业板, 沪市主板, 科创板, 北交所.

Components used:
  - BrowserContextManager  → browser lifecycle
  - WebInspectionNode      → page navigation + evidence (screenshots, HTML, network)
  - ApiCapture             → in-memory JSON API response interception (keyword-filtered)
  - RequestReplayer        → direct API calls reusing browser auth
  - paginate_by_click      → click-based pagination
  - RunContext             → outputs/runs/{run_id}/ organized output
  - RetryPolicy            → run_with_retry for robust page visits
  - run_hooks              → lifecycle shell commands
  - reporter               → JSON + HTML report generation
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from datamarket.cninfo_collector import EXCHANGES, run_cninfo_collector


async def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape cninfo.com.cn announcements")
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--exchanges", nargs="*", default=None,
                        choices=list(EXCHANGES.keys()),
                        help="Exchanges to scrape (default: all)")
    parser.add_argument("--max-clicks", type=int, default=10,
                        help="Max 'load more' clicks per exchange")
    parser.add_argument("--screenshot", action="store_true", default=True, help="Take screenshots (default: on)")
    parser.add_argument("--no-screenshot", action="store_true", help="Disable screenshots")
    parser.add_argument("--save-html", action="store_true", default=True, help="Save HTML snapshots (default: on)")
    parser.add_argument("--no-save-html", action="store_true", help="Disable HTML snapshots")
    parser.add_argument("--save-network", action="store_true", default=True, help="Save network traces (default: on)")
    parser.add_argument("--no-save-network", action="store_true", help="Disable network traces")
    parser.add_argument("--user-data-dir", default=None)
    parser.add_argument("--retry-times", type=int, default=3)
    parser.add_argument("--retry-interval", type=int, default=2000)
    parser.add_argument("--timeout", type=int, default=30000)
    parser.add_argument("--hook-start", action="append", default=None,
                        help="Shell command(s) to run on collection start (repeatable)")
    parser.add_argument("--hook-complete", action="append", default=None,
                        help="Shell command(s) to run on collection complete (repeatable)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    products, summary = await run_cninfo_collector(
        headless=not args.no_headless,
        output_dir=args.output_dir,
        exchanges=args.exchanges,
        max_clicks=args.max_clicks,
        screenshot=not args.no_screenshot,
        save_html=not args.no_save_html,
        save_network=not args.no_save_network,
        user_data_dir=args.user_data_dir,
        retry_times=args.retry_times,
        retry_interval_ms=args.retry_interval,
        timeout=args.timeout,
        hook_start=args.hook_start,
        hook_complete=args.hook_complete,
    )

    print(f"\nTotal announcements: {len(products)}")
    print(f"Run ID: {summary['run_id']}")
    print(f"Output: {summary.get('output_dir', args.output_dir)}")

    # Exchange breakdown
    by_exchange: dict[str, int] = {}
    for a in products:
        by_exchange[a.exchange] = by_exchange.get(a.exchange, 0) + 1
    print("\nBy exchange:")
    for exc, count in sorted(by_exchange.items(), key=lambda x: -x[1]):
        print(f"  {exc}: {count}")


if __name__ == "__main__":
    asyncio.run(main())

"""Cninfo (巨潮资讯网) announcement scraper built on sre_web_inspector.

Captures latest announcements from all three exchanges (深市/沪市/北交所)
using the sre_web_inspector middleware pipeline to intercept API responses,
combined with Playwright Python locators for DOM interaction.

Uses:
  - BrowserContextManager   → browser lifecycle
  - WebInspectionNode       → page navigation + evidence (screenshots, HTML, network)
  - ApiCapture              → in-memory JSON response interception (keyword-filtered)
  - RequestReplayer         → direct API calls reusing browser auth
  - paginate_by_click       → click-based pagination
  - run_with_retry          → robust page visits & clicks
  - run_hooks               → lifecycle shell commands
  - BaseCollector           → shared lifecycle (RunContext, reporter, dedup)
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import Page

from sre_web_inspector.api_capture import ApiCapture
from sre_web_inspector.base_collector import BaseCollector
from sre_web_inspector.browser_context import BrowserContextManager
from sre_web_inspector.hooks import HookConfig, run_hooks
from sre_web_inspector.paginator import paginate_by_click
from sre_web_inspector.request_replayer import RequestReplayer
from sre_web_inspector.retry import RetryPolicy, run_with_retry
from sre_web_inspector.run_context import RunContext

logger = logging.getLogger(__name__)

BASE_URL = "https://www.cninfo.com.cn"

EXCHANGES = {
    "szse":      {"name": "深市主板", "tab": "szseMain"},
    "szse_gem":  {"name": "创业板",   "tab": "szseGem"},
    "sse":       {"name": "沪市主板", "tab": "sseMain"},
    "sse_star":  {"name": "科创板",   "tab": "sseKcp"},
    "bj":        {"name": "北交所",   "tab": "bj"},
}

PAGE_URL = f"{BASE_URL}/new/commonUrl?url=disclosure/list/notice"

# Known API URL keywords for cninfo announcement data.
_API_KEYWORDS = ["classifiedAnnouncements", "announcements", "announcement"]
_API_EXCLUDE = [".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".woff", ".css", ".js"]


@dataclass
class Announcement:
    """Single announcement record."""

    sec_code: str = ""
    sec_name: str = ""
    title: str = ""
    announcement_time: str = ""
    exchange: str = ""
    pdf_url: str = ""
    announcement_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sec_code": self.sec_code,
            "sec_name": self.sec_name,
            "title": self.title,
            "announcement_time": self.announcement_time,
            "exchange": self.exchange,
            "pdf_url": self.pdf_url,
            "announcement_id": self.announcement_id,
        }


class CninfoCollector(BaseCollector[Announcement]):
    """Collect announcements from cninfo.com.cn for all exchanges."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.api_capture = ApiCapture(
            url_keywords=_API_KEYWORDS,
            url_exclude=_API_EXCLUDE,
            max_captures=500,
        )
        self.replayer: RequestReplayer | None = None

    # -- DOM extraction ---------------------------------------------------

    async def _extract_from_dom(self, page: Page) -> list[Announcement]:
        announcements: list[Announcement] = []
        rows = page.locator('a[href*="announcementId"]')
        count = await rows.count()
        if count == 0:
            rows = page.locator('tr:has(a), [class*="row"]:has(a), [class*="item"]:has(a), li:has(a)')
        count = await rows.count()
        logger.info("Found %d announcement row candidates", count)

        for i in range(count):
            try:
                row = rows.nth(i)
                href = await row.get_attribute("href") or ""
                full_text = await row.text_content() or ""
                full_text = re.sub(r"\s+", " ", full_text).strip()
                ann = self._parse_row(href, full_text)
                if ann and ann.title:
                    announcements.append(ann)
            except Exception:
                logger.debug("Failed to parse row %d", i, exc_info=True)
        return announcements

    @staticmethod
    def _parse_row(href: str, text: str) -> Announcement | None:
        full_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        ann = Announcement(pdf_url=full_url)

        if "?" in href:
            qs = parse_qs(urlparse(href).query)
            ann.sec_code = (qs.get("stockCode") or [""])[0]
            ann.announcement_id = (qs.get("announcementId") or [""])[0]
            ann.announcement_time = (qs.get("announcementTime") or [""])[0]

        if not ann.sec_code:
            code_match = re.search(r"\b(\d{6})\b", text)
            if code_match:
                ann.sec_code = code_match.group(1)

        if not ann.announcement_time:
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if date_match:
                ann.announcement_time = date_match.group(1)

        if not text or len(text) < 2:
            return None

        text = re.sub(r"https?://\S+", "", text).strip()
        text = re.sub(r"\d{4}-\d{2}-\d{2}", "", text).strip()

        parts = text.split(None, 1)
        if len(parts) >= 2:
            first = parts[0].strip()
            rest = parts[1].strip()
            if 2 <= len(first) <= 8 and not re.search(r"\d{4,}", first):
                ann.sec_name = first
                ann.title = rest
            else:
                ann.title = text
        elif len(parts) == 1:
            ann.title = parts[0].strip()

        if not ann.title or len(ann.title) < 2:
            return None
        return ann

    # -- API extraction ---------------------------------------------------

    def _extract_from_api_responses(self) -> list[Announcement]:
        announcements: list[Announcement] = []
        seen_ids: set[str] = set()

        for capture in self.api_capture.responses:
            data = capture.get("data", {})

            # Direct list response (e.g. [{...}, {...}])
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    ann = self._parse_api_item(item)
                    if ann and ann.announcement_id and ann.announcement_id not in seen_ids:
                        seen_ids.add(ann.announcement_id)
                        announcements.append(ann)
                continue

            if not isinstance(data, dict):
                continue

            groups = data.get("classifiedAnnouncements")
            if isinstance(groups, list):
                for group in groups:
                    if not isinstance(group, list):
                        continue
                    for item in group:
                        if not isinstance(item, dict):
                            continue
                        ann = self._parse_api_item(item)
                        if ann and ann.announcement_id and ann.announcement_id not in seen_ids:
                            seen_ids.add(ann.announcement_id)
                            announcements.append(ann)
                continue

            # Generic fallback
            items: list[dict] = []
            for key in ("data", "records", "list", "result", "items", "announcements"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            if not items:
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                ann = self._parse_api_item(item)
                if ann and ann.announcement_id and ann.announcement_id not in seen_ids:
                    seen_ids.add(ann.announcement_id)
                    announcements.append(ann)

        return announcements

    @staticmethod
    def _parse_api_item(item: dict[str, Any]) -> Announcement | None:
        ann_id = str(item.get("announcementId", item.get("id", "")))

        raw_time = item.get("announcementTime", item.get("publishDate", 0))
        if isinstance(raw_time, (int, float)) and raw_time > 100000000000:
            from datetime import datetime, timedelta, timezone
            tz_cn = timezone(timedelta(hours=8))
            dt = datetime.fromtimestamp(raw_time / 1000, tz=tz_cn)
            time_str = dt.strftime("%Y-%m-%d")
        else:
            time_str = str(raw_time) if raw_time else ""

        adjunct = str(item.get("adjunctUrl", item.get("pdfUrl", item.get("url", ""))))
        if adjunct and not adjunct.startswith("http"):
            adjunct = f"{BASE_URL}/{adjunct}"

        ann = Announcement(
            sec_code=str(item.get("secCode", item.get("stockCode", ""))),
            sec_name=str(item.get("secName", item.get("stockName", item.get("tileSecName", "")))),
            title=str(item.get("announcementTitle", item.get("title", ""))),
            announcement_time=time_str,
            announcement_id=ann_id,
            pdf_url=adjunct,
        )
        return ann if ann.title else None

    # -- API replay -------------------------------------------------------

    async def _replay_announcement_api(
        self,
        exchange_name: str,
        tab: str,
        *,
        page_num: int = 1,
        page_size: int = 30,
    ) -> list[Announcement]:
        """Replay the announcement API directly via browser auth context."""
        if self.replayer is None:
            if self.cm.context is None:
                return []
            self.replayer = RequestReplayer(
                self.cm.context,
                output_dir=self.output_dir / "replay" / "cninfo",
                save_response=True,
            )
        try:
            result = await self.replayer.post_json(
                f"{BASE_URL}/new/disclosure",
                name=f"announcement_{exchange_name}_{page_num:03d}",
                data={
                    "stock": "",
                    "searchkey": "",
                    "category": "",
                    "pageNum": page_num,
                    "pageSize": page_size,
                    "column": tab,
                    "tabName": "fulltext",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": True,
                },
            )
            if isinstance(result.data, dict):
                announcements: list[Announcement] = []
                groups = result.data.get("classifiedAnnouncements")
                if isinstance(groups, list):
                    for group in groups:
                        if not isinstance(group, list):
                            continue
                        for item in group:
                            if not isinstance(item, dict):
                                continue
                            ann = self._parse_api_item(item)
                            if ann:
                                ann.exchange = exchange_name
                                announcements.append(ann)
                return announcements
            return []
        except Exception:
            logger.debug("API replay failed for %s", exchange_name, exc_info=True)
            return []

    # -- collection -------------------------------------------------------

    async def _collect_one_exchange(
        self,
        exchange_name: str,
        tab: str,
        page: Page,
        max_clicks: int,
        *,
        screenshot: bool = True,
        save_html: bool = True,
        save_network: bool = True,
    ) -> list[Announcement]:
        """Collect announcements for one exchange using ApiCapture + pagination."""
        url = f"{PAGE_URL}#{tab}"
        logger.info("Navigating to %s (%s)", exchange_name, url)

        await self.inspector.inspect_page(
            url,
            page=page,
            name=f"cninfo_{tab}",
            output_dir=self.output_dir,
            screenshot=screenshot,
            save_html=save_html,
            save_network=save_network,
            timeout=self.timeout,
            wait_for_network_idle=True,
            network_idle_timeout=self.timeout,
            wait_for_selector='a[href*="announcementId"]',
            wait_ms=1000,
        )

        all_anns: list[Announcement] = []
        seen_ids: set[str] = set()

        async for click_num, _ in paginate_by_click(
            page,
            next_selector=".btn-next",
            max_clicks=max_clicks,
        ):
            api_anns = self._extract_from_api_responses()
            fresh = 0
            for ann in api_anns:
                if ann.announcement_id and ann.announcement_id not in seen_ids:
                    seen_ids.add(ann.announcement_id)
                    ann.exchange = exchange_name
                    all_anns.append(ann)
                    fresh += 1

            dom_anns = await self._extract_from_dom(page)
            dom_new = 0
            for ann in dom_anns:
                if ann.announcement_id and ann.announcement_id not in seen_ids:
                    seen_ids.add(ann.announcement_id)
                    ann.exchange = exchange_name
                    all_anns.append(ann)
                    dom_new += 1

            logger.info("  [%s] click %d: api=%d dom=%d (total %d)",
                        exchange_name, click_num, fresh, dom_new, len(all_anns))

        return all_anns

    async def collect(
        self,
        *,
        exchanges: list[str] | None = None,
        max_clicks_per_exchange: int = 10,
        screenshot: bool = True,
        save_html: bool = True,
        save_network: bool = True,
    ) -> list[Announcement]:
        if exchanges is None:
            exchanges = list(EXCHANGES.keys())

        for key in exchanges:
            if key not in EXCHANGES:
                logger.warning("Unknown exchange: %s", key)
                continue

            info = EXCHANGES[key]
            page = await self.cm.new_page()
            self.api_capture.clear()

            try:
                self.api_capture.attach(page)
                anns = await run_with_retry(
                    lambda: self._collect_one_exchange(
                        info["name"], info["tab"], page, max_clicks_per_exchange,
                        screenshot=screenshot, save_html=save_html, save_network=save_network,
                    ),
                    policy=self.retry_policy,
                    name=f"collect_{key}",
                )
                self.results.extend(anns)
                logger.info("Collected %d announcements from %s", len(anns), info["name"])

                # Try API replay as complementary data source
                try:
                    replay_anns = await self._replay_announcement_api(info["name"], info["tab"])
                    replay_new = 0
                    existing_ids = {a.announcement_id for a in self.results if a.announcement_id}
                    for ann in replay_anns:
                        if ann.announcement_id and ann.announcement_id not in existing_ids:
                            existing_ids.add(ann.announcement_id)
                            self.results.append(ann)
                            replay_new += 1
                    if replay_new:
                        logger.info("API replay added %d new announcements from %s", replay_new, info["name"])
                except Exception:
                    logger.debug("API replay failed for %s", info["name"], exc_info=True)

            except Exception:
                logger.warning("Failed to collect from %s, continuing", info["name"], exc_info=True)
            finally:
                self.api_capture.detach(page)
                await page.close()

        return self.results

    # -- BaseCollector hooks -----------------------------------------------

    @staticmethod
    def _items_key() -> str:
        return "announcements"

    def save_results(
        self,
        *,
        filename: str = "cninfo_announcements.json",
        dedup_key: Any = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Save results with exchange breakdown and API captures."""
        by_exchange: dict[str, int] = {}
        for a in self.results:
            by_exchange[a.exchange] = by_exchange.get(a.exchange, 0) + 1

        if dedup_key is None:
            dedup_key = lambda a: f"{a.sec_code}:{a.announcement_id}"  # noqa: E731

        return super().save_results(
            kind="CninfoAnnouncementCollection",
            filename=filename,
            dedup_key=dedup_key,
            api_captures=self.api_capture.responses,
            api_filename="cninfo_api_captures.json",
            source=BASE_URL,
            exchanges=list(EXCHANGES.keys()),
            by_exchange=by_exchange,
            **extra,
        )


async def run_cninfo_collector(
    *,
    headless: bool = True,
    output_dir: str = "outputs",
    exchanges: list[str] | None = None,
    max_clicks: int = 10,
    screenshot: bool = True,
    save_html: bool = True,
    save_network: bool = True,
    user_data_dir: str | None = None,
    retry_times: int = 3,
    retry_interval_ms: int = 2000,
    timeout: int = 30000,
    hook_start: list[str] | None = None,
    hook_complete: list[str] | None = None,
) -> tuple[list[Announcement], dict[str, Any]]:
    browser_kwargs: dict[str, Any] = {
        "headless": headless,
        "slow_mo": 300,
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

        collector = CninfoCollector(cm, run_ctx=run_ctx, retry_policy=retry, timeout=timeout)
        products = await collector.collect(
            exchanges=exchanges, max_clicks_per_exchange=max_clicks,
            screenshot=screenshot, save_html=save_html, save_network=save_network,
        )
        summary = collector.save_results()

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

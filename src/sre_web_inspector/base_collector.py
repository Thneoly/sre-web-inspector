"""Base class for data collectors built on sre_web_inspector.

Eliminates the ~70% boilerplate shared by every business collector:
  - __init__  (cm, run_ctx, retry_policy, timeout, inspector)
  - output_dir property
  - save_results  (dedup, JSON dump, reporter calls)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from .browser_context import BrowserContextManager
from .inspector import WebInspectionNode
from .reporter import write_html_report, write_json_report
from .retry import RetryPolicy
from .run_context import RunContext

T = TypeVar("T")

# Default retry policies suitable for most scraping tasks.
DEFAULT_RETRY = RetryPolicy(times=3, interval_ms=2000)


class BaseCollector(ABC, Generic[T]):
    """Abstract base for page-inspection / data-collection tasks.

    Subclasses implement ``collect()`` and call ``save_results()`` at the end.
    """

    def __init__(
        self,
        cm: BrowserContextManager,
        *,
        run_ctx: RunContext | None = None,
        retry_policy: RetryPolicy | None = None,
        timeout: int = 30000,
    ) -> None:
        self.cm = cm
        self.inspector = WebInspectionNode(cm)
        self.run_ctx = run_ctx or RunContext.create()
        self.retry_policy = retry_policy or DEFAULT_RETRY
        self.timeout = timeout
        self.results: list[T] = []

    # -- helpers ----------------------------------------------------------

    @property
    def output_dir(self) -> Path:
        return self.run_ctx.output_dir

    @abstractmethod
    async def collect(self) -> list[T]:
        """Run the collection.  Subclasses must implement."""
        ...

    # -- save -------------------------------------------------------------

    def save_results(
        self,
        *,
        kind: str,
        filename: str = "results.json",
        dedup_key: Callable[[T], str] | None = None,
        api_captures: list[dict[str, Any]] | None = None,
        api_filename: str = "api_captures.json",
        **extra_summary,
    ) -> dict[str, Any]:
        """Dedup, persist raw data, write reports, return summary dict.

        Parameters
        ----------
        kind:
            Label used in the summary (e.g. ``"CninfoAnnouncementCollection"``).
        filename:
            Name of the raw-results JSON file written into ``output_dir``.
        dedup_key:
            Optional callable(item) → str; when provided only the first
            occurrence of each key is kept.
        api_captures:
            Optional raw API capture list (written alongside results for debugging).
        api_filename:
            Filename for the api_captures JSON dump.
        **extra_summary:
            Additional top-level keys merged into the summary dict.
        """
        # Dedup
        items = self._dedup(self.results, key=dedup_key)

        # Raw data
        (self.output_dir / filename).write_text(
            json.dumps(
                {"total": len(items), self._items_key(): [self._item_to_dict(i) for i in items]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # API captures (optional)
        if api_captures:
            (self.output_dir / api_filename).write_text(
                json.dumps(api_captures, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        # Summary
        summary: dict[str, Any] = {
            "kind": kind,
            "run_id": self.run_ctx.run_id,
            "output_dir": str(self.output_dir),
            "total": len(items),
            "items": [self._item_to_dict(i) for i in items],
            **extra_summary,
        }

        write_json_report(summary, self.output_dir)
        write_html_report(summary, self.output_dir)
        return summary

    # -- overridable hooks ------------------------------------------------

    @staticmethod
    def _items_key() -> str:
        """Plural key used in the raw JSON envelope.  Override to rename."""
        return "items"

    @staticmethod
    def _item_to_dict(item: T) -> dict[str, Any]:
        """Convert one result item to a plain dict.  Override if items have ``to_dict()``."""
        if hasattr(item, "to_dict"):
            return item.to_dict()  # type: ignore[union-attr]
        raise NotImplementedError("Override _item_to_dict or add to_dict() to your item class")

    def _make_summary(self) -> dict[str, Any]:
        """Minimal summary for the HTML reporter."""
        return {
            "kind": "WebInspectionRun",
            "run_id": self.run_ctx.run_id,
            "output_dir": str(self.output_dir),
            "ok": True,
            "global_replays": [],
            "pages": [],
        }

    # -- internal ---------------------------------------------------------

    @staticmethod
    def _dedup(items: list[T], key: Callable[[T], str] | None) -> list[T]:
        if key is None:
            return list(items)
        seen: set[str] = set()
        unique: list[T] = []
        for item in items:
            k = key(item)
            if k not in seen:
                seen.add(k)
                unique.append(item)
        return unique

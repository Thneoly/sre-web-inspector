from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    times: int = 1
    interval_ms: int = 1000

    @classmethod
    def from_config(cls, cfg: dict | None, *, default_times: int = 1, default_interval_ms: int = 1000) -> "RetryPolicy":
        cfg = cfg or {}
        return cls(
            times=max(int(cfg.get("times", default_times)), 1),
            interval_ms=max(int(cfg.get("interval_ms", cfg.get("interval", default_interval_ms))), 0),
        )


async def run_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    name: str = "operation",
) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, policy.times + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - caller needs generic retry protection.
            last_error = exc
            if attempt >= policy.times:
                break
            if policy.interval_ms > 0:
                await asyncio.sleep(policy.interval_ms / 1000)
    raise RuntimeError(f"{name} failed after {policy.times} attempt(s): {last_error}") from last_error

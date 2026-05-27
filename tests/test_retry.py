from __future__ import annotations

import pytest

from sre_web_inspector.retry import RetryPolicy, run_with_retry


class TestRetryPolicy:
    def test_default_values(self):
        p = RetryPolicy()
        assert p.times == 1
        assert p.interval_ms == 1000

    def test_custom_values(self):
        p = RetryPolicy(times=3, interval_ms=500)
        assert p.times == 3
        assert p.interval_ms == 500

    def test_from_config_empty(self):
        p = RetryPolicy.from_config(None)
        assert p.times == 1
        assert p.interval_ms == 1000

    def test_from_config_with_values(self):
        p = RetryPolicy.from_config({"times": 5, "interval_ms": 250})
        assert p.times == 5
        assert p.interval_ms == 250

    def test_from_config_clamps_times_to_1(self):
        p = RetryPolicy.from_config({"times": 0, "interval_ms": 100})
        assert p.times == 1

    def test_from_config_with_interval_alias(self):
        p = RetryPolicy.from_config({"times": 2, "interval": 500})
        assert p.interval_ms == 500

    def test_from_config_falls_back_to_defaults(self):
        p = RetryPolicy.from_config({}, default_times=3, default_interval_ms=2000)
        assert p.times == 3
        assert p.interval_ms == 2000


class TestRunWithRetry:
    @pytest.mark.asyncio
    async def test_succeeds_first_attempt(self):
        call_count = 0

        async def work():
            nonlocal call_count
            call_count += 1
            return "done"

        result = await run_with_retry(work, policy=RetryPolicy(times=3, interval_ms=10))
        assert result == "done"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_succeeds_on_retry(self):
        call_count = 0

        async def work():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await run_with_retry(work, policy=RetryPolicy(times=5, interval_ms=10))
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def work():
            raise ValueError("always fail")

        with pytest.raises(RuntimeError, match="always fail"):
            await run_with_retry(work, policy=RetryPolicy(times=3, interval_ms=10), name="test_op")

    @pytest.mark.asyncio
    async def test_no_retry_when_times_is_1(self):
        call_count = 0

        async def work():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        with pytest.raises(RuntimeError):
            await run_with_retry(work, policy=RetryPolicy(times=1, interval_ms=10))
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_zero_interval_does_not_sleep(self):
        call_count = 0

        async def work():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        result = await run_with_retry(work, policy=RetryPolicy(times=5, interval_ms=0))
        assert result == "ok"
        assert call_count == 3

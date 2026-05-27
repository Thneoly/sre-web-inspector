from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_dir():
    """Temporary directory cleaned up after the test."""
    d = Path(tempfile.mkdtemp(prefix="sre_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def sample_config():
    """Minimal valid config dict for testing."""
    return {
        "vars": {"base_url": "http://localhost:8765", "namespace": "test"},
        "runtime": {
            "output_dir": "outputs",
            "concurrency": 1,
            "timeout": 60000,
            "retry": {"times": 1, "interval_ms": 100},
        },
        "browser": {"headless": True, "slow_mo": 0},
        "pages": [
            {
                "name": "test_page",
                "url": "{{ base_url }}/hello",
                "screenshot": False,
                "save_html": False,
                "save_network": False,
                "wait_ms": 100,
                "lifecycle": {"close_after_inspection": True},
            }
        ],
    }

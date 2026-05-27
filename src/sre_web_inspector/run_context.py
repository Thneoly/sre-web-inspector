from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def make_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


@dataclass(slots=True)
class RunContext:
    run_id: str
    output_dir: Path

    @classmethod
    def create(cls, base_output_dir: str | Path = "outputs", run_id: str | None = None) -> "RunContext":
        rid = run_id or make_run_id()
        root = Path(base_output_dir) / "runs" / rid
        for sub in ("screenshots", "html", "network", "responses", "replay", "logs"):
            (root / sub).mkdir(parents=True, exist_ok=True)
        return cls(run_id=rid, output_dir=root)

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoginResult:
    enabled: bool
    mode: str | None = None
    skipped: bool = False
    success: bool = False
    reason: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HookConfig:
    commands: list[str] = field(default_factory=list)
    timeout: int = 30  # seconds per command


def _build_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if extra:
        env.update(extra)
    return env


async def run_hooks(hooks: HookConfig | None, *, env: dict[str, str] | None = None) -> None:
    if not hooks or not hooks.commands:
        return
    for cmd in hooks.commands:
        logger.info("Running hook: %s", cmd)
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                env=_build_env(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=hooks.timeout
            )
            if proc.returncode != 0:
                logger.warning("Hook returned %d: %s\nstderr: %s", proc.returncode, cmd, stderr.decode())
            elif stdout:
                logger.info("Hook output: %s", stdout.decode().strip())
        except asyncio.TimeoutError:
            logger.warning("Hook timed out after %ds: %s", hooks.timeout, cmd)
        except Exception:
            logger.exception("Hook failed: %s", cmd)

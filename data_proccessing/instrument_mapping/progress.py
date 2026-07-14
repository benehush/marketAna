"""Small terminal progress helpers for mapping builds."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO


ProgressCallback = Callable[[str, int, int, str], None]


@dataclass(slots=True)
class TerminalProgressBar:
    """Render compact progress bars without adding a tqdm dependency."""

    enabled: bool = True
    width: int = 28
    stream: TextIO = sys.stderr
    min_interval_seconds: float = 0.08
    _last_render_at: float = field(default=0.0, init=False)
    _last_stage: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self._last_render_at = 0.0
        self._last_stage = ""

    def __call__(self, stage: str, current: int, total: int, message: str = "") -> None:
        if not self.enabled:
            return
        total = max(total, 0)
        current = max(0, min(current, total)) if total else max(0, current)
        now = time.monotonic()
        is_done = total > 0 and current >= total
        if (
            stage == self._last_stage
            and not is_done
            and now - self._last_render_at < self.min_interval_seconds
        ):
            return
        self._last_render_at = now
        self._last_stage = stage

        if total:
            ratio = current / total
            filled = min(self.width, int(self.width * ratio))
            bar = "#" * filled + "-" * (self.width - filled)
            percent = int(ratio * 100)
            line = f"\r[{bar}] {percent:3d}% {stage} {current}/{total}"
        else:
            line = f"\r{' ' * (self.width + 8)} {stage} {current}"
        if message:
            line += f" | {message}"
        self.stream.write(line)
        if is_done:
            self.stream.write("\n")
        self.stream.flush()

"""Group and deduplicate signals by product."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from data_proccessing.models import DirectionSignal


def aggregate_signals(signals: Iterable[DirectionSignal]) -> dict[str, list[DirectionSignal]]:
    grouped: dict[str, list[DirectionSignal]] = defaultdict(list)
    seen: set[tuple[str, int, int, str]] = set()
    for signal in signals:
        if not signal.product_key:
            continue
        key = (signal.product_key, signal.start, signal.end, signal.direction)
        if key in seen:
            continue
        seen.add(key)
        grouped[signal.product_key].append(signal)
    return dict(grouped)

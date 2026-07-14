"""Publication date validation shared by import and repair workflows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re


MIN_PUBLISH_YEAR = 2000


def valid_publish_time(value: datetime | None, *, now: datetime | None = None) -> datetime | None:
    if value is None:
        return None
    upper_year = (now or datetime.now()).year + 1
    return value if MIN_PUBLISH_YEAR <= value.year <= upper_year else None


def publish_time_from_path(path: str | Path, *, now: datetime | None = None) -> datetime | None:
    for part in reversed(Path(path).parts):
        if not re.fullmatch(r"\d{8}", part):
            continue
        try:
            parsed = datetime.strptime(part, "%Y%m%d")
        except ValueError:
            continue
        validated = valid_publish_time(parsed, now=now)
        if validated is not None:
            return validated
    return None

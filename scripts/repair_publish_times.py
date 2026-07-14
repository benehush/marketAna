"""Preview or repair invalid article publication dates from file path dates."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from back_end.app.core.database import get_engine
from back_end.app.core.dates import publish_time_from_path, valid_publish_time
from back_end.app.models import Article


def repair_publish_times(session: Session, *, apply: bool = False) -> list[dict[str, str | int | None]]:
    changes = []
    for article in session.scalars(select(Article).order_by(Article.id)).all():
        expected = publish_time_from_path(article.file_url or "")
        current_valid = valid_publish_time(article.publish_time)
        if expected is None or (current_valid is not None and current_valid.date() == expected.date()):
            continue
        changes.append({
            "article_id": article.id,
            "title": article.title,
            "before": article.publish_time.isoformat() if article.publish_time else None,
            "after": expected.isoformat(),
        })
        if apply:
            article.publish_time = expected
    if apply:
        session.commit()
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist changes; default is dry-run")
    args = parser.parse_args()
    engine = get_engine()
    try:
        with Session(engine) as session:
            changes = repair_publish_times(session, apply=args.apply)
            for item in changes:
                print(f"{item['article_id']} {item['before']} -> {item['after']} {item['title']}")
            print(f"{'updated' if args.apply else 'would update'}: {len(changes)}")
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

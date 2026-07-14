from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from back_end.app.core.database import get_session
from back_end.app.models import Article
from back_end.app.repositories import ArticleRepository
from back_end.app.core.dates import publish_time_from_path


SUPPORTED_DOC_EXTENSIONS = {".pdf": "pdf", ".html": "html", ".htm": "html"}
SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".gif",
}
UNSUPPORTED_EXTENSIONS = {".doc", ".docx", ".svg"}


@dataclass
class FileMetadata:
    path: Path
    file_url: str
    file_type: str
    title: str
    company: str | None
    publish_time: datetime | None


@dataclass
class IngestRecord:
    file_url: str
    status: str
    reason: str
    file_type: str = ""
    article_id: int | None = None
    title: str = ""
    company: str = ""
    publish_time: str = ""


@dataclass
class IngestSummary:
    scanned: int = 0
    imported: int = 0
    duplicate: int = 0
    skipped: int = 0
    unsupported: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "duplicate": self.duplicate,
            "skipped": self.skipped,
            "unsupported": self.unsupported,
            "dry_run": self.dry_run,
        }


def iter_files(root: Path) -> Iterable[Path]:
    return (path for path in sorted(root.rglob("*")) if path.is_file())


def build_file_url(path: Path, base_dir: Path | None = None) -> str:
    base = (base_dir or Path.cwd()).resolve()
    resolved = path.resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return resolved.as_posix()


def classify_file(path: Path, *, include_images: bool) -> tuple[str | None, str, str]:
    """Return (file_type, status, reason)."""
    parts_lower = {part.lower() for part in path.parts}
    ext = path.suffix.lower()

    if "img_folder" in parts_lower:
        return None, "skipped", "embedded_resource"
    if ext in SUPPORTED_DOC_EXTENSIONS:
        return SUPPORTED_DOC_EXTENSIONS[ext], "candidate", "supported"
    if ext in SUPPORTED_IMAGE_EXTENSIONS:
        if include_images:
            return "image", "candidate", "supported"
        return None, "skipped", "images_disabled"
    if ext in UNSUPPORTED_EXTENSIONS:
        return None, "unsupported", f"unsupported_extension:{ext}"
    return None, "unsupported", f"unknown_extension:{ext or '<none>'}"


def extract_metadata(path: Path, root: Path, base_dir: Path | None = None) -> FileMetadata:
    file_type, status, reason = classify_file(path, include_images=True)
    if status != "candidate" or file_type is None:
        raise ValueError(f"Cannot extract metadata for {path}: {reason}")

    stem = path.stem
    company = stem.split("_", 1)[0] if "_" in stem else None
    publish_time = parse_publish_time(path, root)

    return FileMetadata(
        path=path,
        file_url=build_file_url(path, base_dir=base_dir),
        file_type=file_type,
        title=stem,
        company=company,
        publish_time=publish_time,
    )


def parse_publish_time(path: Path, root: Path) -> datetime | None:
    # Accept both ``--root data`` and ``--root data/20250401``.  In the
    # latter form the date is the root directory itself, not a child.
    return publish_time_from_path(path.resolve())


def existing_file_urls(session: Session) -> set[str]:
    return set(session.scalars(select(Article.file_url).where(Article.file_url.is_not(None))).all())


def ingest_files(
    session: Session,
    *,
    root: Path,
    limit: int | None = None,
    dry_run: bool = False,
    include_images: bool = False,
    report_path: Path | None = None,
    source: str = "local_data_ingest",
    base_dir: Path | None = None,
) -> tuple[IngestSummary, list[IngestRecord]]:
    root = root.resolve()
    base_dir = (base_dir or Path.cwd()).resolve()
    summary = IngestSummary(dry_run=dry_run)
    records: list[IngestRecord] = []
    known_urls = existing_file_urls(session)
    repo = ArticleRepository(session)

    for path in iter_files(root):
        if limit is not None and summary.imported >= limit:
            break

        summary.scanned += 1
        file_url = build_file_url(path, base_dir=base_dir)
        file_type, status, reason = classify_file(path, include_images=include_images)

        if status == "skipped":
            summary.skipped += 1
            records.append(IngestRecord(file_url=file_url, status=status, reason=reason))
            continue
        if status == "unsupported" or file_type is None:
            summary.unsupported += 1
            records.append(IngestRecord(file_url=file_url, status="unsupported", reason=reason))
            continue
        if file_url in known_urls:
            summary.duplicate += 1
            records.append(IngestRecord(file_url=file_url, status="duplicate", reason="file_url_exists", file_type=file_type))
            continue

        metadata = extract_metadata(path, root, base_dir=base_dir)
        article_id = None
        if not dry_run:
            article = repo.create_article(
                title=metadata.title,
                source=source,
                company=metadata.company,
                file_url=metadata.file_url,
                file_type=metadata.file_type,
                publish_time=metadata.publish_time,
            )
            article_id = article.id
            known_urls.add(metadata.file_url)

        summary.imported += 1
        records.append(
            IngestRecord(
                file_url=metadata.file_url,
                status="imported" if not dry_run else "dry_run",
                reason="created" if not dry_run else "would_create",
                file_type=metadata.file_type,
                article_id=article_id,
                title=metadata.title,
                company=metadata.company or "",
                publish_time=metadata.publish_time.isoformat() if metadata.publish_time else "",
            )
        )

    if report_path is not None:
        write_report(report_path, records)

    if not dry_run:
        session.commit()

    return summary, records


def write_report(report_path: Path, records: list[IngestRecord]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "file_url",
                "status",
                "reason",
                "file_type",
                "article_id",
                "title",
                "company",
                "publish_time",
            ],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record.__dict__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest local data files into articles table.")
    parser.add_argument("--root", default="data", help="Root directory to scan.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of new files to import.")
    parser.add_argument("--dry-run", action="store_true", help="Print/report actions without writing articles.")
    parser.add_argument("--include-images", action="store_true", help="Import standalone image files.")
    parser.add_argument("--report", default="data/ingest_report.csv", help="CSV report path.")
    parser.add_argument("--source", default="local_data_ingest", help="Article source value.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    session = next(get_session())
    try:
        summary, _records = ingest_files(
            session,
            root=Path(args.root),
            limit=args.limit,
            dry_run=args.dry_run,
            include_images=args.include_images,
            report_path=Path(args.report) if args.report else None,
            source=args.source,
        )
        print("ingest summary:", summary.as_dict())
        if args.dry_run:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()

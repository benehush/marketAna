from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.models import Article
from scripts.ingest_files import (
    classify_file,
    extract_metadata,
    ingest_files,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory


def test_classify_file_supported_and_skipped(tmp_path):
    pdf = tmp_path / "20250415" / "五矿期货_328010.PDF"
    html = tmp_path / "20250415" / "国信期货_327947_0.html"
    image = tmp_path / "20250415" / "chart.jpg"
    embedded = tmp_path / "20250415" / "328144" / "img_folder" / "chart.png"
    docx = tmp_path / "20250415" / "report.docx"
    svg = tmp_path / "20250415" / "icon.svg"

    assert classify_file(pdf, include_images=False) == ("pdf", "candidate", "supported")
    assert classify_file(html, include_images=False) == ("html", "candidate", "supported")
    assert classify_file(image, include_images=False) == (None, "skipped", "images_disabled")
    assert classify_file(image, include_images=True) == ("image", "candidate", "supported")
    assert classify_file(embedded, include_images=True) == (None, "skipped", "embedded_resource")
    assert classify_file(docx, include_images=False)[1] == "unsupported"
    assert classify_file(svg, include_images=False)[1] == "unsupported"


def test_extract_metadata_from_data_style_path(tmp_path):
    root = tmp_path / "data"
    path = root / "20250415" / "五矿期货_328010.PDF"
    path.parent.mkdir(parents=True)
    path.write_text("pdf placeholder")

    metadata = extract_metadata(path, root, base_dir=tmp_path)

    assert metadata.file_url == "data/20250415/五矿期货_328010.PDF"
    assert metadata.file_type == "pdf"
    assert metadata.title == "五矿期货_328010"
    assert metadata.company == "五矿期货"
    assert metadata.publish_time == datetime(2025, 4, 15)


def test_ingest_files_is_idempotent_and_writes_report(tmp_path):
    engine, factory = _session_factory()
    root = tmp_path / "data"
    (root / "20250415").mkdir(parents=True)
    (root / "20250415" / "五矿期货_328010.PDF").write_text("pdf")
    (root / "20250415" / "国信期货_327947_0.html").write_text("<html></html>")
    (root / "20250415" / "report.docx").write_text("docx")
    report = tmp_path / "report.csv"

    try:
        session = factory()
        summary, records = ingest_files(
            session,
            root=root,
            report_path=report,
            base_dir=tmp_path,
        )

        assert summary.scanned == 3
        assert summary.imported == 2
        assert summary.unsupported == 1
        assert report.exists()
        assert {record.status for record in records} == {"imported", "unsupported"}

        articles = session.scalars(select(Article).order_by(Article.id)).all()
        assert [article.file_url for article in articles] == [
            "data/20250415/五矿期货_328010.PDF",
            "data/20250415/国信期货_327947_0.html",
        ]
        assert articles[0].status == 0
        session.close()

        session = factory()
        summary2, records2 = ingest_files(session, root=root, base_dir=tmp_path)
        assert summary2.imported == 0
        assert summary2.duplicate == 2
        assert summary2.unsupported == 1
        assert {record.status for record in records2} == {"duplicate", "unsupported"}
        session.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_ingest_files_dry_run_does_not_write(tmp_path):
    engine, factory = _session_factory()
    root = tmp_path / "data"
    (root / "20250415").mkdir(parents=True)
    (root / "20250415" / "国信期货_327947_0.html").write_text("<html></html>")

    try:
        session = factory()
        summary, records = ingest_files(
            session,
            root=root,
            dry_run=True,
            base_dir=tmp_path,
        )

        assert summary.imported == 1
        assert summary.dry_run is True
        assert records[0].status == "dry_run"
        assert session.scalar(select(Article)) is None
        session.close()
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

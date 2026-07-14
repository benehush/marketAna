from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.dates import publish_time_from_path, valid_publish_time
from back_end.app.core.review import clean_review_evidence
from back_end.app.models import AnalysisReviewQueue
from back_end.app.repositories import ArticleRepository
from back_end.app.repositories.review_queue import ReviewQueueRepository
from scripts.repair_publish_times import repair_publish_times
from back_end.app.api import articles as articles_api
from back_end.app.core.exceptions import AppException


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    create_database_tables(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _article(session, title, statuses, *, task_status="success", company="浙商期货"):
    repo = ArticleRepository(session)
    article = repo.create_article(title=title, company=company, file_url=f"data/20250401/{title}.html")
    for index, status in enumerate(statuses):
        session.add(AnalysisReviewQueue(
            article_id=article.id, item_key=f"{title}-{index}", product_key="DCE.M", product="豆粕",
            reason="no_signal", evidence_json={"excerpts": [{"quote": "豆粕库存下降"}]},
            status=status, reviewed_at=datetime(2026, 7, 13) if status != "pending" else None,
        ))
    repo.save_task_log(article_id=article.id, stage="pipeline", status=task_status, message=task_status)
    session.flush()
    return article


def test_queue_tabs_are_mutually_exclusive_and_error_has_priority():
    session = _session()
    _article(session, "pending", ["pending", "rejected"])
    _article(session, "completed", ["resolved", "rejected"])
    _article(session, "rejected", ["rejected"])
    _article(session, "partial", ["pending"], task_status="partial")
    repo = ReviewQueueRepository(session)
    body = repo.list_queue(tab="pending")
    assert body["counts"] == {"pending": 1, "completed": 1, "rejected": 1, "error": 1}
    assert [item["title"] for item in body["items"]] == ["pending"]
    assert [item["title"] for item in repo.list_queue(tab="error")["items"]] == ["partial"]


def test_queue_filters_search_missing_evidence_and_default_sort():
    session = _session()
    first = _article(session, "浙商期货_100", ["pending", "pending"])
    second = _article(session, "东海期货_200", ["pending"], company="东海期货")
    second.review_queue[0].evidence_json = {"excerpts": []}
    repo = ReviewQueueRepository(session)
    assert [row["id"] for row in repo.list_queue(tab="pending")["items"]] == [first.id, second.id]
    assert repo.list_queue(tab="pending", keyword="东海期货 200")["total"] == 1
    assert repo.list_queue(tab="pending", keyword="200")["items"][0]["id"] == second.id
    assert repo.list_queue(tab="pending", company="东海期货", missing_evidence=True)["total"] == 1


def test_dates_and_navigation_evidence_are_sanitized():
    assert publish_time_from_path("data/20250415/327911/report.html") == datetime(2025, 4, 15)
    assert valid_publish_time(datetime(3279, 1, 1)) is None
    evidence = clean_review_evidence(["无障碍浏览 客服电话 首页 公司简介 联系我们", "body_alias", "豆粕库存下降"])
    assert evidence == {"excerpts": [{"quote": "豆粕库存下降"}]}


def test_llm_diagnostic_is_allow_listed_redacted_and_idempotent(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "top-secret-key")
    source = {
        "excerpts": [{"quote": "豆粕库存下降"}],
        "diagnostic": {
            "error_type": "invalid_json",
            "message": "Bearer top-secret-key invalid JSON",
            "parse_errors": [
                {
                    "phase": "initial",
                    "error_type": "invalid_json",
                    "field": "response",
                    "message": "api_key=top-secret-key",
                    "value_excerpt": "bad",
                    "ignored": "drop-me",
                }
            ],
            "raw_response_excerpt": '{"token":"top-secret-key"}',
            "provider": "wenhua",
            "attempt_count": 2,
            "transport_retry_count": 1,
            "correction_retry_count": 1,
            "retry_exhausted": True,
            "ignored": "drop-me",
        },
    }

    once = clean_review_evidence(source)
    twice = clean_review_evidence(once)

    assert once == twice
    assert "top-secret-key" not in str(once)
    assert "ignored" not in str(once)
    assert once["diagnostic"]["error_type"] == "invalid_json"


def test_review_evidence_preserves_safe_context_metadata() -> None:
    source = {
        "kind": "candidate_context",
        "notes": "以下内容仅供核对",
        "excerpts": [
            {
                "quote": "锡价上涨更多是情绪推动，实际影响预计有限。",
                "raw_quote": "锡价上涨更多是情绪推动，实际影响预计有限。",
                "source": "raw_text",
                "start_char": 12,
                "end_char": 34,
                "match_type": "context",
                "validated": False,
                "ignored": "drop-me",
            }
        ],
    }

    cleaned = clean_review_evidence(source)

    assert clean_review_evidence(cleaned) == cleaned
    assert cleaned["kind"] == "candidate_context"
    assert cleaned["excerpts"][0]["start_char"] == 12
    assert cleaned["excerpts"][0]["validated"] is False
    assert "ignored" not in str(cleaned)


def test_publish_time_repair_uses_valid_path_date():
    session = _session()
    article = ArticleRepository(session).create_article(
        title="浙商期货_327911_0", file_url="data/20250415/327911/浙商期货_327911_0.html",
        publish_time=datetime(3279, 1, 1),
    )
    changes = repair_publish_times(session, apply=False)
    assert changes[0]["after"] == "2025-04-15T00:00:00"
    assert article.publish_time.year == 3279
    repair_publish_times(session, apply=True)
    assert article.publish_time == datetime(2025, 4, 15)


def test_article_source_is_served_inline_and_confined_to_data_root(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "report.html"
    source.write_text("<h1>report</h1>", encoding="utf-8")
    session = _session()
    article = ArticleRepository(session).create_article(title="source", file_url="data/report.html")
    monkeypatch.setattr(articles_api, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(articles_api, "get_settings", lambda: type("Settings", (), {"data_root": "data"})())
    response = articles_api.get_article_source(article.id, session=session)
    assert response.path == source
    assert response.headers["content-disposition"].startswith("inline")

    article.file_url = "outside.html"
    try:
        articles_api.get_article_source(article.id, session=session)
    except AppException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("source path outside data root must be denied")

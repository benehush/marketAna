from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.exceptions import AppException
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.repositories import ArticleRepository, ProductRepository
from pn05.product_segmenter import segment_article
from pn06.product_resolver import parse_resolution_json, resolve_article_products
from pn07.models import LLMConfig


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _unknown_article(session) -> int:
    repo = ArticleRepository(session)
    article = repo.create_article(title="未知品种测试")
    repo.save_cleaned_text(article.id, "## 核心正文\n\n【欧集线】运价预期偏强，供给扰动增加。")
    segment_article(article.id, session)
    session.flush()
    return article.id


def _config() -> LLMConfig:
    return LLMConfig(
        provider="openai",
        api_key="test",
        base_url="https://example.test/v1",
        model="fake",
        max_retries=0,
    )


def test_resolver_auto_resolves_catalog_key_and_queues_alias(session_factory, monkeypatch) -> None:
    session = session_factory()
    article_id = _unknown_article(session)
    resolution = ProductRepository(session).pending_resolutions_for_article(article_id)[0]
    calls = []

    class Client:
        def __init__(self, config):
            pass

        def chat(self, messages, *, retries=None):
            calls.append(messages)
            return (
                '{"results":[{"block_ref":"%s","raw_name":"欧集线",'
                '"product_key":"INE.EC","confidence":0.93,"status":"resolved"}]}'
            ) % resolution.id

    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", Client)
    result = resolve_article_products(article_id, session, config=_config())

    assert result.resolved == 1
    assert len(calls) == 1
    segment = ArticleRepository(session).get_product_segments(article_id)[0]
    assert segment.product_key == "INE.EC"
    assert segment.product == "集运指数（欧线）"
    aliases = ProductRepository(session).list_aliases()
    assert [(item.alias, item.status) for item in aliases] == [("欧集线", "pending")]


def test_resolver_keeps_low_confidence_and_transport_failure_pending(session_factory, monkeypatch) -> None:
    session = session_factory()
    article_id = _unknown_article(session)
    resolution = ProductRepository(session).pending_resolutions_for_article(article_id)[0]

    class LowClient:
        def __init__(self, config):
            pass

        def chat(self, messages, *, retries=None):
            return (
                '{"results":[{"block_ref":"%s","product_key":"INE.EC",'
                '"confidence":0.5,"status":"resolved"}]}'
            ) % resolution.id

    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", LowClient)
    result = resolve_article_products(article_id, session, config=_config())
    assert result.pending == 1
    assert ArticleRepository(session).get_product_segments(article_id)[0].product == "未知"

    class FailingClient:
        def __init__(self, config):
            pass

        def chat(self, messages, *, retries=None):
            raise RuntimeError("resolver unavailable")

    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", FailingClient)
    failed = resolve_article_products(article_id, session, config=_config())
    assert failed.pending == 1
    assert "resolver unavailable" in failed.errors[0]


def test_parse_resolution_rejects_out_of_catalog_key_and_bad_json() -> None:
    items, errors = parse_resolution_json(
        '{"results":[{"block_ref":"1","product_key":"FAKE.X","confidence":0.99}]}'
    )
    assert items[0]["product_key"] is None
    assert items[0]["confidence"] == 0.0
    assert "目录外" in errors[0]

    assert parse_resolution_json("not json")[0] == []


def test_manual_resolution_and_second_alias_review_close_the_loop(session_factory) -> None:
    session = session_factory()
    article_id = _unknown_article(session)
    products = ProductRepository(session)
    resolution = products.pending_resolutions_for_article(article_id)[0]

    confirmed = products.confirm_resolution(
        resolution.id,
        product_key="INE.EC",
        reviewed_by="tester",
    )
    assert confirmed.status == "confirmed"
    assert ArticleRepository(session).get_article(article_id).status == ArticleProcessingStatus.CLEANED.value
    assert ArticleRepository(session).get_product_segments(article_id)[0].product_key == "INE.EC"

    alias = products.list_aliases()[0]
    assert products.matcher().detect_products("欧集线走强") == {}
    products.review_alias(alias.id, approve=True, reviewed_by="reviewer")
    assert products.matcher().detect_products("欧集线走强") == {"集运指数（欧线）": 1}


def test_alias_approval_rejects_conflicting_target(session_factory) -> None:
    session = session_factory()
    products = ProductRepository(session)
    first = products.queue_alias("欧集线", "INE.EC", source_resolution_id=None, confidence=0.9)
    second = products.queue_alias("欧集线", "INE.SC", source_resolution_id=None, confidence=0.9)
    assert first is not None and second is not None
    products.review_alias(first.id, approve=True)

    with pytest.raises(AppException) as exc_info:
        products.review_alias(second.id, approve=True)
    assert exc_info.value.status_code == 409

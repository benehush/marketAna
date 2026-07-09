from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.api.articles import get_article_detail, list_articles
from back_end.app.api.companies import get_companies
from back_end.app.api.products import get_products
from back_end.app.api.results import confirm_result
from back_end.app.api.schemas import ConfirmResultRequest
from back_end.app.api.schemas import TaskRunRequest
from back_end.app.api.tasks import run_task
from back_end.app.api.trends import get_trends
from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article, TaskLog
from back_end.app.repositories import ArticleRepository
from pn11.models import BatchResult


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


def test_models_create_tables_and_enforce_status_constraint(session_factory) -> None:
    engine = session_factory.kw["bind"]
    inspector = inspect(engine)

    assert {
        "articles",
        "article_texts",
        "analysis_results",
        "task_logs",
        "manual_confirmations",
    }.issubset(set(inspector.get_table_names()))
    assert any(
        constraint["name"] == "uq_analysis_results_article_product_contract"
        for constraint in inspector.get_unique_constraints("analysis_results")
    )

    session = session_factory()
    session.add(Article(title="bad status", status=99))
    with pytest.raises(IntegrityError):
        session.commit()
    session.close()


def test_repository_status_flow_failure_log_and_result_idempotency(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(
        title="钢材日报",
        source="测试源",
        company="测试期货",
        file_type="pdf",
        publish_time=datetime(2026, 7, 2, 9, 30),
    )

    repository.save_raw_text(article.id, "原始文本", parser_type="pdf")
    assert article.status == ArticleProcessingStatus.PARSED
    repository.save_cleaned_text(article.id, "清洗文本")
    assert article.status == ArticleProcessingStatus.CLEANED
    repository.save_refined_text(article.id, "精修文本")
    assert article.status == ArticleProcessingStatus.CLEANED
    assert article.text.refined_text == "精修文本"
    assert article.text.refined_length == len("精修文本")
    repository.update_status(article.id, ArticleProcessingStatus.RULE_ANALYZED)
    repository.update_status(article.id, ArticleProcessingStatus.LLM_INFERRED)
    repository.save_analysis_result(
        article.id,
        product="螺纹钢",
        direction="看涨",
        reason="需求改善",
        confidence=0.82,
        analysis_method="rule",
        need_manual_review=False,
    )
    assert article.status == ArticleProcessingStatus.STORED

    repository.save_analysis_result(
        article.id,
        product="铁矿石",
        direction="中性",
        reason="供需平衡",
        confidence=0.64,
        analysis_method="llm",
        need_manual_review=True,
    )
    saved = session.scalars(select(AnalysisResult).where(AnalysisResult.article_id == article.id)).all()
    assert {result.product for result in saved} == {"螺纹钢", "铁矿石"}
    assert len(saved) == 2

    repository.save_analysis_result(
        article.id,
        product="铁矿石",
        direction="看跌",
        reason="需求走弱",
        confidence=0.72,
        analysis_method="llm",
        need_manual_review=False,
    )
    saved = session.scalars(select(AnalysisResult).where(AnalysisResult.article_id == article.id)).all()
    assert len(saved) == 2
    assert session.scalar(
        select(AnalysisResult).where(
            AnalysisResult.article_id == article.id,
            AnalysisResult.product == "铁矿石",
        )
    ).direction == "看跌"

    failed = repository.create_article(title="坏文件")
    repository.mark_failed(
        failed.id,
        stage="parser",
        message="文件损坏",
        duration_ms=12,
    )
    session.commit()

    assert failed.status == ArticleProcessingStatus.FAILED
    assert failed.error_msg == "文件损坏"
    assert session.scalar(select(TaskLog).where(TaskLog.article_id == failed.id)).status == "failed"
    session.close()


def test_repository_filters_summary_and_trends(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    first = repository.create_article(
        title="螺纹钢展望",
        company="甲期货",
        publish_time=datetime(2026, 7, 2, 9, 0),
    )
    second = repository.create_article(
        title="铜市场观察",
        company="乙期货",
        publish_time=datetime(2026, 7, 2, 10, 0),
    )
    repository.save_analysis_result(
        first.id,
        product="螺纹钢",
        direction="看涨",
        reason="库存下降",
        confidence=0.8,
        analysis_method="rule",
    )
    repository.save_analysis_result(
        second.id,
        product="沪铜",
        direction="看跌",
        reason="需求偏弱",
        confidence=0.55,
        analysis_method="llm",
        need_manual_review=True,
    )
    session.commit()

    items, total = repository.list_articles(product="螺纹钢", page=1, page_size=10)
    assert total == 1
    assert items[0].title == "螺纹钢展望"
    summary = repository.get_dashboard_summary(today=datetime(2026, 7, 2, 12, 0))
    assert summary["total_articles"] == 2
    assert summary["manual_review_count"] == 1
    assert summary["direction_distribution"]["看涨"] == 1
    assert repository.get_trends(product="螺纹钢")[0]["count"] == 1
    session.close()


def test_api_handlers_return_contracts_for_articles_trends_and_confirm(session_factory) -> None:
    seed_session = session_factory()
    repository = ArticleRepository(seed_session)
    article = repository.create_article(
        title="豆粕行情",
        source="日报",
        company="丙期货",
        publish_time=datetime(2026, 7, 2, 11, 0),
    )
    repository.save_raw_text(article.id, "raw", parser_type="html")
    repository.save_cleaned_text(article.id, "cleaned")
    repository.save_refined_text(article.id, "refined")
    result = repository.save_analysis_result(
        article.id,
        product="豆粕",
        direction="中性",
        reason="震荡整理",
        confidence=0.45,
        analysis_method="llm",
        need_manual_review=True,
    )
    repository.save_task_log(
        article_id=article.id,
        stage="llm",
        status="success",
        message="ok",
        duration_ms=30,
    )
    seed_session.commit()
    seed_session.close()

    api_session = session_factory()

    list_body = list_articles(product="豆粕", page=1, page_size=20, session=api_session)
    assert list_body["code"] == 0
    assert len(list_body["data"]) == 1
    assert list_body["data"][0]["summary"] == "豆粕中性 0.45"
    assert list_body["data"][0]["publish_time"] == "2026-07-02"

    products_body = get_products(session=api_session)
    assert products_body["data"][0]["product"] == "豆粕"
    assert products_body["data"][0]["predictions"][0]["company"] == "丙期货"
    assert products_body["data"][0]["predictions"][0]["date"] == "2026-07-02"

    companies_body = get_companies(session=api_session)
    assert companies_body["data"][0]["company"] == "丙期货"
    assert companies_body["data"][0]["predictions"][0]["product"] == "豆粕"
    assert companies_body["data"][0]["predictions"][0]["date"] == "2026-07-02"

    detail_body = get_article_detail(article.id, session=api_session)
    assert detail_body["data"]["text"]["cleaned_text"] == "cleaned"
    assert detail_body["data"]["text"]["refined_text"] == "refined"
    assert detail_body["data"]["text"]["refined_length"] == len("refined")
    assert detail_body["data"]["task_logs"][0]["stage"] == "llm"
    assert len(detail_body["data"]["analysis_results"]) == 1
    assert detail_body["data"]["analysis_result"]["product"] == "豆粕"
    assert detail_body["data"]["analysis_results"][0]["evidence"]["summary"] == "震荡整理"

    trends_body = get_trends(product="豆粕", session=api_session)
    assert trends_body["data"][0]["product"] == "豆粕"
    assert trends_body["data"][0]["value"] == 0.0

    confirm_body = confirm_result(
        result.id,
        ConfirmResultRequest(
            product="豆粕",
            direction="看涨",
            reason="人工确认需求改善",
            confidence=0.9,
            confirmed_by="analyst",
        ),
        session=api_session,
    )
    assert confirm_body["code"] == 0
    assert confirm_body["data"]["original_direction"] == "中性"

    confirmed_detail = get_article_detail(article.id, session=api_session)
    assert confirmed_detail["data"]["analysis_result"]["direction"] == "看涨"
    assert confirmed_detail["data"]["analysis_result"]["analysis_method"] == "manual"
    assert confirmed_detail["data"]["analysis_result"]["need_manual_review"] is False
    assert confirmed_detail["data"]["analysis_results"][0]["direction"] == "看涨"
    api_session.close()


def test_unknown_analysis_results_are_stored_but_hidden_from_frontend_apis(session_factory) -> None:
    seed_session = session_factory()
    repository = ArticleRepository(seed_session)
    article = repository.create_article(
        title="无有效观点",
        source="日报",
        company="空内容期货",
        publish_time=datetime(2026, 7, 3, 9, 0),
    )
    repository.save_analysis_result(
        article.id,
        product="未知",
        direction="中性",
        reason="文本仅包含导航和免责声明",
        confidence=0.0,
        analysis_method="llm",
        need_manual_review=True,
    )
    seed_session.commit()

    saved = seed_session.scalars(
        select(AnalysisResult).where(AnalysisResult.article_id == article.id)
    ).all()
    assert len(saved) == 1
    assert saved[0].product == "未知"

    list_body = list_articles(page=1, page_size=20, session=seed_session)
    assert list_body["data"] == []

    products_body = get_products(session=seed_session)
    assert products_body["data"] == []

    companies_body = get_companies(session=seed_session)
    assert companies_body["data"] == []

    trends_body = get_trends(session=seed_session)
    assert trends_body["data"] == []

    detail_body = get_article_detail(article.id, session=seed_session)
    assert detail_body["data"]["analysis_result"] is None
    assert detail_body["data"]["analysis_results"] == []

    summary = repository.get_dashboard_summary(today=datetime(2026, 7, 3, 12, 0))
    assert summary["success_count"] == 1
    assert summary["manual_review_count"] == 0
    assert summary["direction_distribution"] == {"看涨": 0, "看跌": 0, "中性": 0}
    seed_session.close()


def test_mixed_unknown_and_valid_results_only_show_valid_result(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(
        title="混合观点",
        source="日报",
        company="混合期货",
        publish_time=datetime(2026, 7, 3, 10, 0),
    )
    repository.save_analysis_results(
        article.id,
        [
            {
                "product": "未知",
                "direction": "中性",
                "reason": "无有效内容",
                "confidence": 0.1,
                "analysis_method": "llm",
                "need_manual_review": True,
                "is_primary": True,
            },
            {
                "product": "豆粕",
                "direction": "看涨",
                "reason": "需求改善",
                "confidence": 0.82,
                "analysis_method": "llm",
                "need_manual_review": False,
                "is_primary": False,
            },
        ],
    )
    session.commit()

    body = list_articles(page=1, page_size=20, session=session)
    assert len(body["data"]) == 1
    assert body["data"][0]["summary"] == "豆粕看涨 0.82"

    products_body = get_products(session=session)
    assert [item["product"] for item in products_body["data"]] == ["豆粕"]

    companies_body = get_companies(session=session)
    assert companies_body["data"][0]["predictions"][0]["product"] == "豆粕"

    trends_body = get_trends(session=session)
    assert trends_body["data"] == [{"date": "2026-07-03", "product": "豆粕", "value": 0.82}]

    detail_body = get_article_detail(article.id, session=session)
    assert detail_body["data"]["analysis_result"]["product"] == "豆粕"
    assert [item["product"] for item in detail_body["data"]["analysis_results"]] == ["豆粕"]
    session.close()


def test_article_detail_builds_traceable_evidence_from_cleaned_text(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="豆粕证据")
    cleaned_text = "豆粕库存下降，价格震荡整理。后续需求恢复，豆粕看涨。"
    reason = "库存下降，价格震荡整理"
    repository.save_raw_text(article.id, "raw", parser_type="html")
    repository.save_cleaned_text(article.id, cleaned_text)
    repository.save_analysis_result(
        article.id,
        product="豆粕",
        direction="中性",
        reason=reason,
        confidence=0.72,
        analysis_method="rule",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_results"][0]["evidence"]

    assert evidence["summary"] == reason
    assert evidence["source"] == "cleaned_text"
    assert evidence["excerpts"][0]["source"] == "cleaned_text"
    assert evidence["excerpts"][0]["match_type"] == "reason"
    assert reason in evidence["excerpts"][0]["quote"]
    assert evidence["excerpts"][0]["start_char"] == 0
    assert evidence["excerpts"][0]["end_char"] > evidence["excerpts"][0]["start_char"]
    session.close()


def test_article_detail_merges_neighboring_evidence_phrases(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="聚乙烯证据")
    cleaned_text = (
        "产员穿全年，产能压力巨大，同时存量负荷也较高，二者：\n"
        "产能压力巨大，存量负荷较高。\n"
        "芝力，基差回落，成本端原油预期也偏弱，聚乙烯价格重心有望震荡下移。"
    )
    reason = "产能压力巨大，存量负荷较高，基差回落，成本端原油预期偏弱"
    repository.save_cleaned_text(article.id, cleaned_text)
    repository.save_analysis_result(
        article.id,
        product="LLDPE",
        direction="看跌",
        reason=reason,
        confidence=1.0,
        analysis_method="llm",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]
    quote = evidence["excerpts"][0]["quote"]

    assert len(evidence["excerpts"]) == 1
    assert evidence["excerpts"][0]["match_type"] == "reason"
    assert "二者：" in quote
    assert "产能压力巨大，存量负荷较高。" in quote
    assert "基差回落，成本端原油预期也偏弱" in quote
    session.close()


def test_article_detail_falls_back_to_analysis_reason_when_evidence_is_not_located(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="棉花证据")
    reason = "进口利润收窄支撑价格"
    repository.save_cleaned_text(article.id, "没有相关文本")
    repository.save_analysis_result(
        article.id,
        product="棉花",
        direction="看涨",
        reason=reason,
        confidence=0.6,
        analysis_method="llm",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]

    assert evidence["summary"] == reason
    assert evidence["source"] == "analysis_reason"
    assert evidence["excerpts"][0]["quote"] == reason
    assert evidence["excerpts"][0]["start_char"] is None
    assert evidence["excerpts"][0]["end_char"] is None
    assert evidence["excerpts"][0]["match_type"] == "fallback"
    assert "未能定位原文" in evidence["notes"]
    session.close()


def test_articles_list_handles_null_publish_time(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(
        title="无发布时间文章",
        source="本地测试",
        company="测试期货",
        publish_time=None,
    )
    repository.save_analysis_result(
        article.id,
        product="螺纹钢",
        direction="看涨",
        reason="需求改善",
        confidence=0.9,
        analysis_method="llm",
    )
    session.commit()

    body = list_articles(page=1, page_size=20, session=session)

    assert body["code"] == 0
    assert body["data"][0]["title"] == "无发布时间文章"
    assert body["data"][0]["publish_time"] == ""
    session.close()


def test_task_run_single_article_uses_pipeline(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="已处理文章")
    repository.save_analysis_result(
        article.id,
        product="豆粕",
        direction="中性",
        reason="已完成",
        confidence=0.7,
        analysis_method="rule",
    )
    session.commit()

    body = run_task(TaskRunRequest(article_id=article.id), session=session)

    assert body["code"] == 0
    assert body["data"]["triggered"] == 1
    assert body["data"]["succeeded"] == 1
    assert body["data"]["failed"] == 0
    session.close()


def test_task_run_limit_uses_batch_process(session_factory, monkeypatch) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    first = repository.create_article(title="待处理 1")
    second = repository.create_article(title="待处理 2")
    session.commit()

    captured = {}

    def fake_batch_process(article_ids, session_factory_arg, *, max_concurrency, pipeline_callback):
        captured["article_ids"] = article_ids
        captured["max_concurrency"] = max_concurrency
        return BatchResult(total=len(article_ids), succeeded=1, failed=1)

    monkeypatch.setattr("back_end.app.api.tasks.batch_process", fake_batch_process)

    body = run_task(TaskRunRequest(limit=2), session=session)

    assert body["code"] == 0
    assert captured["article_ids"] == [first.id, second.id]
    assert captured["max_concurrency"] == 2
    assert body["data"]["triggered"] == 2
    assert body["data"]["succeeded"] == 1
    assert body["data"]["failed"] == 1
    session.close()

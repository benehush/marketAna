from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.api.articles import get_article_detail, list_articles
from back_end.app.api.companies import get_companies
from back_end.app.api.products import get_products
from back_end.app.api.product_review import (
    approve_product_alias,
    confirm_product_resolution,
    get_product_catalog,
    list_product_aliases,
    list_product_resolutions,
)
from back_end.app.api.results import confirm_result, get_result_detail
from back_end.app.api.schemas import (
    ConfirmResultRequest,
    ProductAliasReviewRequest,
    ProductResolutionConfirmRequest,
)
from back_end.app.api.schemas import TaskRunRequest
from back_end.app.api.tasks import run_task
from back_end.app.api.trends import get_trends
from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.exceptions import AppException
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article, ArticleProductSegment, TaskLog
from back_end.app.repositories import ArticleRepository
from pn05.product_segmenter import segment_article
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
        "article_product_segments",
        "analysis_results",
        "task_logs",
        "manual_confirmations",
        "product_resolutions",
        "product_aliases",
    }.issubset(set(inspector.get_table_names()))
    assert any(
        constraint["name"] == "uq_analysis_results_article_product_contract"
        for constraint in inspector.get_unique_constraints("analysis_results")
    )
    assert any(
        constraint["name"] == "uq_article_product_segments_scope"
        for constraint in inspector.get_unique_constraints("article_product_segments")
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
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "螺纹钢",
                "section_type": "core",
                "heading": "螺纹钢",
                "cleaned_text": "螺纹钢需求改善。",
                "start_char": 0,
                "end_char": 8,
                "confidence": 0.9,
            },
            {
                "product": "螺纹钢",
                "section_type": "ocr",
                "heading": "图文识别",
                "cleaned_text": "图文识别显示螺纹钢库存下降。",
                "start_char": 10,
                "end_char": 25,
                "confidence": 0.8,
            },
        ],
    )
    assert len(repository.get_product_segments(article.id)) == 2
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "螺纹钢",
                "section_type": "ocr",
                "heading": "图文识别",
                "cleaned_text": "图文识别显示螺纹钢库存下降。",
                "start_char": 10,
                "end_char": 25,
                "confidence": 0.8,
            }
        ],
    )
    assert len(repository.get_product_segments(article.id)) == 1
    assert repository.find_product_segment(article.id, "螺纹钢").section_type == "ocr"
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
    assert summary["direction_distribution"]["看跌"] == 0
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
    assert products_body["data"] == []

    companies_body = get_companies(session=api_session)
    assert companies_body["data"] == []

    detail_body = get_article_detail(article.id, session=api_session)
    assert detail_body["data"]["text"]["cleaned_text"] == "cleaned"
    assert detail_body["data"]["text"]["refined_text"] == "refined"
    assert detail_body["data"]["text"]["refined_length"] == len("refined")
    assert detail_body["data"]["task_logs"][0]["stage"] == "llm"
    assert len(detail_body["data"]["analysis_results"]) == 1
    assert detail_body["data"]["analysis_result"]["product"] == "豆粕"
    assert detail_body["data"]["analysis_results"][0]["evidence"]["summary"] == "震荡整理"

    trends_body = get_trends(product="豆粕", session=api_session)
    assert trends_body["data"] == []

    with pytest.raises(AppException) as pending_error:
        get_result_detail(result.id, session=api_session)
    assert pending_error.value.status_code == 404

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

    products_body = get_products(session=api_session)
    assert products_body["data"][0]["product"] == "豆粕"
    assert products_body["data"][0]["predictions"][0]["result_id"] == result.id
    assert products_body["data"][0]["predictions"][0]["company"] == "丙期货"

    companies_body = get_companies(session=api_session)
    assert companies_body["data"][0]["predictions"][0]["result_id"] == result.id

    trends_body = get_trends(product="豆粕", session=api_session)
    assert trends_body["data"][0]["value"] == 0.9

    result_body = get_result_detail(result.id, session=api_session)
    assert result_body["data"]["result"]["analysis_method"] == "manual"
    assert result_body["data"]["article"]["company"] == "丙期货"
    assert result_body["data"]["article"]["has_source"] is False
    api_session.close()


def test_result_detail_returns_finalized_rule_and_llm_results_with_evidence(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)

    rule_article = repository.create_article(
        title="螺纹钢日报",
        company="甲期货",
        file_url="data/rebar.html",
        file_type="html",
        publish_time=datetime(2026, 7, 4, 9, 0),
    )
    rule_result = repository.save_analysis_result(
        rule_article.id,
        product="螺纹钢",
        direction="看涨",
        reason="库存持续下降",
        confidence=0.82,
        analysis_method="rule",
    )
    rule_result.evidence_json = {
        "summary": "库存下降支撑价格",
        "source": "segment",
        "excerpts": [{
            "quote": "螺纹钢库存连续第三周下降。",
            "source": "segment",
            "start_char": 10,
            "end_char": 25,
            "match_type": "reason",
        }],
        "notes": "规则命中库存信号",
    }

    llm_article = repository.create_article(
        title="沪铜展望",
        source="研究所",
        company="乙期货",
    )
    repository.save_raw_text(llm_article.id, "沪铜供应偏紧，价格可能走强。", parser_type="html")
    repository.save_cleaned_text(llm_article.id, "沪铜供应偏紧，价格可能走强。")
    llm_result = repository.save_analysis_result(
        llm_article.id,
        product="沪铜",
        direction="看涨",
        reason="供应偏紧",
        confidence=0.76,
        analysis_method="llm",
    )
    session.commit()

    rule_body = get_result_detail(rule_result.id, session=session)["data"]
    assert rule_body["result"]["analysis_method"] == "rule"
    assert rule_body["result"]["evidence"]["excerpts"][0]["quote"] == "螺纹钢库存连续第三周下降。"
    assert rule_body["article"] == {
        "id": rule_article.id,
        "title": "螺纹钢日报",
        "source": None,
        "company": "甲期货",
        "publish_time": "2026-07-04T09:00:00",
        "file_type": "html",
        "has_source": True,
    }

    llm_body = get_result_detail(llm_result.id, session=session)["data"]
    assert llm_body["result"]["analysis_method"] == "llm"
    assert llm_body["result"]["evidence"]["source"] == "cleaned_text"
    assert "沪铜供应偏紧" in llm_body["result"]["evidence"]["excerpts"][0]["quote"]
    session.close()


def test_result_detail_hides_pending_invalid_unstored_and_missing_results(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)

    pending_article = repository.create_article(title="待审核")
    pending = repository.save_analysis_result(
        pending_article.id,
        product="豆粕",
        direction="中性",
        reason="方向不明确",
        confidence=0.4,
        analysis_method="llm",
        need_manual_review=True,
    )

    unknown_article = repository.create_article(title="未知品种")
    unknown = repository.save_analysis_result(
        unknown_article.id,
        product="未知",
        direction="中性",
        reason="无法识别品种",
        confidence=0.1,
        analysis_method="llm",
    )

    unstored_article = repository.create_article(title="尚未入库")
    unstored = repository.save_analysis_result(
        unstored_article.id,
        product="黄金",
        direction="看涨",
        reason="避险需求增加",
        confidence=0.8,
        analysis_method="rule",
        mark_stored=False,
    )

    blank_article = repository.create_article(title="空品种")
    blank_article.status = ArticleProcessingStatus.STORED.value
    blank = AnalysisResult(
        article_id=blank_article.id,
        product=" ",
        product_key="legacy:blank",
        contract_key="",
        direction="中性",
        reason="无品种",
        confidence=0.2,
        analysis_method="rule",
        need_manual_review=False,
    )
    session.add(blank)
    session.commit()

    for result_id in (pending.id, unknown.id, unstored.id, blank.id, 999999):
        with pytest.raises(AppException) as error:
            get_result_detail(result_id, session=session)
        assert error.value.status_code == 404
        assert error.value.message == "Analysis result not found"
    session.close()


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
    assert trends_body["data"] == [{
        "date": "2026-07-03",
        "product": "豆粕",
        "product_key": "DCE.M",
        "product_group": "农产品",
        "value": 0.82,
    }]

    detail_body = get_article_detail(article.id, session=session)
    assert detail_body["data"]["analysis_result"]["product"] == "豆粕"
    assert [item["product"] for item in detail_body["data"]["analysis_results"]] == ["豆粕"]
    session.close()


def test_products_api_deduplicates_same_article_product_predictions(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(
        title="PX重复观点",
        source="日报",
        company="东海期货",
        publish_time=datetime(2025, 4, 1, 9, 0),
    )
    repository.save_analysis_results(
        article.id,
        [
            {
                "product": "PX",
                "contract": "05",
                "direction": "看涨",
                "reason": "PX跟随原油反弹。",
                "confidence": 0.8,
                "analysis_method": "llm",
                "is_primary": False,
            },
            {
                "product": "PX",
                "contract": "09",
                "direction": "看涨",
                "reason": "PX供需好转，反弹概率较高。",
                "confidence": 1.0,
                "analysis_method": "llm",
                "is_primary": True,
            },
        ],
    )
    session.commit()

    products_body = get_products(session=session)
    px_predictions = products_body["data"][0]["predictions"]

    assert products_body["data"][0]["product"] == "PX"
    assert len(px_predictions) == 1
    assert px_predictions[0]["article_id"] == article.id
    assert px_predictions[0]["confidence"] == 1.0
    assert px_predictions[0]["contract"] == "09"
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


def test_article_detail_scopes_fallback_evidence_to_product_anchor(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="PVC证据锚点")
    cleaned_text = (
        "总体来看，当前成材端需求回暖带动库存加速去化，短期内的累库风险得到缓解。"
        "然而，中长期需求压力依在，预计成材价格将维持底部震荡走势。\n"
        "净持仓多空变化不大、空头持仓集中，中期方向不明朗。"
        "3月31日，南非锰矿出口加税传闻引发锰硅盘面价格再起波澜。\n"
        "PVC05合约下跌39元，报5079元，常州SG-5现货价4890元/吨。"
        "厂内库存44万吨，社会库存80.5万吨。"
        "整体而言，库存加速去化，成本支撑预期走强，供需改善，"
        "短期基本面有支撑，但弱宏观主导背景下偏弱震荡。\n"
        "EG05合约下跌4元，报4447元，华东现货下跌35元，报4481元。"
        "乙二醇港口库存78.5万吨，累库1.8万吨。"
    )
    reason = "库存加速去化，成本支撑走强，供需改善，但弱宏观主导背景下偏弱震荡，方向不明。"
    repository.save_cleaned_text(article.id, cleaned_text)
    repository.save_analysis_result(
        article.id,
        product="PVC",
        contract="05",
        direction="中性",
        reason=reason,
        confidence=0.5,
        analysis_method="llm",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]
    quote = "\n".join(item["quote"] for item in evidence["excerpts"])

    assert evidence["source"] == "cleaned_text"
    assert "PVC05" in quote
    assert "库存加速去化" in quote
    assert "成本支撑" in quote
    assert "成材端需求" not in quote
    assert "锰硅" not in quote
    assert "EG05" not in quote
    session.close()


def test_article_detail_avoids_reason_match_when_product_anchor_missing_in_multi_product_text(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="缺失品种锚点")
    reason = "库存加速去化，成本支撑走强"
    repository.save_cleaned_text(
        article.id,
        (
            "PVC05合约下跌，库存加速去化，成本支撑预期走强。"
            "EG05合约下跌，乙二醇库存累库。"
        ),
    )
    repository.save_analysis_result(
        article.id,
        product="棉花",
        direction="中性",
        reason=reason,
        confidence=0.5,
        analysis_method="llm",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]

    assert evidence["source"] == "analysis_reason"
    assert evidence["excerpts"][0]["quote"] == reason
    assert evidence["excerpts"][0]["start_char"] is None
    session.close()


def test_article_detail_prefers_product_segment_evidence(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="多品种证据")
    repository.save_cleaned_text(article.id, "乙二醇弱势。股指震荡。")
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "乙二醇",
                "section_type": "core",
                "heading": "乙二醇",
                "cleaned_text": "乙二醇供应压力偏高，价格承压。",
                "refined_text": "乙二醇供应压力偏高，价格仍然承压。",
                "start_char": 0,
                "end_char": 17,
                "confidence": 0.9,
            },
            {
                "product": "股指",
                "section_type": "core",
                "heading": "股指",
                "cleaned_text": "股指受风险偏好影响维持震荡。",
                "refined_text": "股指受风险偏好影响，维持震荡。",
                "start_char": 18,
                "end_char": 34,
                "confidence": 0.9,
            },
        ],
    )
    repository.save_analysis_result(
        article.id,
        product="乙二醇",
        direction="看跌",
        reason="供应压力偏高",
        confidence=0.82,
        analysis_method="rule",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_results"][0]["evidence"]

    assert evidence["source"] == "segment"
    assert evidence["section_type"] == "core"
    assert evidence["cleaned_text"] == "乙二醇供应压力偏高，价格承压。"
    assert evidence["refined_text"] == "乙二醇供应压力偏高，价格仍然承压。"
    assert "股指" not in evidence["refined_text"]
    session.close()


def test_article_detail_sanitizes_legacy_dirty_reason_and_segment_text(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="东海股指证据")
    dirty_text = (
        "【股指】受光伏设备、化工及电池等板块拖累，国内股市小幅下跌。"
        "投资咨询证号：Z0019876\n\n"
        "邮箱：liub@qh168.com.cn 外部冲击不确定性增加，短期建议谨慎观望。\n"
        "电话：021-68757827"
    )
    repository.save_cleaned_text(article.id, dirty_text)
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "股指",
                "section_type": "core",
                "heading": "股指",
                "cleaned_text": dirty_text,
                "refined_text": dirty_text,
                "start_char": 0,
                "end_char": len(dirty_text),
                "confidence": 0.9,
            }
        ],
    )
    repository.save_analysis_result(
        article.id,
        product="股指",
        direction="看跌",
        reason=dirty_text,
        confidence=0.9,
        analysis_method="rule",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    result = body["data"]["analysis_result"]
    evidence = result["evidence"]

    assert "国内股市小幅下跌" in result["reason"]
    assert "外部冲击不确定性增加" in evidence["summary"]
    assert "谨慎观望" in evidence["refined_text"]
    for value in (result["reason"], evidence["summary"], evidence["cleaned_text"], evidence["refined_text"]):
        assert "Z0019876" not in value
        assert "liub@qh168.com.cn" not in value
        assert "021-68757827" not in value
        assert "\n\n" not in value
    session.close()


def test_article_detail_prefers_reason_matching_complete_segment(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="豆油证据匹配")
    repository.save_cleaned_text(article.id, "豆油多段文本")
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "豆油",
                "section_type": "core",
                "heading": "豆油",
                "cleaned_text": "【豆油】三大油脂商业库存总量为198.55万吨，较上周减少5.97万吨，跌幅",
                "start_char": 0,
                "end_char": 40,
                "confidence": 0.9,
            },
            {
                "product": "豆油",
                "section_type": "core",
                "heading": "豆油",
                "cleaned_text": (
                    "阶段性受国际油脂走强提振反弹，国内菜棕价格溢价支撑稳固，"
                    "窄幅区间震荡行情或维持。"
                ),
                "start_char": 41,
                "end_char": 95,
                "confidence": 0.8,
            },
        ],
    )
    repository.save_analysis_result(
        article.id,
        product="豆油",
        direction="看涨",
        reason="国际油脂走强提振反弹，国内菜棕价格溢价支撑稳固",
        confidence=0.9,
        analysis_method="rule",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]

    assert evidence["source"] == "segment"
    assert "国际油脂走强提振反弹" in evidence["cleaned_text"]
    assert "跌幅" not in evidence["cleaned_text"]
    session.close()


def test_article_detail_trims_dangling_segment_tail_for_display(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="菜粕证据")
    segment_text = (
        "【菜粕】国内逐渐进入水产需求旺季，但豆菜粕现货价差收缩，豆粕替代菜粕消费有望增加。"
        "国内菜粕关税成本限制直接进口骤减，菜籽远期预期到港也不多，压榨产出补充也不足，"
        "中期菜粕依然具备驱动上涨的可能。重点关注中加菜系贸"
    )
    repository.save_cleaned_text(article.id, segment_text)
    repository.save_product_segments(
        article.id,
        [
            {
                "product": "菜粕",
                "section_type": "core",
                "heading": "菜粕",
                "cleaned_text": segment_text,
                "start_char": 0,
                "end_char": len(segment_text),
                "confidence": 0.9,
            }
        ],
    )
    repository.save_analysis_result(
        article.id,
        product="菜粕",
        direction="看涨",
        reason="国内菜粕关税成本限制进口，菜籽远期到港不多，中期具备驱动上涨可能。",
        confidence=0.7,
        analysis_method="llm",
    )
    session.commit()

    body = get_article_detail(article.id, session=session)
    evidence = body["data"]["analysis_result"]["evidence"]

    assert "中期菜粕依然具备驱动上涨的可能。" in evidence["cleaned_text"]
    assert "重点关注中加菜系贸" not in evidence["cleaned_text"]
    assert evidence["cleaned_text"].endswith("中期菜粕依然具备驱动上涨的可能。")
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


def test_product_review_api_confirms_resolution_and_approves_alias(session_factory) -> None:
    session = session_factory()
    repository = ArticleRepository(session)
    article = repository.create_article(title="欧集线日报")
    repository.save_cleaned_text(article.id, "## 核心正文\n\n【欧集线】运价预期偏强。")
    segment_article(article.id, session)
    session.commit()

    catalog = get_product_catalog()
    assert any(item["product_key"] == "INE.EC" for item in catalog["data"])

    pending = list_product_resolutions(limit=100, session=session)["data"]
    assert len(pending) == 1
    response = confirm_product_resolution(
        pending[0]["id"],
        ProductResolutionConfirmRequest(product_key="INE.EC", reviewed_by="analyst"),
        session=session,
    )
    assert response["data"]["resolved_product_key"] == "INE.EC"
    assert response["data"]["reanalysis_required"] is True

    aliases = list_product_aliases(limit=100, session=session)["data"]
    assert aliases[0]["alias"] == "欧集线"
    approved = approve_product_alias(
        aliases[0]["id"], ProductAliasReviewRequest(reviewed_by="reviewer"), session=session
    )
    assert approved["data"]["status"] == "approved"
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

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.exceptions import AppException
from back_end.app.models import AnalysisResult, AnalysisReviewQueue
from back_end.app.repositories import ArticleRepository
from back_end.app.services.ingestion import (
    _reconcile_analysis_results,
    _reconcile_pending_review_items,
    _upsert_review_item,
)


def _session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()


def _review(session) -> AnalysisReviewQueue:
    article = ArticleRepository(session).create_article(title="人工审核测试")
    payload = {
        "product": "豆粕",
        "product_key": "DCE.M",
        "reason": "no_signal",
        "evidence": {"excerpts": [{"quote": "库存下降，需求改善"}]},
    }
    _upsert_review_item(session, article.id, payload)
    session.flush()
    return session.scalar(select(AnalysisReviewQueue))


def test_rejected_review_stays_rejected_after_pipeline_upsert() -> None:
    session = _session()
    item = _review(session)
    ArticleRepository(session).reject_review_item(
        item.id, reviewed_by="auditor", reason_code="navigation_noise", note="误识别"
    )

    _upsert_review_item(session, item.article_id, {
        "product": "豆粕",
        "product_key": "DCE.M",
        "reason": "no_signal",
        "evidence": {"excerpts": [{"quote": "流水线再次触发"}]},
    })
    session.flush()

    assert item.status == "rejected"
    assert item.reviewed_by == "auditor"
    assert item.review_note == "误识别"


def test_pipeline_reconciliation_deletes_only_stale_pending_reviews() -> None:
    session = _session()
    article = ArticleRepository(session).create_article(title="重跑对账")
    stale = AnalysisReviewQueue(
        article_id=article.id, item_key="stale", reason="no_signal", status="pending"
    )
    active = AnalysisReviewQueue(
        article_id=article.id, item_key="active", reason="no_signal", status="pending"
    )
    rejected = AnalysisReviewQueue(
        article_id=article.id, item_key="rejected", reason="no_signal", status="rejected"
    )
    resolved = AnalysisReviewQueue(
        article_id=article.id, item_key="resolved", reason="no_signal", status="resolved"
    )
    session.add_all([stale, active, rejected, resolved])
    session.flush()

    _reconcile_pending_review_items(session, article.id, {"active"})
    session.flush()

    rows = {item.item_key: item.status for item in session.scalars(select(AnalysisReviewQueue)).all()}
    assert rows == {"active": "pending", "rejected": "rejected", "resolved": "resolved"}


def test_analysis_reconciliation_removes_stale_automatic_results_but_keeps_manual() -> None:
    session = _session()
    article = ArticleRepository(session).create_article(title="分析结果重跑对账")
    session.add_all(
        [
            AnalysisResult(
                article_id=article.id, product="沪铝", product_key="SHFE.AL", contract_key="",
                direction="看跌", reason="active", confidence=0.8, analysis_method="rule",
            ),
            AnalysisResult(
                article_id=article.id, product="瓶片", product_key="CZCE.PR", contract_key="",
                direction="看跌", reason="stale", confidence=0.8, analysis_method="rule",
            ),
            AnalysisResult(
                article_id=article.id, product="油菜籽", product_key="CZCE.RS", contract_key="",
                direction="看涨", reason="manual", confidence=1.0, analysis_method="manual",
            ),
        ]
    )
    session.flush()

    _reconcile_analysis_results(
        session,
        article.id,
        [{"product_key": "SHFE.AL", "contract_key": ""}],
    )
    session.flush()

    rows = {row.product_key: row.analysis_method for row in session.scalars(select(AnalysisResult)).all()}
    assert rows == {"SHFE.AL": "rule", "CZCE.RS": "manual"}


def test_manual_conclusion_requires_reason_and_evidence_before_formal_result() -> None:
    session = _session()
    item = _review(session)
    repository = ArticleRepository(session)

    try:
        repository.create_manual_conclusion(
            item.id,
            direction="看涨",
            reason=" ",
            evidence="库存下降",
            product_key="DCE.M",
            reviewed_by="auditor",
        )
    except AppException:
        pass
    else:
        raise AssertionError("an incomplete conclusion must be rejected")
    assert session.scalar(select(AnalysisResult)) is None
    assert item.status == "pending"

    result = repository.create_manual_conclusion(
        item.id,
        direction="看涨",
        reason="库存下降且需求改善",
        evidence="原文：库存环比下降，终端需求回升。",
        product_key="DCE.M",
        reviewed_by="auditor",
    )

    assert result.analysis_method == "manual"
    assert result.need_manual_review is False
    assert result.evidence_json["source"] == "manual"
    assert item.status == "resolved"

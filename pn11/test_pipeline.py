"""
pn11 Pipeline 单元测试

测试流水线编排、状态路由、重试和批量并发处理。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.repositories.articles import ArticleRepository

from pn11.pipeline import run_pipeline
from pn11.batch import batch_process
from pn11.models import PipelineResult, BatchResult
from pn07.models import LLMConfig


# ---- Fixtures ----

@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _f() -> Session:
        return factory()

    _f._engine = engine
    try:
        yield _f
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_article(session: Session, title: str = "测试") -> int:
    repo = ArticleRepository(session)
    a = repo.create_article(
        title=title, file_type="html", file_url="/t.html",
        publish_time=datetime(2026, 7, 3, 10, 0),
    )
    session.commit()
    return a.id


def _mock_parse(article, session, result=None):
    """Mock pn04: 写入 raw_text, status→1。"""
    repo = ArticleRepository(session)
    repo.save_raw_text(article.id, f"raw text for {article.id}", parser_type="html")
    session.commit()


def _mock_clean(article_id, session, result=None):
    """Mock pn05: 写入 cleaned_text, status→2。"""
    repo = ArticleRepository(session)
    repo.save_cleaned_text(article_id, f"cleaned text for {article_id}")
    session.commit()


def _mock_refine(article_id, session, result=None):
    """Mock pn05 refiner: 写入 refined_text, status 保持 2。"""
    repo = ArticleRepository(session)
    repo.save_refined_text(article_id, f"refined text for {article_id}")
    session.commit()


def _mock_rule_high(article_id, session, result=None):
    """Mock pn06 高置信: 直接入库, status→5。"""
    from pn06.models import RuleResult
    repo = ArticleRepository(session)
    repo.update_status(article_id, ArticleProcessingStatus.RULE_ANALYZED)
    repo.save_analysis_result(
        article_id=article_id, product="螺纹钢", direction="看涨",
        reason="需求改善", confidence=0.85, analysis_method="rule",
        mark_stored=True,
    )
    session.commit()
    return RuleResult(product="螺纹钢", direction="看涨", confidence=0.85, need_llm=False)


def _mock_rule_low(article_id, session, result=None):
    """Mock pn06 低置信: status→3, need_llm=True。"""
    from pn06.models import RuleResult
    repo = ArticleRepository(session)
    repo.update_status(article_id, ArticleProcessingStatus.RULE_ANALYZED)
    session.commit()
    return RuleResult(product="豆粕", direction="中性", confidence=0.35, need_llm=True)


def _mock_llm(article_id, session, result=None):
    """Mock pn07: LLM推理, status→5。"""
    repo = ArticleRepository(session)
    repo.update_status(article_id, ArticleProcessingStatus.LLM_INFERRED)
    repo.save_analysis_result(
        article_id=article_id, product="豆粕", direction="中性",
        reason="方向不明确", confidence=0.35, analysis_method="llm",
        need_manual_review=True, mark_stored=True,
    )
    session.commit()


# ---- 测试：正常流程 ----

def test_pipeline_full_flow_high_conf(session_factory):
    """status=0 → parser→cleaner→rule(高置信)→status=5。"""
    session = session_factory()
    aid = _create_article(session)
    session.close()

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser", side_effect=_mock_parse),
        patch("pn11.pipeline._run_cleaner", side_effect=_mock_clean),
        patch("pn11.pipeline._run_refiner", side_effect=_mock_refine),
        patch("pn11.pipeline._run_rule_engine", side_effect=_mock_rule_high),
    ):
        result = run_pipeline(aid, session2)
    session2.commit()

    assert result is True
    article = ArticleRepository(session2).get_article(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    session2.close()


def test_pipeline_full_flow_with_llm(session_factory):
    """status=0 → parser→cleaner→rule(低置信)→llm→status=5。"""
    session = session_factory()
    aid = _create_article(session)
    session.close()

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser", side_effect=_mock_parse),
        patch("pn11.pipeline._run_cleaner", side_effect=_mock_clean),
        patch("pn11.pipeline._run_refiner", side_effect=_mock_refine),
        patch("pn11.pipeline._run_rule_engine", side_effect=_mock_rule_low),
        patch("pn11.pipeline._run_llm_infer", side_effect=_mock_llm),
    ):
        result = run_pipeline(aid, session2)
    session2.commit()

    assert result is True
    article = ArticleRepository(session2).get_article(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    session2.close()


def test_pipeline_runs_refiner_between_cleaner_and_rule_engine(session_factory):
    session = session_factory()
    aid = _create_article(session)
    session.close()

    order = []

    def parse(article, session, result):
        order.append("parser")
        _mock_parse(article, session)

    def clean(article_id, session, result):
        order.append("cleaner")
        _mock_clean(article_id, session)

    def refine(article_id, session, result):
        order.append("refiner")
        _mock_refine(article_id, session)

    def rule(article_id, session, result):
        order.append("rule_engine")
        return _mock_rule_high(article_id, session)

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser", side_effect=parse),
        patch("pn11.pipeline._run_cleaner", side_effect=clean),
        patch("pn11.pipeline._run_refiner", side_effect=refine),
        patch("pn11.pipeline._run_rule_engine", side_effect=rule),
    ):
        result = run_pipeline(aid, session2)
    session2.commit()

    article = ArticleRepository(session2).get_article_detail(aid)
    assert result is True
    assert order == ["parser", "cleaner", "refiner", "rule_engine"]
    assert article.text.refined_text == f"refined text for {aid}"
    assert article.status == ArticleProcessingStatus.STORED.value
    session2.close()


def test_pipeline_refiner_failure_does_not_block_rule_engine(session_factory, monkeypatch):
    session = session_factory()
    aid = _create_article(session)
    session.close()

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def chat(self, messages, *, retries=None):
            raise RuntimeError("refiner down")

    monkeypatch.setattr(
        LLMConfig,
        "from_settings",
        classmethod(lambda cls: LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://example.test",
            model="fake-refiner",
            max_retries=0,
        )),
    )
    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", FailingClient)

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser", side_effect=_mock_parse),
        patch("pn11.pipeline._run_cleaner", side_effect=_mock_clean),
        patch("pn11.pipeline._run_rule_engine", side_effect=_mock_rule_high),
    ):
        result = run_pipeline(aid, session2)
    session2.commit()

    article = ArticleRepository(session2).get_article_detail(aid)
    assert result is True
    assert article.status == ArticleProcessingStatus.STORED.value
    assert article.text.refined_text is None
    assert any(log.stage == "refiner" and log.status == "failed" for log in article.task_logs)
    session2.close()


# ---- 测试：断点续跑 ----

def test_pipeline_resume_from_parsed(session_factory):
    """status=1(PARSED) → 跳过 parser，从 cleaner 开始。"""
    session = session_factory()
    repo = ArticleRepository(session)
    a = repo.create_article(title="test", file_type="html", file_url="/t.html")
    repo.save_raw_text(a.id, "raw", parser_type="html")
    session.commit()
    session.close()

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser") as mock_parser,
        patch("pn11.pipeline._run_cleaner", side_effect=_mock_clean),
        patch("pn11.pipeline._run_refiner", side_effect=_mock_refine),
        patch("pn11.pipeline._run_rule_engine", side_effect=_mock_rule_high),
    ):
        run_pipeline(a.id, session2)
        mock_parser.assert_not_called()  # parser 不应被调用
    session2.commit()

    article = ArticleRepository(session2).get_article(a.id)
    assert article.status == ArticleProcessingStatus.STORED.value
    session2.close()


def test_pipeline_skip_stored(session_factory):
    """status=5(STORED) → 直接返回 True，不执行任何阶段。"""
    session = session_factory()
    repo = ArticleRepository(session)
    a = repo.create_article(title="test")
    repo.save_raw_text(a.id, "raw", parser_type="html")
    repo.save_cleaned_text(a.id, "clean")
    repo.save_analysis_result(
        article_id=a.id, product="螺纹钢", direction="看涨",
        reason="test", confidence=0.9, analysis_method="rule",
        mark_stored=True,
    )
    session.commit()
    session.close()

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser") as mp,
        patch("pn11.pipeline._run_cleaner") as mc,
        patch("pn11.pipeline._run_refiner") as mf,
        patch("pn11.pipeline._run_rule_engine") as mr,
    ):
        result = run_pipeline(a.id, session2)
        mp.assert_not_called()
        mc.assert_not_called()
        mf.assert_not_called()
        mr.assert_not_called()
    assert result is True
    session2.close()


# ---- 测试：失败处理 ----

def test_pipeline_stage_failure(session_factory):
    """parser 失败 → 返回 False。"""
    session = session_factory()
    aid = _create_article(session)
    session.close()

    def _fail_parse(article, session, result=None):
        repo = ArticleRepository(session)
        repo.mark_failed(article.id, stage="parser", message="文件损坏")
        session.commit()
        raise ValueError("parse failed")

    session2 = session_factory()
    with patch("pn11.pipeline._run_parser", side_effect=_fail_parse):
        result = run_pipeline(aid, session2)
    session2.commit()

    assert result is False
    article = ArticleRepository(session2).get_article(aid)
    assert article.status == ArticleProcessingStatus.FAILED.value
    session2.close()


# ---- 测试：重试 ----

def test_pipeline_retry_from_failed_parser(session_factory):
    """status=-1(parser失败) → 重置为 PENDING → parser 重试成功。"""
    session = session_factory()
    repo = ArticleRepository(session)
    a = repo.create_article(title="retry test", file_type="html", file_url="/t.html")
    repo.mark_failed(a.id, stage="parser", message="parser error: 文件损坏")
    session.commit()
    session.close()

    session2 = session_factory()
    with (
        patch("pn11.pipeline._run_parser", side_effect=_mock_parse),
        patch("pn11.pipeline._run_cleaner", side_effect=_mock_clean),
        patch("pn11.pipeline._run_refiner", side_effect=_mock_refine),
        patch("pn11.pipeline._run_rule_engine", side_effect=_mock_rule_high),
    ):
        result = run_pipeline(a.id, session2)
    session2.commit()

    assert result is True
    article = ArticleRepository(session2).get_article(a.id)
    assert article.status == ArticleProcessingStatus.STORED.value
    session2.close()


# ---- 测试：批量处理 ----

def test_batch_process(session_factory):
    """批量处理 3 篇文章。"""
    session = session_factory()
    ids = [_create_article(session, f"test_{i}") for i in range(3)]
    session.close()

    def _full_pipeline(aid, sess):
        repo = ArticleRepository(sess)
        repo.save_raw_text(aid, f"raw_{aid}", parser_type="html")
        repo.save_cleaned_text(aid, f"clean_{aid}")
        sess.commit()
        return True

    # patch 掉内部阶段调用，直接 mock 成功路径
    def _success_pipeline(aid, sess):
        repo = ArticleRepository(sess)
        article = repo.get_article(aid)
        repo.save_raw_text(aid, "raw", parser_type="html")
        repo.save_cleaned_text(aid, "clean")
        repo.save_analysis_result(
            article_id=aid, product="螺纹钢", direction="看涨",
            reason="test", confidence=0.85, analysis_method="rule",
            mark_stored=True,
        )
        sess.commit()
        return True

    result = batch_process(ids, session_factory, max_concurrency=2,
                           pipeline_callback=_success_pipeline)

    assert result.total == 3
    assert result.succeeded == 3
    assert result.failed == 0


def test_batch_process_empty():
    """空列表 → 正常返回。"""
    result = batch_process([], lambda: None)
    assert result.total == 0
    assert result.succeeded == 0


# ---- PipelineResult ----

def test_pipeline_result_summary():
    r = PipelineResult(
        article_id=1, success=True,
        start_status=0, final_status=5,
        stages_run=["parser", "cleaner", "refiner", "rule_engine"],
        total_duration_ms=350,
    )
    assert "OK" in r.summary()
    assert "parser→cleaner→refiner→rule_engine" in r.summary()


# ---- BatchResult ----

def test_batch_result_all_success():
    r = BatchResult(total=5, succeeded=5, failed=0)
    assert r.all_success is True


def test_batch_result_has_failures():
    r = BatchResult(total=5, succeeded=3, failed=2)
    assert r.all_success is False

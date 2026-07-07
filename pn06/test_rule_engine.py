"""
pn06 RuleEngine 单元测试

测试品种检测、方向识别、置信度计算和完整规则引擎流程。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.repositories.articles import ArticleRepository

from pn06.rule_engine import analyze_article, RuleConfig
from pn06.models import RuleResult
from pn06.product_dict import detect_products, get_primary_product
from pn06.direction_rules import detect_direction, extract_reason
from pn06.confidence import calculate_confidence


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


def _create_article_with_clean(session: Session, cleaned: str) -> int:
    repo = ArticleRepository(session)
    a = repo.create_article(title="测试", file_type="html", file_url="/t.html",
                            publish_time=datetime(2026, 7, 3, 10, 0))
    repo.save_raw_text(a.id, "raw", parser_type="html")
    repo.save_cleaned_text(a.id, cleaned)
    session.commit()
    return a.id


# ---- 品种检测 ----

def test_detect_product_single():
    text = "螺纹钢期货今日震荡上行，主力合约收于3650。"
    prods = detect_products(text)
    assert "螺纹钢" in prods

    primary = get_primary_product(text)
    assert primary == "螺纹钢"


def test_detect_product_multi():
    text = "螺纹钢价格上涨，铁矿石跟涨，沪铜震荡整理。螺纹钢短期偏强。"
    primary = get_primary_product(text)
    assert primary == "螺纹钢"  # 出现2次


def test_detect_product_none():
    text = "今日大盘震荡，市场情绪偏乐观。"
    primary = get_primary_product(text)
    assert primary is None


def test_detect_product_alias():
    """简称也能识别。"""
    text = "RB主力合约震荡上行，铁矿跟涨。"
    prods = detect_products(text)
    assert "螺纹钢" in prods  # RB → 螺纹钢
    assert "铁矿石" in prods  # 铁矿 → 铁矿石


# ---- 方向检测 ----

def test_direction_bullish():
    result = detect_direction("螺纹钢价格看涨，短期偏强运行，预计后市继续上涨。")
    assert result["direction"] == "看涨"
    assert result["bullish_count"] >= 3
    assert result["is_conflict"] is False


def test_direction_bearish():
    result = detect_direction("沪铜短期偏弱，价格下跌，做空压力增大。")
    assert result["direction"] == "看跌"
    assert result["bearish_count"] >= 2


def test_direction_neutral():
    result = detect_direction("豆粕以震荡为主，区间运行，观望为宜。")
    assert result["direction"] == "中性"


def test_direction_none():
    result = detect_direction("今日天气晴好，适合户外运动。")
    assert result["direction"] is None


def test_direction_conflict():
    """看涨+看跌同时出现 → 冲突标记。"""
    result = detect_direction("螺纹钢短期看涨，但长期看跌。")
    assert result["is_conflict"] is True


# ---- 置信度 ----

def test_confidence_high():
    result = detect_direction("螺纹钢看涨，上涨趋势明显，偏强运行，做多。")
    conf = calculate_confidence("螺纹钢", result)
    assert conf >= 0.7


def test_confidence_low_vague():
    """仅模糊词，置信度低。"""
    result = detect_direction("螺纹钢预计短期可能上涨。")
    conf = calculate_confidence("螺纹钢", result)
    assert conf < 0.7


def test_confidence_no_product():
    result = detect_direction("螺纹钢看涨。")
    conf = calculate_confidence(None, result)
    assert conf == 0.0


def test_confidence_neutral_capped():
    """中性方向置信度上限 0.6。"""
    result = detect_direction("螺纹钢震荡整理，横盘运行，波动收窄。")
    conf = calculate_confidence("螺纹钢", result)
    assert conf <= 0.6


# ---- 理由提取 ----

def test_reason_extraction():
    text = (
        "近期螺纹钢库存持续下降。下游补库需求增加。"
        "预计螺纹钢短期偏强运行，价格有望上行。"
        "但终端需求复苏力度仍待观察。操作上建议逢低做多。"
    )
    reason = extract_reason(text, "看涨", window=2)
    assert "偏强" in reason or "上行" in reason or "做多" in reason


# ---- 完整引擎流程 ----

def test_full_pipeline_high_conf(session_factory):
    """高置信文章 → 直接入库，status=5。"""
    session = session_factory()
    text = (
        "螺纹钢期货今日看涨。主力合约震荡上行，"
        "短期偏强运行，做多信号明显。上涨趋势延续，"
        "后市继续看涨，建议增持多单。"
    )
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    result = analyze_article(aid, session2)
    session2.commit()

    assert result.need_llm is False
    assert result.confidence >= 0.7
    assert result.product == "螺纹钢"
    assert result.direction == "看涨"

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    assert article.analysis_result is not None
    assert article.analysis_result.analysis_method == "rule"
    session2.close()


def test_full_pipeline_multi_product_high_conf(session_factory):
    """多品种明确观点 → 生成多条规则结果并直接入库。"""
    session = session_factory()
    text = (
        "## 核心正文\n"
        "【螺纹钢】螺纹钢看涨，上涨趋势明确，短期偏强，建议做多。\n"
        "【铁矿石】铁矿石看跌，下跌趋势明确，短期偏弱，建议做空。"
    )
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    result = analyze_article(aid, session2)
    session2.commit()

    assert result.need_llm is False
    assert len(result.results) == 2
    assert {item.product for item in result.results} == {"螺纹钢", "铁矿石"}

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    assert len(article.analysis_results) == 2
    assert {item.direction for item in article.analysis_results} == {"看涨", "看跌"}
    session2.close()


def test_full_pipeline_same_product_different_contracts(session_factory):
    """同一品种不同合约 → 按 contract_key 保存为不同结果。"""
    session = session_factory()
    text = (
        "【甲醇05合约】甲醇05合约看涨，上涨趋势明确，短期偏强，建议做多。"
        "【甲醇09合约】甲醇09合约看跌，下跌趋势明确，短期偏弱，建议做空。"
    )
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    result = analyze_article(aid, session2)
    session2.commit()

    assert result.need_llm is False
    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert len(article.analysis_results) == 2
    assert {item.contract for item in article.analysis_results} == {"05", "09"}
    session2.close()


def test_full_pipeline_low_conf(session_factory):
    """低置信文章 → status=3, need_llm=True。"""
    session = session_factory()
    text = "豆粕可能震荡，方向不明确，等待选择方向。"
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    result = analyze_article(aid, session2)
    session2.commit()

    assert result.need_llm is True
    assert result.confidence < 0.7

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.RULE_ANALYZED.value
    session2.close()


def test_full_pipeline_no_product(session_factory):
    """无品种 → need_llm=True, status=3。"""
    session = session_factory()
    text = "今日大盘震荡上行，市场情绪偏乐观。"
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    result = analyze_article(aid, session2)
    session2.commit()

    assert result.need_llm is True
    assert result.product is None
    session2.close()


def test_full_pipeline_empty_clean(session_factory):
    """空文本 → mark_failed。"""
    session = session_factory()
    aid = _create_article_with_clean(session, "")
    session.close()

    session2 = session_factory()
    with pytest.raises(ValueError):
        analyze_article(aid, session2)
    session2.commit()

    repo = ArticleRepository(session2)
    article = repo.require_article(aid)
    assert article.status == ArticleProcessingStatus.FAILED.value
    session2.close()


def test_full_pipeline_task_log(session_factory):
    """验证 task_log 写入。"""
    from back_end.app.models.article import TaskLog

    session = session_factory()
    text = "螺纹钢期货今日看涨，上涨趋势明确，做多信号强。"
    aid = _create_article_with_clean(session, text)
    session.close()

    session2 = session_factory()
    analyze_article(aid, session2)
    session2.commit()

    logs = session2.query(TaskLog).filter(
        TaskLog.article_id == aid,
        TaskLog.stage == "rule_engine",
        TaskLog.status == "success",
    ).all()
    assert len(logs) == 1
    session2.close()


# ---- RuleResult ----

def test_rule_result_properties():
    r = RuleResult(product="螺纹钢", direction="看涨", confidence=0.85, need_llm=False)
    assert r.is_high_confidence is True
    assert "螺纹钢" in r.summary()

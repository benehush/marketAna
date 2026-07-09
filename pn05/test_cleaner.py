"""
pn05 Cleaner 单元测试

测试文本规范化、噪声过滤、低密度块移除和完整清洗流程。
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models.article import ArticleText, TaskLog
from back_end.app.repositories.articles import ArticleRepository

from pn05.cleaner import clean_article, CleanConfig
from pn05.models import CleanResult
from pn05.normalizer import (
    normalize_whitespace,
    normalize_fullwidth,
    remove_html_residue,
    detect_and_clean_encoding,
)
from pn05.noise_rules import filter_noise_lines, filter_noise_regex
from pn05.refiner import refine_article
from pn05.structured_cleaner import clean_text
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

    def _factory() -> Session:
        return factory()

    _factory._engine = engine
    try:
        yield _factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _create_article_with_raw(session: Session, raw_text: str) -> int:
    """创建带 raw_text 的文章，返回 article_id。"""
    repo = ArticleRepository(session)
    article = repo.create_article(
        title="测试文章",
        file_type="html",
        file_url="/files/test.html",
        publish_time=datetime(2026, 7, 3, 10, 0),
    )
    repo.save_raw_text(article.id, raw_text, parser_type="html")
    session.commit()
    return article.id


# ---- normalize_whitespace ----

def test_normalize_whitespace_crlf():
    assert normalize_whitespace("line1\r\nline2") == "line1\nline2"


def test_normalize_whitespace_excess_newlines():
    text = "para1\n\n\n\n\npara2"
    result = normalize_whitespace(text)
    assert result == "para1\n\npara2"


def test_normalize_whitespace_spaces():
    assert normalize_whitespace("hello    world\t\ttest") == "hello world test"


# ---- normalize_fullwidth ----

def test_normalize_fullwidth_letters():
    assert normalize_fullwidth("Ｔｅｓｔ") == "Test"


def test_normalize_fullwidth_numbers():
    assert normalize_fullwidth("１２３") == "123"


def test_normalize_fullwidth_chinese_punctuation_preserved():
    """中文标点保留不转换。"""
    text = "螺纹钢价格上涨，市场情绪乐观。"
    assert normalize_fullwidth(text) == text


# ---- remove_html_residue ----

def test_remove_html_residue_entities():
    assert remove_html_residue("A&nbsp;B") == "A B"
    assert remove_html_residue("price&amp;value&quot;test") == "price&value\"test"


def test_remove_html_residue_tags():
    assert "script" not in remove_html_residue("<script>alert(1)</script>")
    assert remove_html_residue("<p>text</p>").strip() == "text"


def test_remove_html_residue_numeric_entity():
    assert " " in remove_html_residue("&#160;")


# ---- detect_and_clean_encoding ----

def test_detect_null_bytes():
    assert "\x00" not in detect_and_clean_encoding("hello\x00world")


def test_detect_replacement_chars():
    result = detect_and_clean_encoding("a���b")
    assert "���" not in result


# ---- filter_noise_lines ----

def test_filter_noise_keywords():
    lines = [
        "螺纹钢价格今日小幅上涨。",
        "版权所有 © 2026 某期货公司",
        "市场情绪偏乐观。",
        "免责声明：本报告仅供参考",
        "预计短期内需求改善。",
    ]
    kept, removed = filter_noise_lines(lines)
    assert removed == 2
    assert "版权所有" not in "\n".join(kept)
    assert "免责声明" not in "\n".join(kept)
    assert "螺纹钢" in "\n".join(kept)


def test_filter_noise_url_line():
    lines = ["正文内容", "https://example.com/ads", "更多分析"]
    kept, removed = filter_noise_lines(lines)
    assert removed == 1


def test_filter_noise_separator_line():
    lines = ["标题", "==========", "正文"]
    kept, removed = filter_noise_lines(lines)
    assert removed == 1


def test_filter_noise_website_chrome():
    lines = [
        "无障碍浏览",
        "正文观点：聚乙烯价格中枢有望下降。",
        "上一篇：【PP日报20250402】",
        "客服热线 400-700-5186",
        "下载APP",
    ]
    kept, removed = filter_noise_lines(lines)
    joined = "\n".join(kept)
    assert removed == 4
    assert "聚乙烯" in joined
    assert "上一篇" not in joined


# ---- filter_noise_regex ----

def test_filter_disclaimer_paragraph():
    text = "市场分析\n免责声明：本报告中的信息来源于公开资料，本公司对这些信息的准确性和完整性不作任何保证。\n\n螺纹钢展望"
    result, removed = filter_noise_regex(text)
    assert removed > 0
    assert "免责声明" not in result


# ---- low density filtering ----

def test_low_density_filtered_in_cleaner(session_factory):
    """低密度块（纯英文/数字的页眉页脚）在清洗中被移除。"""
    session = session_factory()
    raw = "Page 1 of 10\n\n螺纹钢市场分析报告\n\n今日价格小幅上涨。\n\nContact: info@test.com"
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2, config=CleanConfig(min_density_ratio=0.1, min_paragraph_chars=5))
    session2.commit()

    assert "螺纹钢" in cleaned
    # 纯英文页眉页脚应被移除
    assert "Page 1 of 10" not in cleaned
    assert "Contact:" not in cleaned
    session2.close()


# ---- Full pipeline tests ----

def test_clean_full_pipeline(session_factory):
    """完整清洗流程 + Repository 状态验证。"""
    session = session_factory()
    raw = (
        "版权所有 © 某期货公司\n"
        "==========================\n"
        "螺纹钢市场分析日报\n"
        "分析师：张三\n\n"
        "今日螺纹钢期货主力合约震荡上行，收于 3650 元/吨。\n"
        "下游补库需求增加，库存压力有所缓解。\n\n"
        "免责声明：本报告仅供参考，不构成投资建议。\n"
        "市场有风险，投资需谨慎。\n"
    )
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2)
    session2.commit()

    # 正文保留
    assert "螺纹钢" in cleaned
    assert "3650" in cleaned
    assert "震荡上行" in cleaned
    # 噪声移除
    assert "版权所有" not in cleaned
    assert "免责声明" not in cleaned
    assert "=====" not in cleaned

    # 验证数据库状态
    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.CLEANED.value
    assert article.text.cleaned_text == cleaned
    assert article.text.cleaned_length == len(cleaned)
    session2.close()


def test_structured_cleaner_outputs_markdown_sections():
    raw = (
        "# 【L日报20250402】\n"
        "来源文件: data/20250403/324783/浙商期货_324783_0.html\n"
        "解析器: html\n\n"
        "## 正文文本\n"
        "无障碍浏览\n"
        "免责申明: 本报告仅供参考。\n\n"
        "## 图片OCR文本: img_folder/report.png\n"
        "[图片分片 1/6]\n"
        "观点: 聚乙烯震荡下行阶段，后期价格中枢有望下降。\n"
        "逻辑: 新增装置密集落地，产能压力较大，成本端原油预期偏弱。\n"
        "01-02 01-24 02-15 03-08 03-30 04-22 05-15\n"
        "5,000 5,000\n"
        "12505-C-7900\n\n"
        "## AI图表解读: img_folder/report.png\n"
        "主要品种: 聚乙烯。方向线索: 看跌或震荡偏弱。\n"
    )

    cleaned, stats = clean_text(raw, CleanConfig())

    assert cleaned.startswith("# 【L日报20250402】")
    assert "## 文档信息" in cleaned
    assert "## 图文识别正文" in cleaned
    assert "聚乙烯震荡下行" in cleaned
    assert "价格中枢有望下降" in cleaned
    assert "## AI图表解读" in cleaned
    assert "01-02 01-24" not in cleaned
    assert "5,000 5,000" not in cleaned
    assert "12505-C-7900" not in cleaned
    assert stats.numeric_blocks_removed >= 3


def test_structured_cleaner_keeps_semantic_numbers():
    raw = (
        "# 螺纹钢日报\n"
        "解析器: pdf\n\n"
        "## 正文文本\n"
        "今日螺纹钢期货主力合约震荡上行，收于 3650 元/吨。\n"
        "下游补库需求增加，库存压力有所缓解。\n"
        "01-02 01-24 02-15 03-08 03-30 04-22\n"
    )

    cleaned, _stats = clean_text(raw, CleanConfig())

    assert "3650 元/吨" in cleaned
    assert "震荡上行" in cleaned
    assert "01-02 01-24" not in cleaned


def test_structured_cleaner_drops_navigation_only_lines():
    raw = (
        "# 晨报\n"
        "解析器: html\n\n"
        "## 正文文本\n"
        "晨报\n"
        "日报\n"
        "农产品\n"
        "能源化工\n"
        "有色金属\n"
        "交易策略\n"
        "尿素日报20250401\n"
        "尿素库存下降，现货价格震荡偏强。\n"
    )

    cleaned, _stats = clean_text(raw, CleanConfig())

    assert "尿素库存下降" in cleaned
    assert "\n农产品\n" not in cleaned
    assert "\n能源化工\n" not in cleaned
    assert "尿素日报20250401" not in cleaned


def test_clean_article_rejects_navigation_only_content(session_factory):
    session = session_factory()
    raw = (
        "# 晨报\n"
        "来源文件: data/example.html\n"
        "解析器: html\n\n"
        "## 正文文本\n"
        "晨报\n"
        "日报\n"
        "农产品\n"
        "能源化工\n"
        "有色金属\n"
        "黑色金属\n"
        "金融期货\n"
        "周报\n"
        "月报\n"
        "年报\n"
        "交易策略\n"
        "尿素日报20250331\n"
        "尿素日报20250327\n"
        "尿素日报20250401\n"
    )
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    with pytest.raises(ValueError, match="未发现可分析正文"):
        clean_article(aid, session2)
    session2.commit()

    article = ArticleRepository(session2).get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.FAILED.value
    assert "目录、导航" in article.error_msg
    session2.close()


def test_structured_cleaner_table_keeps_headers_drops_numeric_rows():
    raw = (
        "# 价格表\n"
        "解析器: pdf\n\n"
        "## 表格数据\n"
        "| 区域 | 现货价格 | 变化 |\n"
        "| --- | --- | --- |\n"
        "| 华东 | 3650 | +20 |\n"
        "| 3650 | 3660 | 20 |\n"
        "01-02 01-24 02-15 03-08 03-30 04-22\n"
    )

    cleaned, _stats = clean_text(raw, CleanConfig())

    assert "## 表格与数据" in cleaned
    assert "| 区域 | 现货价格 | 变化 |" in cleaned
    assert "| 华东 | 3650 | +20 |" in cleaned
    assert "| 3650 | 3660 | 20 |" not in cleaned
    assert "01-02 01-24" not in cleaned


def test_clean_structured_pipeline_writes_markdown(session_factory):
    session = session_factory()
    raw = (
        "# 【L日报20250402】\n"
        "来源文件: data/20250403/324783/浙商期货_324783_0.html\n"
        "解析器: html\n\n"
        "## 图片OCR文本: img_folder/report.png\n"
        "观点: 聚乙烯震荡下行阶段，后期价格中枢有望下降。\n"
        "01-02 01-24 02-15 03-08 03-30 04-22 05-15\n"
    )
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2)
    session2.commit()

    assert "## 图文识别正文" in cleaned
    assert "聚乙烯" in cleaned
    assert "01-02 01-24" not in cleaned
    article = ArticleRepository(session2).get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.CLEANED.value
    assert article.text.cleaned_text == cleaned
    session2.close()


def test_clean_with_html_residue(session_factory):
    """HTML 残留被清除。"""
    session = session_factory()
    raw = "市场分析<br><br>螺纹钢价格&nbsp;上涨。<p>需求改善</p>"
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2)
    session2.commit()

    assert "<br>" not in cleaned
    assert "&nbsp;" not in cleaned
    assert "<p>" not in cleaned
    assert "螺纹钢" in cleaned
    session2.close()


def test_clean_empty_raw(session_factory):
    """空 raw_text 标记失败。"""
    session = session_factory()
    aid = _create_article_with_raw(session, "")
    session.close()

    session2 = session_factory()
    with pytest.raises(ValueError, match="raw_text 为空"):
        clean_article(aid, session2)
    session2.commit()

    repo = ArticleRepository(session2)
    article = repo.require_article(aid)
    assert article.status == ArticleProcessingStatus.FAILED.value
    session2.close()


def test_clean_task_log(session_factory):
    """验证 task_log 记录。"""
    session = session_factory()
    aid = _create_article_with_raw(session, "螺纹钢分析：今日价格上涨。")
    session.close()

    session2 = session_factory()
    clean_article(aid, session2)
    session2.commit()

    logs = session2.query(TaskLog).filter(
        TaskLog.article_id == aid,
        TaskLog.stage == "cleaner",
        TaskLog.status == "success",
    ).all()
    assert len(logs) == 1
    assert "raw=" in logs[0].message
    session2.close()


def test_refiner_writes_refined_text_and_preserves_cleaned_text(session_factory, monkeypatch):
    session = session_factory()
    aid = _create_article_with_raw(session, "螺纹钢价格上涨。")
    cleaned = clean_article(aid, session)
    session.commit()

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def chat(self, messages, *, retries=None):
            assert "cleaned_text" in messages[1]["content"]
            return "螺纹钢价格上涨，市场整体表现偏强。"

    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", FakeClient)

    refined = refine_article(
        aid,
        session,
        config=LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://example.test",
            model="fake-refiner",
            max_retries=0,
        ),
    )
    session.commit()

    article = ArticleRepository(session).get_article_detail(aid)
    assert refined == "螺纹钢价格上涨，市场整体表现偏强。"
    assert article.text.cleaned_text == cleaned
    assert article.text.refined_text == refined
    assert article.text.refined_length == len(refined)
    assert article.status == ArticleProcessingStatus.CLEANED.value
    assert session.scalars(select(TaskLog).where(
        TaskLog.article_id == aid,
        TaskLog.stage == "refiner",
        TaskLog.status == "success",
    )).first() is not None
    session.close()


def test_refiner_failure_is_non_blocking_and_does_not_overwrite(session_factory, monkeypatch):
    session = session_factory()
    aid = _create_article_with_raw(session, "豆粕库存下降，价格震荡偏强。")
    clean_article(aid, session)
    repo = ArticleRepository(session)
    repo.save_refined_text(aid, "已有精修文本")
    session.commit()

    class FailingClient:
        def __init__(self, config):
            self.config = config

        def chat(self, messages, *, retries=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("pn07.llm_client.LLMAPIClient", FailingClient)

    refined = refine_article(
        aid,
        session,
        config=LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://example.test",
            model="fake-refiner",
            max_retries=0,
        ),
    )
    session.commit()

    article = ArticleRepository(session).get_article_detail(aid)
    assert refined is None
    assert article.status == ArticleProcessingStatus.CLEANED.value
    assert article.text.refined_text == "已有精修文本"
    assert session.scalars(select(TaskLog).where(
        TaskLog.article_id == aid,
        TaskLog.stage == "refiner",
        TaskLog.status == "failed",
    )).first() is not None
    session.close()


def test_clean_ratio_tracking(session_factory):
    """验证清洗比例计算。"""
    session = session_factory()
    # 大量噪声 + 少量正文
    raw = "广告\n" * 50 + "螺纹钢价格上涨。\n" + "版权信息\n" * 10
    aid = _create_article_with_raw(session, raw)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2)
    session2.commit()

    # 正文应保留
    assert "螺纹钢" in cleaned
    # 清洗比例应 > 0
    article = ArticleRepository(session2).get_article_detail(aid)
    assert article.text.cleaned_length < article.text.raw_length
    session2.close()


def test_clean_preserves_chinese(session_factory):
    """中文内容完整保留。"""
    text = (
        "近期铁矿石期货价格受澳洲供应扰动影响明显。"
        "港口库存持续下降，钢厂补库需求支撑矿价。"
        "但终端需求复苏力度仍待观察，短期以震荡偏强为主。"
    )
    session = session_factory()
    aid = _create_article_with_raw(session, text)
    session.close()

    session2 = session_factory()
    cleaned = clean_article(aid, session2)
    session2.commit()

    assert "铁矿石" in cleaned
    assert "港口库存" in cleaned
    assert "震荡偏强" in cleaned
    session2.close()


# ---- CleanResult model ----

def test_clean_result_summary():
    r = CleanResult(
        raw_length=1000,
        cleaned_length=800,
        removal_ratio=0.2,
        noise_lines_removed=5,
        duration_ms=45,
    )
    assert r.total_removed == 200
    assert "20.0%" in r.summary()

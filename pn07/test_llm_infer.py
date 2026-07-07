"""
pn07 LLMInfer 单元测试

测试 JSON 解析、Prompt 构建、和完整推理流程（mock LLM 调用）。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models.article import TaskLog
from back_end.app.repositories.articles import ArticleRepository

from pn07.models import LLMConfig, InferResult
from pn07.json_parser import parse_llm_json
from pn07.llm_client import LLMAPIClient
from pn07.prompt_builder import build_messages


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


def _create_article(session: Session, cleaned: str, title: str = "测试标题") -> int:
    repo = ArticleRepository(session)
    a = repo.create_article(
        title=title, source="日报", company="测试期货",
        file_type="html", file_url="/t.html",
        publish_time=datetime(2026, 7, 3, 10, 0),
    )
    repo.save_raw_text(a.id, "raw", parser_type="html")
    repo.save_cleaned_text(a.id, cleaned)
    session.commit()
    return a.id


# ---- Prompt Builder ----

def test_prompt_build():
    msgs = build_messages(
        "螺纹钢价格上涨。",
        title="螺纹钢日报",
        source="日报",
        company="测试期货",
        publish_time="2026-07-03",
    )
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "资深期货市场分析师" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "螺纹钢日报" in msgs[1]["content"]
    assert "测试期货" in msgs[1]["content"]


def test_prompt_truncation():
    long_text = "螺纹钢" * 5000
    msgs = build_messages(long_text, max_input_chars=500)
    user = msgs[1]["content"]
    assert "已截断" in user
    assert len(user) < len(long_text) + 200


# ---- JSON Parser ----

def test_json_parse_normal():
    raw = '{"product":"螺纹钢","direction":"看涨","reason":"需求改善","confidence":0.85}'
    data, errors = parse_llm_json(raw)
    assert errors == []
    assert data["product"] == "螺纹钢"
    assert data["direction"] == "看涨"
    assert data["confidence"] == 0.85


def test_json_parse_multi_results():
    raw = (
        '{"results":['
        '{"product":"原油","contract":"","direction":"看涨","reason":"供应风险","confidence":0.82},'
        '{"product":"沪铜","contract":"2505","direction":"看跌","reason":"需求偏弱","confidence":0.66}'
        ']}'
    )
    data, errors = parse_llm_json(raw)
    assert errors == []
    assert len(data["results"]) == 2
    assert data["product"] == "原油"
    assert data["results"][1]["contract"] == "2505"


def test_json_parse_markdown_wrap():
    raw = '```json\n{"product":"沪铜","direction":"看跌","reason":"需求偏弱","confidence":0.7}\n```'
    data, errors = parse_llm_json(raw)
    assert errors == []
    assert data["product"] == "沪铜"
    assert data["direction"] == "看跌"


def test_json_parse_trailing_comma():
    raw = '{"product":"豆粕","direction":"中性","reason":"震荡",}'
    data, errors = parse_llm_json(raw)
    # 尾部逗号应被修复
    assert data["product"] == "豆粕"


def test_json_parse_extra_text():
    raw = '分析结果如下：\n{"product":"铁矿石","direction":"看涨","reason":"供应偏紧","confidence":0.9}\n以上供参考。'
    data, errors = parse_llm_json(raw)
    assert errors == []
    assert data["product"] == "铁矿石"


def test_json_parse_single_quotes():
    raw = "{'product':'原油','direction':'看涨','reason':'供应偏紧','confidence':0.8}"
    data, errors = parse_llm_json(raw)
    assert data["product"] == "原油"
    assert data["direction"] == "看涨"


def test_json_parse_invalid_direction():
    raw = '{"product":"黄金","direction":"暴涨","reason":"避险","confidence":0.9}'
    data, errors = parse_llm_json(raw)
    assert data["direction"] is None
    assert len(errors) > 0


def test_json_parse_missing_fields():
    raw = '{"product":"螺纹钢"}'
    data, errors = parse_llm_json(raw)
    assert data["product"] == "螺纹钢"
    assert data["direction"] is None
    assert len(errors) >= 2


def test_json_parse_confidence_range():
    raw = '{"product":"焦煤","direction":"看跌","reason":"","confidence":1.5}'
    data, errors = parse_llm_json(raw)
    assert data["confidence"] == 1.0


def test_json_parse_confidence_negative():
    raw = '{"product":"焦煤","direction":"看跌","reason":"","confidence":-0.3}'
    data, errors = parse_llm_json(raw)
    assert data["confidence"] == 0.0


def test_json_parse_garbage():
    raw = "这不是有效的 JSON 输出"
    data, errors = parse_llm_json(raw)
    assert len(errors) > 0
    assert data["product"] is None


# ---- Full pipeline (mock LLM) ----

_MOCK_LLM_RESPONSE = (
    '{"product":"螺纹钢","direction":"看涨",'
    '"reason":"库存下降，需求改善","confidence":0.85}'
)


def test_full_infer_high_conf(session_factory):
    """Mock LLM 返回高置信 JSON → 入库。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "螺纹钢价格上涨，短期偏强。", title="螺纹钢日报")
    session.close()

    config = LLMConfig(api_key="sk-test", base_url="https://test.api",
                       model="test-model", timeout_seconds=5)

    session2 = session_factory()
    with patch("pn07.llm_client.LLMAPIClient.chat", return_value=_MOCK_LLM_RESPONSE):
        result = infer_article(aid, session2, config=config)
    session2.commit()

    assert result.product == "螺纹钢"
    assert result.direction == "看涨"
    assert result.confidence == 0.85
    assert result.need_manual_review is False
    assert result.model == "test-model"

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    assert article.analysis_result.analysis_method == "llm"
    session2.close()


def test_full_infer_multi_results(session_factory):
    """Mock LLM 返回多品种 JSON → 多条结果入库。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "原油偏强，沪铜偏弱。", title="多品种日报")
    session.close()

    response = (
        '{"results":['
        '{"product":"原油","contract":"","direction":"看涨","reason":"供应风险升温","confidence":0.82},'
        '{"product":"沪铜","contract":"","direction":"看跌","reason":"需求承压","confidence":0.61}'
        ']}'
    )
    config = LLMConfig(api_key="sk-test", base_url="https://test.api",
                       model="test-model", timeout_seconds=5)

    session2 = session_factory()
    with patch("pn07.llm_client.LLMAPIClient.chat", return_value=response):
        result = infer_article(aid, session2, config=config)
    session2.commit()

    assert len(result.results) == 2
    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    assert {item.product for item in article.analysis_results} == {"原油", "沪铜"}
    assert all(item.model_name == "test-model" for item in article.analysis_results)
    session2.close()


def test_full_infer_low_conf(session_factory):
    """confidence < 0.5 → need_manual_review=True。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "市场可能震荡。")
    session.close()

    low_conf_response = (
        '{"product":"豆粕","direction":"中性",'
        '"reason":"方向不明确","confidence":0.35}'
    )
    config = LLMConfig(api_key="sk-test", base_url="https://test.api",
                       model="test", timeout_seconds=5)

    session2 = session_factory()
    with patch("pn07.llm_client.LLMAPIClient.chat", return_value=low_conf_response):
        result = infer_article(aid, session2, config=config)
    session2.commit()

    assert result.confidence == 0.35
    assert result.need_manual_review is True

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.analysis_result.need_manual_review is True
    session2.close()


def test_full_infer_empty_results_marks_no_market_view(session_factory):
    """LLM 返回空 results → 记录无可分析观点，而不是误报 JSON 不可解析。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "晨报 日报 农产品 能源化工 交易策略 尿素日报", title="目录页")
    session.close()

    config = LLMConfig(api_key="sk-test", base_url="https://test.api",
                       model="test", timeout_seconds=5)

    session2 = session_factory()
    with patch("pn07.llm_client.LLMAPIClient.chat", return_value='{"results":[]}'):
        result = infer_article(aid, session2, config=config)
    session2.commit()

    assert result.product == "未知"
    assert result.direction == "中性"
    assert result.need_manual_review is True

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.STORED.value
    assert "未识别到可分析的期货观点" in article.analysis_result.reason
    assert article.analysis_result.llm_error_msg == "LLM 返回 results 为空"
    session2.close()


def test_full_infer_llm_failure(session_factory):
    """LLM 全部失败 → mark_failed。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "螺纹钢分析。")
    session.close()

    config = LLMConfig(api_key="sk-test", base_url="https://test.api",
                       model="test", timeout_seconds=1, max_retries=1)

    session2 = session_factory()
    with patch("pn07.llm_client.LLMAPIClient.chat", side_effect=RuntimeError("API down")):
        result = infer_article(aid, session2, config=config)
    session2.commit()

    assert result.ok is False
    assert "API down" in result.error_msg

    repo = ArticleRepository(session2)
    article = repo.get_article_detail(aid)
    assert article.status == ArticleProcessingStatus.FAILED.value
    session2.close()


def test_full_infer_empty_clean(session_factory):
    """空文本 → mark_failed。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "")
    session.close()

    session2 = session_factory()
    with pytest.raises(ValueError):
        infer_article(aid, session2)
    session2.commit()

    repo = ArticleRepository(session2)
    assert repo.require_article(aid).status == ArticleProcessingStatus.FAILED.value
    session2.close()


def test_full_infer_task_log(session_factory):
    """验证 task_log 含模型信息。"""
    from pn07.llm_infer import infer_article

    session = session_factory()
    aid = _create_article(session, "螺纹钢看涨。", title="日报")
    session.close()

    config = LLMConfig(api_key="sk", base_url="https://x", model="gpt-test", timeout_seconds=5)
    session2 = session_factory()

    with patch("pn07.llm_client.LLMAPIClient.chat", return_value=_MOCK_LLM_RESPONSE):
        infer_article(aid, session2, config=config)
    session2.commit()

    logs = session2.query(TaskLog).filter(
        TaskLog.article_id == aid,
        TaskLog.stage == "llm_infer",
    ).all()
    assert len(logs) == 1
    assert "gpt-test" in logs[0].message
    session2.close()


# ---- LLMConfig ----

def test_llm_config_is_configured():
    assert LLMConfig().is_configured is False
    assert LLMConfig(api_key="k", base_url="u").is_configured is True
    assert LLMConfig(provider="wenhua", base_url="https://example.test/api").is_configured is True


def test_wenhua_sse_line_parser():
    line = 'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}'
    content, stopped = LLMAPIClient._parse_wenhua_sse_line(line)
    assert content == "你好"
    assert stopped is False

    content, stopped = LLMAPIClient._parse_wenhua_sse_line(
        '{"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}'
    )
    assert content == ""
    assert stopped is True


def test_wenhua_chat_stream(monkeypatch):
    class FakeResponse:
        status_code = 200

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"{\\"product\\":\\"螺纹钢\\""},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":",\\"direction\\":\\"看涨\\",\\"reason\\":\\"需求改善\\",\\"confidence\\":0.8}"},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}',
                ]
            )

    class FakeStream:
        def __enter__(self):
            return FakeResponse()

        def __exit__(self, exc_type, exc, tb):
            return False

    captured = {}

    def fake_stream(method, url, json, headers, timeout):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = json
        return FakeStream()

    monkeypatch.setattr("httpx.stream", fake_stream)

    client = LLMAPIClient(
        LLMConfig(
            provider="wenhua",
            base_url="https://swarm.wenhua.com.cn/aiservice/api/ShiXi/GetContent",
            timeout_seconds=5,
        )
    )
    response = client.chat([{"role": "user", "content": "请输出 JSON"}], retries=0)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/GetContent")
    assert captured["json"]["content"] == "user:\n请输出 JSON"
    assert '"product":"螺纹钢"' in response
    assert '"direction":"看涨"' in response


# ---- InferResult ----

def test_infer_result_summary():
    r = InferResult(product="沪铜", direction="看跌", confidence=0.72, model="gpt-4", retry_count=1)
    assert "沪铜" in r.summary()
    assert "0.72" in r.summary()

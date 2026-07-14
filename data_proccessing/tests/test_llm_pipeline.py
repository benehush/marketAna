from pathlib import Path

import httpx
import pytest

from data_proccessing.instrument_mapping.runtime import RuntimeLexicon
from data_proccessing.llm.client import HttpLLMClient, LLMRequestError
from data_proccessing.llm.parser import parse_llm_response
from data_proccessing.models import Document
from data_proccessing.pipeline.processor import process_document


def _lexicon() -> RuntimeLexicon:
    return RuntimeLexicon(
        [{"product_key": "SHFE.RB", "canonical": "螺纹钢", "aliases": ["螺纹钢"], "negative_contexts": []}]
    )


def test_llm_parser_accepts_wrapped_json() -> None:
    outputs, errors = parse_llm_response(
        '分析如下：```json\n{"product":"螺纹钢","direction":"看涨","reason":"库存下降","confidence":0.8}\n```',
        expected_product_key="SHFE.RB",
    )
    assert errors == []
    assert outputs[0].direction == "看涨"
    assert outputs[0].confidence == 0.8


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        ("not json", "invalid_json"),
        ('{"product":"不存在","direction":"中性","reason":"x","confidence":0.5}', "product_mismatch"),
        ('{"product":"螺纹钢","direction":"bullish","reason":"x","confidence":0.5}', "invalid_direction"),
        ('{"product":"螺纹钢","direction":"中性","reason":"","confidence":0.5}', "empty_reason"),
        ('{"product":"螺纹钢","direction":"中性","reason":"x","confidence":"NaN"}', "invalid_confidence"),
        ('{"product":"螺纹钢","direction":"中性","reason":"x","confidence":1.2}', "invalid_confidence"),
    ],
)
def test_llm_parser_returns_typed_strict_errors(raw: str, expected_error: str) -> None:
    outputs, errors = parse_llm_response(raw, expected_product_key="SHFE.RB")
    assert outputs == []
    assert errors[0].error_type == expected_error


@pytest.mark.parametrize(
    "raw",
    [
        '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8}',
        '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":[]}',
        '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":["E1","E1"]}',
        '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":["E9"]}',
    ],
)
def test_llm_parser_requires_known_unique_evidence_ids(raw: str) -> None:
    outputs, errors = parse_llm_response(
        raw,
        expected_product_key="SHFE.RB",
        expected_evidence_ids=frozenset({"E1", "E2"}),
    )

    assert outputs == []
    assert errors[0].error_type == "invalid_evidence"


def test_pipeline_skip_llm_emits_review_queue() -> None:
    result = process_document(Document("doc-1", "螺纹钢上涨后回落，库存增加，短期震荡"), _lexicon(), skip_llm=True)
    assert result.review_queue or result.analyses
    assert result.processing_stats["signal_count"] > 0


def test_no_signal_review_keeps_owned_section_as_evidence() -> None:
    lexicon = RuntimeLexicon(
        [{"product_key": "SHFE.AL", "canonical": "沪铝", "aliases": ["铝"], "negative_contexts": []}]
    )
    result = process_document(Document("doc-no-signal", "【铝】铝市场等待后续政策指引。"), lexicon, skip_llm=True)
    review = next(item for item in result.review_queue if item.get("product_key") == "SHFE.AL")

    assert review["reason"] == "no_signal"
    assert review["evidence"]["excerpts"][0]["quote"] == "铝市场等待后续政策指引。"


def test_related_product_review_is_labeled_and_keeps_mention() -> None:
    lexicon = RuntimeLexicon(
        [
            {"product_key": "DCE.EG", "canonical": "乙二醇", "aliases": ["乙二醇"], "negative_contexts": []},
            {"product_key": "CZCE.PR", "canonical": "瓶片", "aliases": ["瓶片"], "negative_contexts": []},
        ]
    )
    text = "【乙二醇】乙二醇供应下降，关注瓶片能否增加开工支撑，乙二醇短期震荡。"

    result = process_document(Document("doc-related", text), lexicon, skip_llm=True)
    review = next(item for item in result.review_queue if item.get("product_key") == "CZCE.PR")

    assert review["reason"] == "related_product_mention_only"
    assert "瓶片" in review["evidence"]["excerpts"][0]["quote"]
    assert all(item.product_key != "CZCE.PR" for item in result.analyses)


def test_pipeline_uses_injected_llm_client() -> None:
    class FakeClient:
        def complete(self, messages):
            assert len(messages) == 2
            assert len(messages[1]["content"]) < 1500
            return '{"product":"螺纹钢","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}'

    result = process_document(
        Document("doc-1", "螺纹钢上涨后回落，库存增加，短期震荡。"),
        _lexicon(),
        llm_client=FakeClient(),
    )
    assert result.analyses
    assert result.analyses[0].method == "llm"
    assert result.analyses[0].direction == "看跌"


def test_pipeline_corrects_invalid_output_once() -> None:
    class FakeClient:
        responses = iter(
            [
                '{"product_key":"SHFE.RB","direction":"震荡偏弱","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}',
                '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}',
            ]
        )

        def complete(self, messages):
            if len(messages) == 4:
                assert "product_key 必须为 SHFE.RB" in messages[-1]["content"]
            return next(self.responses)

    result = process_document(
        Document("doc-recovered", "螺纹钢上涨后回落，库存增加，短期震荡。"),
        _lexicon(),
        llm_client=FakeClient(),
    )

    assert next(item for item in result.analyses if item.method == "llm").direction == "看跌"
    assert result.errors == ()
    assert result.processing_stats["llm_recovered_count"] == 1
    assert result.processing_stats["llm_retry_count"] == 1


def test_pipeline_corrects_missing_evidence_ids_once() -> None:
    class FakeClient:
        responses = iter(
            [
                '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8}',
                '{"product_key":"SHFE.RB","direction":"看跌","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}',
            ]
        )

        def complete(self, messages):
            if len(messages) == 4:
                assert "evidence_ids 只能从" in messages[-1]["content"]
            return next(self.responses)

    result = process_document(
        Document("doc-evidence-recovered", "螺纹钢上涨后回落，库存增加，短期震荡。"),
        _lexicon(),
        llm_client=FakeClient(),
    )

    llm = next(item for item in result.analyses if item.method == "llm")
    assert llm.evidence_excerpts
    assert result.processing_stats["llm_recovered_count"] == 1


def test_pipeline_persists_diagnostic_after_failed_correction() -> None:
    class FakeClient:
        responses = iter(
            [
                '{"product_key":"SHFE.RB","direction":"震荡偏弱","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}',
                '{"product_key":"SHFE.RB","direction":"偏空","reason":"库存增加","confidence":0.8,"evidence_ids":["E1"]}',
            ]
        )

        def complete(self, _messages):
            return next(self.responses)

    result = process_document(
        Document("doc-failed", "螺纹钢上涨后回落，库存增加，短期震荡。"),
        _lexicon(),
        llm_client=FakeClient(),
    )
    review = next(item for item in result.review_queue if item.get("reason") == "llm_error_or_invalid_output")
    diagnostic = review["evidence"]["diagnostic"]

    assert diagnostic["error_type"] == "invalid_direction"
    assert diagnostic["correction_retry_count"] == 1
    assert diagnostic["retry_exhausted"] is True
    assert [item["phase"] for item in diagnostic["parse_errors"]] == ["initial", "correction"]
    assert len(result.errors) == 1
    assert result.processing_stats["llm_error_by_type"] == {"invalid_direction": 1}
    assert review["evidence"]["kind"] == "candidate_context"
    assert review["evidence"]["excerpts"]
    assert review["evidence"]["excerpts"][0]["validated"] is False


def test_conflicting_product_scoped_signals_fall_back_to_llm() -> None:
    lexicon = RuntimeLexicon(
        [
            {"product_key": "CZCE.MA", "canonical": "甲醇", "aliases": ["甲醇"], "negative_contexts": []},
            {"product_key": "DCE.PP", "canonical": "PP", "aliases": ["PP"], "negative_contexts": []},
        ]
    )
    text = "【甲醇】甲醇价格下跌，09合约偏空。【PP】PP价格上涨后回落，库存增加，价格预计震荡修复。"

    class FakeClient:
        def complete(self, messages):
            prompt = messages[1]["content"]
            assert "PP价格上涨后回落，库存增加，价格预计震荡修复。" in prompt
            assert "甲醇供应压力凸显" not in prompt
            return '{"product":"PP","direction":"中性","reason":"价格预计震荡修复。","confidence":0.8,"evidence_ids":["E1"]}'

    result = process_document(Document("doc-2", text), lexicon, llm_client=FakeClient())
    pp = next(item for item in result.analyses if item.product_key == "DCE.PP")

    assert pp.method == "llm"
    assert pp.direction == "中性"
    assert pp.need_manual_review is False
    assert pp.processing_stats["fallback_reason"] == "rule_uncertain"
    assert result.processing_stats["llm_count"] == 1


def test_foreign_heading_signal_is_not_preserved_when_llm_is_unavailable() -> None:
    lexicon = RuntimeLexicon(
        [
            {"product_key": "CZCE.MA", "canonical": "甲醇", "aliases": ["甲醇"], "negative_contexts": []},
            {"product_key": "DCE.PP", "canonical": "PP", "aliases": ["PP"], "negative_contexts": []},
        ]
    )
    text = "【甲醇】甲醇供应压力凸显，价格下跌，09合约偏空。【PP】PP下游需求一般，等待后续指引。"

    result = process_document(Document("doc-3", text), lexicon, skip_llm=True)

    assert all(item.product_key != "DCE.PP" for item in result.analyses)
    assert any(item.get("product_key") == "DCE.PP" for item in result.review_queue)


def test_wenhua_http_client_parses_sse(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def iter_lines(self):
            return iter(
                [
                    'data: {"choices":[{"delta":{"content":"{\\"product\\":\\"PP\\","},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":"\\"direction\\":\\"中性\\"}"},"finish_reason":null}]}',
                    'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}',
                ]
            )

    def fake_stream(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr("data_proccessing.llm.client.httpx.stream", fake_stream)
    client = HttpLLMClient(
        api_key="secret",
        base_url="https://example.test/GetContent",
        model="wenhua-shixi",
        provider="wenhua",
    )

    result = client.complete([{"role": "user", "content": "判断 PP"}])

    assert result.content == '{"product":"PP","direction":"中性"}'
    assert result.sse_line_count == 3
    assert captured["url"].endswith("/GetContent")
    assert captured["json"] == {"input": "user:\n判断 PP", "content": "user:\n判断 PP"}


def test_openai_client_retries_timeout_and_5xx(monkeypatch) -> None:
    calls = []
    sleeps = []

    class FakeResponse:
        headers = {"content-type": "application/json"}
        text = "temporary"

        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.payload = payload

        def json(self):
            return self.payload

    responses = iter(
        [
            httpx.ReadTimeout("slow"),
            FakeResponse(503),
            FakeResponse(200, {"choices": [{"message": {"content": "{}"}}]}),
        ]
    )

    def fake_post(*_args, **_kwargs):
        calls.append(1)
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr("data_proccessing.llm.client.httpx.post", fake_post)
    monkeypatch.setattr("data_proccessing.llm.client.time.sleep", sleeps.append)
    client = HttpLLMClient(api_key="secret", base_url="https://example.test", model="m", max_retries=2)

    result = client.complete([{"role": "user", "content": "test"}])

    assert result.attempt_count == 3
    assert result.transport_retry_count == 2
    assert len(calls) == 3
    assert sleeps == [1, 2]


def test_wenhua_empty_sse_has_sanitized_diagnostic(monkeypatch) -> None:
    class FakeResponse:
        status_code = 200
        headers = {"content-type": "text/event-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def iter_lines(self):
            return iter(['data: {"token":"secret","status":"waiting"}', "data: [DONE]"])

    monkeypatch.setattr("data_proccessing.llm.client.httpx.stream", lambda *_args, **_kwargs: FakeResponse())
    client = HttpLLMClient(
        api_key="secret", base_url="https://example.test", model="m", provider="wenhua", max_retries=0
    )

    with pytest.raises(LLMRequestError) as caught:
        client.complete([{"role": "user", "content": "test"}])

    diagnostic = caught.value.to_diagnostic()
    assert diagnostic["error_type"] == "empty_sse_response"
    assert diagnostic["sse_line_count"] == 2
    assert diagnostic["done_received"] is True
    assert "secret" not in "".join(diagnostic["sse_event_samples"])
    assert "[REDACTED]" in "".join(diagnostic["sse_event_samples"])

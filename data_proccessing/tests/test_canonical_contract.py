from data_proccessing.instrument_mapping.runtime import LexiconMatch
from data_proccessing.models import AnalysisResult, DirectionSignal, Document, EvidenceExcerpt
from data_proccessing.pipeline.canonical import build_evidence_candidates, to_canonical_result
from data_proccessing.pipeline.processor import DocumentProcessingResult


def _match(text: str, alias: str, product_key: str, display_name: str, *, occurrence: int = 0) -> LexiconMatch:
    start = -1
    offset = 0
    for _ in range(occurrence + 1):
        start = text.index(alias, offset)
        offset = start + len(alias)
    return LexiconMatch(product_key, display_name, alias, start, start + len(alias), "test", "body_alias")


def _signal(text: str, phrase: str, product_key: str, direction: str, *, occurrence: int = 0) -> DirectionSignal:
    start = -1
    offset = 0
    for _ in range(occurrence + 1):
        start = text.index(phrase, offset)
        offset = start + len(phrase)
    return DirectionSignal(
        signal_id=f"{product_key}-{start}",
        product_key=product_key,
        raw_alias=product_key,
        direction=direction,  # type: ignore[arg-type]
        signal_type="direction_word",
        phrase=phrase,
        value=None,
        confidence=1.0,
        start=start,
        end=start + len(phrase),
        evidence_text=text,
    )


def test_canonical_reason_and_evidence_are_complete_and_product_scoped() -> None:
    text = (
        "【PX】PX价格上涨，短期偏强。"
        "【PTA】PTA跟随PX成本走强而上升，幅度不及原料。"
        "另外下游开工继续回升，PTA去库将持续。"
        "【乙二醇】乙二醇供应承压，价格下跌。"
    )
    matches = (
        _match(text, "PX", "CZCE.PX", "PX", occurrence=0),
        _match(text, "PTA", "CZCE.TA", "PTA", occurrence=0),
        _match(text, "PX", "CZCE.PX", "PX", occurrence=2),
        _match(text, "乙二醇", "DCE.EG", "乙二醇", occurrence=0),
    )
    signals = (
        # This cross-section signal must not become PTA evidence.
        _signal(text, "上涨", "CZCE.TA", "看涨"),
        _signal(text, "上升", "CZCE.TA", "看涨"),
        _signal(text, "回升", "CZCE.TA", "看涨"),
    )
    analysis = AnalysisResult(
        source_id="doc-1",
        product_key="CZCE.TA",
        product="PTA",
        direction="看涨",
        reason="旧的截断理由",
        confidence=0.9,
        method="rule",
    )
    result = DocumentProcessingResult(Document("doc-1", text), matches, signals, (analysis,))

    payload = to_canonical_result(result)
    item = payload["results"][0]

    assert item["reason"] == "PTA跟随PX成本走强而上升，幅度不及原料。 另外下游开工继续回升，PTA去库将持续。"
    assert item["need_manual_review"] is False
    assert all(excerpt["quote"].endswith("。") for excerpt in item["evidence"]["excerpts"])
    assert all("乙二醇" not in excerpt["quote"] for excerpt in item["evidence"]["excerpts"])
    assert all("PX价格上涨" not in excerpt["quote"] for excerpt in item["evidence"]["excerpts"])
    assert all(
        text[excerpt["start_char"]:excerpt["end_char"]] == excerpt["raw_quote"]
        for excerpt in item["evidence"]["excerpts"]
    )


def test_canonical_marks_result_for_review_without_complete_scoped_evidence() -> None:
    text = "【甲醇】甲醇价格偏空。【PP】PP下游需求一般，短期震荡"
    matches = (
        _match(text, "甲醇", "CZCE.MA", "甲醇"),
        _match(text, "PP", "DCE.PP", "PP"),
    )
    signals = (_signal(text, "偏空", "DCE.PP", "看跌"),)
    analysis = AnalysisResult(
        source_id="doc-2",
        product_key="DCE.PP",
        product="PP",
        direction="看跌",
        reason="甲醇价格偏空",
        confidence=0.8,
        method="rule",
    )
    result = DocumentProcessingResult(Document("doc-2", text), matches, signals, (analysis,))

    item = to_canonical_result(result)["results"][0]

    assert item["reason"] == ""
    assert item["evidence"]["excerpts"] == []
    assert item["need_manual_review"] is True


def test_canonical_rejects_unexplained_other_product_in_same_section() -> None:
    text = "【PTA】PTA库存下降，乙二醇价格上涨。【乙二醇】乙二醇短期震荡。"
    matches = (
        _match(text, "PTA", "CZCE.TA", "PTA"),
        _match(text, "乙二醇", "DCE.EG", "乙二醇", occurrence=0),
        _match(text, "乙二醇", "DCE.EG", "乙二醇", occurrence=1),
    )
    signals = (_signal(text, "上涨", "CZCE.TA", "看涨"),)
    analysis = AnalysisResult(
        source_id="doc-3",
        product_key="CZCE.TA",
        product="PTA",
        direction="看涨",
        reason="乙二醇价格上涨",
        confidence=0.8,
        method="rule",
    )
    result = DocumentProcessingResult(Document("doc-3", text), matches, signals, (analysis,))

    item = to_canonical_result(result)["results"][0]

    assert item["evidence"]["excerpts"] == []
    assert item["need_manual_review"] is True


def test_canonical_accepts_explicit_cross_product_causal_evidence() -> None:
    text = "【铝】铝基本面整体平淡，当前主要矛盾是宏观偏弱和铜价下跌，短期偏空。"
    matches = (
        _match(text, "铝", "SHFE.AL", "沪铝"),
        _match(text, "铜", "SHFE.CU", "沪铜"),
    )
    signals = (_signal(text, "偏空", "SHFE.AL", "看跌"),)
    analysis = AnalysisResult(
        source_id="doc-cross-product",
        product_key="SHFE.AL",
        product="沪铝",
        direction="看跌",
        reason="短期偏空",
        confidence=0.8,
        method="rule",
    )
    result = DocumentProcessingResult(Document("doc-cross-product", text), matches, signals, (analysis,))

    item = to_canonical_result(result)["results"][0]

    assert item["evidence"]["excerpts"][0]["quote"].endswith("短期偏空。")
    assert item["need_manual_review"] is False


def test_candidates_exclude_other_product_only_sentence() -> None:
    text = "【玉米】玉米目前疲软。玉米淀粉消费较差，开机趋下滑。玉米预期很难有提振。"
    matches = (
        _match(text, "玉米", "DCE.C", "玉米", occurrence=0),
        _match(text, "玉米", "DCE.C", "玉米", occurrence=1),
        _match(text, "玉米淀粉", "DCE.CS", "玉米淀粉"),
        _match(text, "玉米", "DCE.C", "玉米", occurrence=3),
    )

    candidates = build_evidence_candidates(product_key="DCE.C", raw_text=text, matches=matches)

    assert any("玉米目前疲软" in item.quote for item in candidates)
    assert any("很难有提振" in item.quote for item in candidates)
    assert all("玉米淀粉消费较差" not in item.quote for item in candidates)


def test_shared_heading_target_clause_is_valid_rule_evidence() -> None:
    text = "【硅锰/硅铁】周一，硅锰现货价格持平，硅铁现货价格小幅回落。"
    matches = (
        _match(text, "硅锰", "CZCE.SM", "锰硅", occurrence=0),
        _match(text, "硅铁", "CZCE.SF", "硅铁", occurrence=0),
        _match(text, "硅锰", "CZCE.SM", "锰硅", occurrence=1),
        _match(text, "硅铁", "CZCE.SF", "硅铁", occurrence=1),
    )
    signal = _signal(text, "回落", "CZCE.SF", "看跌")
    analysis = AnalysisResult(
        source_id="doc-shared",
        product_key="CZCE.SF",
        product="硅铁",
        direction="看跌",
        reason="旧理由",
        confidence=0.8,
        method="rule",
    )

    item = to_canonical_result(
        DocumentProcessingResult(Document("doc-shared", text), matches, (signal,), (analysis,))
    )["results"][0]

    assert item["need_manual_review"] is False
    assert "硅铁现货价格小幅回落" in item["evidence"]["excerpts"][0]["quote"]


def test_canonical_llm_preserves_reason_and_prevalidated_neutral_evidence() -> None:
    text = "【锡】综合来看，锡价上涨更多是情绪推动，实际影响预计有限。"
    match = _match(text, "锡", "SHFE.SN", "沪锡")
    start = text.index("综合来看")
    end = len(text)
    excerpt = EvidenceExcerpt(
        quote=text[start:end],
        raw_quote=text[start:end],
        source="raw_text",
        start_char=start,
        end_char=end,
        match_type="llm_selected",
    )
    analysis = AnalysisResult(
        source_id="doc-tin",
        product_key="SHFE.SN",
        product="沪锡",
        direction="中性",
        reason="情绪利多与实际影响有限并存，方向中性。",
        confidence=0.6,
        method="llm",
        evidence_excerpts=(excerpt,),
    )

    item = to_canonical_result(
        DocumentProcessingResult(Document("doc-tin", text), (match,), (), (analysis,))
    )["results"][0]

    assert item["reason"] == analysis.reason
    assert item["need_manual_review"] is False
    assert item["evidence"]["excerpts"][0]["raw_quote"] == text[start:end]
    assert text[item["evidence"]["excerpts"][0]["start_char"]:item["evidence"]["excerpts"][0]["end_char"]] == text[start:end]


def test_canonical_preserves_structured_review_diagnostic() -> None:
    diagnostic = {
        "error_type": "invalid_json",
        "message": "JSON 格式无效",
        "parse_errors": [],
        "raw_response_excerpt": "{bad",
        "provider": "wenhua",
        "attempt_count": 2,
        "transport_retry_count": 0,
        "correction_retry_count": 1,
        "retry_exhausted": True,
    }
    result = DocumentProcessingResult(
        Document("doc-diagnostic", "螺纹钢短期震荡。"),
        (),
        (),
        (),
        ({"reason": "llm_error_or_invalid_output", "evidence": {"excerpts": [], "diagnostic": diagnostic}},),
        ({"product_key": "SHFE.RB", "diagnostic": diagnostic},),
    )

    payload = to_canonical_result(result)

    assert payload["review_queue"][0]["evidence"]["diagnostic"] == diagnostic
    assert payload["processing_stats"]["error_count"] == 1

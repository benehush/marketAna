from data_proccessing.instrument_mapping.runtime import RuntimeLexicon
from data_proccessing.signals.arbitrator import arbitrate
from data_proccessing.signals.aggregator import aggregate_signals
from data_proccessing.signals.extractor import extract_signals


def _signals(text: str):
    lexicon = RuntimeLexicon(
        [{"product_key": "SHFE.RB", "canonical": "螺纹钢", "aliases": ["螺纹钢"], "negative_contexts": []}]
    )
    matches = lexicon.find_matches(text)
    return extract_signals(text, matches)


def test_domain_signal_wins_over_nested_generic_word() -> None:
    signals = _signals("螺纹钢库存下降，需求改善，短期偏强")
    phrases = {signal.phrase for signal in signals}
    assert "库存下降" in phrases
    assert "需求改善" in phrases
    assert "下降" not in phrases


def test_conflict_is_sent_to_llm_fallback() -> None:
    signals = _signals("螺纹钢上涨后快速回落，库存增加，短期震荡")
    result = arbitrate("SHFE.RB", aggregate_signals(signals)["SHFE.RB"])
    assert result.decision in {"llm_fallback", "rule_accept"}
    assert result.signals
    assert result.bullish_score > 0
    assert result.bearish_score > 0


def test_historical_signal_is_discounted() -> None:
    signals = _signals("螺纹钢昨日上涨，但今日库存增加")
    historical = [signal for signal in signals if "历史" in signal.context_flags or "historical" in signal.context_flags]
    assert historical


def test_heading_section_captures_direction_beyond_fixed_window() -> None:
    lexicon = RuntimeLexicon(
        [{"product_key": "SHFE.AL", "canonical": "沪铝", "aliases": ["铝"], "negative_contexts": []}]
    )
    text = "【铝】" + "铝基本面整体平淡，产量处于高位，需求端没有爆发增长可能。" * 3 + "短期偏空。"

    signals = extract_signals(text, lexicon.find_matches(text), context_window=20)

    assert any(signal.product_key == "SHFE.AL" and signal.phrase == "偏空" for signal in signals)


def test_related_product_does_not_borrow_owner_section_signals() -> None:
    lexicon = RuntimeLexicon(
        [
            {"product_key": "DCE.EG", "canonical": "乙二醇", "aliases": ["乙二醇"], "negative_contexts": []},
            {"product_key": "CZCE.PR", "canonical": "瓶片", "aliases": ["瓶片"], "negative_contexts": []},
        ]
    )
    text = "【乙二醇】乙二醇供应下降，关注瓶片能否增加开工支撑，乙二醇短期震荡。"

    signals = extract_signals(text, lexicon.find_matches(text))

    assert any(signal.product_key == "DCE.EG" for signal in signals)
    assert all(signal.product_key != "CZCE.PR" for signal in signals)


def test_shared_heading_assigns_each_signal_to_its_nearest_product_clause() -> None:
    lexicon = RuntimeLexicon(
        [
            {"product_key": "CZCE.SM", "canonical": "锰硅", "aliases": ["硅锰"], "negative_contexts": []},
            {"product_key": "CZCE.SF", "canonical": "硅铁", "aliases": ["硅铁"], "negative_contexts": []},
        ]
    )
    text = "【硅锰/硅铁】周一，硅锰现货价格持平，硅铁现货价格小幅回落。"

    signals = extract_signals(text, lexicon.find_matches(text))

    assert any(item.product_key == "CZCE.SM" and item.phrase == "持平" for item in signals)
    assert any(item.product_key == "CZCE.SF" and item.phrase == "回落" for item in signals)
    assert all(not (item.product_key == "CZCE.SM" and item.phrase == "回落") for item in signals)
    assert all(not (item.product_key == "CZCE.SF" and item.phrase == "持平") for item in signals)

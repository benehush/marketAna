from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_proccessing.instrument_mapping import BuildConfig, Document, build_instrument_lexicon
from data_proccessing.instrument_mapping.builder import _candidate_status, _score_candidate, write_build_artifacts
from data_proccessing.instrument_mapping.models import CandidateEvidence
from data_proccessing.instrument_mapping.seed_catalog import normalize_alias


def _candidate(result, raw_alias: str):
    normalized = normalize_alias(raw_alias)
    return next(
        item
        for item in result.candidates
        if item.normalized_alias == normalized or item.raw_alias.casefold() == raw_alias.casefold()
    )


def _entry(result, product_key: str):
    return next(item for item in result.lexicon if item.product_key == product_key)


def test_contract_bracket_and_label_patterns_are_mapped() -> None:
    text = (
        "RB2505合约震荡上行，螺纹钢库存下降。\n"
        "PTA05 合约跟随PX反弹。\n"
        "【铁矿石】港口库存小幅回升。\n"
        "商品：碳酸锂 现货价格偏弱。"
    )
    result = build_instrument_lexicon([Document(source_id="doc-1", raw_text=text)])

    assert _candidate(result, "RB").suggested_product_key == "SHFE.RB"
    assert _candidate(result, "RB").status in {"approved_seed", "auto_approved"}
    assert _candidate(result, "PTA").suggested_product_key == "CZCE.TA"
    assert _candidate(result, "铁矿石").suggested_product_key == "DCE.I"
    assert _candidate(result, "碳酸锂").suggested_product_key == "GFEX.LC"

    rb_entry = _entry(result, "SHFE.RB")
    assert "RB" in rb_entry.aliases
    assert rb_entry.contract_patterns


def test_negative_contexts_do_not_pollute_domestic_aliases() -> None:
    text = (
        "邮箱：liub@qh168.com.cn，投资咨询证号：Z0019876。\n"
        "COMEX黄金回落，LME铜走强，美豆油受政策扰动。\n"
        "国内市场今日震荡。"
    )
    result = build_instrument_lexicon([Document(source_id="doc-1", raw_text=text)])
    approved_aliases = {
        candidate.raw_alias
        for candidate in result.candidates
        if candidate.status in {"approved_seed", "auto_approved"}
    }

    assert "qh168" not in approved_aliases
    assert "Z0019876" not in approved_aliases
    assert "黄金" not in approved_aliases
    assert "铜" not in approved_aliases
    assert "豆油" not in approved_aliases


def test_dynamic_aliases_and_ocr_variants_are_discovered() -> None:
    text = (
        "【欧集线】运价预期偏强，供给扰动增加。\n"
        "【L日报20250401】聚乙烯日报。\n"
        "【硅锰/硅铁】铁合金价格震荡。\n"
        "L 2505 合约下跌，聚乙烯库存偏高，PE价格承压。\n"
        "LU燃油跟随原油震荡。"
    )
    result = build_instrument_lexicon(
        [Document(source_id="doc-1", raw_text=text, title="L日报20250401")],
        config=BuildConfig(auto_approve_threshold=0.7),
    )

    assert _candidate(result, "欧集线").suggested_product_key == "INE.EC"
    assert _candidate(result, "欧集线").status in {"approved_seed", "auto_approved"}
    assert _candidate(result, "L").suggested_product_key == "DCE.L"
    assert _candidate(result, "聚乙烯").suggested_product_key == "DCE.L"
    assert _candidate(result, "PE").suggested_product_key == "DCE.L"
    assert _candidate(result, "LU燃油").suggested_product_key == "INE.LU"
    assert _candidate(result, "硅锰").suggested_product_key == "CZCE.SM"
    assert _candidate(result, "硅铁").suggested_product_key == "CZCE.SF"


def test_unknown_but_product_like_alias_enters_review_queue() -> None:
    text = "【镍铁】镍铁期货主力合约库存下降，现货价格偏强。"
    result = build_instrument_lexicon(
        [
            Document(source_id="doc-1", raw_text=text),
            Document(source_id="doc-2", raw_text="【镍铁】镍铁期货主力合约震荡，库存回落。"),
        ]
    )
    candidate = _candidate(result, "镍铁")

    assert candidate.status == "review_required"
    assert candidate.suggested_product_key is None
    assert candidate.evidence_snippets


def test_unlinked_candidates_require_clean_shape_futures_context_and_cross_document_repetition() -> None:
    single_document = build_instrument_lexicon(
        [Document(source_id="doc-1", raw_text="【镍铁】镍铁期货主力合约震荡，库存回落。")]
    )
    candidate = _candidate(single_document, "镍铁")

    assert candidate.status == "rejected"

    suffix_only = build_instrument_lexicon(
        [
            Document(source_id="doc-1", raw_text="天风期货研究报告显示市场震荡。"),
            Document(source_id="doc-2", raw_text="天风期货日报关注库存变化。"),
        ]
    )
    suffix_candidate = _candidate(suffix_only, "天风")

    assert suffix_candidate.status == "rejected"
    assert suffix_candidate.evidence_types == ("suffix_pattern",)


def test_institution_and_disclaimer_noise_are_rejected_before_review() -> None:
    result = build_instrument_lexicon(
        [
            Document(source_id="doc-1", raw_text="国信期货订阅号，扫码关注瑞达期货研究院。"),
            Document(source_id="doc-2", raw_text="本报告版权为五矿期货，未经宝城期货许可不得转载。"),
        ]
    )

    for alias in ("国信", "扫码关注瑞达", "本报告版权为五矿", "未经宝城"):
        candidate = _candidate(result, alias)
        assert candidate.status == "rejected"
        assert "institution_or_disclaimer" in candidate.negative_reasons


def test_generic_and_malformed_aliases_are_rejected_before_review() -> None:
    text = (
        "【现货】期货价格震荡。 【盘面】期货价格震荡。 【油脂】期货价格震荡。\n"
        "【粕类】期货价格震荡。 【蛋白粕】期货价格震荡。 【豆菜粕】期货价格震荡。\n"
        "【大豆】期货价格震荡。 【西部】期货价格震荡。\n"
        "[\x04] [\ufffd\ufffd] [120.5E,30.2N] [-2,-1] [2505] [++--]"
    )
    result = build_instrument_lexicon([Document(source_id="doc-1", raw_text=text)])

    for alias in ("现货", "盘面", "油脂", "粕类", "蛋白粕", "豆菜粕", "大豆", "西部"):
        candidate = _candidate(result, alias)
        assert candidate.status == "rejected"
        assert "generic_or_sector_term" in candidate.negative_reasons

    rejected_reasons = {
        reason
        for candidate in result.candidates
        if candidate.status == "rejected"
        for reason in candidate.negative_reasons
    }
    assert {"control_character", "mojibake", "numeric_coordinate_or_range", "punctuation_dominated"} <= rejected_reasons


def test_report_separates_seed_and_auto_approved_alias_counts() -> None:
    result = build_instrument_lexicon([Document(source_id="doc-1", raw_text="RB2505合约震荡。")])

    assert result.report["approved_seed_aliases"] == result.report["status_counts"].get("approved_seed", 0)
    assert result.report["auto_approved_aliases"] == result.report["status_counts"].get("auto_approved", 0)


def test_alias_candidate_jsonl_escapes_control_characters(tmp_path: Path) -> None:
    result = build_instrument_lexicon([Document(source_id="doc-1", raw_text="【\x85坏】期货价格震荡。")])

    write_build_artifacts(result, tmp_path)
    payload = (tmp_path / "alias_candidates.jsonl").read_text(encoding="utf-8")

    assert "\x85" not in payload
    for line in payload.splitlines():
        json.loads(line)


def test_auto_approval_requires_two_evidence_classes_for_linked_aliases() -> None:
    one_class = CandidateEvidence(
        raw_alias="测试别名",
        normalized_alias="测试别名",
        suggested_product_keys={"SHFE.RB"},
        occurrence_count=1,
        document_ids={"doc-1"},
        evidence_types={"catalog_alias", "bracket_heading"},
    )
    two_classes = CandidateEvidence(
        raw_alias="测试别名",
        normalized_alias="测试别名",
        suggested_product_keys={"SHFE.RB"},
        occurrence_count=1,
        document_ids={"doc-1"},
        evidence_types={"catalog_alias", "market_context"},
    )

    assert _candidate_status(
        evidence=one_class,
        normalized_alias=one_class.normalized_alias,
        suggested_key="SHFE.RB",
        seed_alias_keys={},
        score=_score_candidate(one_class),
        config=BuildConfig(),
    ) == "review_required"
    assert _candidate_status(
        evidence=two_classes,
        normalized_alias=two_classes.normalized_alias,
        suggested_key="SHFE.RB",
        seed_alias_keys={},
        score=_score_candidate(two_classes),
        config=BuildConfig(),
    ) == "auto_approved"


def test_dirty_pdf_sample_discovers_core_anchors() -> None:
    sample_path = Path("tests/outputs/01_parsed_raw_text.txt")
    if not sample_path.exists():
        pytest.skip("optional dirty-PDF regression fixture is unavailable")
    sample = sample_path.read_text(encoding="utf-8")
    result = build_instrument_lexicon([Document(source_id="dirty-pdf", raw_text=sample)])
    approved_keys = {
        candidate.suggested_product_key
        for candidate in result.candidates
        if candidate.status in {"approved_seed", "auto_approved"}
    }

    assert {
        "GROUP.CFFEX.INDEX",
        "SHFE.AU",
        "SHFE.AG",
        "GROUP.SHFE.STEEL",
        "DCE.I",
        "INE.SC",
        "CZCE.TA",
        "DCE.EG",
    }.issubset(approved_keys)


def test_ocr_lldpe_sample_aggregates_l_aliases() -> None:
    sample_path = Path("tests/outputs/zs323354/01_parsed_raw_text.txt")
    if not sample_path.exists():
        pytest.skip("optional OCR regression fixture is unavailable")
    sample = sample_path.read_text(encoding="utf-8")
    result = build_instrument_lexicon(
        [Document(source_id="ocr-l", raw_text=sample, title="L日报20250401", file_name="浙商期货_323354_0.html")]
    )
    l_entry = _entry(result, "DCE.L")

    assert "L" in l_entry.aliases
    assert "LLDPE" in l_entry.aliases
    assert "聚乙烯" in l_entry.aliases
    assert "PE" in l_entry.aliases

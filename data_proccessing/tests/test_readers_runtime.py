from pathlib import Path

from data_proccessing.instrument_mapping.runtime import RuntimeLexicon
from data_proccessing.readers.base import read_path


def test_text_reader_preserves_source_and_title(tmp_path: Path) -> None:
    path = tmp_path / "report.txt"
    path.write_bytes("# 螺纹钢日报\n库存下降".encode("utf-8"))
    document = read_path(path)
    assert document.title == "螺纹钢日报"
    assert document.raw_text.endswith("库存下降")
    assert document.file_type == "txt"


def test_runtime_lexicon_matches_alias_and_contract() -> None:
    lexicon = RuntimeLexicon(
        [
            {
                "product_key": "SHFE.RB",
                "canonical": "螺纹钢",
                "aliases": ["螺纹钢", "RB"],
                "negative_contexts": [],
            }
        ]
    )
    matches = lexicon.find_matches("RB2509合约上涨，螺纹钢库存下降")
    assert [item.product_key for item in matches] == ["SHFE.RB", "SHFE.RB"]
    assert matches[0].alias == "RB2509"


def test_runtime_lexicon_rejects_negative_context() -> None:
    lexicon = RuntimeLexicon(
        [
            {
                "product_key": "SHFE.AU",
                "canonical": "黄金",
                "aliases": ["黄金"],
                "negative_contexts": ["COMEX"],
            }
        ]
    )
    assert lexicon.find_matches("COMEX黄金上涨") == []

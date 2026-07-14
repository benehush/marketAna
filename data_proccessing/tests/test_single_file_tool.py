from pathlib import Path

from data_proccessing.test_single_file import run_single_file


def test_single_file_tool_writes_readable_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "report.txt"
    input_path.write_text("螺纹钢库存下降，需求改善，短期偏强。", encoding="utf-8")
    lexicon_path = tmp_path / "lexicon.json"
    lexicon_path.write_text(
        '[{"product_key":"SHFE.RB","canonical":"螺纹钢","aliases":["螺纹钢"],"negative_contexts":[]}]',
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"

    result = run_single_file(input_path, lexicon_path=lexicon_path, output_dir=output_dir, skip_llm=True)

    assert result.analyses
    assert (output_dir / "01_raw_text.txt").exists()
    assert (output_dir / "04_signals.jsonl").exists()
    assert (output_dir / "08_readable_report.md").read_text(encoding="utf-8").find("螺纹钢") >= 0

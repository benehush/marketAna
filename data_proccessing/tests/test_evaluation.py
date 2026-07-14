import json
from pathlib import Path

from data_proccessing.evaluation.runner import evaluate_dataset
from data_proccessing.instrument_mapping.runtime import RuntimeLexicon


def test_evaluation_runner_calculates_basic_metrics(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps({
            "source_id": "doc-1",
            "raw_text": "螺纹钢库存下降，需求改善，短期偏强",
            "product_key": "SHFE.RB",
            "direction": "看涨",
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lexicon = RuntimeLexicon(
        [{"product_key": "SHFE.RB", "canonical": "螺纹钢", "aliases": ["螺纹钢"], "negative_contexts": []}]
    )
    report = evaluate_dataset(dataset, lexicon)
    assert report["metrics"]["total"] == 1
    assert report["metrics"]["instrument_recall"] == 1.0

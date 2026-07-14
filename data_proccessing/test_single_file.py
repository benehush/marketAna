"""单文件数据处理测试工具。

用法：

    uv run python -m data_proccessing.test_single_file \
        sample/zheshang_cleaned.txt --skip-llm

默认会在 ``data_proccessing/output/<文件名>`` 下生成可阅读的处理结果。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from data_proccessing.config import ProcessingConfig
from data_proccessing.instrument_mapping.runtime import load_runtime_lexicon
from data_proccessing.llm.client import HttpLLMClient
from data_proccessing.pipeline.processor import DocumentProcessingResult, process_document
from data_proccessing.pipeline.canonical import to_canonical_result
from data_proccessing.readers.base import read_path


DEFAULT_LEXICON = "data_proccessing/instrument_mapping/artifacts/instrument_lexicon.json"


def run_single_file(
    input_path: str | Path,
    *,
    lexicon_path: str | Path = DEFAULT_LEXICON,
    output_dir: str | Path | None = None,
    skip_llm: bool = False,
) -> DocumentProcessingResult:
    """处理一个文件并输出详细中间结果。"""

    input_file = Path(input_path)
    document = read_path(input_file)
    lexicon = load_runtime_lexicon(lexicon_path)
    config = ProcessingConfig.from_env()
    llm_client = _build_llm_client(config, skip_llm=skip_llm)
    result = process_document(
        document,
        lexicon,
        llm_client=llm_client,
        config=config,
        skip_llm=skip_llm,
    )

    target_dir = Path(output_dir) if output_dir else Path("data_proccessing/output") / input_file.stem
    _write_outputs(result, target_dir)
    _print_result(result, target_dir)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="处理单个研报文件并输出可读结果")
    parser.add_argument("input", help="待处理文件：TXT、HTML、PDF、PNG/JPG")
    parser.add_argument("--lexicon", default=DEFAULT_LEXICON, help="运行时品种词典 JSON 路径")
    parser.add_argument("--output-dir", help="结果输出目录")
    parser.add_argument("--skip-llm", action="store_true", help="只运行规则，不调用 LLM")
    args = parser.parse_args()

    try:
        run_single_file(
            args.input,
            lexicon_path=args.lexicon,
            output_dir=args.output_dir,
            skip_llm=args.skip_llm,
        )
    except Exception as exc:
        print(f"处理失败：{type(exc).__name__}: {exc}")
        return 1
    return 0


def _build_llm_client(config: ProcessingConfig, *, skip_llm: bool) -> HttpLLMClient | None:
    if skip_llm:
        return None
    if not (config.llm_api_key and config.llm_base_url and config.llm_model):
        return None
    return HttpLLMClient(
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
        timeout_seconds=config.llm_timeout_seconds,
        provider=config.llm_provider,
        max_retries=config.llm_max_retries,
    )


def _write_outputs(result: DocumentProcessingResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    document = result.document
    (output_dir / "01_raw_text.txt").write_text(document.raw_text, encoding="utf-8")
    _write_json(output_dir / "02_document.json", asdict(document))
    _write_json(output_dir / "03_product_matches.json", [asdict(item) for item in result.matches])
    _write_jsonl(output_dir / "04_signals.jsonl", [asdict(item) for item in result.signals])
    _write_jsonl(output_dir / "05_analysis_results.jsonl", [asdict(item) for item in result.analyses])
    _write_jsonl(output_dir / "06_review_queue.jsonl", list(result.review_queue))
    _write_json(output_dir / "09_canonical_result.json", to_canonical_result(result))
    _write_json(
        output_dir / "07_summary.json",
        {
            "source_id": document.source_id,
            "processing_stats": result.processing_stats,
            "errors": list(result.errors),
            "match_count": len(result.matches),
            "signal_count": len(result.signals),
            "analysis_count": len(result.analyses),
            "review_count": len(result.review_queue),
        },
    )
    (output_dir / "08_readable_report.md").write_text(_readable_report(result), encoding="utf-8")


def _print_result(result: DocumentProcessingResult, output_dir: Path) -> None:
    document = result.document
    print("=== 单文件处理完成 ===")
    print(f"文件：{document.file_name or document.source_id}")
    print(f"类型：{document.file_type}，原文长度：{len(document.raw_text)}")
    print(f"品种匹配：{len(result.matches)}，方向信号：{len(result.signals)}")
    if result.analyses:
        print("分析结果：")
        for item in result.analyses:
            print(
                f"  - {item.product} ({item.product_key})：{item.direction or '待判断'}，"
                f"置信度={item.confidence:.2f}，方法={item.method}"
            )
    else:
        print("分析结果：暂无，已进入审核或 LLM 兜底队列")
    if result.review_queue:
        print(f"审核队列：{len(result.review_queue)} 条")
    if result.errors:
        print(f"错误：{len(result.errors)} 条")
    print(f"详细结果：{output_dir / '08_readable_report.md'}")


def _readable_report(result: DocumentProcessingResult) -> str:
    document = result.document
    lines = [
        "# 单文件数据处理结果",
        "",
        "## 文档信息",
        "",
        f"- 文件：`{document.file_name or document.source_id}`",
        f"- 类型：`{document.file_type}`",
        f"- 标题：{document.title or '无'}",
        f"- 原文长度：{len(document.raw_text)}",
        "",
        "## 品种匹配",
        "",
    ]
    if result.matches:
        lines.extend(
            f"- `{item.product_key}` / {item.display_name}：`{item.alias}`，位置 `{item.start}:{item.end}`，来源 `{item.source}`"
            for item in result.matches
        )
    else:
        lines.append("- 未匹配到标准品种")

    lines.extend(["", "## 方向信号", ""])
    if result.signals:
        lines.extend(
            f"- **{item.direction}** · {item.signal_type} · `{item.phrase}` · 置信度 {item.confidence:.2f}"
            f"\n  - 证据：{item.evidence_text}"
            for item in result.signals
        )
    else:
        lines.append("- 未提取到方向信号")

    lines.extend(["", "## 分析结果", ""])
    if result.analyses:
        for item in result.analyses:
            lines.extend(
                [
                    f"### {item.product}（{item.product_key}）",
                    "",
                    f"- 方向：**{item.direction or '待判断'}**",
                    f"- 方法：`{item.method}`",
                    f"- 置信度：`{item.confidence:.2f}`",
                    f"- 人工审核：`{'是' if item.need_manual_review else '否'}`",
                    f"- 理由：{item.reason or '无'}",
                    f"- 证据：{'；'.join(item.evidence) or '无'}",
                    "",
                ]
            )
    else:
        lines.append("- 暂无最终分析结果")

    lines.extend(["## 审核队列", ""])
    if result.review_queue:
        lines.extend(f"- `{json.dumps(item, ensure_ascii=False)}`" for item in result.review_queue)
    else:
        lines.append("- 无")

    lines.extend(["", "## 处理统计", "", "```json", json.dumps(result.processing_stats, ensure_ascii=False, indent=2), "```"])
    if result.errors:
        lines.extend(["", "## 错误", "", *[f"- {error}" for error in result.errors]])
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())

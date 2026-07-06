# pn11 流水线联调与异常处理 计划

## 摘要

pn11 是开发者 B 的收口模块。将 pn04（Parser）、pn05（Cleaner）、pn06（RuleEngine）、pn07（LLMInfer）串成端到端流水线，提供 `run_pipeline(article_id, session) → bool` 作为 pn03 Scheduler 的 `pipeline_callback`。支持按状态断点续跑、失败重试、批量并发处理和全流程耗时统计。

## 关键改动

- **核心编排** (`pipeline.py`)：
  - `run_pipeline(article_id, session)`：按 `article.status` 路由到对应阶段。
  - 状态路由：0→parser, 1→cleaner, 2→rule_engine, 3→llm_infer, 5→跳过。
  - 失败重试：`status=-1` 时根据 `error_msg` 判断失败阶段，重置状态后从对应阶段重跑。
  - 总览日志：流水线完成后写汇总 `task_log(stage="pipeline")`。

- **批量并发** (`batch.py`)：
  - `batch_process(article_ids, session_factory, max_concurrency=5)`。
  - `ThreadPoolExecutor` 并发，每篇文章独立 Session。
  - 并发数可配置，适用于 Scheduler 扫出的批次。

- **数据模型** (`models.py`)：
  - `PipelineResult`：单篇结果（stages_run、error_stage、耗时）。
  - `BatchResult`：批量汇总（总数、成功、失败）。

## 实现顺序

1. 定义 `PipelineResult`、`BatchResult`（`models.py`）。
2. 实现 `run_pipeline`：状态路由 + 阶段调用 + 重试逻辑（`pipeline.py`）。
3. 实现 `batch_process`：ThreadPoolExecutor 并发（`batch.py`）。
4. 编写测试（mock 各 pn 阶段）。
5. 编写 README 和本文档。

## 验证方案

- 正常流程：status=0 → 经 parser/cleaner/rule_engine → status=5。
- LLM 流程：rule_engine 低置信 → llm_infer → status=5。
- 断点续跑：status=1 → 跳过 parser，从 cleaner 开始。
- 已完成跳过：status=5 → 直接返回 True。
- 失败处理：parser 异常 → 返回 False，status=-1。
- 重试：status=-1 → 重置状态 → 从失败阶段重跑。
- 批量并发：3 篇文章 × 2 并发 → 全部完成。

## 实际实现

- [x] `pn11/` 全部 5 个模块文件
- [x] `test_pipeline.py` — 9 个测试用例
- [x] 依赖：仅 Python stdlib `concurrent.futures`

## 与各模块关系

| 模块 | 调用方式 |
|------|---------|
| pn03 | `run_pipeline` 作为 `pipeline_callback` |
| pn04 | `parse_article(article, session)` |
| pn05 | `clean_article(article_id, session)` |
| pn06 | `analyze_article(article_id, session)` → `RuleResult.need_llm` |
| pn07 | `infer_article(article_id, session)` |

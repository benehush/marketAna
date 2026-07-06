# pn06 规则识别模块 RuleEngine 计划

## 摘要

pn06 使用关键词词典 + 正则规则识别期货品种和走势方向（看涨/看跌/中性）。高置信度（≥0.7）直接通过 `ArticleRepository.save_analysis_result(mark_stored=True)` 入库（`analysis_method="rule"`, `status→5`），低成本处理明确观点文章；低置信度（<0.7）更新状态为 `RULE_ANALYZED(3)` 并标记 `need_llm=True`，交由 pn07 LLMInfer 处理。覆盖 25+ 期货品种，30+ 确定词和 12 种模糊正则模式，支持方向冲突检测和中性方向置信度上限。

## 关键改动

- 品种关键词词典（`product_dict.py`）：
  - 25+ 期货品种（螺纹钢、铁矿石、沪铜、原油、豆粕、棕榈油、焦煤、黄金等），每个品种含多个同义词/简称/英文代码。
  - 反向映射：任一关键词 → 正名（如 "RB" → "螺纹钢"）。
  - `detect_products()` 返回所有提及品种及次数；`get_primary_product()` 返回出现最多的品种。

- 方向识别规则（`direction_rules.py`）：
  - 看涨类：12 个确定词（看涨、上涨、偏强、反弹、做多…）+ 6 个模糊正则（"预计.*上涨"…）。
  - 看跌类：12 个确定词（看跌、下跌、偏弱、回落、做空…）+ 6 个模糊正则（"预计.*下跌"…）。
  - 中性类：10 个确定词（震荡、区间、盘整、横盘…）+ 6 个模糊正则（"以.*震荡.*为主"…）。
  - 方向判定：取匹配数最多的方向。涨跌同时出现 → `is_conflict=True`。
  - 理由提取：找到方向关键词所在句子 → 取前后各 N 句窗口拼接。

- 置信度评分（`confidence.py`）：
  - `base_score=0.5` → 确定词加分（每次 +0.15）→ 模糊词减分（每次 -0.1）→ 多处一致加分 → 冲突扣分（-0.25）。
  - 中性方向上限 0.6（本质是不确定）。
  - 仅模糊词无确定词 → 上限 0.55。
  - 未检测到品种或方向 → 置信度 0。

- 主引擎（`rule_engine.py`）：
  - `analyze_article(article_id, session)`：读取 `cleaned_text` → 品种检测 → 方向检测 → 置信度计算 → 决策。
  - 高置信（≥0.7 + 品种 + 方向）→ `save_analysis_result(mark_stored=True)`，`status→5`。
  - 低置信 → `update_status(RULE_ANALYZED)`，`result.need_llm=True`。

- 边界处理：
  - 未检测到品种/方向 → 置信度 0, `need_llm=True`。
  - 多品种 → 选出现次数最多的品种。
  - 方向冲突 → 取更多匹配项的方向，强制 `need_llm=True`。
  - 空文本 → `mark_failed`。

## 实现顺序

1. 定义 `RuleConfig`、`RuleResult` 数据类（`models.py`）。
2. 建立品种关键词词典 + 反向映射 + 检测函数（`product_dict.py`）。
3. 定义方向关键词 + 正则模式 + 方向判定 + 理由提取（`direction_rules.py`）。
4. 实现置信度评分器（`confidence.py`）。
5. 实现主引擎：流程编排 + 入库决策（`rule_engine.py`）。
6. 编写测试用例，覆盖品种检测、方向识别、置信度计算和完整流程。
7. 编写 README 和本文档。

## 验证方案

- 品种检测：
  - 单品种识别、多品种取最多、无品种返回 None。
  - 简称/别名识别（"RB"→"螺纹钢"、"铁矿"→"铁矿石"）。

- 方向检测：
  - 看涨/看跌/中性确定词正确分类。
  - 模糊正则模式匹配。
  - 无方向表达 → 返回 None。
  - 涨跌冲突标记 `is_conflict=True`。

- 置信度：
  - 高置信（多个确定词匹配）≥ 0.7。
  - 低置信（仅模糊词）< 0.7。
  - 无品种 → 0。
  - 中性方向上限 0.6。

- 集成测试：
  - 高置信文章 → `status=5`（STORED），`analysis_method="rule"`，`need_llm=False`。
  - 低置信/无品种文章 → `status=3`（RULE_ANALYZED），`need_llm=True`。
  - 空文本 → `status=-1`（FAILED）。
  - task_log 正确写入。

- 回归验证：
  - `uv run pytest pn06/ -v` 全部 18 个测试通过。

## 假设与默认选择

- 置信度阈值 0.7 与项目 `Settings.rule_confidence_threshold` 保持一致。
- 品种词典初始覆盖 25 个主流期货品种；新增品种只需在 `PRODUCT_DICT` 中追加。
- 方向规则基于中文期货研报常见表达模式，不涵盖英文报告。
- 理由提取使用简单句子窗口（前后各 2 句），不做 NLP 语义分析。
- 无新增依赖，仅使用 Python 标准库 `re`。

## pn06 规则识别模块实际实现情况

通过阅读和验证本阶段代码，pn06 的品种词典、方向规则、置信度评分和入库决策已按计划落地。高置信文章可直接跳过 LLM 调用，降低推理成本。

### 已实现的框架

**1. 品种关键词词典** (`pn06/product_dict.py`)
- **`PRODUCT_DICT`**：25 个期货品种，每个含 3-5 个关键词变体。
- **`get_alias_map()`**：懒加载反向映射（任一关键词 → 正名）。
- **`detect_products()`**：返回 `{正名: 提及次数}`，按次数降序排列。
- **`get_primary_product()`**：返回出现最多的品种。

**2. 方向识别规则** (`pn06/direction_rules.py`)
- **看涨**：12 确定词 + 6 模糊正则。
- **看跌**：12 确定词 + 6 模糊正则。
- **中性**：10 确定词 + 6 模糊正则。
- **`detect_direction()`**：返回 `{direction, bullish_count, bearish_count, neutral_count, is_conflict, ...}`。
- **`extract_reason()`**：方向关键词定位 + 前后 N 句窗口提取。

**3. 置信度评分器** (`pn06/confidence.py`)
- **`calculate_confidence()`**：base + 确定加分 - 模糊减分 + 多处一致加分 - 冲突扣分。
- 中性上限 0.6 + 纯模糊上限 0.55 + clamp 0-1。

**4. 主引擎** (`pn06/rule_engine.py`)
- **`analyze_article(article_id, session)`**：6 步流程 → 高置信直接入库 / 低置信 `status=3` + `need_llm=True`。
- **`RuleResult`** 包含 `product/direction/reason/confidence/need_llm/detail`。

### 尚未实现（但计划也说不做）

- 品种词典当前 25 个，未覆盖所有期货品种（如纤维板、胶合板等小众品种），可按需扩展。
- 方向规则仅覆盖中文表达，英文研报需要扩充英文关键词。
- 不修改 `back_end/app/services/` 或 `back_end/app/core/status.py` 中的现有文件。

### 计划中声明的功能验证

| 验证项 | 状态 |
|--------|------|
| 单品种识别 + 多品种取最多 + 无品种返回 None | ✅ `test_detect_product_*` 系列 |
| 简称/别名识别（RB→螺纹钢） | ✅ `test_detect_product_alias` |
| 看涨/看跌/中性确定词分类 | ✅ `test_direction_bullish` / `bearish` / `neutral` |
| 无方向 → None | ✅ `test_direction_none` |
| 涨跌冲突标记 | ✅ `test_direction_conflict` |
| 高置信 ≥ 0.7 vs 低置信 < 0.7 | ✅ `test_confidence_high` / `low_vague` |
| 无品种 → 置信度 0 | ✅ `test_confidence_no_product` |
| 中性上限 0.6 | ✅ `test_confidence_neutral_capped` |
| 理由窗口提取 | ✅ `test_reason_extraction` |
| 高置信 → status=5 + analysis_method=rule | ✅ `test_full_pipeline_high_conf` |
| 低置信 → status=3 + need_llm=True | ✅ `test_full_pipeline_low_conf` |
| 无品种 → need_llm=True | ✅ `test_full_pipeline_no_product` |
| 空文本 → mark_failed | ✅ `test_full_pipeline_empty_clean` |
| task_log 记录 | ✅ `test_full_pipeline_task_log` |
| 全量测试 | ✅ 18 个测试用例全部通过 |

**总结**：pn06 已完成规则识别模块的核心实现。25 个期货品种的词典 + 52 个方向关键词/模式可覆盖大部分中文研报的明确观点表达。高置信文章直接入库（跳过 LLM），低置信文章自动标记 `need_llm` 交由 pn07 处理。后续 pn07 LLMInfer 可直接消费 `cleaned_text` 和 `need_llm` 标记。

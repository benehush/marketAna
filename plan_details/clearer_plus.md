# Cleaner 二次精清计划

## Summary
- 在 `pn05/structured_cleaner.py` 增加一层“OCR 语义精清”，放在现有噪声规则、数字噪声过滤之后，输出前进一步压缩低价值 OCR 行。
- 目标是保留观点、逻辑、核心驱动和可分析数据，删除免责声明残留、页脚、英文乱码、图表标题/数据源噪声和低价值表格数字行。
- 默认偏保守：不改 parser，不让 LLM 参与清洗，避免清洗阶段引入外部依赖。

## Key Changes
- 扩展 `CleanConfig`：
  - 新增 `semantic_line_filter: bool = True`。
  - 新增 `strict_ocr_noise_filter: bool = True`。
  - 新增 `max_ocr_noise_alpha_ratio`、`min_ocr_semantic_cjk_chars` 等可调阈值。
- 强化行级过滤：
  - 在 OCR/body 模式下删除免责声明残句、数据来源/更新频率、公司页脚、图表标题串、纯表头式短句、英文乱码占比高的行。
  - 保留含 `观点、逻辑、建议、价格、供应、需求、库存、成本、利润、基差、开工率、产能、装置、负荷、原油、产业链` 等语义信号的行。
  - 对“含语义词但明显是纯图表标题”的行继续删除，例如多个日期/地区/数据源组合但没有判断句。
- 提升结构输出：
  - 对 OCR 中识别到的 `观点:`、`逻辑:`、`建议:` 行优先保留，并输出到 `## 图文识别正文` 顶部。
  - 对明显核心观点/逻辑内容可整理成连续段落，但不新增原文没有的信息。
  - 不在 cleaner 阶段强行改写成完整自然语言；自然语言润色仍交给 `refiner`。
- 规则与证据稳定性：
  - `cleaned_text` 继续作为规则识别和证据定位来源。
  - 避免为了可读性过度改写原句，只做删除噪声、轻量 OCR 修复和结构排序。

## Test Plan
- 新增结构化清洗测试：
  - OCR 乱码行如 `ASSEW RETA S...`、`Laeeaieuban...` 被删除。
  - 免责声明残句如 `会计或税务的最终操作建议`、`请务必阅读正文之后的免责条款` 被删除。
  - 数据源/图表噪声如 `数据永源:WIND`、`更新频率: 日度`、多日期坐标轴继续删除。
  - 核心句保留：`聚乙烯震荡下行`、`产能压力巨大`、`基差回落`、`原油预期偏弱`。
- 回归测试：
  - 语义数字保留，如 `3650 元/吨`。
  - Markdown 表格中有中文表头和语义数据的行仍保留。
  - 导航-only 内容仍被判失败。
  - `pn05/test_cleaner.py`、`pn11/test_pipeline.py`、`tests/test_backend_data.py` 保持通过。
- 手动验证：
  - 用 `tests/manual_single_file_pipeline.py ... --output-dir tests/outputs` 重新生成四段输出。
  - 对比 `02_cleaned_text.txt` 长度下降，`03_recognition_text.txt` 误识别品种减少，`04_refined_text.txt` 更稳定。

## Assumptions
- 清洗目标优先服务规则识别和 LLM 精修，不追求保留完整研报所有图表数据。
- `cleaned_text` 可以比当前更短、更聚焦，但不能删除核心观点、逻辑和可解释行情判断。
- 表格保留策略偏保守：Markdown 表格和含中文业务字段的数据行保留；OCR 价格曲线、坐标轴、数据源说明优先删除。

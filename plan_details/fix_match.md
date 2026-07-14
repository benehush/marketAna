# 修复分析依据误匹配与品种边界漏切

## Summary

目标是让 PVC 这类结果的“结论依据”只来自同品种原文窗口，避免用“库存去化/方向不明/震荡”等泛化 reason 词误匹配到成材、锰硅、EG。方案分两层：先修 evidence fallback 的匹配策略，再增强分段器识别 `PVC05合约` / `EG05合约` 这种品种+合约格式。

## Key Changes

- Evidence fallback 改为“品种锚点优先”：
  - 在没有对应 `article_product_segments` 时，先从产品目录生成锚点：`display_name`、`official_name`、aliases、`symbol+contract`、`product+contract`，如 `PVC`、`聚氯乙烯`、`PVC05`、`EG05`。
  - 如果全文中存在当前品种锚点，只允许在该锚点附近截取 evidence；截取边界到下一个不同品种锚点前为止，避免 PVC 窗口吞进 EG。
  - 在锚点窗口内再匹配 reason 片段；匹配到则 `match_type=reason`，否则以品种锚点窗口作为 `keyword` evidence。
  - 如果当前品种锚点不存在，但文本明显是多品种文档，则不要用泛化 reason 匹配，直接回退 `analysis_reason`。
  - 如果当前品种锚点不存在且文本不像多品种文档，保留现有 reason 模糊匹配，以兼容单品种旧数据。

- 分段器增强：
  - 让 `_is_product_prefix/_extract_heading` 识别行首或句首的 `PVC05合约`、`PVC05 合约`、`EG05合约`、`PTA05合约` 等格式。
  - 新品种边界应切在 `PVC05合约...` 前，并把 heading 归一为标准品种名，如 `PVC`、`乙二醇`。
  - 保持已有 `【品种】`、`品种：`、Markdown 标题识别逻辑不变。

- API/前端兼容：
  - 不新增数据库字段，不做迁移。
  - 不改变 `AnalysisEvidence.source` 枚举，仍使用 `segment | cleaned_text | raw_text | analysis_reason`。
  - 前端无需改动；修复后仍消费现有 `evidence.excerpts` / `cleaned_text` / `refined_text`。

## Test Plan

- Serializer evidence tests:
  - 构造包含成材、锰硅、PVC、EG 的 cleaned_text；PVC reason 为“库存加速去化，成本支撑走强...”，断言 PVC evidence：
    - 包含 `PVC05`
    - 包含 PVC 的“库存加速去化/成本支撑”
    - 不包含“成材端需求”
    - 不包含“锰硅”
    - 不包含 `EG05`
  - 当前品种锚点缺失、但文本含多个其他品种锚点时，断言回退到 `analysis_reason`，不返回错误原文 excerpt。
  - 当前品种锚点缺失、文本不像多品种文档时，保留现有 reason 定位行为，避免破坏旧单品种测试。
  - 现有“优先使用 segment evidence”的测试保持不变。

- Segmenter tests:
  - 输入 `PVC05合约...。\nEG05合约...。`，断言切出两个分段：`PVC` 和 `乙二醇`。
  - 输入 `PTA05 合约...`，断言识别为 `PTA`。
  - 输入已有 `【乙二醇】`、`乙二醇：` 样例，断言原有行为不回退。

- 验证命令：
  - `uv run pytest pn05/test_product_segmenter.py tests/test_backend_data.py`

## Assumptions

- 本次只修“证据定位”和“品种边界漏切”，不调整 LLM reason 生成策略。
- 对已入库历史数据，修复 serializers 后页面 evidence 会即时变正确；分段器增强只影响重跑后的 `article_product_segments`。
- 对无法定位同品种锚点的多品种结果，宁愿展示 `analysis_reason`，也不展示疑似错误的跨品种原文。

# pn07 LLM 推理模块 LLMInfer 计划

## 摘要

pn07 对 pn06 RuleEngine 无法高置信识别的文章调用大语言模型（OpenAI 兼容 API）。通过结构化 System/User Prompt 强制 JSON 输出，解析后进行字段校验和异常修复。低置信（<0.5）自动标记 `need_manual_review=True`，前端可高亮"待人工确认"。支持最多 3 次指数退避重试（429/5xx/超时），4xx 错误不重试。HTTP 调用基于项目已有的 `httpx` 库，无新增依赖。

## 关键改动

- LLM API 客户端（`llm_client.py`）：
  - `LLMAPIClient` 类，基于 `httpx` 调用 OpenAI 兼容 `/v1/chat/completions` 端点。
  - 自动从 `Settings`（`.env`）读取 `api_key/base_url/model`。
  - 重试策略：429/5xx/超时 → 指数退避 1s/2s/4s（最多 3 次）；401/403 → 立即抛异常；400 → 立即抛异常。
  - `health_check()` 方法：快速验证 API 连通性（`GET /v1/models`）。

- Prompt 构建器（`prompt_builder.py`）：
  - System Prompt：角色设定为"资深期货市场分析师"，明确 JSON 输出规范和四字段规则。
  - User Prompt：组装标题、来源、期货公司、发布时间和正文。
  - 正文超长自动截断（默认 8000 字符），附加 `[文本过长，已截断...]` 标记。

- JSON 解析器（`json_parser.py`）：
  - 8 种异常格式修复：
    - 代码块包裹（```json...```）→ 提取内容。
    - 前后多余文字 → 正则提取 `{...}`。
    - 尾部逗号 `,}` → 正则移除。
    - 单引号 `'key':'value'` → 替换双引号。
    - 字段缺失 → 填充 `null`/默认值。
    - `direction` 非法值 → 置 `null`。
    - `confidence` 非数字/越界 → clamp 0-1。
    - 完全无法解析 → 返回 `product=None` + errors 列表。
  - `parse_llm_json()` 返回 `(parsed_dict, errors)`。

- 主推理入口（`llm_infer.py`）：
  - `infer_article(article_id, session)`：
    1. 读取 `article_texts.cleaned_text` + 文章元信息。
    2. 构建 Prompt。
    3. 调用 LLM API（含重试）。
    4. 解析并校验 JSON。
    5. 决策：`confidence < 0.5` → `need_manual_review=True`。
    6. `save_analysis_result(mark_stored=True)` + `status→4→5`。
    7. 写 task_log（含模型名、重试次数、耗时）。
  - 全部重试耗尽 → `mark_failed`。
  - LLM 输出的关键字段缺失 → 仍入库但标记 `need_manual_review=True`。

- 配置（`models.py`）：
  - `LLMConfig`：从 `Settings` 自动读取，支持 `api_key/base_url/model/timeout/max_retries/temperature/max_tokens/manual_review_threshold`。
  - `InferResult`：包含 `product/direction/reason/confidence/need_manual_review/model/duration_ms/retry_count/error_msg/raw_response`。

## 实现顺序

1. 定义 `LLMConfig`、`InferResult` 数据类（`models.py`）。
2. 实现 `LLMAPIClient`：httpx 调用 + 重试 + 健康检查（`llm_client.py`）。
3. 实现 `build_messages()`：System/User Prompt（`prompt_builder.py`）。
4. 实现 `parse_llm_json()`：JSON 提取 + 修复 + 校验（`json_parser.py`）。
5. 实现 `infer_article()`：主编排 + Repository 集成（`llm_infer.py`）。
6. 编写测试用例：mock LLM 调用，覆盖正常解析、异常格式修复、重试逻辑和集成流程。
7. 编写 README 和本文档。

## 验证方案

- Prompt 构建：
  - 包含所有上下文字段（标题、来源、公司、时间）。
  - 超长正文正确截断。

- JSON 解析：
  - 标准 JSON → 正确解析。
  - ````json...```` 包裹 → 正确解析。
  - 尾部逗号 → 修复后解析。
  - 前后多余文字 → 正确提取 JSON。
  - 单引号 → 修复后解析。
  - direction 非法值（"暴涨"）→ `direction=None` + errors。
  - confidence 越界（1.5/-0.3）→ clamp 1.0/0.0。
  - 垃圾文本无法解析 → errors 非空 + `product=None`。

- 集成测试（mock LLM）：
  - 高置信（0.85）→ `need_manual_review=False` + `status=5` + `analysis_method="llm"`。
  - 低置信（0.35）→ `need_manual_review=True`。
  - LLM API 全部失败 → `status=-1`（FAILED）+ `error_msg` 包含原因。
  - 空文本 → `status=-1`（FAILED）。
  - task_log 包含模型名（"gpt-test"）。

- 回归验证：
  - `uv run pytest pn07/ -v` 全部 17 个测试通过。

## 假设与默认选择

- LLM API 兼容 OpenAI `/v1/chat/completions` 协议（支持 OpenAI、DeepSeek、通义千问等）。
- API 配置通过 `.env` 中的 `LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 获取。
- 温度设为 0.1（低温度保证稳定 JSON 输出）。
- `manual_review_threshold=0.5`（< 0.5 标记待人工确认）。
- 输入正文截断默认 8000 字符（适配大多模型的上下文窗口）。
- 不修改 `back_end/app/services/llm_client.py`（pn01 占位文件）。

## pn07 LLM 推理模块实际实现情况

通过阅读和验证本阶段代码，pn07 的 LLM API 客户端、Prompt 构建器、JSON 解析修复和完整推理流程已按计划落地。模块通过 `ArticleRepository` 接口写入分析结果和更新状态。

### 已实现的框架

**1. LLM API 客户端** (`pn07/llm_client.py`)
- **`LLMAPIClient`**：基于 httpx 的 OpenAI 兼容 API 客户端。
- **`chat()`**：发送 chat completion 请求，自动重试（指数退避 1s/2s/4s），429/5xx/超时重试，4xx 不重试。
- **`health_check()`**：通过 `GET /v1/models` 验证 API 连通性。
- **`is_configured`**：检查 `api_key` 和 `base_url` 是否配置。

**2. Prompt 构建器** (`pn07/prompt_builder.py`)
- **`SYSTEM_PROMPT`**：中文 System Prompt，明确角色、JSON 格式和四字段规则。
- **`build_messages()`**：组装 System + User messages；User 含标题、来源、公司、时间和正文；正文超长自动截断。

**3. JSON 解析器** (`pn07/json_parser.py`)
- **`parse_llm_json()`**：3 层提取策略（代码块 → 正则 `{...}` → 原文）。
- **`_repair_json()`**：尾部逗号移除 + 单引号替换 + 注释行移除。
- 字段校验：`product/direction/reason/confidence` 逐字段验证和默认值处理。
- `direction` 枚举校验（限 `看涨/看跌/中性`）；`confidence` clamp 0-1。

**4. 主推理入口** (`pn07/llm_infer.py`)
- **`infer_article(article_id, session)`**：7 步完整推理流程 + Repository 集成。
- 自动决策：`confidence < 0.5` → `need_manual_review=True`。
- 全部重试耗尽 → `mark_failed`；关键字段缺失 → 入库但标记 `need_manual_review`。
- task_log 包含模型名、重试次数、品种、方向、置信度。

**5. 数据模型** (`pn07/models.py`)
- **`LLMConfig`**：从 Settings 自动读取（`from_settings()`），8 个可配置参数。
- **`InferResult`**：10 个字段完整记录推理过程和结果。

### 尚未实现（但计划也说不做）

- LLM API 需要用户自行在 `.env` 中配置 `LLM_API_KEY` 和 `LLM_BASE_URL`；未配置时推理会抛出 `RuntimeError`。
- 不修改 `back_end/app/services/llm_client.py`（pn01 占位文件）。
- 流式输出（streaming）暂不支持 — 当前场景输出短 JSON，不需要。
- 多模型投票/集成策略属于后续扩展，不在 pn07 范围内。

### 计划中声明的功能验证

| 验证项 | 状态 |
|--------|------|
| Prompt 包含上下文字段 | ✅ `test_prompt_build` |
| 超长正文截断 | ✅ `test_prompt_truncation` |
| 标准 JSON 解析 | ✅ `test_json_parse_normal` |
| Markdown 代码块包裹解析 | ✅ `test_json_parse_markdown_wrap` |
| 尾部逗号修复 | ✅ `test_json_parse_trailing_comma` |
| 前后多余文字提取 | ✅ `test_json_parse_extra_text` |
| 单引号修复 | ✅ `test_json_parse_single_quotes` |
| direction 非法值 → null | ✅ `test_json_parse_invalid_direction` |
| 字段缺失 → 默认值 | ✅ `test_json_parse_missing_fields` |
| confidence 越界 clamp | ✅ `test_json_parse_confidence_range` / `_negative` |
| 垃圾文本解析失败 | ✅ `test_json_parse_garbage` |
| Mock LLM 高置信推理 | ✅ `test_full_infer_high_conf` |
| Mock LLM 低置信推理 → need_manual_review | ✅ `test_full_infer_low_conf` |
| LLM 全部失败 → mark_failed | ✅ `test_full_infer_llm_failure` |
| 空文本 → mark_failed | ✅ `test_full_infer_empty_clean` |
| task_log 含模型信息 | ✅ `test_full_infer_task_log` |
| 全量测试 | ✅ 17 个测试用例全部通过 |

**总结**：pn07 已完成 LLM 推理模块的核心实现。支持任意 OpenAI 兼容 API，8 种 JSON 异常格式自动修复，3 次指数退避重试，低置信自动标记人工确认。模块通过 `ArticleRepository` 接口写入分析结果（`analysis_method="llm"`）。后续 pn11 Pipeline 编排可基于 `RuleResult.need_llm` 标记决定是否调用 pn07。

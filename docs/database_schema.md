# MarketANA 数据库核心表设计

本文档是开发者 A 对 pn02「数据库模型与状态流转设计」的交付说明，内容基于当前实现 [back_end/app/models/article.py](/home/sanmu/marketANA/back_end/app/models/article.py)。数据库模型使用 SQLAlchemy 2.0 ORM 定义，目标是支撑文章导入、文本解析清洗、规则/LLM 分析、任务日志追踪和人工确认审计。

## 1. 设计目标

- 用 `articles` 作为文章主表，保存外部导入文章的元信息和处理状态。
- 用 `article_texts` 保存一篇文章的原始文本和清洗后文本。
- 用 `analysis_results` 保存当前有效分析结果，一篇文章可包含多个品种/合约观点，供前端页面、趋势图和统计查询使用。
- 用 `task_logs` 记录解析、清洗、规则识别、LLM 推理等流水线阶段日志。
- 用 `manual_confirmations` 保存人工修正确认记录，保留修改前后对比，满足审计需求。

## 2. 枚举与状态流转

### 2.1 文章状态

`articles.status` 只能使用以下值：

| status | 含义 | 写入阶段 |
| --- | --- | --- |
| `0` | 未处理 | 文章创建后的默认状态 |
| `1` | 解析完成 | Parser 写入 `article_texts.raw_text` 后 |
| `2` | 清洗完成 | Cleaner 写入 `article_texts.cleaned_text` 后 |
| `3` | 规则识别完成 | RuleEngine 完成初步识别后 |
| `4` | LLM 推理完成 | LLMInfer 完成模型推理后 |
| `5` | 已入库 | `analysis_results` 当前有效结果保存后 |
| `-1` | 失败 | 任意阶段失败后 |

正常流转：

```text
0 -> 1 -> 2 -> 3 -> 4 -> 5
```

失败流转：

```text
任意状态 -> -1
```

失败时应同时写入：

- `articles.status = -1`
- `articles.error_msg`
- `task_logs` 中对应失败阶段日志

### 2.2 分析方向

`analysis_results.direction` 和 `manual_confirmations.confirmed_direction` 只能使用：

| value | 含义 |
| --- | --- |
| `看涨` | 文章判断后续走势偏强或上涨 |
| `看跌` | 文章判断后续走势偏弱或下跌 |
| `中性` | 文章判断震荡、观望或方向不明确 |

### 2.3 分析方法

`analysis_results.analysis_method` 只能使用：

| value | 含义 |
| --- | --- |
| `rule` | 规则引擎生成 |
| `llm` | 大模型生成 |
| `manual` | 人工确认或修正后生成 |

### 2.4 置信度

`confidence` 和 `confirmed_confidence` 统一使用 `0 <= value <= 1` 的小数值。前端展示百分比时自行转换，例如 `0.82` 展示为 `82%`。

## 3. 表结构

### 3.1 `articles`

文章主表，保存文章元信息、处理状态和失败原因。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | 是 | 自增 | 主键 |
| `title` | `String(255)` | 是 | 无 | 文章标题 |
| `source` | `String(128)` | 否 | `NULL` | 文章来源 |
| `company` | `String(128)` | 否 | `NULL` | 期货公司 |
| `file_url` | `String(1024)` | 否 | `NULL` | 原始文件或文章地址 |
| `file_type` | `String(32)` | 否 | `NULL` | 文件类型，如 `pdf`、`html`、`png` |
| `publish_time` | `DateTime` | 否 | `NULL` | 原文发布时间 |
| `status` | `Integer` | 是 | `0` | 处理状态 |
| `error_msg` | `Text` | 否 | `NULL` | 失败原因 |
| `created_at` | `DateTime` | 是 | `func.now()` | 创建时间 |
| `updated_at` | `DateTime` | 是 | `func.now()` | 更新时间 |

约束与索引：

| 名称 | 类型 | 字段 | 说明 |
| --- | --- | --- | --- |
| `ck_articles_status` | CheckConstraint | `status` | 限制状态只能为 `-1,0,1,2,3,4,5` |
| `ix_articles_status_created_at` | Index | `status`, `created_at` | 调度器按状态和创建时间扫描待处理文章 |
| `ix_articles_company` | Index | `company` | 前端按期货公司筛选 |
| `ix_articles_publish_time` | Index | `publish_time` | 按发布时间排序和时间范围筛选 |

关系：

- 一对一：`articles -> article_texts`
- 一对多：`articles -> analysis_results`
- 一对多：`articles -> task_logs`
- 一对多：`articles -> manual_confirmations`

### 3.2 `article_texts`

文章文本表，保存解析后的原始文本、清洗后的分析文本和 LLM 精修后的展示文本。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | 是 | 自增 | 主键 |
| `article_id` | `ForeignKey(articles.id)` | 是 | 无 | 关联文章 |
| `raw_text` | `Text` / MySQL `LONGTEXT` | 否 | `NULL` | 解析出的原始文本 |
| `cleaned_text` | `Text` / MySQL `LONGTEXT` | 否 | `NULL` | 清洗后的文本 |
| `refined_text` | `Text` / MySQL `LONGTEXT` | 否 | `NULL` | LLM 精修后的用户展示文本 |
| `raw_length` | `Integer` | 是 | `0` | 原始文本长度 |
| `cleaned_length` | `Integer` | 是 | `0` | 清洗后文本长度 |
| `refined_length` | `Integer` | 是 | `0` | 精修后文本长度 |
| `parser_type` | `String(64)` | 否 | `NULL` | 解析器类型，如 `pdf`、`html`、`ocr` |
| `created_at` | `DateTime` | 是 | `func.now()` | 创建时间 |
| `updated_at` | `DateTime` | 是 | `func.now()` | 更新时间 |

约束与索引：

| 名称 | 类型 | 字段 | 说明 |
| --- | --- | --- | --- |
| `uq_article_texts_article_id` | UniqueConstraint | `article_id` | 一篇文章只保留一条文本记录 |
| 自动索引 | Index | `article_id` | 加速按文章查询文本 |

外键：

- `article_id -> articles.id`
- `ondelete="CASCADE"`，删除文章时同步删除文本记录。

### 3.3 `analysis_results`

分析结果表，保存当前有效的品种/合约、方向、理由、置信度和分析方法。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | 是 | 自增 | 主键 |
| `article_id` | `ForeignKey(articles.id)` | 是 | 无 | 关联文章 |
| `product` | `String(128)` | 是 | 无 | 期货品种 |
| `contract` | `String(64)` | 否 | `NULL` | 合约，如 `05`、`2505` |
| `contract_key` | `String(64)` | 是 | `""` | 合约归一化键，参与幂等唯一约束 |
| `direction` | `String(16)` | 是 | 无 | `看涨`、`看跌`、`中性` |
| `reason` | `Text` | 否 | `NULL` | 分析理由 |
| `confidence` | `Float` | 是 | 无 | 置信度，范围 `0-1` |
| `analysis_method` | `String(32)` | 是 | 无 | `rule`、`llm`、`manual` |
| `need_manual_review` | `Boolean` | 是 | `False` | 是否需要人工确认 |
| `is_primary` | `Boolean` | 是 | `False` | 是否为文章兼容主结果 |
| `model_name` | `String(128)` | 否 | `NULL` | LLM 模型名称 |
| `llm_duration_ms` | `Integer` | 否 | `NULL` | LLM 调用耗时 |
| `llm_retry_count` | `Integer` | 否 | `NULL` | LLM 重试次数 |
| `llm_error_msg` | `Text` | 否 | `NULL` | LLM 解析/调用错误摘要 |
| `analysis_time` | `DateTime` | 是 | `func.now()` | 分析完成时间 |
| `created_at` | `DateTime` | 是 | `func.now()` | 创建时间 |
| `updated_at` | `DateTime` | 是 | `func.now()` | 更新时间 |

约束与索引：

| 名称 | 类型 | 字段 | 说明 |
| --- | --- | --- | --- |
| `uq_analysis_results_article_product_contract` | UniqueConstraint | `article_id`, `product`, `contract_key` | 同一文章同一品种合约只保留一条当前有效结果 |
| `ck_analysis_results_direction` | CheckConstraint | `direction` | 限制方向枚举 |
| `ck_analysis_results_confidence` | CheckConstraint | `confidence` | 限制置信度为 `0-1` |
| `ck_analysis_results_method` | CheckConstraint | `analysis_method` | 限制分析方法枚举 |
| `ix_analysis_results_product` | Index | `product` | 前端按品种筛选和聚合 |
| `ix_analysis_results_direction` | Index | `direction` | 前端按方向筛选和统计 |
| `ix_analysis_results_product_direction` | Index | `product`, `direction` | 品种 + 方向组合查询 |
| `ix_analysis_results_analysis_time` | Index | `analysis_time` | 按分析时间查询趋势 |

外键：

- `article_id -> articles.id`
- `ondelete="CASCADE"`，删除文章时同步删除分析结果。

### 3.4 `task_logs`

任务日志表，记录调度和流水线阶段执行情况。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | 是 | 自增 | 主键 |
| `article_id` | `ForeignKey(articles.id)` | 否 | `NULL` | 关联文章；允许为空以记录全局任务日志 |
| `stage` | `String(64)` | 是 | 无 | 阶段，如 `scheduler`、`parser`、`cleaner`、`rule`、`llm`、`repository` |
| `status` | `String(32)` | 是 | 无 | 阶段执行状态，如 `success`、`failed` |
| `message` | `Text` | 否 | `NULL` | 日志信息或错误原因 |
| `duration_ms` | `Integer` | 否 | `NULL` | 阶段耗时，单位毫秒 |
| `created_at` | `DateTime` | 是 | `func.now()` | 日志创建时间 |

约束与索引：

| 名称 | 类型 | 字段 | 说明 |
| --- | --- | --- | --- |
| `ix_task_logs_article_stage` | Index | `article_id`, `stage` | 按文章和阶段查看处理过程 |
| `ix_task_logs_created_at` | Index | `created_at` | 按日志时间排序和排查问题 |
| 自动索引 | Index | `article_id` | 加速按文章查询日志 |

外键：

- `article_id -> articles.id`
- `ondelete="CASCADE"`，删除文章时同步删除该文章日志。

### 3.5 `manual_confirmations`

人工确认记录表，保存分析结果被人工修正前后的完整对比。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `id` | `Integer` | 是 | 自增 | 主键 |
| `article_id` | `ForeignKey(articles.id)` | 是 | 无 | 关联文章 |
| `original_product` | `String(128)` | 否 | `NULL` | 修正前品种 |
| `original_direction` | `String(16)` | 否 | `NULL` | 修正前方向 |
| `original_reason` | `Text` | 否 | `NULL` | 修正前理由 |
| `original_confidence` | `Float` | 否 | `NULL` | 修正前置信度 |
| `confirmed_product` | `String(128)` | 是 | 无 | 人工确认后的品种 |
| `confirmed_direction` | `String(16)` | 是 | 无 | 人工确认后的方向 |
| `confirmed_reason` | `Text` | 否 | `NULL` | 人工确认后的理由 |
| `confirmed_confidence` | `Float` | 是 | 无 | 人工确认后的置信度 |
| `confirmed_by` | `String(128)` | 否 | `NULL` | 确认人 |
| `note` | `Text` | 否 | `NULL` | 备注 |
| `confirmed_at` | `DateTime` | 是 | `func.now()` | 确认时间 |

约束与索引：

| 名称 | 类型 | 字段 | 说明 |
| --- | --- | --- | --- |
| `ck_manual_confirmations_direction` | CheckConstraint | `confirmed_direction` | 限制人工确认方向枚举 |
| `ck_manual_confirmations_confidence` | CheckConstraint | `confirmed_confidence` | 限制人工确认置信度为 `0-1` |
| `ix_manual_confirmations_confirmed_at` | Index | `confirmed_at` | 按确认时间查询审计记录 |
| 自动索引 | Index | `article_id` | 加速按文章查询确认记录 |

外键：

- `article_id -> articles.id`
- `ondelete="CASCADE"`，删除文章时同步删除人工确认记录。

## 4. 关系模型

```text
articles
  ├── article_texts          一对一，保存原始、清洗和精修文本
  ├── analysis_results       一对多，保存当前有效多品种分析结果
  ├── task_logs              一对多，保存流水线执行日志
  └── manual_confirmations   一对多，保存人工确认审计记录
```

所有子表外键均使用 `ondelete="CASCADE"`。删除文章时，文本、分析结果、任务日志和人工确认记录会随文章一起删除。

## 5. 设计取舍

### 5.1 当前分析结果按品种/合约保留

`analysis_results` 使用 `(article_id, product, contract_key)` 唯一约束，表示一篇文章可保留多条当前有效结果，但同一品种合约重跑时更新旧结果。

理由：

- 晨会、日报常包含多个期货品种，需要分别进入品种、公司和趋势统计。
- 可避免同一品种合约多次重跑导致重复统计。
- `is_primary` 保留文章级主结果，兼容旧前端字段 `analysis_result`。

如果后续需要分析结果历史，可以新增 `analysis_result_versions` 或增加 `is_current` 字段。

### 5.2 人工确认保留审计记录

人工确认会更新 `analysis_results` 当前结果，同时新增 `manual_confirmations` 记录保存原始值和确认值。

理由：

- 前端读取当前结论时不需要合并多张表。
- 审计记录仍可追踪人工修改前后的变化。
- `analysis_method` 更新为 `manual` 后，前端可以区分人工确认结果。

### 5.3 文本表与文章表分离

`raw_text`、`cleaned_text` 和 `refined_text` 可能很长，单独放在 `article_texts` 中。MySQL 使用 `LONGTEXT`，其他数据库回退到 SQLAlchemy `Text`。

理由：

- 文章列表查询不必默认加载大文本。
- 详情页需要时再读取正文。
- 后续可以独立优化文本存储或全文检索。

### 5.4 `task_logs.article_id` 允许为空

`task_logs.article_id` 允许 `NULL`，用于记录调度器级别的全局日志，例如一次扫描命中数量、触发数量或空扫描。

### 5.5 索引优先服务当前查询

当前索引主要服务：

- 调度器扫描待处理文章：`articles.status + created_at`
- 前端筛选：`company`、`publish_time`、`product`、`direction`
- 趋势聚合：`analysis_time`
- 详情排查：`task_logs.article_id + stage`
- 人工确认审计：`manual_confirmations.confirmed_at`

暂未加入全文索引、版本索引和复杂联合索引，避免第一版过度设计。

## 6. 对其他开发者的约定

### 6.1 给开发者 B

- 流水线不要直接写 SQL，优先通过 Repository 方法更新状态、保存文本、保存分析结果和写日志。
- 正常阶段必须按 `0 -> 1 -> 2 -> 3 -> 4 -> 5` 推进。
- 任意阶段失败必须写入 `status = -1`、`error_msg` 和 `task_logs`。
- `direction` 只能写入 `看涨`、`看跌`、`中性`。
- `confidence` 必须是 `0-1` 小数。

### 6.2 给开发者 C

- 前端展示文章列表、品种、公司和趋势时，以 `analysis_results` 当前有效结果为准。
- `need_manual_review = true` 表示需要人工确认。
- 人工确认成功后，当前分析结果会变成 `analysis_method = "manual"`，且 `need_manual_review = false`。
- 置信度按小数返回，页面展示百分比时自行乘以 `100`。

## 7. 验证方式

当前测试覆盖在 [tests/test_backend_data.py](/home/sanmu/marketANA/tests/test_backend_data.py)：

- 核心表能创建成功。
- `analysis_results` 存在 `(article_id, product, contract_key)` 唯一约束。
- `articles.status` 非法值会触发约束错误。
- 状态流转、失败日志、分析结果幂等覆盖可用。
- 统计、趋势、列表、详情、人工确认接口契约可用。

建议验证命令：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

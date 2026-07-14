# MarketANA 并行开发具体实施计划

> 文档目的：为数据处理、后端、前端三条工作线提供可以直接执行的开发顺序、接口契约和验收标准。
>
> 当前仓库中目录名实际为 `data_proccessing`，本文沿用该目录名；后续如统一改名，应一次性修改导入路径、脚本入口和文档，不在并行开发中混用两种目录名。

## 1. 项目目标与当前基线

### 1.1 最终目标

用户上传或导入一篇 PDF、HTML、图片或文本资讯后，系统能够完成：

```text
文章进入数据库
    -> 文本解析与清洗
    -> 品种识别与标准化
    -> 方向信号提取
    -> 规则/LLM 仲裁
    -> 分析结果和证据入库
    -> 后端 API 返回
    -> 前端展示趋势、文章详情和待复核结果
```

系统必须满足以下要求：

1. 一篇文章可以对应多个期货品种和合约。
2. 每条分析结果必须能够追溯到原文证据。
3. 低置信度、冲突或无法解析的结果不能静默丢失，必须进入人工复核队列。
4. 重跑同一篇文章不能产生重复有效结果。
5. 数据处理模块可以独立运行和测试，不直接依赖前端，也不把原始 JSONL 暴露给前端。

### 1.2 当前已完成部分

目前 `data_proccessing` 已具备独立运行能力：

- `readers/`：文本、HTML、PDF、图片读取器。
- `instrument_mapping/`：品种词典、引导式自发现、运行时匹配和复核队列。
- `signals/`：方向信号提取、证据保留、聚合和冲突仲裁。
- `llm/`：LLM 客户端、上下文构造和严格 JSON 解析。
- `pipeline/`：单文档、批处理、结果输出和处理统计。
- `test_single_file.py`：单文件处理入口，可生成可读报告。
- `evaluation/`：标注数据和指标评估骨架。
- `tests/`：数据处理模块单元测试和隔离测试。

后端和前端也已有基础工程：

- 后端已有文章、文本、分析结果、任务日志、人工确认等模型和查询 API。
- 前端已使用真实 API，具备文章、品种、公司、趋势和详情页的类型定义。

### 1.3 当前主要缺口

并行开发的重点不是重新编写已有模块，而是补齐以下连接点：

1. `data_proccessing` 输出需要通过明确的导入适配层进入后端数据库。
2. 数据处理输出中的 `method`、`product_key`、`evidence` 等字段需要映射到后端字段。
3. `source_id` 必须稳定映射为数据库 `article_id`，不能依赖文章标题或数组下标。
4. 当前证据可能过长或混入其他品种，需要建立“品种级证据”和简短理由的质量门槛。
5. 数据处理运行链路、后端入库链路和前端展示链路需要用同一篇样例文章完成闭环。
6. 后端部分旧代码仍有对 `pn` 模块的依赖。新数据处理链路不得新增此类依赖，清理旧模块前先完成替代接口和回归测试。

## 2. 并行开发原则

### 2.1 三条工作线

| 工作线 | 主要职责 | 允许修改的目录 | 交付物 |
| --- | --- | --- | --- |
| A：数据处理 | 解析、清洗、品种映射、信号分析、LLM fallback、质量评估 | `data_proccessing/` | 标准结果契约、导入适配所需输出、测试集和评估报告 |
| B：后端集成 | 数据库导入、幂等、任务状态、查询 API、人工确认 | `back_end/app/`、`tests/`、`docs/` | 导入服务、接口测试、数据库 read-back 验证 |
| C：前端联调 | API 对接、详情证据、趋势、复核页面、异常状态 | `front_end/src/` | 页面联调、类型检查、演示脚本 |

如果只有一个人开发，仍按 A -> B -> C 的顺序执行；不要先同时修改三层，否则出现问题时无法判断是算法、入库还是展示错误。

### 2.2 共享规则

1. 先改契约和样例，再改实现。
2. 每条工作线只通过文件格式、数据库字段或 HTTP API 对齐，不直接导入另一条工作线的内部模块。
3. 所有方向值只能是 `看涨`、`看跌`、`中性`。
4. 所有分析方法只能是 `rule`、`llm`、`manual`。
5. `product_key` 是稳定主键，展示名称 `product` 不能作为唯一身份。
6. 品种识别结果和方向分析结果是不同实体，不能把每条信号直接当成一条分析结果。
7. 低置信度但方向明确的结果可以入库并标记 `need_manual_review=true`；没有合法方向的结果只进入复核队列，不写入正式分析结果表。
8. 不在前端读取 `results.jsonl`、`evidence.jsonl` 或其他数据处理内部文件。
9. 不在新的数据处理代码中调用 `pn03`、`pn04` 或其他 `pn` 模块。旧模块清理之前，使用独立适配层逐步替换其调用。

## 3. 第一阶段：冻结公共契约（0.5 天）

三条工作线开始前共同确认以下内容，并将示例保存到 `docs/`：

- `docs/data_processing_contract.md`
- `docs/api_mock.md`
- `docs/integration_mapping.md`

### 3.1 数据处理标准输出

数据处理内部可以继续输出多个 JSONL 文件，但对外集成只认一个标准文档结果对象：

```json
{
  "source_id": "stable-source-id",
  "pipeline_version": "dp-0.1.0",
  "document": {
    "title": "文章标题",
    "source": "来源",
    "company": "期货公司",
    "file_type": "pdf",
    "publish_time": "2026-07-12T08:00:00+08:00",
    "raw_text": "原始文本",
    "cleaned_text": "清洗文本"
  },
  "results": [
    {
      "product_key": "DCE.L",
      "product": "LLDPE",
      "contract": null,
      "contract_key": "",
      "direction": "看跌",
      "reason": "需求偏弱且库存压力上升，短期价格偏弱。",
      "confidence": 0.71,
      "analysis_method": "rule",
      "need_manual_review": false,
      "evidence": {
        "summary": "需求偏弱且库存压力上升",
        "source": "cleaned_text",
        "section_type": "core",
        "excerpts": [
          {
            "quote": "需求偏弱，库存继续上升",
            "start_char": 120,
            "end_char": 133,
            "match_type": "reason"
          }
        ],
        "notes": "证据必须与当前 product_key 相关。"
      },
      "metadata": {
        "bullish_score": 0.0,
        "bearish_score": 1.6,
        "neutral_score": 0.0
      }
    }
  ],
  "review_queue": [],
  "processing_stats": {
    "matched_products": 1,
    "signal_count": 2,
    "rule_results": 1,
    "llm_results": 0,
    "error_count": 0
  }
}
```

### 3.2 数据库映射

| 数据处理字段 | 后端字段 | 规则 |
| --- | --- | --- |
| `source_id` | `articles.id` 的外部映射依据 | 优先使用已有 `article_id`；批处理使用规范化 `file_url` 或稳定文件路径匹配 |
| `document.title` | `articles.title` | 必填 |
| `document.source` | `articles.source` | 允许为空 |
| `document.company` | `articles.company` | 允许为空 |
| `document.file_type` | `articles.file_type` | 统一为 `txt/html/pdf/image` 等小写值 |
| `document.publish_time` | `articles.publish_time` | 统一时区和 ISO 8601 格式 |
| `document.raw_text` | `article_texts.raw_text` | 保存原始解析文本 |
| `document.cleaned_text` | `article_texts.cleaned_text` | 保存清洗后文本 |
| `results[].product_key` | `analysis_results.product_key` | 稳定身份，不能为空 |
| `results[].product` | `analysis_results.product` | 展示名 |
| `results[].contract` | `analysis_results.contract` | 只能保存合约信息，不拼入 `product_key` |
| `results[].contract_key` | `analysis_results.contract_key` | 无合约时使用空字符串 |
| `results[].analysis_method` | `analysis_results.analysis_method` | 只允许 `rule/llm/manual` |
| `results[].direction` | `analysis_results.direction` | 只允许三种方向 |
| `results[].evidence` | 产品分段或证据序列化字段 | 必须可回溯到文本位置 |
| `review_queue[]` | 复核队列/产品解析复核记录 | 不写入正式有效结果，除非人工确认 |

### 3.3 文章状态

沿用后端现有状态，不新增含义：

| 状态 | 含义 |
| --- | --- |
| `0` | 待处理 |
| `1` | 解析完成 |
| `2` | 清洗完成 |
| `3` | 规则识别完成 |
| `4` | LLM 推理完成 |
| `5` | 结果已入库 |
| `-1` | 处理失败 |

状态更新必须和对应阶段日志、事务边界一起设计，不能只在页面上修改状态。

## 4. 第二阶段：数据处理工作线 A

目标：把当前独立处理能力稳定为可被后端消费的“纯计算模块”。

### A1. 固定单篇输入和输出

1. 选择一篇真实 PDF 作为 golden article，同时准备 TXT、HTML、图片各一篇。
2. 为每个样例固定 `source_id`、标题、来源、发布时间和预期品种。
3. 明确单文件入口、批处理入口和标准输出入口。
4. 保留现有 `01` 至 `08` 调试产物，但新增一个面向集成的 canonical result 文件或对象。

验收：同一输入重复运行，两次标准输出中的结果顺序、`product_key`、方向和统计字段一致。

### A2. 修正品种级证据质量

1. 每条结果只截取当前品种附近的句子、段落或产品分段。
2. `reason` 限制为 1 至 3 句，面向前端阅读；详细原文只放 `evidence.excerpts`。
3. 证据中不得出现与当前 `product_key` 无关的其他品种关键词，除非原文明确构成比较关系。
4. 每条 excerpt 保存 `quote`、字符起止位置、来源和匹配类型。
5. 无法定位证据时标记 `need_manual_review=true`，不要生成看似确定的理由。

验收：golden article 的每个结果都能在 `cleaned_text` 中定位，前端展示理由不超过合理长度。

### A3. 完善分流和人工复核

1. 明确规则直接通过阈值、LLM fallback、冲突 fallback、解析失败四种路径。
2. 冲突信号不得被错误地判为高置信规则结果。
3. LLM 返回必须经过 JSON、方向、品种和置信度校验。
4. 无方向、无法标准化品种、证据缺失、规则与 LLM 冲突的结果写入 `review_queue`。
5. 复核队列中的每一项必须带原文片段和失败原因。

验收：构造明确看涨、明确看跌、震荡、正负冲突、无品种、无方向六类文本，分流结果符合预期。

### A4. 建立小型标注集和质量门槛

至少准备 20 篇人工标注样例，覆盖：

- PDF、HTML、TXT、图片；
- 单品种和多品种；
- 看涨、看跌、中性和冲突观点；
- 明确观点和隐含观点；
- 有合约和无合约。

记录品种识别准确率、方向准确率、证据可定位率、人工复核率和单篇平均耗时。低于目标的样例必须进入回归测试。

## 5. 第三阶段：后端集成工作线 B

目标：让后端接收数据处理结果并可靠入库，前端只通过 API 读取。

### B1. 实现导入适配层

导入适配层应位于后端 service 或独立 integration 模块，职责限定为：

1. 读取 canonical result。
2. 根据 `source_id` 找到或创建文章。
3. 保存原始文本和清洗文本。
4. 将每个有效 `results[]` 映射为一条 `analysis_results`。
5. 将证据写入后端已有的产品分段/证据结构。
6. 保存处理统计和阶段日志。
7. 将复核项写入复核队列。
8. 在一个事务中完成结果、文本、日志和状态更新。

导入层不能调用前端代码，也不能把 JSONL 路径硬编码到 API 路由中。临时演示可以从文件导入，正式流程应接收内存对象或任务产物引用。

### B2. 做好幂等和版本控制

幂等键至少包含：

```text
(article_id, product_key, contract_key)
```

导入策略：

1. 首次导入：新增文章文本、结果、日志。
2. 同一 `pipeline_version` 重跑：更新当前有效结果，不新增重复结果。
3. 新的 `pipeline_version` 重跑：保留当前有效结果并记录版本，或按项目约定替换，但必须可追溯。
4. 导入失败：事务回滚，文章标记 `-1`，日志记录失败阶段和错误信息。
5. 部分结果失败：有效结果可以保存，但文章和复核队列必须能反映部分失败，不能伪装成完全成功。

### B3. 对齐任务和状态流转

优先完成单篇触发，再接批量调度：

1. `POST /api/tasks/run` 指定 `article_id`。
2. 后端调用数据处理入口或读取该文章对应的处理产物。
3. 处理完成后返回成功数、失败数、复核数和耗时。
4. 单篇链路稳定后，再启用批量任务和并发控制。
5. 旧调度或旧流水线存在 `pn` 依赖时，先用适配层隔离，待新链路回归通过后再清理。

### B4. 验证现有 API 的真实读回

必须使用数据库真实数据验证：

- `GET /api/dashboard/summary`
- `GET /api/articles`
- `GET /api/articles/{id}`
- `GET /api/trends`
- `POST /api/results/{result_id}/confirm`

重点检查：

1. 一个文章详情是否能返回多条分析结果。
2. `product_key`、`contract_key` 是否完整。
3. `evidence` 是否是结构化对象，而非字符串数组。
4. `need_manual_review` 是否能被前端读取。
5. 已确认结果是否会反映到列表、详情和趋势统计。

## 6. 第四阶段：前端工作线 C

目标：前端只依赖后端契约，完整展示结果、证据和复核状态。

### C1. 先用固定 mock 对接页面

在后端导入层完成前，使用与 canonical result 对齐的 API mock 完成：

1. 首页统计卡片。
2. 品种趋势热力图或折线图。
3. 文章列表和筛选。
4. 文章详情中的多品种结果。
5. 方向、置信度、分析方法和人工复核标记。
6. 证据摘要和原文 excerpt 展示。

### C2. 处理所有非正常状态

页面必须覆盖：

- 加载中；
- 无文章；
- 无分析结果；
- 部分结果待复核；
- 文章处理失败；
- API 错误；
- 证据为空或无法定位；
- 一篇文章存在多个品种结果。

不要把 `processing_stats`、规则分数等内部调试字段直接作为主要用户文案。它们可以在详情页折叠区域展示。

### C3. 联调人工确认流程

至少完成一条完整链路：

```text
前端发现 need_manual_review=true
    -> 用户查看品种、方向、理由和证据
    -> 用户提交确认方向/品种/理由/置信度
    -> 后端写入 manual_confirmations
    -> 当前结果变为 manual
    -> 列表、详情和趋势重新读取后保持一致
```

品种别名复核和方向复核要区分：前者解决 `product_key`，后者解决方向结论，不能共用含义不清的按钮或状态。

## 7. 第五阶段：按依赖关系进行集成

### 7.1 推荐执行顺序

```text
阶段 0：冻结契约和 golden article
          |
          +--> A：数据处理 canonical output
          |
          +--> B：数据库导入 mock + 幂等测试
          |
          +--> C：前端 API mock 页面
                         |
阶段 1：A 输出接入 B 的真实导入层
                         |
阶段 2：B 的真实数据库接入 C 的 API
                         |
阶段 3：单篇端到端回归
                         |
阶段 4：批量、人工复核、异常和性能验收
```

### 7.2 单篇 golden article 联调清单

1. 数据处理读取样例文件。
2. 输出标准结果和可读报告。
3. 后端创建或找到对应 `article_id`。
4. 导入原文、清洗文本、产品结果、证据和日志。
5. 检查数据库中的文章状态是否为 `5`。
6. 调用文章详情 API，核对所有字段。
7. 打开前端详情页，核对品种、方向、理由、置信度和证据。
8. 调用趋势 API，核对方向值与热力图正负值。
9. 对低置信结果执行人工确认。
10. 再次读取列表、详情和趋势，确认数据一致。

### 7.3 多格式和多品种联调

单篇闭环通过后，使用至少 10 篇样例：

| 类型 | 最低数量 | 必须覆盖 |
| --- | ---: | --- |
| TXT | 2 | 明确看涨、看跌 |
| HTML | 2 | 清洗噪声、表格或标题 |
| PDF | 3 | 多页、多品种、证据定位 |
| 图片 | 2 | OCR、低质量文本、待复核 |
| 冲突/异常文本 | 1 | 冲突方向或无法识别 |

检查是否出现重复结果、错误品种串证据、空方向入库、状态错误和趋势重复计数。

## 8. 测试计划

### 8.1 数据处理测试

- 读取器：TXT、HTML、PDF、图片和不支持格式。
- 品种映射：标准名、别名、合约、未知品种、复核队列。
- 信号提取：看涨、看跌、中性、上下文否定和冲突。
- 仲裁：规则通过、LLM fallback、强冲突和 LLM 失败。
- 输出：JSON 可序列化、字段完整、结果顺序稳定。
- 证据：每条证据可定位、长度受控、品种范围正确。
- 隔离：数据处理包不导入 `pn03`、`pn04` 或后端内部模块。

### 8.2 后端测试

- canonical result 导入成功。
- 缺少必填字段时拒绝导入并记录错误。
- 方向、方法、置信度非法时拒绝导入。
- 同一文章重复导入不产生重复结果。
- 多品种文章保存多条结果。
- 复核队列和人工确认记录可读回。
- 文章状态按阶段推进，失败事务回滚。
- dashboard、articles、detail、trends 返回结构稳定。

### 8.3 前端测试

- API 类型与真实返回一致。
- 多结果详情显示正确。
- 证据 excerpt 展示和空值处理正确。
- 低置信度标记和人工确认交互正确。
- 过滤、分页、趋势切换和空状态正确。
- `npm run build` 和 `npm run type-check` 通过。

### 8.4 端到端测试

端到端测试不依赖外部 LLM，默认使用 fake LLM 或 `--skip-llm`，保证可重复。另行安排一轮真实 LLM 冒烟测试，只验证调用、超时、重试和解析，不把模型随机结果作为稳定单元测试断言。

## 9. 分支、提交和协作约定

### 9.1 分支建议

- `feature/data-processing-contract`
- `feature/backend-ingestion`
- `feature/frontend-integration`
- `integration/golden-article`

### 9.2 提交粒度

每个提交只完成一个可验证目标，例如：

- `data: add canonical result contract`
- `data: scope evidence by product`
- `backend: import canonical analysis result`
- `backend: make result import idempotent`
- `frontend: render structured evidence`
- `test: add golden article e2e fixture`

不要在同一个提交里同时改算法、数据库结构和页面样式。数据库字段变更必须同时提交迁移、模型、序列化和测试。

### 9.3 每日同步内容

每条工作线每天只需要同步四项：

1. 已完成的接口或文件。
2. 当前使用的契约版本。
3. 阻塞点和需要其他工作线提供的最小信息。
4. 可复现的测试命令和结果。

## 10. 里程碑与完成定义

### M1：契约冻结

- 标准输出字段、枚举和数据库映射已确认。
- golden article 已固定。
- 前后端 mock 可以独立运行。

### M2：数据处理可交付

- 单文件和批处理均可运行。
- 所有正式结果有标准 `product_key`、方向、理由和证据。
- 冲突、低置信和未知品种进入复核队列。
- 数据处理测试通过，至少 20 篇标注样例可评估。

### M3：后端可交付

- canonical result 可以事务化导入数据库。
- 重跑幂等。
- 文章详情 API 可返回多品种结果和结构化证据。
- 状态、日志、复核和人工确认链路可追踪。

### M4：前端可交付

- 首页、列表、详情和趋势使用真实 API。
- 多品种、低置信、失败和空数据状态可展示。
- 人工确认后页面结果和趋势正确更新。

### M5：项目验收

- 至少 10 篇混合格式文章完成端到端处理。
- 规则、LLM、人工复核三条路径至少各验证一次。
- 后端测试、数据处理测试、前端 build/type-check 全部通过。
- 没有重复结果、空方向正式结果、跨品种证据和无法解释的状态跳转。
- 输出接口文档、运行说明、测试报告和演示脚本。

## 11. 建议的实际执行顺序

如果现在立即开始，按下面顺序执行：

1. 先在 `docs/` 固定 canonical result 示例和字段映射表。
2. 用当前 `data_proccessing/output/demo` 作为第一份 golden article，人工检查每条证据是否属于对应品种。
3. 数据处理线先修正短 `reason`、品种级 evidence 和冲突分流。
4. 后端线用固定 JSON 做导入适配和幂等测试，不等待真实算法完成。
5. 前端线用后端 API 形状的 mock 完成多结果详情和复核状态展示。
6. 将 golden article 导入数据库，逐字段调用详情 API 核对。
7. 前端切换真实 API，完成单篇闭环。
8. 扩展到 10 篇混合格式样例，修复跨模块问题。
9. 最后再接批量调度、真实 LLM、性能测试和旧 `pn` 模块清理。

优先级必须保持为：

```text
契约一致性 > 单篇端到端正确 > 证据可追溯 > 幂等和异常 > 批量性能 > 页面美化
```

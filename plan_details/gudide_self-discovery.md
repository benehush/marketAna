# Guided Self-Discovery 品种关键词映射表

## Summary
在 `data_proccessing/` 中新建一套独立的数据处理 v1 模块，第一步只负责“品种关键词映射表”构建。方案采用“权威种子目录 + 原始语料自发现 + 证据评分 + 人工审核队列”，不依赖旧清洗/分段/规则流程；现有 `pn06` 目录仅作为第一版标准品种宇宙的参考基准。

## Key Changes
- 新建 `data_proccessing/instrument_mapping/` 包，包含：
  - 标准品种种子目录：国内期货品种 `product_key / display_name / official_name / exchange / symbol / group / seed_aliases`。
  - 自发现引擎：直接扫描 `raw_text`、标题、文件名、OCR 文本，不要求全文清洗。
  - 映射产物：`instrument_lexicon.json`、`alias_candidates.jsonl`、`build_report.json`。
  - 可复用 API：`build_instrument_lexicon(documents, config) -> LexiconBuildResult`。

- 候选发现算法：
  - 强信号：`【品种】`、`品种：`、`商品：`、`[中文名]期货/合约/主力`、`[A-Z]{1,5}\d{2,4}合约`、交易所代码如 `RB/SC/PTA/IF/TL`。
  - 弱信号：标题/文件名中的品种词、板块标题后的品种枚举、短句内靠近“涨跌/库存/基差/开工/利润/持仓”的名词片段。
  - OCR 容错：处理全角半角、大小写、空白断裂、`L 2505`/`L2505`、`P TA`、常见括号和冒号变体。
  - 负例过滤：排除邮箱域名、证书号、页码、机构名、宏观泛词、外盘前缀误配，如 `COMEX黄金`、`LME铜`、`美豆油` 不映射到国内品种。

- 候选归一与打分：
  - 对每个候选建立证据包：出现次数、文档数、标题命中、括号标题命中、合约代码邻近、方向信号邻近、所属上下文、样例片段。
  - 用四级决策：
    - `approved_seed`：种子目录内确定别名，直接进入映射表。
    - `auto_approved`：符号/合约/官方名高置信命中，自动绑定标准品种。
    - `review_required`：疑似新别名或冲突别名，进入审核队列。
    - `rejected`：命中过滤规则或分数不足。
  - 冲突解决优先级：人工别名 > 官方名/交易所符号 > 标题强证据 > 语境统计；长别名优先于短别名，具体品种优先于板块聚合词。

- 映射表结构：
  - 每个标准品种保存 `canonical`、`symbol`、`aliases`、`contract_patterns`、`negative_contexts`、`confidence`、`evidence_count`。
  - 未归属候选保存为审核项，包含 `raw_alias`、`suggested_product_key`、`score`、`evidence_snippets`、`source_docs`。
  - 第一版不改数据库；后续可把审核项接入现有前端产品审核流。

## Algorithm Details
- 扫描阶段保持 O(n)：每篇文章只做一次字符级 pass，使用预编译正则和滑动窗口。
- 先发现“锚点”，再扩展别名：例如 `L2505合约` 锚定 `DCE.L`，同文档标题里的 `聚乙烯`、正文里的 `PE` 会被提升为候选别名。
- 引入“证据三角定位”：
  - 形态证据：像不像品种名或合约代码。
  - 目录证据：是否可被标准品种、官方名、交易所代码解释。
  - 语境证据：是否靠近价格、涨跌、库存、基差、供需等期货语境。
- 只有三类证据中至少两类成立，才自动进入映射表；否则进入审核队列，避免追求覆盖率导致脏别名污染全局。

## Test Plan
- 单元测试：
  - `RB2505合约`、`PTA05 合约`、`【铁矿石】`、`商品：碳酸锂` 能正确发现并映射。
  - `qh168.com.cn`、证书号、页码、`COMEX黄金`、`LME铜`、`美豆油` 不产生国内品种误配。
  - `欧集线`、`LU燃油`、OCR 断裂代码进入正确的自动通过或审核队列。
- 样本回归：
  - 用 `tests/outputs/01_parsed_raw_text.txt` 验证脏 PDF 文本仍能发现股指、黄金、白银、钢材、铁矿石、原油、PTA、乙二醇等锚点。
  - 用 `tests/outputs/zs323354/01_parsed_raw_text.txt` 验证 OCR 文本中 `L/LLDPE/聚乙烯/PE` 能聚合到 `DCE.L`。
- 验证命令：
  - `uv run pytest data_proccessing/instrument_mapping/tests`
  - 增加一个只读样本构建命令，输出覆盖率、候选数、自动通过率、需审核 Top N。

## Assumptions
- 保留目录名拼写 `data_proccessing`，不新建 `data_processing`。
- 第一阶段只构建“品种关键词映射表”，不实现方向判断、分段、LLM 兜底或数据库迁移。
- 允许使用标准期货品种目录作为种子，但新模块不运行旧清洗/分段/matcher 代码。
- 默认优先精度：自动写入映射表的别名必须高置信；低置信候选宁可进入审核队列。

# 修复分段断句、豆油误识别与 Evidence 匹配

## Summary
修复东海期货豆油案例中“结论依据”断在“跌幅”的问题，并减少 `美豆油` 被误判为国内品种 `豆油`。同时让详情页 evidence 优先选择与 `reason` 语义更接近的分段，避免规则结论和展示依据不一致。

## Key Changes
- 调整品种分段断句：
  - 修改 `pn05.product_segmenter._sentence_spans()`，普通单换行不再作为句子边界，只按 `。！？；` 分句。
  - 保留文本原始 start/end 偏移，避免影响 evidence 定位。
  - 结果中豆油段应包含 `跌幅 2.92%` 以及后续完整句子。
- 修复 `美豆油` 误识别：
  - 在 `pn06.product_dict.detect_products()` 中把 alias 匹配从简单 `text.count()` 改为带边界/排除规则的计数。
  - 对 `豆油` alias 增加负向前缀排除：不匹配 `美豆油`，但仍匹配 `豆油`、`豆油期货`、`Y豆油`。
  - 同步让 `pn05.product_segmenter._mentions_product()` 使用同一类匹配逻辑，避免分段和规则识别结果不一致。
- 改进 evidence 选择：
  - 修改 `back_end.app.api.serializers._best_segment_for_result()`，候选分段先按 `reason` 与 `cleaned_text/refined_text` 的关键词重合度打分。
  - 若某个分段直接包含 reason 短语或多个 reason 关键词，优先选它；否则回退当前 section 优先级、confidence、segment_index 排序。
  - 对过短且明显不完整的分段降权，例如结尾为 `跌幅`、`涨幅`、`同比`、`环比`、`产地`、`等待` 等未完成词时，不作为首选。

## Public API / Types
- 不新增数据库字段，不改 API 字段名。
- `analysis_result.evidence.cleaned_text/refined_text/excerpts` 可能变为更完整、更匹配 reason 的片段。
- 已有数据需要重新跑 `product_segmenter/refiner/rule_engine` 后才能修复持久化分段；API evidence 匹配改进会对已有多个分段的数据即时生效。

## Test Plan
- `pn05/test_product_segmenter.py`
  - 添加东海豆油样例：`跌幅\n2.92%` 不应被切断，豆油分段应包含 `跌幅 2.92%` 或至少同时包含 `跌幅` 与 `2.92%`。
  - 添加 `美豆油` 场景：棕榈油段中出现 `美豆油波动加剧` 时，不应生成单独豆油分段。
- `pn06/test_rule_engine.py`
  - 添加产品识别单测：`美豆油受政策影响波动增加` 不识别为 `豆油`；`豆油库存下降` 仍识别为 `豆油`。
- `tests/test_backend_data.py`
  - 构造同一品种多个分段，一个断在 `跌幅`，另一个包含 reason 关键词；断言详情 API 选择更匹配、更完整的 evidence。
- 回归运行：
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest pn05/test_product_segmenter.py pn06/test_rule_engine.py tests/test_backend_data.py`

## Assumptions
- 本次只修规则和分段选择，不引入新的 LLM 调用。
- `美豆油` 作为外盘/相关市场描述，不等同于国内期货品种 `豆油`。
- 普通单换行视为 PDF 折行，不视为句子边界；段落或标题边界仍由已有 `【品种】`/标题切分逻辑负责。

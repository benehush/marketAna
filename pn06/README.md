# pn06 规则识别模块 RuleEngine

## 概述

使用标准品种目录、最长优先匹配和正则规则识别期货品种及走势方向（看涨/看跌/中性）。
高置信度（≥0.7）直接入库，低成本处理明确观点文章；低置信度交由 pn07 LLMInfer。

## 目录结构

```
pn06/
├── __init__.py          # 导出 analyze_article, RuleConfig
├── rule_engine.py       # 主引擎：流程编排 + 入库决策
├── product_catalog.py   # 境内期货标准目录与稳定 product_key
├── product_dict.py      # 确定性 ProductMatcher 与兼容词典
├── product_resolver.py  # 未知品种批量 LLM 归一化
├── direction_rules.py   # 方向关键词 + 正则模式 + 理由窗口
├── confidence.py        # 置信度评分器
├── models.py            # RuleConfig, RuleResult
├── test_rule_engine.py  # 单元测试
└── README.md            # 本文档
```

## 决策流程

```
cleaned_text
  → 品种检测 (product_dict)
  → 方向检测 (direction_rules)
  → 置信度计算 (confidence)
  → decision:
      ≥ 0.7 → save_analysis_result → status=5 (STORED) ✅
      < 0.7 → status=3 (RULE_ANALYZED) → pn07 LLMInfer
```

## 使用方法

```python
from pn06 import analyze_article

result = analyze_article(article_id, session)
print(result.product)      # "螺纹钢"
print(result.direction)    # "看涨"
print(result.confidence)   # 0.85
print(result.need_llm)     # False → 已直接入库
```

## 扩展品种

新增正式上市品种时编辑 `product_catalog.py` 中的 `PRODUCT_CATALOG`。文章中的机构简称不直接改静态目录：先在“品种审核”确认当前文章，再批准生成的动态别名。

```python
_p("EXCHANGE.CODE", "展示名", "官方名", "EXCHANGE", "CODE", "品种组", "明确别名")
```

## 测试

```bash
uv run pytest pn06/ -v
```

# pn05 数据清洗模块 Cleaner

## 概述

清洗 pn04 Parser 输出的 `raw_text`，移除广告、免责声明、HTML 残留、异常空白、低密度噪声块和 OCR 数字图表噪声，输出轻量 Markdown 文本供 pn06/pn07 分析；清洗后可通过 LLM 精修生成用户展示用的 `refined_text`。

## 目录结构

```
pn05/
├── __init__.py          # 导出 clean_article, refine_article, CleanConfig
├── cleaner.py           # 主清洗器：流程编排 + Repository 集成
├── refiner.py           # LLM 精修器：cleaned_text → refined_text
├── structured_cleaner.py # pn04 模板分区清洗 + OCR 数字噪声压制
├── normalizer.py        # 文本规范化（空白、全半角、HTML 残留、编码）
├── noise_rules.py       # 噪声规则库（行级关键词 + 正则段落模式）
├── models.py            # CleanConfig, CleanResult
├── test_cleaner.py      # 单元测试
└── README.md            # 本文档
```

## 清洗流程

```
raw_text
  → 编码检测修复    (detect_and_clean_encoding)
  → HTML 残留移除   (remove_html_residue)
  → pn04 模板分区    (# 标题 / 正文 / 表格 / 图片 OCR / AI 解读)
  → 分区噪声过滤    (filter_noise_lines + filter_noise_regex)
  → OCR 数字噪声压制 (坐标轴日期、刻度、纯数字图例)
  → 空白/全半角规范化
  → 轻量 Markdown 输出
  → cleaned_text     → 写入 article_texts + status=2
  → LLM 精修          → refined_text（失败不中断）
```

默认输出模板：

```text
# <标题>

## 文档信息
来源文件: ...
解析器: ...

## 核心正文
...

## 表格与数据
...

## 图文识别正文
...

## AI图表解读
...
```

## 使用方法

```python
from pn05 import clean_article, refine_article, CleanConfig

config = CleanConfig(
    min_density_ratio=0.15,   # 中文密度阈值
    filter_low_density=True,  # 移除页眉页脚
    structured_output=True,   # 输出轻量 Markdown 模板
    drop_numeric_dominant_blocks=True,  # 删除价格曲线 OCR 数字噪声
)

cleaned = clean_article(article_id, session, config=config)
# cleaned_text 已写入，status 已更新为 2 (CLEANED)

refined = refine_article(article_id, session)
# refined_text 已写入；若 LLM 未配置或调用失败，返回 None 并保留 cleaned_text
```

## 噪声规则扩展

编辑 `noise_rules.py` 中的列表即可扩展规则：

```python
# 新增行级关键词
NOISE_LINE_KEYWORDS.append("新广告词")

# 新增正则段落模式
NOISE_REGEX_PATTERNS.append(r"新广告标题[\s\S]*?(?=\n\n|\Z)")
```

OCR 价格曲线常见的横轴日期串、纵轴刻度、纯数字图例由 `structured_cleaner.py`
按行/连续块删除；正文句子里的有效数字会保留，例如“收于 3650 元/吨”。

## 测试

```bash
uv run pytest pn05/ -v
```

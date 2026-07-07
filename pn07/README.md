# pn07 LLM 推理模块 LLMInfer

## 概述

对 pn06 RuleEngine 无法高置信识别的文章，调用大语言模型（OpenAI 兼容 API）进行推理。通过结构化 Prompt 强制输出 JSON，解析后入库。低置信（<0.5）自动标记 `need_manual_review`。

## 目录结构

```
pn07/
├── __init__.py          # 导出 infer_article, LLMConfig
├── llm_infer.py         # 主入口：编排完整推理流程
├── llm_client.py        # httpx OpenAI 兼容 API 客户端（含重试）
├── prompt_builder.py    # System/User prompt 模板
├── json_parser.py       # JSON 提取 + 修复 + 字段校验
├── models.py            # LLMConfig, InferResult
├── test_llm_infer.py    # 单元测试（mock HTTP）
└── README.md            # 本文档
```

## 使用方法

```python
from pn07 import infer_article, LLMConfig

# 使用 .env 配置
config = LLMConfig.from_settings()

result = infer_article(article_id, session, config=config)
print(result.product)           # "螺纹钢"
print(result.direction)         # "看涨"
print(result.confidence)        # 0.82
print(result.need_manual_review) # False
```

## 配置

在 `.env` 中设置：

```env
LLM_PROVIDER=wenhua
LLM_API_KEY=
LLM_BASE_URL=https://swarm.wenhua.com.cn/aiservice/api/ShiXi/GetContent
LLM_MODEL=wenhua-shixi
LLM_TIMEOUT_SECONDS=30
```

`LLM_PROVIDER=openai` 时仍使用 OpenAI 兼容接口 `/v1/chat/completions`；
`LLM_PROVIDER=wenhua` 时使用文华 `GetContent` 接口，并按 SSE 流式响应拼接 `choices[].delta.content`，直到 `finish_reason="stop"`。

## JSON 解析能力

| 异常格式 | 修复策略 |
|---------|---------|
| ` ```json ... ``` ` | 提取代码块 |
| `{...}` 前后有文字 | 正则提取 |
| `,}` 尾部逗号 | 正则移除 |
| `'key':'value'` 单引号 | 替换双引号 |
| 字段缺失 | 填充 null |
| direction 非法值 | 置 null |
| confidence 越界 | clamp 0-1 |

## 测试

```bash
uv run pytest pn07/ -v
```

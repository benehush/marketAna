# pn11 流水线联调与异常处理

## 概述

将 pn03-pn07 串成完整的端到端流水线。提供 `run_pipeline`（单篇）和 `batch_process`（批量并发）两个入口。

## 使用

```python
from pn11 import run_pipeline, batch_process

# 单篇处理 — 作为 pn03 Scheduler 的 callback
scheduler = Scheduler(
    session_factory=...,
    pipeline_callback=run_pipeline,
)

# 批量处理
results = batch_process([1,2,3], session_factory, max_concurrency=5)
print(results.summary())  # 批量处理完成: 3篇, 成功=3, 失败=0
```

## 状态路由

```
status=0  → parser → cleaner → refiner → rule_engine → (llm_infer) → stored
status=1  → cleaner → refiner → rule_engine → (llm_infer) → stored
status=2  → refiner → rule_engine → (llm_infer) → stored
status=3  → llm_infer → stored
status=5  → 跳过（已完成）
status=-1 → 根据 error_msg 判断失败阶段，重置后重试
```

## 测试

```bash
uv run pytest pn11/ -v
```

# canonical result 到数据库映射

| canonical 字段 | 数据库字段 | 说明 |
| --- | --- | --- |
| `source_id` | `articles.file_url` / 调用方 `article_id` | 不能使用标题或数组下标作为身份 |
| `document.title/source/company/file_type/publish_time` | `articles.*` | 文件类型统一小写 |
| `document.raw_text/cleaned_text` | `article_texts.raw_text/cleaned_text` | 导入与结果在同一事务 |
| `results.product_key/product/contract/contract_key` | `analysis_results.*` | 幂等键为 `(article_id, product_key, contract_key)` |
| `results.analysis_method/direction/reason/confidence/need_manual_review` | `analysis_results.*` | 只接受固定枚举和 0-1 置信度 |
| `results.evidence` | `analysis_results.evidence_json` | 保留结构化 excerpt 与字符位置 |
| `review_queue[]` | `analysis_review_queue` | 正式结果之外的失败、冲突和未知品种 |
| `processing_stats` | `task_logs.message` | 统计用于审计，不作为主要展示文案 |

文章状态沿用 `0 -> 1 -> 2 -> 3/4 -> 5`，失败为 `-1`。导入层只在 canonical 校验通过后写入；异常由调用方回滚并记录失败日志。

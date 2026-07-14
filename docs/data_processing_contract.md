# 数据处理 canonical result 契约

`data_proccessing.pipeline.to_canonical_result()` 是数据处理与后端之间唯一的结果边界。后端不得读取 `results.jsonl`、`evidence.jsonl` 等调试产物。

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
    "raw_text": "原文",
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
            "match_type": "reason",
            "source": "cleaned_text"
          }
        ],
        "notes": "证据必须与当前 product_key 相关。"
      },
      "metadata": {}
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

枚举固定为：方向 `看涨/看跌/中性`，方法 `rule/llm/manual`。正式结果必须有 `product_key` 和合法方向；证据无法定位时必须把 `need_manual_review` 设为 `true`。

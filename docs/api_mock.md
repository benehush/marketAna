# MarketANA API Mock Contract

本文档用于对齐当前前端初版页面的真实接口需求。前端代码位置：

- API client: `front_end/src/api/client.ts`
- TypeScript types: `front_end/src/api/types.ts`
- Mock data: `front_end/src/mock/*.json`

当前前端打开了 `USE_MOCK = true`。切到真实后端时，会直接请求 `http://localhost:8000` 下的 4 个接口：

- `GET /api/products`
- `GET /api/companies`
- `GET /api/trends`
- `GET /api/articles`

## 1. Unified Response

所有接口统一返回：

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

前端当前类型为：

```ts
export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}
```

注意：当前前端没有处理 `data: null`，真实接口报错时可以返回 `data: null`，但成功响应必须保证 `data` 类型稳定。

错误响应建议：

```json
{
  "code": 10001,
  "message": "Request validation failed",
  "data": null,
  "detail": []
}
```

## 2. Shared Enums

方向枚举固定：

```ts
type Direction = "看涨" | "看跌" | "中性"
```

置信度统一使用 `0-1` 小数，前端会渲染为百分比：

```ts
(confidence * 100).toFixed(0) + "%"
```

趋势热力图的 `value` 规则：

- `value > 0`：看涨强度
- `value < 0`：看跌强度
- `value = 0`：中性

## 3. Products Page

### `GET /api/products`

用于“品种”页面。前端期望 `data` 直接是数组。

Type:

```ts
interface ProductItem {
  product: string
  predictions: Prediction[]
}

interface Prediction {
  direction: "看涨" | "看跌" | "中性"
  confidence: number
  company: string
  date: string
  reason?: string
}
```

Response mock:

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "product": "螺纹钢",
      "predictions": [
        {
          "direction": "看涨",
          "confidence": 0.82,
          "company": "南华期货",
          "date": "2026-06-15",
          "reason": "基建投资加速，需求端支撑较强"
        },
        {
          "direction": "看跌",
          "confidence": 0.63,
          "company": "中信期货",
          "date": "2026-06-16",
          "reason": "房地产开工不及预期，库存累积"
        }
      ]
    },
    {
      "product": "铁矿石",
      "predictions": [
        {
          "direction": "看涨",
          "confidence": 0.75,
          "company": "永安期货",
          "date": "2026-06-14",
          "reason": "海外发运减少，港口库存下降"
        },
        {
          "direction": "中性",
          "confidence": 0.52,
          "company": "国泰君安",
          "date": "2026-06-17",
          "reason": "供需双弱，短期震荡"
        }
      ]
    }
  ]
}
```

Empty response:

```json
{
  "code": 0,
  "message": "ok",
  "data": []
}
```

后端映射建议：

- 从 `analysis_results.product` 分组。
- 每条 `predictions[]` 来自一条有效分析结果。
- `date` 优先取 `articles.publish_time` 的日期部分；没有发布时间时取 `analysis_results.analysis_time` 的日期部分。
- `company` 取 `articles.company`，为空时可用空字符串或来源名兜底。
- `reason` 取 `analysis_results.reason`。

## 4. Companies Page

### `GET /api/companies`

用于“期货公司”页面。前端期望 `data` 直接是数组。

Type:

```ts
interface CompanyItem {
  company: string
  predictions: {
    product: string
    direction: "看涨" | "看跌" | "中性"
    confidence: number
    date: string
  }[]
}
```

Response mock:

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "company": "南华期货",
      "predictions": [
        {
          "product": "螺纹钢",
          "direction": "看涨",
          "confidence": 0.82,
          "date": "2026-06-15"
        },
        {
          "product": "沪铜",
          "direction": "看涨",
          "confidence": 0.7,
          "date": "2026-06-15"
        }
      ]
    },
    {
      "company": "中信期货",
      "predictions": [
        {
          "product": "豆粕",
          "direction": "看跌",
          "confidence": 0.65,
          "date": "2026-06-16"
        }
      ]
    }
  ]
}
```

Empty response:

```json
{
  "code": 0,
  "message": "ok",
  "data": []
}
```

后端映射建议：

- 从 `articles.company` 分组。
- `predictions[].product` 取 `analysis_results.product`。
- `predictions[].date` 优先取 `articles.publish_time` 的日期部分。

## 5. Trends Page

### `GET /api/trends`

用于“趋势分析”页面热力图。前端当前不传 query 参数，期望一次性返回所有热力图点位。

Type:

```ts
interface HeatmapData {
  date: string
  product: string
  value: number
}
```

Response mock:

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "date": "2026-06-01",
      "product": "螺纹钢",
      "value": 0.8
    },
    {
      "date": "2026-06-02",
      "product": "螺纹钢",
      "value": -0.3
    },
    {
      "date": "2026-06-01",
      "product": "豆粕",
      "value": -0.6
    },
    {
      "date": "2026-06-02",
      "product": "沪铜",
      "value": 0
    }
  ]
}
```

Empty response:

```json
{
  "code": 0,
  "message": "ok",
  "data": []
}
```

后端映射建议：

- 当前前端需要的是热力图强度，不是 `{ direction, count }` 聚合行。
- 可按 `date + product` 聚合，将方向转为分值后取平均或加权平均：
  - `看涨` -> `+confidence`
  - `看跌` -> `-confidence`
  - `中性` -> `0`
- `value` 建议限制在 `[-1, 1]`。

如果后端仍保留 pn09 原始趋势接口 `{ items: [{ date, product, direction, count }] }`，需要新增一个前端适配接口，或在 `client.ts` 增加转换逻辑。当前“直接适配前端初版”的选择是让 `/api/trends` 返回 `HeatmapData[]`。

## 6. Articles Page

### `GET /api/articles`

用于“资讯”页面。前端当前不传筛选和分页参数，期望 `data` 直接是数组。

Type:

```ts
interface ArticleItem {
  id: number
  title: string
  source: string
  company: string
  publish_time: string
  summary?: string
  url?: string
}
```

Response mock:

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "id": 1,
      "title": "螺纹钢市场周报：需求边际回暖，短期支撑较强",
      "source": "南华期货",
      "company": "南华期货",
      "publish_time": "2026-06-15",
      "summary": "本周螺纹钢表需环比回升，库存去化加速，短期价格有支撑。",
      "url": "/files/rebar-weekly.html"
    },
    {
      "id": 2,
      "title": "铁矿石：海外发运回落，港口库存下降",
      "source": "永安期货",
      "company": "永安期货",
      "publish_time": "2026-06-14",
      "summary": "澳大利亚和巴西发运量均出现回落，港口库存由增转降，矿价偏强运行。",
      "url": "/files/iron-ore.html"
    }
  ]
}
```

Empty response:

```json
{
  "code": 0,
  "message": "ok",
  "data": []
}
```

后端映射建议：

- `id` 取 `articles.id`。
- `title` 取 `articles.title`。
- `source` 取 `articles.source`，为空时可用 `articles.company`。
- `company` 取 `articles.company`，为空时可用空字符串。
- `publish_time` 当前前端 mock 使用日期字符串 `YYYY-MM-DD`；建议真实接口也返回日期部分，避免页面显示过长。
- `summary` 可先取 `analysis_results.reason`，没有分析结果时优先取 `article_texts.refined_text`，再回退 `article_texts.cleaned_text` 前 80-120 字。
- `url` 可映射 `articles.file_url`。当前组件尚未渲染 `url`，但类型已预留。

## 7. Current Frontend Gaps

以下 pn09 原接口当前前端初版没有调用：

- `GET /api/dashboard/summary`
- `GET /api/articles/{article_id}`
- `POST /api/tasks/run`
- `POST /api/results/{result_id}/confirm`

这些接口可以保留给后续 dashboard、详情页、手动刷新和人工确认功能，但不要作为当前初版页面的必需联调项。

## 8. Backend Raw Contracts Reserved For Later

后续如果前端扩展详情页和人工确认，可继续使用以下后端原始契约。

### `GET /api/dashboard/summary`

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "today_articles": 12,
    "total_articles": 86,
    "success_count": 72,
    "failed_count": 3,
    "success_rate": 0.8372,
    "manual_review_count": 5,
    "direction_distribution": {
      "看涨": 31,
      "看跌": 24,
      "中性": 17
    }
  }
}
```

### `GET /api/articles/{article_id}`

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "article": {
      "id": 101,
      "title": "豆粕短期需求改善",
      "source": "日报",
      "company": "甲期货",
      "file_url": "/files/soymeal.html",
      "file_type": "html",
      "publish_time": "2026-07-02T09:00:00",
      "status": 5,
      "error_msg": null,
      "created_at": "2026-07-02T09:05:00",
      "updated_at": "2026-07-02T09:08:00",
      "product": "豆粕",
      "direction": "看涨",
      "reason": "下游补库增加，库存压力缓解。",
      "confidence": 0.82,
      "need_manual_review": false,
      "analysis_time": "2026-07-02T09:08:00"
    },
    "text": {
      "id": 501,
      "article_id": 101,
      "raw_text": "原始正文...",
      "cleaned_text": "清洗后正文...",
      "refined_text": "精修后展示正文...",
      "raw_length": 2034,
      "cleaned_length": 1680,
      "refined_length": 1520,
      "parser_type": "html",
      "created_at": "2026-07-02T09:06:00",
      "updated_at": "2026-07-02T09:07:00"
    },
    "analysis_result": {
      "id": 201,
      "article_id": 101,
      "product": "豆粕",
      "direction": "看涨",
      "reason": "下游补库增加，库存压力缓解。",
      "confidence": 0.82,
      "analysis_method": "llm",
      "need_manual_review": false,
      "analysis_time": "2026-07-02T09:08:00"
    },
    "task_logs": [
      {
        "id": 1,
        "article_id": 101,
        "stage": "llm",
        "status": "success",
        "message": "ok",
        "duration_ms": 430,
        "created_at": "2026-07-02T09:08:00"
      }
    ],
    "manual_confirmations": []
  }
}
```

### `POST /api/tasks/run`

Request:

```json
{
  "article_id": null,
  "limit": 20
}
```

Response:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "triggered": false,
    "article_id": null,
    "limit": 20,
    "message": "Pipeline runner is not wired yet"
  }
}
```

### `POST /api/results/{result_id}/confirm`

Request:

```json
{
  "product": "豆粕",
  "direction": "看涨",
  "reason": "人工确认需求改善。",
  "confidence": 0.9,
  "confirmed_by": "analyst",
  "note": "修正低置信 LLM 结果"
}
```

Response:

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "id": 301,
    "article_id": 101,
    "original_product": "豆粕",
    "original_direction": "中性",
    "original_reason": "震荡整理。",
    "original_confidence": 0.45,
    "confirmed_product": "豆粕",
    "confirmed_direction": "看涨",
    "confirmed_reason": "人工确认需求改善。",
    "confirmed_confidence": 0.9,
    "confirmed_by": "analyst",
    "note": "修正低置信 LLM 结果",
    "confirmed_at": "2026-07-02T10:00:00"
  }
}
```

## 9. Acceptance Checklist

- `/api/products` 返回 `ProductItem[]`，品种页可渲染卡片和展开预测。
- `/api/companies` 返回 `CompanyItem[]`，公司页可渲染公司卡片和预测列表。
- `/api/trends` 返回 `HeatmapData[]`，热力图可按 `date/product/value` 渲染。
- `/api/articles` 返回 `ArticleItem[]`，资讯页可渲染标题、来源、日期和摘要。
- 所有成功响应保持 `code: 0`、`message: "ok"`。
- 当前初版接口不要返回分页对象 `{ items, total }`，否则前端 `res.data` 会类型不匹配。

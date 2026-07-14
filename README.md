# MarketANA

## 完整使用流程

### 1. 启动 MySQL

启动本地 MySQL 8.4 数据库，用于后端与流水线集成：

```bash
docker compose up -d mysql
```

检查 MySQL 是否就绪（约需 10-30 秒）：

```bash
docker compose logs -f mysql
```

看到类似 `port: 3306  MySQL Community Server - GPL` 的日志即表示启动完成。

### 2. 初始化数据库表

创建本地环境变量文件（如果还没有）：

```bash
cp .env.example .env
```

初始化数据库表结构：

```bash
uv run python -c "from back_end.app.core.database import create_database_tables; create_database_tables()"
```

或者使用初始化脚本（推荐用模块方式，避免直接运行脚本时找不到 `back_end` 包）：

```bash
uv run python -m scripts.init_db
```

如果数据库是在品种归一化功能上线前创建的，先备份数据库，再执行一次迁移：

```bash
mysql -u marketana -p marketana < scripts/migrate_product_resolution_20260710.sql
```

如需启用独立数据处理流水线的结构化证据和复核队列，再执行一次 canonical 结果迁移：

```bash
mysql -u marketana -p marketana < scripts/migrate_canonical_result.sql
```

启用审核队列的审核人、驳回原因和审核时间字段：

```bash
docker compose exec -T mysql mysql -umarketana -pmarketana_password marketana \
  < scripts/migrate_manual_review_20260713.sql
```

如果已经执行过旧版人工审核迁移，只需补充结构化驳回原因列：

```bash
docker compose exec -T mysql mysql -umarketana -pmarketana_password marketana \
  < scripts/migrate_review_queue_upgrade_20260713.sql
```

异常发布日期可先预览、确认后修复：

```bash
uv run python scripts/repair_publish_times.py
uv run python scripts/repair_publish_times.py --apply
```

### 3. 导入本地数据文件

预览将要插入 `articles` 表的文件：

```bash
uv run python scripts/ingest_files.py --root data --dry-run --limit 20
```

插入最多 20 条新的 PDF/HTML 文章任务：

```bash
uv run python scripts/ingest_files.py --root data --limit 20
```

默认跳过独立图片文件。如需包含图片，请显式指定：

```bash
uv run python scripts/ingest_files.py --root data --limit 20 --include-images
```

导入器默认会将 CSV 报告写入 `data/ingest_report.csv`。它会跳过 `img_folder` 中的资源、`.svg` 文件以及不受支持的文档类型（如 `.doc/.docx`）。

导入成功后，文章以 `status=0`（待处理）状态存入数据库。

### 4. 启动后端服务（含自动清洗流水线）

```bash
uv run uvicorn back_end.app.main:app --reload --host 0.0.0.0
```

应用启动时自动执行以下操作：

- 创建数据库连接池
- 启动后台 Scheduler 定时调度器
- Scheduler **每 5 分钟**自动扫描待处理文章（`status=0`）
- 扫描到的文章自动执行完整流水线：**解析 → 清洗 → 品种分段 → 未知品种归一化 → LLM 文本精修 → 规则引擎分析 → LLM 分析**

每个阶段的具体含义：

| 阶段 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **parser** | 从源文件（PDF/HTML/图片）提取原始文本 | 文件 URL | `raw_text` 写入数据库 |
| **cleaner** | 清洗原始文本（去噪、规范化） | `raw_text` | `cleaned_text` 写入数据库 |
| **product_segmenter** | 按品种切分核心正文/图文识别正文 | `cleaned_text` | `article_product_segments` 写入数据库 |
| **product_resolver** | 批量归一化未知品种，失败不阻断流水线 | 未知品种分段 | 标准 `product_key` 或待人工审核记录 |
| **refiner** | 将有效品种分段润色成通俗自然的展示文本 | `article_product_segments.cleaned_text` | 段级 `refined_text` 写入数据库（失败不中断） |
| **rule_engine** | 基于规则的市场方向判断 | 品种分段优先，回退 `cleaned_text` | 分析结果（方向+置信度） |
| **llm_infer** | LLM 深度分析（低置信度时触发） | 品种分段优先，回退 `cleaned_text` | 分析结果（方向+理由） |

### 5. （可选）手动触发处理

根目录的 `main.py` 只是占位入口，执行它只会打印 `Hello from marketana!`，不会触发数据处理。

如果不想等待定时器自动触发，可以用以下任一方式立即执行。

#### 方式 A：通过后端 API 触发

先启动后端服务：

```bash
uv run uvicorn back_end.app.main:app --reload --host 0.0.0.0
```

**处理所有待处理文章：**

```bash
curl -X POST http://localhost:8000/api/tasks/run
```

**处理单篇文章：**

```bash
curl -X POST http://localhost:8000/api/tasks/run \
  -H "Content-Type: application/json" \
  -d '{"article_id": 7}'
```

也可以指定批量上限：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/run \
  -H "Content-Type: application/json" \
  -d '{"limit": 20}'
```

#### 方式 B：不启动后端，直接从命令行触发数据库任务

处理最多 20 篇待处理文章：

```bash
uv run python -c "from back_end.app.core.database import get_session; from back_end.app.api.tasks import run_task; from back_end.app.api.schemas import TaskRunRequest; s=next(get_session()); print(run_task(TaskRunRequest(limit=20), session=s)); s.close()"
```

处理指定文章，例如 `article_id=1`：

```bash
uv run python -c "from back_end.app.core.database import get_session; from pn11 import run_pipeline; s=next(get_session()); ok=run_pipeline(1, s); s.commit(); print({'article_id': 1, 'success': ok}); s.close()"
```

#### 方式 C：单文件手动调试，不写入正式数据库

适合排查某个 PDF/HTML/图片文件的解析、清洗、识别和分段效果：

```bash
uv run python tests/manual_single_file_pipeline.py data/20250401/323354/浙商期货_323354_0.html --output-dir tests/outputs/
```

如果暂时不想调用真实 LLM：

```bash
uv run python tests/manual_single_file_pipeline.py data/20250401/323354/浙商期货_323354_0.html --output-dir tests/outputs --skip-llm
```

输出文件包括：

- `01_parsed_raw_text.txt`
- `02_cleaned_text.txt`
- `03_recognition_text.txt`
- `04_refined_text.txt`
- `05_product_segments.txt`

### 6. （可选）查看处理结果

文章处理完成后，可通过 API 查询分析结果：

```bash
# 查看文章列表
curl http://127.0.0.1:8000/api/articles

# 查看公司预测汇总
curl http://127.0.0.1:8000/api/companies

# 查看产品预测汇总
curl http://127.0.0.1:8000/api/products

# 查看趋势热力图
curl http://127.0.0.1:8000/api/trends

# 查看仪表盘统计
curl http://127.0.0.1:8000/api/dashboard/summary
```

### 7. 停止与清理

停止后端服务：按下 `Ctrl+C`

停止 MySQL 容器（保留数据卷，下次启动数据还在）：

```bash
docker compose down
```

停止 MySQL 容器并删除所有数据：

```bash
docker compose down -v
```

---

## 常用命令参考

```bash
docker compose ps          # 查看容器状态
docker compose logs -f mysql  # 查看 MySQL 日志
docker compose down        # 停止并移除容器
```

## 环境变量说明

默认的 Docker Compose 连接字符串为：

```env
DATABASE_URL=mysql+pymysql://marketana:marketana_password@127.0.0.1:3306/marketana?charset=utf8mb4
```

其他可配置的环境变量参见 `.env.example`。

LLM 调用较慢时可以调整：

```env
LLM_TIMEOUT_SECONDS=300  # 单次请求最多等待秒数
LLM_MAX_RETRIES=2        # 超时/网络错误/5xx/429/空 SSE 后最多重试次数
```

前端 `/review-queue` 是内部审核工作台，按待审核、已完成、已驳回和处理异常归类文章。审核人员可以驳回误识别、重新解析整篇，或在填写标准品种、方向、理由和证据后创建正式人工结论；已驳回状态不会被流水线重跑覆盖。

升级编号证据协议后，可先预览仍处于待审核且没有可展示证据的历史文章：

```bash
uv run python -m scripts.reprocess_missing_evidence --dry-run --limit 100
```

确认列表后再显式重跑。默认串行调用模型，可按服务容量调整并发数：

```bash
uv run python -m scripts.reprocess_missing_evidence --apply --limit 100 --concurrency 1
```

如果日志出现 `请求超时`，通常表示模型服务在该时间内没有返回结果。可以适当增大 `LLM_TIMEOUT_SECONDS`，或减小批量处理数量，避免多篇文章连续等待。


```mermaid
flowchart TD
    A[本地研报文件<br/>PDF / HTML / 图片] --> B[scripts/ingest_files.py<br/>导入 articles 表]

    B --> C[(MySQL<br/>articles / article_texts<br/>segments / results / logs)]

    C --> D[FastAPI 后端<br/>back_end/app/main.py]

    D --> E[pn03 Scheduler<br/>定时扫描 status=0]
    D --> F[/api/tasks/run<br/>手动触发]

    E --> G[pn11 Pipeline<br/>端到端编排]
    F --> G

    G --> H[pn04 Parser<br/>解析文件为 raw_text]
    H --> I[pn05 Cleaner<br/>清洗为 cleaned_text]
    I --> J[pn05 Product Segmenter<br/>按品种切分片段]
    J --> K[pn06 Product Resolver<br/>未知品种归一化]
    K --> L[pn05 Refiner<br/>LLM 精修展示文本]
    L --> M[pn06 Rule Engine<br/>规则判断方向/置信度]
    M -->|低置信度| N[pn07 LLM Infer<br/>LLM 深度分析]
    M -->|高置信度| O[(analysis_results)]
    N --> O

    O --> C
    K --> P[(product_resolutions<br/>待人工审核)]
    P --> C

    C --> Q[Repositories<br/>back_end/app/repositories]
    Q --> R[API Routers<br/>articles/products/trends<br/>companies/dashboard/review]
    R --> S[Serializers<br/>back_end/app/api/serializers.py]
    S --> T[Vue 前端<br/>front_end/src/views]

    T --> U[产品页 / 公司页 / 趋势热力图<br/>文章详情 / 人工审核]
```

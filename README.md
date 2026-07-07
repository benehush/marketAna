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

或者使用初始化脚本：

```bash
uv run python scripts/init_db.py
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
- 扫描到的文章自动执行完整流水线：**解析 → 清洗 → 规则引擎分析 → LLM 分析**

每个阶段的具体含义：

| 阶段 | 功能 | 输入 | 输出 |
|------|------|------|------|
| **parser** | 从源文件（PDF/HTML/图片）提取原始文本 | 文件 URL | `raw_text` 写入数据库 |
| **cleaner** | 清洗原始文本（去噪、规范化） | `raw_text` | `cleaned_text` 写入数据库 |
| **rule_engine** | 基于规则的市场方向判断 | `cleaned_text` | 分析结果（方向+置信度） |
| **llm_infer** | LLM 深度分析（低置信度时触发） | `cleaned_text` | 分析结果（方向+理由） |

### 5. （可选）手动触发处理

如果不想等待定时器自动触发，可以手动调用 API 立即执行：

**处理所有待处理文章：**

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/run
```

**处理单篇文章：**

```bash
curl -X POST http://127.0.0.1:8000/api/tasks/run \
  -H "Content-Type: application/json" \
  -d '{"article_id": 1}'
```

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
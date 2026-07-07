# pn04 文件解析模块 Parser 计划

## 摘要

pn04 实现文章文件解析模块，支持 PDF（PyMuPDF）、HTML（BeautifulSoup + lxml）、图片（Tesseract OCR）三种格式的解析，将原始研报文件转换为纯文本。解析结果通过 `ArticleRepository.save_raw_text()` 写入 `article_texts` 表，成功更新 `status=1`（PARSED），失败更新 `status=-1`（FAILED）并记录错误日志和 task_log。表格内容自动转换为 Markdown 格式以保留结构化信息。

## 关键改动

- 解析器路由：
  - `detect_parser_type(file_type, file_url)` 根据 `article.file_type`（优先）和 URL 扩展名判断解析器类型。
  - 支持 PDF、HTML、PNG/JPG/BMP/TIFF/WebP，其他格式抛出 `UnsupportedFormatError`。

- PDF 解析（`PdfParser`）：
  - 使用 PyMuPDF（fitz）按页读取文本，保留页码标记（`## Page N`）。
  - 自动检测页面中的表格 → 调用 `pdf_table_to_markdown()` 转为 Markdown。
  - 扫描件 PDF（无文本层）可降级到 OCR 处理（通过 `ImageParser.ocr_from_bytes()`）。

- HTML 解析（`HtmlParser`）：
  - 使用 BeautifulSoup + lxml 解析，自动移除 `<script>/<style>/<nav>/<footer>/<header>` 等噪声标签。
  - 30+ CSS 选择器移除广告、导航、侧边栏、弹窗、评论区等无关区域。
  - `<table>` 先转为 Markdown 再移除 DOM 节点，避免表格数据丢失。
  - 自动检测并移除免责声明段落（10 种常见模式）。
  - 支持 GBK/Latin-1 编码降级（国内网站常见编码）。

- 图片 OCR（`ImageParser`）：
  - 使用 Pillow 进行预处理：RGBA→灰度、对比度增强、锐化、小图放大。
  - 使用 pytesseract 进行 OCR 识别，默认语言 `chi_sim+eng`。
  - 同时提供 `ocr_from_bytes()` 方法供 PDF 扫描页降级调用。

- 表格工具（`table_utils.py`）：
  - `html_table_to_markdown()`：HTML `<table>` → Markdown，处理 colspan 合并单元格。
  - `pdf_table_to_markdown()`：PDF 二维数组 → Markdown。
  - 可选在表格前后添加自然语言描述，避免趋势信息丢失。

- 主入口（`parser.py`）：
  - `parse_article(article, session)`：统一入口，自动路由 → 解析 → 入库 → task_log。
  - 异常时调用 `repo.mark_failed()` 写入 `error_msg + status=-1`。

- 配置（`ParseConfig`）：
  - OCR 语言、PDF OCR 降级开关、表格提取开关、文本截断长度等均可配置。

## 实现顺序

1. 定义 `ParserType` 枚举、`ParseResult`、`ParseConfig` 数据类（`models.py`）。
2. 定义 `ParserError` 异常体系（`exceptions.py`）。
3. 实现表格转换工具（`table_utils.py`）。
4. 实现 `ImageParser` → `HtmlParser` → `PdfParser` 三个子解析器。
5. 实现 `parse_article()` 主入口：路由 + Repository 集成 + task_log。
6. 编写测试用例，覆盖各格式解析、异常处理和集成流程。
7. 编写 README 和本文档。

## 验证方案

- 类型检测：
  - `file_type="pdf"` → `ParserType.PDF`；URL 扩展名 `.html` → `ParserType.HTML`。
  - 优先级：file_type > 扩展名。未知格式 → `ParserType.UNKNOWN`。

- HTML 解析：
  - 基本正文提取（`<script>/<style>/<nav>/<footer>` 被移除）。
  - 表格 → Markdown 转换正确。
  - 文件不存在 → `FileNotFoundError_`。

- PDF 解析：
  - 使用 PyMuPDF 创建样本 PDF → 解析验证文本内容 + 元数据（页数、文本页数）。

- 图片解析：
  - 文件不存在 → `FileNotFoundError_`；不支持格式 → `FileReadError`。

- 集成测试：
  - HTML 文章从 `parse_article()` 入口 → `status=1`（PARSED），`article_texts.raw_text` 正确。
  - 不支持的格式 → `status=-1`（FAILED），`error_msg` 写入。
  - 文件不存在 / file_url 为空 → 标记失败 + task_log 记录。

- 回归验证：
  - `uv run pytest pn04/ -v` 全部 18 个测试通过。

## 假设与默认选择

- 文章文件存储于本地文件系统，`file_url` 为相对或绝对路径。
- OCR 功能需要系统安装 Tesseract 引擎（`tesseract-ocr` + `tesseract-ocr-chi-sim`）。
- 扫描件 PDF OCR 降级为可选功能（`ParseConfig.pdf_ocr_fallback`），默认开启。
- 超过 `max_text_length`（500K 字符）的文本会被截断并附加标记。
- 编码检测（chardet）未作为硬依赖引入，因为 pn04 处理的是已解码的 str；编码问题在文件读取阶段由各解析器自行处理（如 HTML 的 GBK 降级）。

## pn04 文件解析模块实际实现情况

通过阅读和验证本阶段代码，pn04 的三类解析器（PDF/HTML/Image）、表格转换工具、主入口函数和异常处理体系已按计划落地。模块通过 `ArticleRepository` 接口与数据库交互，不直接操作 SQL。

### 已实现的框架

**1. 类型检测与数据模型** (`pn04/models.py`)
- **`ParserType` 枚举**：PDF、HTML、IMAGE、UNKNOWN。
- **`detect_parser_type()`**：`file_type` > URL 扩展名优先级判断，覆盖 12 种文件扩展名和 8 种 MIME 类型。
- **`ParseResult` / `ParseConfig`**：解析结果数据类和可配置解析参数。

**2. 异常体系** (`pn04/exceptions.py`)
- **`ParserError`** 基类 → **`UnsupportedFormatError`** / **`FileReadError`** / **`FileNotFoundError_`** / **`OCRError`** / **`EmptyContentError`** 五个子类。

**3. PDF 解析器** (`pn04/pdf_parser.py`)
- **`PdfParser`**：PyMuPDF 逐页读取 + `## Page N` 标记 + 表格检测提取 + 扫描页 OCR 降级。
- 返回 `ParseResult`，包含 `total_pages/text_pages/ocr_pages/tables_found` 元数据。

**4. HTML 解析器** (`pn04/html_parser.py`)
- **`HtmlParser`**：BeautifulSoup + lxml 解析，15 种噪声标签移除 + 30+ CSS 选择器过滤 + 正文容器优先查找。
- 10 种免责声明正则模式后处理 + GBK/Latin-1 编码降级。
- `<table>` → Markdown 转换后从 DOM 移除，避免重复提取。

**5. 图片 OCR 解析器** (`pn04/image_parser.py`)
- **`ImageParser`**：Pillow 预处理（灰度 → 对比度增强 → 锐化 → 放大）+ pytesseract OCR。
- 同时提供 `ocr_from_bytes()` 供 PDF 扫描页降级使用。

**6. 表格工具** (`pn04/table_utils.py`)
- `html_table_to_markdown()`：处理 colspan 合并单元格。
- `pdf_table_to_markdown()`：二维数组 → Markdown，支持自定义表头。
- 可选自然语言描述（表格前后追加）。

**7. 主入口** (`pn04/parser.py`)
- **`parse_article(article, session)`**：读取 `article.file_type/file_url` → 路由解析器 → 调用 `repo.save_raw_text()` → 写 task_log。
- 异常统一调用 `repo.mark_failed()` 写入 `status=-1` + `error_msg`。
- 支持 `base_dir` 参数解析相对路径。

### 尚未实现（但计划也说不做）

- OCR 功能依赖系统级 Tesseract 引擎，需单独安装；未安装时 OCR 解析会抛出 `ImportError`。
- 未引入 chardet 编码检测库（pn04 处理已解码 str，编码问题在各解析器内部处理）。
- 不修改 `back_end/app/services/` 中的任何现有文件。
- 网络文件（HTTP URL）的下载和解析不在 pn04 范围内。

### 计划中声明的功能验证

| 验证项 | 状态 |
|--------|------|
| file_type 和 URL 扩展名类型检测 | ✅ `test_detect_parser_type_*` 系列 |
| HTML 正文提取 + 脚本/样式/导航移除 | ✅ `test_html_parser_basic` |
| HTML 表格 → Markdown | ✅ `test_html_parser_table_extraction` |
| HTML 文件不存在异常 | ✅ `test_html_parser_file_not_found` |
| PDF 解析（含 PyMuPDF 样本） | ✅ `test_pdf_parser_with_sample` |
| PDF 文件不存在异常 | ✅ `test_pdf_parser_file_not_found` |
| 图片文件不存在/不支持格式异常 | ✅ `test_image_parser_*` 系列 |
| parse_article HTML 集成 + status=1 | ✅ `test_parse_article_html` |
| 不支持格式 → status=-1 | ✅ `test_parse_article_unsupported_format` |
| 文件不存在 / file_url 为空 → 失败 | ✅ `test_parse_article_file_not_found` / `test_parse_article_empty_file_url` |
| task_log 成功/失败记录 | ✅ `test_parse_article_task_log_recorded` / `test_parse_article_failure_log_recorded` |
| 全量测试 | ✅ 18 个测试用例全部通过 |

**总结**：pn04 已完成多格式文章解析模块的核心实现。PDF、HTML、图片三类解析器均可独立工作，表格内容被转为 Markdown 保留结构化信息。模块通过 `ArticleRepository` 接口写入数据库，状态流转（0→1 或 0→-1）和 task_log 记录完整。后续 pn05 Cleaner 可直接消费 `article_texts.raw_text`。



# pn04 Parser 优化方案：确定性解析 + 可选 AI 图文增强

## Summary
将 pn04 从“按格式抽文本”升级为“文档容器解析器”：PDF/HTML/图片统一输出带来源标记的 `raw_text`，优先使用确定性解析和 OCR，复杂图表/图片正文再用可选 AI 增强。默认策略采用用户确认的“可选增强”：AI 失败不阻塞解析；AI 生成内容允许写入 `article_texts.raw_text`，但必须带明确标记，方便 pn05 清洗和排错。

## Key Changes
- 保持 `parse_article(article, session, config, base_dir)` 对外入口不变，继续成功写入 `article_texts.raw_text`、`status=1`，失败写 `error_msg`、`status=-1`。
- 扩展 `ParseConfig`：
  - `html_extract_embedded_images=True`
  - `image_ocr_engine="tesseract"`，预留 `"paddle"` 但默认不强依赖
  - `parser_ai_enabled=False`
  - `parser_ai_model=None`
  - `parser_ai_max_images=3`
  - `min_meaningful_text_chars=200`
- 统一 `raw_text` 输出格式：
  ```text
  # 文档标题
  来源文件: ...
  解析器: html/pdf/image

  ## 正文文本
  ...

  ## 表格数据
  <Markdown 表格 + 简短自然语言描述>

  ## 图片OCR文本: <relative image path>
  ...

  ## AI图表解读: <relative image path>
  ...
  ```
- AI 内容必须只用于补充图表、长图、扫描图、正文图片；不能覆盖确定性抽取文本。

## Implementation Changes
- HTML 解析：
  - 先删除 `script/style/nav/footer/header/form` 等噪声节点。
  - 用候选块评分选择正文容器，而不是简单命中第一个 `content/body`：评分因素包括中文字符数、段落数、表格数、正文关键词、链接密度低、导航关键词少。
  - 对正文容器内的 `<table>` 转 Markdown；对 `<img>` 解析相对路径，过滤 logo/icon/二维码等小图，保留大图、长图、正文图。
  - 对浙商样例这种 `<div class="con_p"><img ...></div>`，必须把 `img_folder/*.png` 作为正文资产进入 OCR/AI 增强。
- PDF 解析：
  - 继续用 PyMuPDF 按页抽文本，保留 `## Page N`。
  - 低文本页走 OCR fallback。
  - 表格继续用 `page.find_tables()`，转 Markdown；抽取失败时不阻塞正文文本。
- 图片解析：
  - 默认使用 Tesseract；大长图先按高度切片 OCR，再按顺序拼接，避免 1785x9611 这类长图识别质量差或超时。
  - 图片预处理增加白底合成、灰度、对比度、放大、可选二值化。
- AI 增强：
  - 新增 pn04 内部 AI 增强器，复用 pn07 的 OpenAI 兼容配置。
  - 仅当 `parser_ai_enabled=True` 且模型配置可用时运行。
  - 输入为 OCR 文本 + 图片；输出固定为 Markdown 段落，包含“主要品种/方向线索/表格或图表关键信息/无法确认的信息”。
  - AI 调用失败、超时、未配置时，只记录 task_log warning，不标记解析失败。
- Repository/API 不改表结构；`raw_text` 继续作为 pn05 输入，`metadata` 暂不入库。

## Test Plan
- 单元测试：
  - HTML 正文候选评分能避开导航/页脚，命中正文容器。
  - HTML 内嵌图片路径能从相对路径解析到本地文件。
  - 长图切片 OCR 按顺序拼接。
  - HTML/PDF 表格输出 Markdown。
  - AI 未配置或调用失败时解析仍成功。
- 真实样例验收：
  - `data/20250401/东海期货_323471.PDF`：解析结果包含“研究所晨会观点精萃”、页码、宏观/股指/贵金属/钢材等正文段落。
  - `data/20250401/323354/浙商期货_323354_0.html`：解析结果不能只剩免责声明/客服/上一篇下一篇，必须包含正文图片 OCR 或 AI 图表解读段。
  - 含表格 HTML/PDF：输出含 Markdown 表格和自然语言表格说明。
  - 损坏文件、不支持格式、缺失内嵌图片：失败或降级行为符合预期，并写入 task_log。
- 命令：
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest pn04/ -v`
  - 额外增加真实样例 smoke test，可跳过 AI 调用，AI 部分用 mock。

## Assumptions
- 默认 OCR 使用当前依赖里的 Tesseract；PaddleOCR 作为后续可插拔引擎，不在本轮强制引入新依赖。
- AI 是可选增强，不是 parser 成败条件。
- `raw_text` 可以包含带标题标记的 OCR/AI 补充段，pn05 后续负责去噪和规范化。
- 不新增数据库字段；如以后需要保存解析 metadata，再单独设计迁移。

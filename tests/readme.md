已加好单文件手动测试脚本：[tests/manual_single_file_pipeline.py](/home/sanmu/marketANA/tests/manual_single_file_pipeline.py)。

用法示例：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python tests/manual_single_file_pipeline.py data/20250401/323354/浙商期货_323354_0.html
```

运行到清洗阶段时，终端会显示 `清洗进度` 进度条。

如果只想跳过真实 LLM 调用：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python tests/manual_single_file_pipeline.py data/20250401/323354/浙商期货_323354_0.html --skip-llm
```

如果想把五段结果写成文件：

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python tests/manual_single_file_pipeline.py data/20250401/323354/浙商期货_323354_0.html --output-dir tests/outputs
```

会输出/写入：

- `01_parsed_raw_text.txt`：解析后的文本
- `02_cleaned_text.txt`：清洗后的文本
- `03_recognition_text.txt`：规则识别 + LLM 识别结果
- `04_refined_text.txt`：LLM 分段精修结果拼接
- `05_product_segments.txt`：按品种切分后的正文片段，含分段 `refined_text`

验证过：
- 用你打开过的 HTML 样例跑 `--skip-llm` 成功。
- `py_compile` 通过。

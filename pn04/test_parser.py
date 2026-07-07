"""
pn04 Parser 单元测试

使用内存 SQLite 和 mock 数据测试各解析器的功能，
包括正常解析、异常处理、表格提取和 Repository 集成。
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from back_end.app.core.database import Base, create_database_tables
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models.article import Article, TaskLog
from back_end.app.repositories.articles import ArticleRepository

from pn04.exceptions import (
    FileNotFoundError_,
    FileReadError,
    ParserError,
)
from pn04.models import (
    ParserType,
    ParseConfig,
    ParseResult,
    detect_parser_type,
)
from pn04.parser import parse_article
from pn04.table_utils import html_table_to_markdown, pdf_table_to_markdown


# ---- Database fixtures ----

@pytest.fixture
def session_factory():
    """创建内存 SQLite 测试数据库。"""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    create_database_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def session(session_factory) -> Session:
    return session_factory()


@pytest.fixture
def repo(session) -> ArticleRepository:
    return ArticleRepository(session)


@pytest.fixture
def sample_article(repo) -> Article:
    """创建测试用 Article。"""
    article = repo.create_article(
        title="测试研报",
        source="日报",
        company="测试期货",
        file_type="html",
        file_url="/files/test_report.html",
        publish_time=datetime(2026, 7, 3, 10, 0),
    )
    repo.session.commit()
    return article


@pytest.fixture
def temp_dir():
    """创建临时文件目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


# ---- ParserType 检测 ----

def test_detect_parser_type_by_file_type():
    """通过 file_type 字段检测解析器类型。"""
    assert detect_parser_type("pdf", None) == ParserType.PDF
    assert detect_parser_type("html", None) == ParserType.HTML
    assert detect_parser_type("image/png", None) == ParserType.IMAGE


def test_detect_parser_type_by_extension():
    """通过 URL 扩展名检测解析器类型。"""
    assert detect_parser_type(None, "/files/report.pdf") == ParserType.PDF
    assert detect_parser_type(None, "/files/report.html") == ParserType.HTML
    assert detect_parser_type(None, "/files/report.htm") == ParserType.HTML
    assert detect_parser_type(None, "/files/chart.png") == ParserType.IMAGE
    assert detect_parser_type(None, "/files/chart.jpg") == ParserType.IMAGE


def test_detect_parser_type_unknown():
    """无法识别时返回 UNKNOWN。"""
    assert detect_parser_type(None, None) == ParserType.UNKNOWN
    assert detect_parser_type("docx", None) == ParserType.UNKNOWN
    assert detect_parser_type(None, "/files/report.docx") == ParserType.UNKNOWN


def test_detect_parser_type_priority():
    """file_type 优先于扩展名。"""
    assert detect_parser_type("html", "/files/report.pdf") == ParserType.HTML


# ---- 表格转换 ----

def test_html_table_to_markdown():
    """HTML table → Markdown 转换。"""
    from bs4 import BeautifulSoup

    html = """
    <table>
        <tr><th>品种</th><th>方向</th><th>置信度</th></tr>
        <tr><td>螺纹钢</td><td>看涨</td><td>0.85</td></tr>
        <tr><td>铁矿石</td><td>看跌</td><td>0.72</td></tr>
    </table>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    result = html_table_to_markdown(table, add_description=False)

    assert "| 品种 | 方向 | 置信度 |" in result
    assert "| 螺纹钢 | 看涨 | 0.85 |" in result
    assert "| 铁矿石 | 看跌 | 0.72 |" in result


def test_html_table_to_markdown_empty():
    """空表格返回空字符串。"""
    from bs4 import BeautifulSoup

    html = "<table></table>"
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    result = html_table_to_markdown(table)
    assert result == ""


def test_pdf_table_to_markdown():
    """PDF cells → Markdown 转换。"""
    cells = [
        ["品种", "方向", "变化"],
        ["螺纹钢", "看涨", "+2.3%"],
        ["沪铜", "看跌", "-1.1%"],
    ]
    result = pdf_table_to_markdown(cells, add_description=False)
    assert "| 品种 | 方向 | 变化 |" in result
    assert "| 螺纹钢 | 看涨 | +2.3% |" in result


# ---- HTML Parser ----

def test_html_parser_basic(temp_dir):
    """基本 HTML 解析：提取正文，移除脚本和样式。"""
    html_content = """<!DOCTYPE html>
<html>
<head><title>测试报告</title></head>
<body>
    <script>console.log('noise')</script>
    <style>.ad { display: none; }</style>
    <nav>导航菜单</nav>
    <div class="content">
        <h1>螺纹钢市场分析</h1>
        <p>今日螺纹钢价格小幅上涨，市场情绪偏乐观。</p>
    </div>
    <footer>版权所有 © 2026</footer>
</body>
</html>"""
    file_path = os.path.join(temp_dir, "test.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from pn04.html_parser import HtmlParser

    parser = HtmlParser(config=ParseConfig(extract_tables=False))
    result = parser.parse(file_path)

    assert result.parser_type == ParserType.HTML
    assert "螺纹钢市场分析" in result.raw_text
    assert "console.log" not in result.raw_text
    assert "导航菜单" not in result.raw_text


def test_html_parser_table_extraction(temp_dir):
    """HTML 表格提取为 Markdown。"""
    html_content = """<!DOCTYPE html>
<html><body>
    <table>
        <tr><th>品种</th><th>方向</th></tr>
        <tr><td>螺纹钢</td><td>看涨</td></tr>
    </table>
</body></html>"""
    file_path = os.path.join(temp_dir, "table_test.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from pn04.html_parser import HtmlParser

    parser = HtmlParser()
    result = parser.parse(file_path)

    assert "| 品种 | 方向 |" in result.raw_text
    assert "| 螺纹钢 | 看涨 |" in result.raw_text


def test_html_parser_selects_main_content_over_navigation(temp_dir):
    """HTML 正文候选评分应避开导航/页脚，命中正文块。"""
    html_content = """<!DOCTYPE html>
<html><body>
    <div class="nav">
        <a>首页</a><a>走近公司</a><a>在线服务</a><a>下载APP</a>
        <a>客服中心</a><a>上一篇</a><a>下一篇</a>
    </div>
    <div class="content">
        <h1>铜市场日报</h1>
        <p>沪铜价格震荡偏强，新能源需求保持韧性。</p>
        <p>库存继续去化，现货升水支撑价格。</p>
    </div>
    <footer>客服电话 400-000-0000</footer>
</body></html>"""
    file_path = os.path.join(temp_dir, "main_content.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from pn04.html_parser import HtmlParser

    result = HtmlParser().parse(file_path)
    assert "铜市场日报" in result.raw_text
    assert "新能源需求保持韧性" in result.raw_text
    assert "客服中心" not in result.raw_text


def test_html_parser_extracts_embedded_report_image(temp_dir, monkeypatch):
    """HTML 正文图片应进入 OCR 段，覆盖浙商长图类页面。"""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow 未安装")

    image_dir = os.path.join(temp_dir, "img_folder")
    os.makedirs(image_dir)
    image_path = os.path.join(image_dir, "report.png")
    Image.new("RGB", (900, 1200), "white").save(image_path)

    html_content = """<!DOCTYPE html>
<html><body>
    <div class="conten conten_w">
        <h2 class="con_tt">【L日报20250401】</h2>
        <div class="con_p"><p><img src="img_folder/report.png" /></p></div>
    </div>
    <div class="about"><a>上一篇</a><a>下一篇</a></div>
</body></html>"""
    file_path = os.path.join(temp_dir, "zhe_report.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    from pn04.html_parser import HtmlParser
    from pn04.image_parser import ImageParser

    def fake_extract(self, path):
        return ParseResult(
            parser_type=ParserType.IMAGE,
            raw_text="OCR正文：L日报包含现货价格、基差及盘面价差图表。",
            metadata={"file_path": path},
        )

    monkeypatch.setattr(ImageParser, "extract_image_text", fake_extract)

    result = HtmlParser().parse(file_path)
    assert "## 图片OCR文本: img_folder/report.png" in result.raw_text
    assert "OCR正文：L日报包含现货价格" in result.raw_text
    assert "上一篇" not in result.raw_text


def test_html_parser_file_not_found():
    """HTML 文件不存在时抛出异常。"""
    from pn04.html_parser import HtmlParser

    parser = HtmlParser()
    with pytest.raises(FileNotFoundError_):
        parser.parse("/nonexistent/path.html")


# ---- PDF Parser ----

def test_pdf_parser_file_not_found():
    """PDF 文件不存在时抛出异常。"""
    from pn04.pdf_parser import PdfParser

    parser = PdfParser()
    with pytest.raises(FileNotFoundError_):
        parser.parse("/nonexistent/path.pdf")


def test_pdf_parser_with_sample(temp_dir):
    """使用 PyMuPDF 创建简单 PDF 并验证解析。"""
    try:
        import fitz
    except ImportError:
        pytest.skip("pymupdf 未安装")

    file_path = os.path.join(temp_dir, "sample.pdf")
    doc = fitz.open()
    page = doc.new_page()
    # Use ASCII text + CJK font for reliable extraction
    page.insert_text((72, 72), "Steel Market Analysis Report", fontsize=14)
    page.insert_text((72, 100), "Steel rebar prices rose slightly today.", fontsize=11)
    doc.save(file_path)
    doc.close()

    from pn04.pdf_parser import PdfParser

    parser = PdfParser()
    result = parser.parse(file_path)

    assert result.parser_type == ParserType.PDF
    assert "Steel Market" in result.raw_text
    assert result.metadata["total_pages"] == 1


# ---- Image Parser ----

def test_image_parser_file_not_found():
    """图片文件不存在时抛出异常。"""
    from pn04.image_parser import ImageParser

    parser = ImageParser()
    with pytest.raises(FileNotFoundError_):
        parser.parse("/nonexistent/path.png")


def test_image_parser_unsupported_format(temp_dir):
    """不支持的图片格式抛出异常。"""
    file_path = os.path.join(temp_dir, "test.txt")
    with open(file_path, "w") as f:
        f.write("not an image")

    from pn04.image_parser import ImageParser

    parser = ImageParser()
    with pytest.raises(FileReadError):
        parser.parse(file_path)


def test_image_parser_slices_tall_images(temp_dir, monkeypatch):
    """长图 OCR 应按高度切片并按顺序拼接。"""
    try:
        from PIL import Image
    except ImportError:
        pytest.skip("Pillow 未安装")

    file_path = os.path.join(temp_dir, "long.png")
    Image.new("RGB", (900, 3800), "white").save(file_path)

    from pn04.image_parser import ImageParser

    monkeypatch.setattr(ImageParser, "_ensure_supported_engine", lambda self: None)

    def fake_ocr(self, image, *, file_path):
        width, height = image.size
        return f"slice {width}x{height}"

    monkeypatch.setattr(ImageParser, "_ocr_pil_image", fake_ocr)

    parser = ImageParser(ParseConfig(image_slice_height=1000))
    result = parser.extract_image_text(file_path)

    assert "[图片分片 1/4]" in result.raw_text
    assert "[图片分片 4/4]" in result.raw_text
    assert "slice 900x800" in result.raw_text


# ---- 主解析器 parse_article 集成测试 ----

def test_parse_article_html(temp_dir, session, sample_article):
    """集成测试：通过 parse_article 解析 HTML 文章。"""
    html_content = """<!DOCTYPE html>
<html><body>
    <h1>豆粕市场日报</h1>
    <p>豆粕期货主力合约今日震荡上行。</p>
    <p>下游饲料需求增加，库存压力有所缓解。</p>
</body></html>"""
    file_path = os.path.join(temp_dir, "report.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    sample_article.file_url = file_path
    sample_article.file_type = "html"
    session.commit()

    raw_text = parse_article(sample_article, session, base_dir=temp_dir)
    session.commit()

    assert "豆粕期货" in raw_text
    session.refresh(sample_article)
    assert sample_article.status == ArticleProcessingStatus.PARSED.value
    assert sample_article.text is not None
    assert sample_article.text.parser_type == "html"


def test_parse_article_unsupported_format(session, sample_article, temp_dir):
    """不支持的文件格式标记为失败。"""
    file_path = os.path.join(temp_dir, "report.docx")
    with open(file_path, "w") as f:
        f.write("dummy")

    sample_article.file_url = file_path
    sample_article.file_type = "docx"
    session.commit()

    with pytest.raises(ParserError):
        parse_article(sample_article, session, base_dir=temp_dir)
    session.commit()

    session.refresh(sample_article)
    assert sample_article.status == ArticleProcessingStatus.FAILED.value


def test_parse_article_file_not_found(session, sample_article):
    """文件不存在时标记为失败。"""
    sample_article.file_url = "/nonexistent/file.html"
    sample_article.file_type = "html"
    session.commit()

    with pytest.raises(ParserError):
        parse_article(sample_article, session)
    session.commit()

    session.refresh(sample_article)
    assert sample_article.status == ArticleProcessingStatus.FAILED.value


def test_parse_article_empty_file_url(session, sample_article):
    """file_url 为空时标记为失败。"""
    sample_article.file_url = None
    sample_article.file_type = "html"
    session.commit()

    with pytest.raises(ParserError):
        parse_article(sample_article, session)
    session.commit()

    session.refresh(sample_article)
    assert sample_article.status == ArticleProcessingStatus.FAILED.value


def test_parse_article_task_log_recorded(session, sample_article, temp_dir):
    """验证成功解析后 task_log 被正确记录。"""
    html = "<html><body><p>测试内容</p></body></html>"
    file_path = os.path.join(temp_dir, "log_test.html")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)

    sample_article.file_url = file_path
    sample_article.file_type = "html"
    session.commit()

    parse_article(sample_article, session, base_dir=temp_dir)
    session.commit()

    logs = session.query(TaskLog).filter(
        TaskLog.article_id == sample_article.id,
        TaskLog.stage == "parser",
    ).all()
    success_log = [l for l in logs if l.status == "success"]
    assert len(success_log) == 1


def test_parse_article_failure_log_recorded(session, sample_article):
    """验证失败解析后 task_log 被正确记录。"""
    sample_article.file_url = "/nonexistent/file.html"
    sample_article.file_type = "html"
    session.commit()

    with pytest.raises(ParserError):
        parse_article(sample_article, session)
    session.commit()

    logs = session.query(TaskLog).filter(
        TaskLog.article_id == sample_article.id,
        TaskLog.stage == "parser",
        TaskLog.status == "failed",
    ).all()
    assert len(logs) >= 1


# ---- ParseConfig 和 ParseResult ----

def test_parse_result_auto_length():
    """ParseResult 自动计算长度。"""
    result = ParseResult(
        parser_type=ParserType.HTML,
        raw_text="Hello World",
    )
    assert result.raw_length == 11


def test_parse_config_defaults():
    """ParseConfig 默认值。"""
    config = ParseConfig()
    assert config.ocr_lang == "chi_sim+eng"
    assert config.pdf_ocr_fallback is True
    assert config.extract_tables is True
    assert config.html_extract_embedded_images is True
    assert config.image_ocr_engine == "tesseract"
    assert config.parser_ai_enabled is False
    assert config.parser_ai_max_images == 3
    assert config.min_meaningful_text_chars == 200
    assert config.max_text_length == 500_000

"""
pn05 数据清洗模块 Cleaner

清洗 pn04 Parser 输出的 raw_text，移除广告、免责声明、
HTML 残留、异常空白和低密度噪声块，输出干净的纯文本。

主要入口:
    clean_article(article_id, session) -> str
    refine_article(article_id, session) -> str | None
"""

from pn05.cleaner import clean_article, CleanConfig
from pn05.refiner import refine_article

__all__ = ["clean_article", "CleanConfig", "refine_article"]

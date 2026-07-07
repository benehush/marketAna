"""
文章接口 - 提供文章的列表查询与详情查看功能
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from back_end.app.api.serializers import get_displayable_analysis_results, serialize_article_detail
from back_end.app.core.database import get_session
from back_end.app.core.exceptions import AppException, ErrorCode
from back_end.app.core.responses import success_response
from back_end.app.repositories import ArticleRepository

router = APIRouter(prefix="/api/articles", tags=["articles"])


@router.get("")
def list_articles(
    product: str | None = None,
    company: str | None = None,
    direction: str | None = None,
    status: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> dict:
    """查询文章列表，返回前端资讯页使用的数组结构。

    筛选条件（均为可选）：
    - product:   产品名称
    - company:   公司名称
    - direction: 市场方向
    - status:    文章状态
    - start_time / end_time: 发布时间范围
    - keyword:   关键词模糊搜索

    Args:
        page:     页码，从 1 开始
        page_size:每页条数，默认 20，最大 100

    Returns:
        dict: 形如 {"code": 200, "data": [{"id": ..., "title": ..., ...}]}
    """
    repository = ArticleRepository(session)
    items, _total = repository.list_articles(
        product=product,
        company=company,
        direction=direction,
        status=status,
        start_time=start_time,
        end_time=end_time,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return success_response([serialize_frontend_article(article) for article in items])


def serialize_frontend_article(article) -> dict:
    """
    将 Article ORM 对象序列化为前端资讯列表所需的字典格式。

    摘要（summary）优先级：
    1. 分析结果中的 reason（分析理由）
    2. 清洗后的文本前 120 个字符

    Args:
        article: Article ORM 实例（已加载 analysis_result 和 text 关系）

    Returns:
        dict: 包含 id、title、source、company、publish_time、summary、url 字段
    """
    results = get_displayable_analysis_results(article)
    article_text = article.text
    summary = None
    # 优先取分析理由作为摘要，其次取清洗文本的前 120 字
    if results:
        parts = []
        for result in sorted(results, key=lambda item: (not item.is_primary, item.product, item.contract_key))[:4]:
            contract = f"{result.contract} " if result.contract else ""
            parts.append(f"{result.product}{contract}{result.direction} {result.confidence:.2f}")
        summary = "；".join(parts)
    elif article_text and article_text.cleaned_text:
        summary = article_text.cleaned_text[:120]

    return {
        "id": article.id,
        "title": article.title,
        "source": article.source or "",
        "company": article.company or article.source or "",  # 公司名优先取 company，回退到 source
        "publish_time": article.publish_time.date().isoformat() if article.publish_time else "",
        "summary": summary,
        "url": article.file_url,
    }


@router.get("/{article_id}")
def get_article_detail(
    article_id: int,
    session: Session = Depends(get_session),
) -> dict:
    """
    获取单篇文章的详细信息（含关联的文本、分析结果、任务日志、人工确认记录）。

    Args:
        article_id: 文章 ID（路径参数）

    Raises:
        AppException: 当文章不存在时返回 404 错误

    Returns:
        dict: 文章详细数据，经过 serialize_article_detail 序列化
    """
    repository = ArticleRepository(session)
    article = repository.get_article_detail(article_id)
    if article is None:
        raise AppException(
            code=ErrorCode.NOT_FOUND,
            message="Article not found",
            detail={"article_id": article_id},
            status_code=404,
        )
    return success_response(serialize_article_detail(article))

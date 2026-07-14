"""
公司数据接口 - 获取所有公司及其对应的市场分析预测结果
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from back_end.app.core.database import get_session
from back_end.app.core.display import formal_analysis_clause
from back_end.app.core.responses import success_response
from back_end.app.core.status import ArticleProcessingStatus
from back_end.app.models import AnalysisResult, Article
from data_proccessing.catalog import product_group


router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("")
def get_companies(session: Session = Depends(get_session)) -> dict:
    """
    获取全部公司的预测数据汇总。

    查询逻辑：
    1. 关联 AnalysisResult 与 Article 表，获取每篇文章对应的分析结果
    2. 按公司名升序、文章发布时间降序排序
    3. 按公司名分组，将预测结果聚合成列表

    Returns:
        dict: 形如 {"code": 0, "message": "ok", "data": [{"company": "...", "predictions": [...]}]}
    """
    # 构建联合查询语句：AnalysisResult JOIN Article ON article_id
    stmt = (
        select(AnalysisResult, Article)
        .join(Article, Article.id == AnalysisResult.article_id)
        .where(
            Article.status == ArticleProcessingStatus.STORED.value,
            formal_analysis_clause(AnalysisResult),
        )
        .order_by(Article.company.asc(), Article.publish_time.desc())
    )

    # 按公司名分组的中间容器
    grouped: dict[str, list[dict]] = {}
 
    # 遍历查询结果，将每个分析结果归入对应公司
    for result, article in session.execute(stmt).all():
        # 公司名优先取 article.company，若为空则回退到 source，再为空则为空字符串
        company = article.company or article.source or ""
        # 日期优先取文章发布时间，若为空则回退到分析时间
        date_source = article.publish_time or result.analysis_time

        # 将当前预测追加到该公司对应的列表中
        if company not in grouped:
            grouped[company] = []
        
        grouped[company].append({
            "article_id": article.id,
            "result_id": result.id,
            "product": result.product,
            "product_key": result.product_key,
            "product_group": product_group(result.product_key),
            "contract": result.contract,
            "direction": result.direction,
            "confidence": result.confidence,
            "date": date_source.date().isoformat() if date_source else "",
            "need_manual_review": result.need_manual_review,
        })

    # 将分组字典转换为前端期望的列表格式
    data =[]
    for company, predictions in grouped.items():
        data.append({
            "company": company,
            "predictions": predictions,
        })

    return success_response(data)

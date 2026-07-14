"""
定义 Pydantic 请求校验模型（`ConfirmResultRequest`、`TaskRunRequest`）
和工具函数（`datetime_to_iso`）

"""
from datetime import datetime

from pydantic import BaseModel, Field


class ConfirmResultRequest(BaseModel):
    product: str = Field(min_length=1, max_length=128)
    product_key: str | None = Field(default=None, max_length=64)
    direction: str
    reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confirmed_by: str | None = Field(default=None, max_length=128)
    note: str | None = None


class TaskRunRequest(BaseModel):
    article_id: int | None = None
    limit: int | None = Field(default=None, ge=1, le=100)


class ProductResolutionConfirmRequest(BaseModel):
    product_key: str = Field(min_length=1, max_length=64)
    reviewed_by: str | None = Field(default=None, max_length=128)
    note: str | None = None


class ProductAliasReviewRequest(BaseModel):
    reviewed_by: str | None = Field(default=None, max_length=128)
    note: str | None = None


class RejectAnalysisReviewRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=128)
    reason_code: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=2000)


class CreateManualConclusionRequest(BaseModel):
    direction: str
    reason: str = Field(min_length=1, max_length=10000)
    evidence: str = Field(min_length=1, max_length=20000)
    product_key: str = Field(min_length=1, max_length=64)
    reviewed_by: str = Field(min_length=1, max_length=128)


def datetime_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

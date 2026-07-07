"""
定义 Pydantic 请求校验模型（`ConfirmResultRequest`、`TaskRunRequest`）
和工具函数（`datetime_to_iso`）

"""
from datetime import datetime

from pydantic import BaseModel, Field


class ConfirmResultRequest(BaseModel):
    product: str = Field(min_length=1, max_length=128)
    direction: str
    reason: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confirmed_by: str | None = Field(default=None, max_length=128)
    note: str | None = None


class TaskRunRequest(BaseModel):
    article_id: int | None = None
    limit: int | None = Field(default=None, ge=1, le=100)


def datetime_to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None

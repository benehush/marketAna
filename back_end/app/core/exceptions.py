from enum import IntEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(IntEnum):
    OK = 0                        # 成功
    INTERNAL_ERROR = 10000         # 未预期的服务器内部错误
    VALIDATION_ERROR = 10001       # 请求参数校验失败
    DATABASE_UNCONFIGURED = 20001  # 数据库未配置
    DATABASE_ERROR = 20002         # 数据库操作出错
    LLM_UNCONFIGURED = 30001       # 大模型未配置


class AppException(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: Any | None = None,
        status_code: int = 400,
    ) -> None:
        self.code = code
        self.message = message
        self.detail = detail
        self.status_code = status_code


def error_payload(code: ErrorCode, message: str, detail: Any | None = None) -> dict:
    return {
        "code": int(code),
        "message": message,
        "data": None,
        "detail": detail,
    }


def register_exception_handlers(app: FastAPI) -> None:
    # 捕获手动抛出的业务错误
    @app.exception_handler(AppException)
    async def handle_app_exception(
        request: Request,
        exc: AppException,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(exc.code, exc.message, exc.detail),
        )
    
    # 捕获 Pydantic 参数校验错误，返回 422 + 具体校验错误列表
    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                ErrorCode.VALIDATION_ERROR,
                "Request validation failed",
                exc.errors(),
            ),
        )

    # 捕获未预期的异常，返回 500 + 通用错误信息
    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=error_payload(ErrorCode.INTERNAL_ERROR, "Internal server error"),
        )

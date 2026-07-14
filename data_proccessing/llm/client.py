"""Injectable LLM client protocol with typed diagnostics and bounded retries."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any, Protocol, Sequence

import httpx

from data_proccessing.llm.diagnostics import sanitize_text


Message = dict[str, str]
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True, slots=True)
class LLMCallResult:
    content: str
    provider: str
    model: str = ""
    duration_ms: int = 0
    attempt_count: int = 1
    transport_retry_count: int = 0
    http_status: int | None = None
    content_type: str = ""
    sse_line_count: int | None = None
    sse_event_samples: tuple[str, ...] = ()
    done_received: bool | None = None


class LLMRequestError(RuntimeError):
    """A terminal request/provider failure with persistence-safe metadata."""

    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        provider: str,
        model: str = "",
        attempt_count: int = 1,
        transport_retry_count: int = 0,
        retry_exhausted: bool = False,
        http_status: int | None = None,
        content_type: str = "",
        raw_response_excerpt: str = "",
        sse_line_count: int | None = None,
        sse_event_samples: Sequence[str] = (),
        done_received: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.provider = provider
        self.model = model
        self.attempt_count = attempt_count
        self.transport_retry_count = transport_retry_count
        self.retry_exhausted = retry_exhausted
        self.http_status = http_status
        self.content_type = content_type
        self.raw_response_excerpt = raw_response_excerpt
        self.sse_line_count = sse_line_count
        self.sse_event_samples = tuple(sse_event_samples)
        self.done_received = done_received

    def to_diagnostic(self) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "error_type": self.error_type,
            "message": self.message,
            "parse_errors": [],
            "raw_response_excerpt": self.raw_response_excerpt,
            "provider": self.provider,
            "attempt_count": self.attempt_count,
            "transport_retry_count": self.transport_retry_count,
            "correction_retry_count": 0,
            "retry_exhausted": self.retry_exhausted,
        }
        for key in ("http_status", "sse_line_count", "done_received"):
            value = getattr(self, key)
            if value is not None:
                diagnostic[key] = value
        if self.content_type:
            diagnostic["content_type"] = self.content_type
        if self.sse_event_samples:
            diagnostic["sse_event_samples"] = list(self.sse_event_samples)
        return diagnostic


class LLMClient(Protocol):
    def complete(self, messages: Sequence[Message]) -> LLMCallResult | str: ...


class HttpLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int = 60,
        provider: str = "openai",
        max_retries: int = 0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.provider = provider.casefold()
        self.max_retries = max(0, int(max_retries))

    def complete(self, messages: Sequence[Message]) -> LLMCallResult:
        if self.provider == "wenhua":
            return self._complete_wenhua(messages)
        return self._complete_openai(messages)

    def _complete_openai(self, messages: Sequence[Message]) -> LLMCallResult:
        started = time.perf_counter()
        last_error: LLMRequestError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    self.base_url,
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "messages": list(messages), "temperature": 0},
                    timeout=self.timeout_seconds,
                )
                status = int(response.status_code)
                content_type = str(response.headers.get("content-type") or "")
                if status >= 400:
                    last_error = self._http_error(
                        status,
                        _response_text(response),
                        attempt=attempt,
                        content_type=content_type,
                    )
                    if status in _RETRYABLE_HTTP_STATUS and attempt < self.max_retries:
                        self._backoff(attempt)
                        continue
                    raise last_error
                try:
                    payload = response.json()
                    content = payload["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise self._request_error(
                        "provider_response_error",
                        "LLM 响应缺少 choices[0].message.content 或不是合法 JSON",
                        attempt=attempt,
                        http_status=status,
                        content_type=content_type,
                        raw_response=_response_text(response),
                    ) from exc
                if not isinstance(content, str) or not content.strip():
                    raise self._request_error(
                        "provider_response_error",
                        "LLM 响应 content 为空",
                        attempt=attempt,
                        http_status=status,
                        content_type=content_type,
                        raw_response=_response_text(response),
                    )
                return LLMCallResult(
                    content=content,
                    provider=self.provider,
                    model=self.model,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    attempt_count=attempt + 1,
                    transport_retry_count=attempt,
                    http_status=status,
                    content_type=content_type,
                )
            except LLMRequestError:
                raise
            except httpx.TimeoutException as exc:
                last_error = self._request_error(
                    "request_timeout",
                    f"LLM 请求超时（{self.timeout_seconds} 秒）",
                    attempt=attempt,
                    retry_exhausted=attempt >= self.max_retries,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                last_error = self._request_error(
                    "network_error",
                    f"LLM 网络错误：{exc}",
                    attempt=attempt,
                    retry_exhausted=attempt >= self.max_retries,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error from exc
        assert last_error is not None
        raise last_error

    def _complete_wenhua(self, messages: Sequence[Message]) -> LLMCallResult:
        started = time.perf_counter()
        last_error: LLMRequestError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                with httpx.stream(
                    "POST",
                    self.base_url,
                    headers=headers,
                    json=self._wenhua_payload(messages),
                    timeout=self.timeout_seconds + 10,
                ) as response:
                    status = int(getattr(response, "status_code", 200))
                    response_headers = getattr(response, "headers", {})
                    content_type = str(response_headers.get("content-type") or "")
                    if status >= 400:
                        last_error = self._http_error(
                            status,
                            _stream_response_text(response),
                            attempt=attempt,
                            content_type=content_type,
                        )
                        if status in _RETRYABLE_HTTP_STATUS and attempt < self.max_retries:
                            self._backoff(attempt)
                            continue
                        raise last_error

                    parts: list[str] = []
                    line_count = 0
                    event_samples: list[str] = []
                    done_received = False
                    for line in response.iter_lines():
                        text = str(line).strip()
                        if not text:
                            continue
                        line_count += 1
                        if len(event_samples) < 3:
                            event_samples.append(self._safe(text, limit=300))
                        if self._is_done_line(text):
                            done_received = True
                        content, stopped = self._parse_wenhua_sse_line(text)
                        if content:
                            parts.append(content)
                        if stopped:
                            break
                    if parts:
                        return LLMCallResult(
                            content="".join(parts),
                            provider=self.provider,
                            model=self.model,
                            duration_ms=round((time.perf_counter() - started) * 1000),
                            attempt_count=attempt + 1,
                            transport_retry_count=attempt,
                            http_status=status,
                            content_type=content_type,
                            sse_line_count=line_count,
                            sse_event_samples=tuple(event_samples),
                            done_received=done_received,
                        )
                    last_error = self._request_error(
                        "empty_sse_response",
                        "文华 SSE 未解析出 choices[0].delta.content",
                        attempt=attempt,
                        retry_exhausted=attempt >= self.max_retries,
                        http_status=status,
                        content_type=content_type,
                        sse_line_count=line_count,
                        sse_event_samples=event_samples,
                        done_received=done_received,
                    )
                    if attempt < self.max_retries:
                        self._backoff(attempt)
                        continue
                    raise last_error
            except LLMRequestError:
                raise
            except httpx.TimeoutException as exc:
                last_error = self._request_error(
                    "request_timeout",
                    f"文华 LLM 请求超时（{self.timeout_seconds} 秒）",
                    attempt=attempt,
                    retry_exhausted=attempt >= self.max_retries,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error from exc
            except httpx.RequestError as exc:
                last_error = self._request_error(
                    "network_error",
                    f"文华 LLM 网络错误：{exc}",
                    attempt=attempt,
                    retry_exhausted=attempt >= self.max_retries,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise last_error from exc
        assert last_error is not None
        raise last_error

    def _http_error(self, status: int, body: str, *, attempt: int, content_type: str) -> LLMRequestError:
        return self._request_error(
            "http_error",
            f"LLM HTTP {status}",
            attempt=attempt,
            retry_exhausted=status in _RETRYABLE_HTTP_STATUS and attempt >= self.max_retries,
            http_status=status,
            content_type=content_type,
            raw_response=body,
        )

    def _request_error(
        self,
        error_type: str,
        message: str,
        *,
        attempt: int,
        retry_exhausted: bool = False,
        http_status: int | None = None,
        content_type: str = "",
        raw_response: str = "",
        sse_line_count: int | None = None,
        sse_event_samples: Sequence[str] = (),
        done_received: bool | None = None,
    ) -> LLMRequestError:
        return LLMRequestError(
            error_type,
            self._safe(message, limit=1000),
            provider=self.provider,
            model=self.model,
            attempt_count=attempt + 1,
            transport_retry_count=attempt,
            retry_exhausted=retry_exhausted,
            http_status=http_status,
            content_type=self._safe(content_type, limit=200),
            raw_response_excerpt=self._safe(raw_response, limit=500),
            sse_line_count=sse_line_count,
            sse_event_samples=[self._safe(item, limit=300) for item in sse_event_samples[:3]],
            done_received=done_received,
        )

    def _safe(self, value: object, *, limit: int) -> str:
        return sanitize_text(value, secrets=(self.api_key,), limit=limit)

    @staticmethod
    def _backoff(attempt: int) -> None:
        time.sleep(2**attempt)

    @staticmethod
    def _messages_to_content(messages: Sequence[Message]) -> str:
        return "\n\n".join(
            f"{message.get('role', 'user')}:\n{str(message.get('content') or '').strip()}"
            for message in messages
            if str(message.get("content") or "").strip()
        )

    @classmethod
    def _wenhua_payload(cls, messages: Sequence[Message]) -> dict[str, str]:
        content = cls._messages_to_content(messages)
        # The current SHIXIModel contract requires both properties. Keeping
        # content also preserves compatibility with the earlier endpoint.
        return {"input": content, "content": content}

    @staticmethod
    def _is_done_line(line: str) -> bool:
        text = line.strip()
        if text.startswith("data:"):
            text = text[5:].strip()
        return text == "[DONE]"

    @staticmethod
    def _parse_wenhua_sse_line(line: str) -> tuple[str, bool]:
        text = line.strip()
        if not text:
            return "", False
        if text.startswith("data:"):
            text = text[5:].strip()
        if text == "[DONE]":
            return "", True
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return "", False
        choices = payload.get("choices") or []
        if not choices:
            return "", False
        first = choices[0]
        content = (first.get("delta") or {}).get("content") or ""
        return str(content), first.get("finish_reason") == "stop"


def _response_text(response: Any) -> str:
    try:
        return str(response.text)
    except Exception:
        return ""


def _stream_response_text(response: Any) -> str:
    try:
        data = response.read()
        return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
    except Exception:
        return ""

"""
pn07 LLM API 客户端

使用 httpx 调用 OpenAI 兼容 API (/v1/chat/completions)。
支持自动重试（指数退避）和健康检查。
"""

from __future__ import annotations

import logging
import json
import time

logger = logging.getLogger(__name__)


class LLMAPIClient:
    """OpenAI 兼容 API 客户端。

    Usage:
        config = LLMConfig.from_settings()
        client = LLMAPIClient(config)
        if client.health_check():
            response = client.chat([{"role": "user", "content": "..."}])
    """

    def __init__(self, config) -> None:
        """
        Args:
            config: pn07.models.LLMConfig 实例
        """
        self._config = config
        self._provider = config.provider.lower()
        self._api_key = config.api_key
        self._base_url = config.base_url.rstrip("/")
        self._model = config.model
        self._timeout = config.timeout_seconds
        self._max_retries = config.max_retries

    @property
    def is_configured(self) -> bool:
        return self._config.is_configured

    def chat(self, messages: list[dict], *, retries: int | None = None) -> str:
        """
        发送 chat completion 请求。

        Args:
            messages: [{"role":"system","content":"..."}, {"role":"user","content":"..."}]
            retries: 最大重试次数（None=使用配置默认值）

        Returns:
            LLM 返回的文本内容

        Raises:
            RuntimeError: 所有重试耗尽或 API 配置无效
            ValueError: 4xx 客户端错误（不重试）
        """
        import httpx

        if not self.is_configured:
            raise RuntimeError("LLM API 未配置（缺少 api_key/base_url 或 provider 配置）")

        if self._provider == "wenhua":
            return self._chat_wenhua(messages, retries=retries)

        max_retries = retries if retries is not None else self._max_retries
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                url = self._openai_url("chat/completions")
                headers = {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self._model,
                    "messages": messages,
                    "temperature": self._config.temperature,
                    "max_tokens": self._config.max_tokens,
                }
                enable_thinking = getattr(self._config, "enable_thinking", None)
                if enable_thinking is not None:
                    payload["enable_thinking"] = enable_thinking

                response = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout + 10,  # 额外 10s 缓冲
                )

                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]

                elif response.status_code in (429, 500, 502, 503, 504):
                    # 可重试错误
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if attempt < max_retries:
                        wait = 2 ** attempt
                        logger.warning("LLM API 重试 %s/%s, 等待 %ss: %s", attempt + 1, max_retries, wait, last_error)
                        time.sleep(wait)
                        continue

                elif response.status_code in (401, 403):
                    raise ValueError(f"LLM API 认证失败: HTTP {response.status_code}")

                elif response.status_code == 400:
                    raise ValueError(f"LLM API 请求错误: {response.text[:300]}")

                else:
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    if attempt < max_retries:
                        time.sleep(2 ** attempt)
                        continue

            except httpx.TimeoutException:
                last_error = f"请求超时 ({self._timeout}s)"
                if attempt < max_retries:
                    logger.warning("LLM API 超时重试 %s/%s", attempt + 1, max_retries)
                    continue
            except httpx.RequestError as exc:
                last_error = f"网络错误: {exc}"
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

        raise RuntimeError(f"LLM API 调用失败（已重试 {max_retries} 次）: {last_error}")

    WENHUA_SSE_URL: str = "https://swarm.wenhua.com.cn/aiservice/api/ShiXi/GetContent"

    def _chat_wenhua(self, messages: list[dict], *, retries: int | None = None) -> str:
        """调用文华 ShiXi/GetContent SSE 接口并拼接完整回答。

        SSE 流式协议：
        - 每条数据为一行 JSON，可能带 "data:" 前缀
        - choices[0].delta.content 为增量文本
        - finish_reason == "stop" 表示流正常结束
        - [DONE] 为备选结束信号

        使用 iter_bytes + 行缓冲区确保跨 chunk 的行正确拼接。
        """
        import httpx

        max_retries = retries if retries is not None else self._max_retries
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                headers = {
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                }

                stream_timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

                with httpx.stream(
                    "POST",
                    self.WENHUA_SSE_URL,
                    json={"content": self._messages_to_content(messages)},
                    headers=headers,
                    timeout=stream_timeout,
                ) as response:
                    if response.status_code in (401, 403):
                        raise ValueError(f"LLM API 认证失败: HTTP {response.status_code}")
                    if response.status_code == 400:
                        body = response.read().decode("utf-8", errors="ignore")
                        raise ValueError(f"LLM API 请求错误: {body[:300]}")
                    if response.status_code != 200:
                        body = response.read().decode("utf-8", errors="ignore")
                        last_error = f"HTTP {response.status_code}: {body[:200]}"
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                            time.sleep(2 ** attempt)
                            continue
                        break

                    content_parts: list[str] = []
                    stopped = False
                    line_buffer = ""

                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        chunk_text = chunk.decode("utf-8", errors="ignore")
                        line_buffer += chunk_text

                        while "\n" in line_buffer:
                            raw_line, line_buffer = line_buffer.split("\n", 1)
                            piece, is_stop = self._parse_wenhua_sse_line(raw_line)
                            if piece:
                                content_parts.append(piece)
                            if is_stop:
                                stopped = True
                                break

                        if stopped:
                            break

                    if line_buffer.strip() and not stopped:
                        piece, is_stop = self._parse_wenhua_sse_line(line_buffer)
                        if piece:
                            content_parts.append(piece)
                        if is_stop:
                            stopped = True

                    if content_parts:
                        if not stopped:
                            logger.warning(
                                "文华 SSE 流结束但未收到 finish_reason=stop，"
                                "已收到 %d 个分片，共 %d 字符",
                                len(content_parts), sum(len(p) for p in content_parts),
                            )
                        return "".join(content_parts)
                    if stopped:
                        return ""
                    last_error = "文华 SSE 响应为空"

            except httpx.TimeoutException:
                last_error = "请求超时 (connect=10s, read=120s)"
                if attempt < max_retries:
                    logger.warning("文华 SSE 超时重试 %s/%s", attempt + 1, max_retries)
                    continue
            except httpx.RequestError as exc:
                last_error = f"网络错误: {exc}"
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue

        raise RuntimeError(f"LLM API 调用失败（已重试 {max_retries} 次）: {last_error}")

    @staticmethod
    def _messages_to_content(messages: list[dict]) -> str:
        """将 chat messages 合并为文华接口的 content 字段。"""
        blocks: list[str] = []
        for message in messages:
            role = message.get("role", "user")
            content = str(message.get("content", "")).strip()
            if content:
                blocks.append(f"{role}:\n{content}")
        return "\n\n".join(blocks)

    @staticmethod
    def _parse_wenhua_sse_line(line: str) -> tuple[str, bool]:
        """解析单行 SSE/JSON 响应，返回 (content_delta, is_stop)。

        结束判断：
        1. finish_reason == "stop"  → 正常结束（最可靠）
        2. [DONE]                    → OpenAI 兼容结束标记
        3. finish_reason 为其他非空值 → 异常结束（如 "length"/"content_filter"）
        """
        text = line.strip()
        if not text:
            return "", False
        if text.startswith("data:"):
            text = text[5:].strip()
        if text == "[DONE]":
            return "", True

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return "", False

        choices = data.get("choices") or []
        if not choices:
            return "", False

        first = choices[0]
        delta = first.get("delta") or {}
        content = delta.get("content") or ""

        finish_reason = first.get("finish_reason")
        # None 或空 → 未结束；"stop" → 正常结束；其他 → 异常结束
        is_stop = (finish_reason == "stop")

        if finish_reason and finish_reason != "stop":
            logger.warning("文华 SSE 异常结束: finish_reason=%s", finish_reason)

        return str(content), is_stop

    def health_check(self) -> bool:
        """快速验证 API 配置是否可用（发空消息检查连通性）。"""
        if not self.is_configured:
            return False
        if self._provider == "wenhua":
            return True
        try:
            import httpx
            url = self._openai_url("models")
            headers = {"Authorization": f"Bearer {self._api_key}"}
            resp = httpx.get(url, headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def _openai_url(self, path: str) -> str:
        """Build OpenAI-compatible endpoint URLs from root or /v1 base_url."""
        base_url = self._base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}/{path.lstrip('/')}"
        return f"{base_url}/v1/{path.lstrip('/')}"

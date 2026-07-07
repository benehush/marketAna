"""
pn07 数据模型

定义 LLM 推理配置和推理结果。
"""

from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """LLM 推理配置，默认从 Settings 读取。"""

    provider: str = "openai"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout_seconds: int = 30
    max_retries: int = 3
    temperature: float = 0.1          # 低温度保证稳定 JSON 输出
    max_tokens: int = 800
    manual_review_threshold: float = 0.5   # < 此值标记待人工确认
    max_input_chars: int = 8000           # 输入文本截断长度

    @property
    def is_configured(self) -> bool:
        if self.provider.lower() == "wenhua":
            return bool(self.base_url)
        return bool(self.api_key and self.base_url)

    @classmethod
    def from_settings(cls) -> "LLMConfig":
        """从项目 Settings 创建配置。"""
        from back_end.app.core.config import get_settings

        s = get_settings()
        return cls(
            provider=(s.llm_provider or "openai").lower(),
            api_key=s.llm_api_key or "",
            base_url=s.llm_base_url or "",
            model=s.llm_model or "",
            timeout_seconds=s.llm_timeout_seconds,
        )


@dataclass
class InferItem:
    """单个品种的 LLM 推理结果。"""

    product: str | None = None
    contract: str | None = None
    direction: str | None = None
    reason: str = ""
    confidence: float = 0.0
    need_manual_review: bool = False


@dataclass
class InferResult:
    """LLM 推理结果。"""

    results: list[InferItem] = field(default_factory=list)
    product: str | None = None
    contract: str | None = None
    direction: str | None = None
    reason: str = ""
    confidence: float = 0.0
    need_manual_review: bool = False
    model: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    error_msg: str = ""
    raw_response: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.results) or (self.product is not None and self.direction is not None)

    def __post_init__(self) -> None:
        if self.results and self.product is None:
            primary = max(self.results, key=lambda item: item.confidence)
            self.product = primary.product
            self.contract = primary.contract
            self.direction = primary.direction
            self.reason = primary.reason
            self.confidence = primary.confidence
            self.need_manual_review = any(item.need_manual_review for item in self.results)

    def summary(self) -> str:
        return (
            f"product={self.product} direction={self.direction} "
            f"confidence={self.confidence:.2f} manual={self.need_manual_review} "
            f"model={self.model} retries={self.retry_count} "
            f"duration={self.duration_ms}ms"
        )

"""Configuration for the standalone data-processing package."""

from __future__ import annotations

from dataclasses import dataclass
import os


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True, slots=True)
class ProcessingConfig:
    auto_approve_threshold: float = 0.72
    review_threshold: float = 0.35
    rule_accept_threshold: float = 0.70
    llm_fallback_margin: float = 0.20
    max_llm_snippets: int = 6
    max_llm_chars: int = 1200
    context_window: int = 80
    llm_timeout_seconds: int = 60
    llm_provider: str = "openai"
    llm_max_retries: int = 2
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    pipeline_version: str = "data-processing-v1"

    @classmethod
    def from_env(cls) -> "ProcessingConfig":
        return cls(
            auto_approve_threshold=_float("DATA_AUTO_APPROVE_THRESHOLD", 0.72),
            review_threshold=_float("DATA_REVIEW_THRESHOLD", 0.35),
            rule_accept_threshold=_float("DATA_RULE_ACCEPT_THRESHOLD", 0.70),
            llm_fallback_margin=_float("DATA_LLM_FALLBACK_MARGIN", 0.20),
            max_llm_snippets=_int("DATA_MAX_LLM_SNIPPETS", 6),
            max_llm_chars=_int("DATA_MAX_LLM_CHARS", 1200),
            context_window=_int("DATA_CONTEXT_WINDOW", 80),
            llm_timeout_seconds=_int("DATA_LLM_TIMEOUT_SECONDS", _int("LLM_TIMEOUT_SECONDS", 60)),
            llm_provider=os.getenv("DATA_LLM_PROVIDER", os.getenv("LLM_PROVIDER", "openai")),
            llm_max_retries=_int("DATA_LLM_MAX_RETRIES", _int("LLM_MAX_RETRIES", 2)),
            llm_api_key=os.getenv("DATA_LLM_API_KEY", os.getenv("LLM_API_KEY", "")),
            llm_base_url=os.getenv("DATA_LLM_BASE_URL", os.getenv("LLM_BASE_URL", "")),
            llm_model=os.getenv("DATA_LLM_MODEL", os.getenv("LLM_MODEL", "")),
            pipeline_version=os.getenv("DATA_PIPELINE_VERSION", "data-processing-v1"),
        )

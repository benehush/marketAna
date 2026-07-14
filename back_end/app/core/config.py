from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MarketANA"
    app_env: str = "development"
    log_level: str = "INFO"
    data_root: str = "data"

    database_url: str | None = None

    llm_provider: str = "wenhua"
    llm_api_key: str | None = None
    llm_base_url: str | None = "https://swarm.wenhua.com.cn/aiservice/api/ShiXi/GetContent"
    llm_model: str | None = "wenhua-shixi"
    llm_timeout_seconds: int = 300
    llm_max_retries: int = 2

    task_batch_size: int = 20
    rule_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # Scheduler 轮询间隔（秒）
    scheduler_poll_interval_seconds: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

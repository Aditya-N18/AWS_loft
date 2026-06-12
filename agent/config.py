from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    senso_api_key: str
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_host: str
    agent_mock_mode: bool
    churn_threshold: float
    anthropic_model: str
    clickhouse_host: str
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_db: str
    root_dir: Path
    output_dir: Path
    templates_dir: Path
    fixtures_dir: Path

    @classmethod
    def load(cls) -> Settings:
        root = ROOT_DIR
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            senso_api_key=os.getenv("SENSO_API_KEY", ""),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
            langfuse_host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
            agent_mock_mode=_bool(os.getenv("AGENT_MOCK_MODE"), default=True),
            churn_threshold=float(os.getenv("CHURN_THRESHOLD", "5000")),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            clickhouse_host=os.getenv("CLICKHOUSE_HOST", ""),
            clickhouse_user=os.getenv("CLICKHOUSE_USER", ""),
            clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            clickhouse_db=os.getenv("CLICKHOUSE_DB", "ghost_churn"),
            root_dir=root,
            output_dir=root / "output",
            templates_dir=root / "templates",
            fixtures_dir=root / "agent" / "fixtures",
        )

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_senso(self) -> bool:
        return bool(self.senso_api_key)

    @property
    def has_langfuse(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


settings = Settings.load()

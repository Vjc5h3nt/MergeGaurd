"""Configuration loader: environment variables + per-repo .github/ai-reviewer.yml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TriggerConfig(BaseModel):
    on_review_request: bool = True
    on_label: str = "ai-code-review"
    on_push_to_branches: list[str] = Field(default_factory=list)


class ContextConfig(BaseModel):
    architecture_doc: str = "docs/ARCHITECTURE.md"
    coding_standards: str = "docs/CODING_STANDARDS.md"
    test_patterns: str = "tests/README.md"


class AnalysisConfig(BaseModel):
    risk_threshold_block: int = 75
    risk_threshold_warn: int = 50
    check_security: bool = True
    check_test_coverage: bool = True
    check_breaking_changes: bool = True


class OutputConfig(BaseModel):
    post_inline_comments: bool = True
    post_summary_comment: bool = True
    auto_approve_below_risk: int = 20


class RepoConfig(BaseModel):
    trigger: TriggerConfig = Field(default_factory=TriggerConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "RepoConfig":
        if not path.exists():
            return cls()
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls.model_validate(data)


class AppConfig(BaseModel):
    """Runtime configuration assembled from environment variables."""

    # GitHub
    github_token: str = Field(default="", description="GITHUB_TOKEN env var")
    github_app_id: str = Field(default="", description="GITHUB_APP_ID env var")
    github_app_private_key_path: str = Field(default="")
    github_webhook_secret: str = Field(default="")

    # AWS / Bedrock
    aws_region: str = Field(default="us-east-1")
    bedrock_model_id: str = Field(default="us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    bedrock_model_haiku_id: str = Field(default="us.anthropic.claude-haiku-3-5-20241022-v1:0")
    bedrock_region: str = Field(default="us-east-1")

    # Feedback store
    feedback_s3_bucket: str = Field(default="")
    feedback_db_path: str = Field(default="")

    # MergeGuard
    log_level: str = Field(default="INFO")
    cache_dir: Path = Field(default=Path("/tmp/mergeguard-cache"))

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            github_token=os.getenv("GITHUB_TOKEN", ""),
            github_app_id=os.getenv("GITHUB_APP_ID", ""),
            github_app_private_key_path=os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", ""),
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
            aws_region=os.getenv("AWS_REGION", "us-east-1"),
            bedrock_model_id=os.getenv(
                "BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
            ),
            bedrock_model_haiku_id=os.getenv(
                "BEDROCK_MODEL_HAIKU_ID", "us.anthropic.claude-haiku-3-5-20241022-v1:0"
            ),
            bedrock_region=os.getenv("BEDROCK_REGION", "us-east-1"),
            log_level=os.getenv("MERGEGUARD_LOG_LEVEL", "INFO"),
            cache_dir=Path(os.getenv("MERGEGUARD_CACHE_DIR", "/tmp/mergeguard-cache")),
            feedback_s3_bucket=os.getenv("MERGEGUARD_FEEDBACK_BUCKET", ""),
            feedback_db_path=os.getenv("MERGEGUARD_FEEDBACK_DB", ""),
        )


_app_config: AppConfig | None = None


def get_config() -> AppConfig:
    global _app_config
    if _app_config is None:
        _app_config = AppConfig.from_env()
    return _app_config

"""
Centralized configuration using Pydantic Settings.
All values can be overridden via environment variables or .env file.
"""

from typing import Literal, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"
    MAX_DIFF_SIZE_KB: int = 500          # Skip review if diff is too large
    MAX_FILES_PER_REVIEW: int = 20       # Limit files reviewed per PR

    # ── LLM (Model-Agnostic) ─────────────────────────────────────────────────
    LLM_PROVIDER: Literal["openai", "anthropic", "azure_openai", "ollama"] = "openai"
    LLM_MODEL: str = "gpt-4o"           # Override per provider
    LLM_TEMPERATURE: float = 0.2        # Low temp for consistent reviews
    LLM_MAX_TOKENS: int = 4096
    LLM_TIMEOUT_SECONDS: int = 120

    # Provider-specific API keys (only set the one you use)
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    AZURE_OPENAI_API_KEY: Optional[str] = None
    AZURE_OPENAI_ENDPOINT: Optional[str] = None
    AZURE_OPENAI_DEPLOYMENT: Optional[str] = None
    OLLAMA_BASE_URL: str = "http://localhost:11434"

    # ── GitHub ────────────────────────────────────────────────────────────────
    GITHUB_WEBHOOK_SECRET: Optional[str] = None   # For verifying webhook payloads
    GITHUB_TOKEN: Optional[str] = None            # PAT or GitHub App token
    GITHUB_APP_ID: Optional[str] = None
    GITHUB_APP_PRIVATE_KEY_PATH: Optional[str] = None

    # ── GitLab ────────────────────────────────────────────────────────────────
    GITLAB_WEBHOOK_SECRET: Optional[str] = None
    GITLAB_TOKEN: Optional[str] = None            # Personal or project access token
    GITLAB_BASE_URL: str = "https://gitlab.com"

    # ── RAG ──────────────────────────────────────────────────────────────────
    RAG_ENABLED: bool = False                    # Set true to enable repo-level context
    RAG_EMBEDDING_PROVIDER: str = "openai"       # openai | voyageai | sentence_transformers
    RAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_INDEX_PATH: str = "/tmp/rag_indexes"     # Where to persist FAISS indexes
    VOYAGE_API_KEY: Optional[str] = None         # For voyageai provider

    # ── Review Behaviour ─────────────────────────────────────────────────────
    REVIEW_LANGUAGES: list[str] = []              # Empty = all languages
    SKIP_PATTERNS: list[str] = [                  # Files to never review
        "*.lock",
        "*.min.js",
        "*.min.css",
        "package-lock.json",
        "yarn.lock",
        "poetry.lock",
        "*.generated.*",
        "migrations/*",
        "*.pb.go",
        "*.pb.py",
    ]
    POST_INLINE_COMMENTS: bool = True
    POST_SUMMARY_COMMENT: bool = True
    MIN_SEVERITY_TO_COMMENT: Literal["low", "medium", "high", "critical"] = "medium"


settings = Settings()

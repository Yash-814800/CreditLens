from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# These must exactly match the placeholder strings in .env.example: production
# start-up is refused if the corresponding secret is left equal to one of these.
_PLACEHOLDER_JWT_SECRET = "change-me-to-a-random-32-plus-character-secret"  # nosec B105
_PLACEHOLDER_HMAC_PEPPER = "change-me-to-a-random-32-plus-character-pepper"
_PLACEHOLDER_DEMO_PASSWORD = "change-me-demo-only"  # nosec B105


class Settings(BaseSettings):
    """App configuration loaded from environment (.env locally, real env/SSM in
    prod). See CLAUDE.md rule 2: no hardcoded secrets, .env is gitignored."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Postgres admin/migration role (alembic only; the app never connects as this).
    postgres_db: str = "creditlens"
    postgres_user: str = "creditlens_admin"
    postgres_password: str = ""

    # Least-privilege runtime role the app itself connects as.
    app_db_user: str = "creditlens_app"
    app_db_password: str = ""
    database_url: str = (
        "postgresql+asyncpg://creditlens_app:change-me-local-only@db:5432/creditlens"
    )

    jwt_secret: str = ""
    jwt_expire_minutes: int = 30
    hmac_pepper: str = ""

    gemini_api_key: str = ""
    gemini_vision_model: str = ""
    gemini_summary_model: str = ""
    mock_llm: bool = True
    # Hard ceiling on real Gemini calls in one process lifetime (extraction + summary).
    # A safety backstop against a runaway loop or misbehaving retry burning budget,
    # not a rate limit — see app/services/extraction/call_budget.py.
    gemini_max_calls_per_run: int = 20
    # When enabled, each document is extracted twice with different prompt/field orderings.
    # Disagreement on critical numeric fields becomes a fraud finding and lowers confidence.
    extraction_self_consistency: bool = False

    storage_backend: Literal["local", "s3"] = "local"
    s3_bucket: str = ""
    aws_region: str = "ap-south-1"

    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    max_upload_mb: int = 15
    rate_limit_login: str = "5/minute"
    rate_limit_upload: str = "10/minute"

    enable_demo_endpoints: bool = True
    demo_underwriter_password: str = ""
    demo_auditor_password: str = ""
    demo_admin_password: str = ""

    site_address: str = "localhost"
    retention_days: int = 90

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def production_guard_errors(self) -> list[str]:
        """Every reason production start-up would be unsafe right now. Empty means safe.

        Kept as a plain method (rather than a validator that always runs) so tests can
        construct a Settings instance for a *hypothetical* production config without the
        real process's env forcing app_env back to non-production first.
        """
        if self.app_env != "production":
            return []

        problems: list[str] = []
        if self.mock_llm:
            problems.append("MOCK_LLM must be false when APP_ENV=production")

        for name, value, placeholder in (
            ("JWT_SECRET", self.jwt_secret, _PLACEHOLDER_JWT_SECRET),
            ("HMAC_PEPPER", self.hmac_pepper, _PLACEHOLDER_HMAC_PEPPER),
        ):
            if not value or len(value) < 32:
                problems.append(f"{name} must be set and at least 32 characters in production")
            elif value == placeholder:
                problems.append(f"{name} must not be left at its .env.example placeholder value")

        for name, value in (
            ("DEMO_UNDERWRITER_PASSWORD", self.demo_underwriter_password),
            ("DEMO_AUDITOR_PASSWORD", self.demo_auditor_password),
            ("DEMO_ADMIN_PASSWORD", self.demo_admin_password),
        ):
            if value == _PLACEHOLDER_DEMO_PASSWORD:
                problems.append(f"{name} must not be left at its .env.example placeholder value")

        return problems


def load_settings() -> Settings:
    settings = Settings()
    problems = settings.production_guard_errors()
    if problems:
        joined = "\n".join(f"  - {p}" for p in problems)
        raise RuntimeError(f"Refusing to start in production mode:\n{joined}")
    return settings


settings = load_settings()

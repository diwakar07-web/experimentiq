"""
ExperimentIQ — Application Settings

Purpose:
    Provides a type-safe, validated, configuration-driven settings model
    using Pydantic Settings v2. All configuration values are read from
    environment variables or a .env file. Nothing is hardcoded.

Design:
    - Singleton pattern via lru_cache ensures settings are loaded once.
    - Nested models group related settings for clarity.
    - All fields have validation, defaults, and docstrings.

Dependencies:
    - pydantic-settings >= 2.0
    - python-dotenv >= 1.0

Inputs:
    Environment variables or .env file (see .env.example).

Outputs:
    A fully validated Settings instance.
"""

from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Project root resolution (three levels up from this file: config/ → experimentiq/)
# ---------------------------------------------------------------------------
PROJECT_ROOT: Path = Path(__file__).parent.parent.resolve()


# ---------------------------------------------------------------------------
# Nested Configuration Models
# ---------------------------------------------------------------------------


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection configuration."""

    model_config = SettingsConfigDict(env_prefix="DB_", env_file=".env", extra="ignore")

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL port")
    name: str = Field(default="experimentiq_db", description="Database name")
    user: str = Field(default="experimentiq", description="Database user")
    password: str = Field(default="experimentiq_password", description="Database password")
    bulk_insert_chunk_size: int = Field(
        default=10000,
        ge=100,
        le=100000,
        description="Number of rows per bulk insert batch",
    )

    @property
    def dsn(self) -> str:
        """Return the SQLAlchemy-compatible DSN string."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )

    @property
    def psycopg2_dsn(self) -> str:
        """Return raw psycopg2 DSN string."""
        return (
            f"host={self.host} port={self.port} dbname={self.name} "
            f"user={self.user} password={self.password}"
        )


class GeneratorSettings(BaseSettings):
    """Synthetic data generation configuration."""

    model_config = SettingsConfigDict(env_prefix="GENERATOR_", env_file=".env", extra="ignore")

    num_users: int = Field(
        default=500000,
        ge=1000,
        le=5000000,
        description="Total number of simulated users",
    )
    experiment_days: int = Field(
        default=90,
        ge=7,
        le=365,
        description="Duration of the experiment in days",
    )
    baseline_conversion_rate: float = Field(
        default=0.035,
        ge=0.001,
        le=0.5,
        description="Purchase conversion rate for the control group",
    )
    variant_uplift: float = Field(
        default=0.15,
        ge=-0.5,
        le=2.0,
        description="Relative uplift for the variant group (e.g., 0.15 = 15% relative increase)",
    )
    random_seed: int = Field(
        default=42,
        description="Random seed for reproducible data generation",
    )
    variant_split: float = Field(
        default=0.50,
        ge=0.1,
        le=0.9,
        description="Proportion of users assigned to the variant group",
    )
    experiment_start_date: date = Field(
        default=date(2024, 1, 1),
        description="Experiment start date (ISO 8601)",
    )
    max_events_per_session: int = Field(
        default=20,
        ge=2,
        le=100,
        description="Maximum number of events tracked per session",
    )
    avg_sessions_per_user: float = Field(
        default=2.5,
        ge=1.0,
        le=20.0,
        description="Average number of sessions per user over experiment duration",
    )

    @field_validator("variant_split")
    @classmethod
    def validate_split(cls, v: float) -> float:
        """Ensure variant split leaves room for the control group."""
        if not 0.1 <= v <= 0.9:
            raise ValueError("variant_split must be between 0.1 and 0.9")
        return v

    @property
    def variant_conversion_rate(self) -> float:
        """Compute the absolute conversion rate for the variant group."""
        return self.baseline_conversion_rate * (1 + self.variant_uplift)

    @property
    def experiment_end_date(self) -> date:
        """Compute the experiment end date from start + duration."""
        from datetime import timedelta

        return self.experiment_start_date + timedelta(days=self.experiment_days)


class StatisticsSettings(BaseSettings):
    """Statistical analysis configuration."""

    model_config = SettingsConfigDict(env_prefix="STATS_", env_file=".env", extra="ignore")

    alpha: float = Field(
        default=0.05,
        ge=0.001,
        le=0.2,
        description="Significance level for hypothesis testing",
    )
    power_target: float = Field(
        default=0.80,
        ge=0.50,
        le=0.99,
        description="Target statistical power (1 - beta)",
    )
    mde: float = Field(
        default=0.003,
        ge=0.0001,
        le=0.1,
        description="Minimum detectable effect (absolute difference in conversion rate)",
    )
    correction_method: Literal["bonferroni", "benjamini_hochberg", "none"] = Field(
        default="benjamini_hochberg",
        description="Multiple testing correction method",
    )
    srm_alpha: float = Field(
        default=0.01,
        ge=0.001,
        le=0.1,
        description="Significance level for Sample Ratio Mismatch detection",
    )


class RecommendationSettings(BaseSettings):
    """Recommendation engine configuration."""

    model_config = SettingsConfigDict(env_prefix="RECOMMENDATION_", env_file=".env", extra="ignore")

    min_practical_uplift: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="Minimum relative uplift required to recommend LAUNCH",
    )
    guardrail_tolerance: float = Field(
        default=0.02,
        ge=0.0,
        le=0.5,
        description="Maximum acceptable relative degradation in guardrail metrics",
    )


class OutputSettings(BaseSettings):
    """Output path configuration (all relative to project root)."""

    model_config = SettingsConfigDict(env_prefix="OUTPUT_", env_file=".env", extra="ignore")

    data_raw_dir: str = Field(default="data/raw", description="Raw generated CSV directory")
    data_processed_dir: str = Field(
        default="data/processed", description="Processed analytical datasets"
    )
    data_exports_dir: str = Field(
        default="data/exports", description="Power BI ready exports"
    )
    reports_dir: str = Field(default="data/reports", description="Generated PDF reports")

    def raw_path(self) -> Path:
        return PROJECT_ROOT / self.data_raw_dir

    def processed_path(self) -> Path:
        return PROJECT_ROOT / self.data_processed_dir

    def exports_path(self) -> Path:
        return PROJECT_ROOT / self.data_exports_dir

    def reports_path(self) -> Path:
        return PROJECT_ROOT / self.reports_dir


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(env_prefix="LOG_", env_file=".env", extra="ignore")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging verbosity level"
    )
    file: str = Field(
        default="data/logs/pipeline.log",
        description="Log file path (relative to project root). Empty string disables file logging.",
    )
    use_rich: bool = Field(
        default=True,
        description="Use rich console handler for formatted terminal output",
    )

    def log_file_path(self) -> Path | None:
        """Return the absolute path to the log file, or None if disabled."""
        if not self.file:
            return None
        return PROJECT_ROOT / self.file


class AnalyticsSettings(BaseSettings):
    """Analytics engine configuration."""

    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", env_file=".env", extra="ignore")

    fetch_chunk_size: int = Field(
        default=50000,
        ge=1000,
        description="Number of rows fetched per database chunk during analytics queries",
    )


# ---------------------------------------------------------------------------
# Root Settings Model
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """
    ExperimentIQ application settings.

    All configuration is read from environment variables or a .env file.
    Nested models group related settings logically.

    Usage:
        from config import get_settings
        settings = get_settings()
        print(settings.database.dsn)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    generator: GeneratorSettings = Field(default_factory=GeneratorSettings)
    statistics: StatisticsSettings = Field(default_factory=StatisticsSettings)
    recommendation: RecommendationSettings = Field(
        default_factory=RecommendationSettings
    )
    output: OutputSettings = Field(default_factory=OutputSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)

    @model_validator(mode="after")
    def ensure_output_directories_exist(self) -> "Settings":
        """Create all required output directories on first load."""
        directories = [
            self.output.raw_path(),
            self.output.processed_path(),
            self.output.exports_path(),
            self.output.reports_path(),
        ]
        # Also create log directory
        log_path = self.logging.log_file_path()
        if log_path is not None:
            directories.append(log_path.parent)

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

        return self

    @property
    def project_root(self) -> Path:
        """Return the absolute project root path."""
        return PROJECT_ROOT


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the application settings singleton.

    Uses lru_cache to ensure settings are loaded from environment only once.
    Call get_settings.cache_clear() in tests to force reload.

    Returns:
        Settings: Fully validated application configuration.

    Raises:
        ValidationError: If any required setting fails validation.
    """
    logger.debug("Loading application settings from environment")
    settings = Settings()
    logger.info(
        "Settings loaded | DB: %s:%s/%s | Users: %s | Seed: %s",
        settings.database.host,
        settings.database.port,
        settings.database.name,
        settings.generator.num_users,
        settings.generator.random_seed,
    )
    return settings

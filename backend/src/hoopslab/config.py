"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated HoopsLab settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="HOOPSLAB_",
        extra="ignore",
        frozen=True,
    )

    database_url: str = Field(
        default="postgresql+psycopg://hoopslab:hoopslab@localhost:5432/hoopslab"
    )
    source_cache_dir: Path = Path("data/raw")

    @model_validator(mode="after")
    def database_must_use_postgresql(self) -> Self:
        """Reject a subtly incompatible database before startup."""
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            msg = "database_url must use PostgreSQL"
            raise ValueError(msg)
        return self


@lru_cache
def get_settings() -> Settings:
    """Return one immutable settings instance per process."""
    return Settings()

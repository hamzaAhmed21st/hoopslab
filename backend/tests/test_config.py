"""Configuration contract tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from hoopslab.config import Settings


def test_settings_load_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_dir = tmp_path / "source-cache"
    monkeypatch.setenv(
        "HOOPSLAB_DATABASE_URL",
        "postgresql+psycopg://analyst:secret@db.internal:5432/shots",
    )
    monkeypatch.setenv("HOOPSLAB_SOURCE_CACHE_DIR", str(cache_dir))
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.database_url.endswith("@db.internal:5432/shots")
    assert settings.source_cache_dir == cache_dir


def test_settings_reject_non_postgresql_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError, match="must use PostgreSQL"):
        Settings(database_url="sqlite:///hoopslab.db")

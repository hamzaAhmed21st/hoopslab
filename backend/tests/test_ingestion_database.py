"""Real PostgreSQL ingestion, idempotency, and provenance integration tests."""

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from hoopslab.ingestion import (
    IngestionConflictError,
    SourceDataError,
    ingest_season,
)
from hoopslab.quality import generate_quality_report
from hoopslab.sources.archive import SourceAsset, file_sha256


@pytest.fixture
def database_engine() -> Iterator[Engine]:
    database_url = os.environ.get("HOOPSLAB_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("HOOPSLAB_TEST_DATABASE_URL is not configured")
    engine = sa.create_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


def _cleanup(engine: Engine, season_start: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM games WHERE season_start = :season"),
            {"season": season_start},
        )
        connection.execute(
            sa.text("DELETE FROM players WHERE source_player_id IN (100, 200, 300)")
        )
        connection.execute(
            sa.text("DELETE FROM teams WHERE source_team_id IN (1, 2, 3)")
        )
        connection.execute(
            sa.text("DELETE FROM ingestion_runs WHERE season_start = :season"),
            {"season": season_start},
        )


def test_atomic_ingestion_is_idempotent_and_auditable(
    database_engine: Engine,
    tmp_path: Path,
    resolved_season_rows_factory: Callable[[int], list[dict[str, Any]]],
) -> None:
    season_start = 2098
    _cleanup(database_engine, season_start)
    path = tmp_path / "season.parquet"
    rows = resolved_season_rows_factory(season_start)
    pq.write_table(pa.Table.from_pylist(rows), path)
    asset = SourceAsset(season_start, "rg", file_sha256(path), expected_rows=len(rows))

    try:
        first = ingest_season(database_engine, asset, path, batch_size=2)
        second = ingest_season(database_engine, asset, path, batch_size=2)

        with database_engine.connect() as connection:
            counts = (
                connection.execute(
                    sa.text(
                        """
                    SELECT
                        (SELECT COUNT(*) FROM shots AS s JOIN games AS g
                         ON g.source_game_id = s.game_id
                         WHERE g.season_start = :season) AS shots,
                        (SELECT COUNT(*) FROM games
                         WHERE season_start = :season) AS games,
                        (SELECT COUNT(*) FROM ingestion_runs
                         WHERE season_start = :season
                           AND status = 'completed') AS completed,
                        (SELECT COUNT(*) FROM ingestion_runs
                         WHERE season_start = :season AND status = 'skipped') AS skipped
                    """
                    ),
                    {"season": season_start},
                )
                .mappings()
                .one()
            )
            report = generate_quality_report(connection)

        assert first.status == "completed"
        assert second.status == "skipped"
        assert dict(counts) == {"shots": 6, "games": 3, "completed": 1, "skipped": 1}
        integrity = report["integrity"]
        assert isinstance(integrity, dict)
        assert integrity["duplicate_shot_keys"] == 0
        assert integrity["participant_relationship_failures"] == 0

        changed_rows = [*rows, {**rows[0], "GAME_EVENT_ID": 12}]
        changed_path = tmp_path / "changed.parquet"
        pq.write_table(pa.Table.from_pylist(changed_rows), changed_path)
        changed_asset = SourceAsset(
            season_start,
            "rg",
            file_sha256(changed_path),
            expected_rows=len(changed_rows),
        )
        with pytest.raises(IngestionConflictError, match="already completed"):
            ingest_season(database_engine, changed_asset, changed_path, batch_size=2)
    finally:
        _cleanup(database_engine, season_start)


def test_failed_normalization_never_records_completion_or_partial_data(
    database_engine: Engine,
    tmp_path: Path,
    resolved_season_rows_factory: Callable[[int], list[dict[str, Any]]],
) -> None:
    season_start = 2097
    _cleanup(database_engine, season_start)
    path = tmp_path / "ambiguous.parquet"
    rows = resolved_season_rows_factory(season_start)[:2]
    pq.write_table(pa.Table.from_pylist(rows), path)
    asset = SourceAsset(season_start, "rg", file_sha256(path), expected_rows=len(rows))

    try:
        with pytest.raises(SourceDataError, match="not uniquely resolvable"):
            ingest_season(database_engine, asset, path, batch_size=2)
        with database_engine.connect() as connection:
            statuses = (
                connection.execute(
                    sa.text(
                        "SELECT status FROM ingestion_runs "
                        "WHERE season_start = :season ORDER BY run_id"
                    ),
                    {"season": season_start},
                )
                .scalars()
                .all()
            )
            games = connection.execute(
                sa.text("SELECT COUNT(*) FROM games WHERE season_start = :season"),
                {"season": season_start},
            ).scalar_one()
        assert statuses == ["failed"]
        assert games == 0
    finally:
        _cleanup(database_engine, season_start)

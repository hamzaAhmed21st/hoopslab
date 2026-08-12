"""Version-pinned NBA Data Archive downloader and schema validator."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from hoopslab.domain.shots import ArchiveShotRow, NormalizedShot, normalize_shot

SOURCE_REPOSITORY = "cdechoch/nba-data-archive"
SOURCE_REVISION = "328e29170d2b338105cbd8f61fae129dcad4b754"

REQUIRED_COLUMNS = frozenset(
    {
        "GAME_ID",
        "GAME_EVENT_ID",
        "PLAYER_ID",
        "PLAYER_NAME",
        "TEAM_ID",
        "TEAM_NAME",
        "PERIOD",
        "MINUTES_REMAINING",
        "SECONDS_REMAINING",
        "EVENT_TYPE",
        "ACTION_TYPE",
        "SHOT_TYPE",
        "SHOT_ZONE_BASIC",
        "SHOT_ZONE_AREA",
        "SHOT_ZONE_RANGE",
        "SHOT_DISTANCE",
        "LOC_X",
        "LOC_Y",
        "SHOT_ATTEMPTED_FLAG",
        "SHOT_MADE_FLAG",
        "GAME_DATE",
        "HTM",
        "VTM",
        "_season",
        "_season_type",
    }
)


class SourceError(RuntimeError):
    """Base error for source access and validation failures."""


class SourceIntegrityError(SourceError):
    """Downloaded bytes do not match the pinned manifest."""


class SourceSchemaError(SourceError):
    """The source no longer satisfies the shotdetail contract."""


@dataclass(frozen=True)
class SourceAsset:
    """Immutable manifest entry for one completed-season source file."""

    season_start: int
    season_type: str
    sha256: str

    @property
    def relative_path(self) -> str:
        """Return the repository path for this asset."""
        prefix = "" if self.season_type == "rg" else "po_"
        return f"per_season/shotdetail/{prefix}{self.season_start}.parquet"

    @property
    def url(self) -> str:
        """Return a revision-pinned public download URL."""
        return (
            "https://huggingface.co/datasets/"
            f"{SOURCE_REPOSITORY}/resolve/{SOURCE_REVISION}/{self.relative_path}"
            "?download=true"
        )


VALIDATION_ASSET = SourceAsset(
    season_start=2023,
    season_type="rg",
    sha256="93ea6168f5ff925e114c1406906adc931e8d3f2e95403f23a100bd9068417e4d",
)


@dataclass(frozen=True)
class ValidationReport:
    """Bounded evidence from a source Parquet file."""

    path: Path
    sha256: str
    total_rows: int
    sample_rows: int
    sample_games: int
    sample_players: int
    sample_teams: int
    made: int
    missed: int
    coordinate_x_range: tuple[int, int]
    coordinate_y_range: tuple[int, int]


def file_sha256(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_asset(
    asset: SourceAsset,
    destination: Path,
    *,
    client: httpx.Client | None = None,
) -> Path:
    """Download an asset atomically and enforce its manifest hash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if file_sha256(destination) == asset.sha256:
            return destination
        raise SourceIntegrityError(f"existing file has wrong SHA-256: {destination}")

    temporary_path = destination.with_suffix(f"{destination.suffix}.part")
    owns_client = client is None
    download_client = client or httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
    )
    try:
        with download_client.stream("GET", asset.url) as response:
            response.raise_for_status()
            with temporary_path.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
        actual_hash = file_sha256(temporary_path)
        if actual_hash != asset.sha256:
            raise SourceIntegrityError(
                f"downloaded SHA-256 {actual_hash} does not match {asset.sha256}"
            )
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)
        if owns_client:
            download_client.close()
    return destination


def _python_rows(table: pa.Table) -> Iterator[Mapping[str, Any]]:
    for batch in table.to_batches(max_chunksize=1_024):
        yield from batch.to_pylist()


def iter_normalized_shots(
    path: Path, *, row_limit: int | None = None
) -> Iterator[NormalizedShot]:
    """Yield normalized shots after checking the physical source schema."""
    parquet_file = pq.ParquetFile(path)
    missing_columns = REQUIRED_COLUMNS.difference(parquet_file.schema_arrow.names)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise SourceSchemaError(f"missing required columns: {missing}")

    yielded = 0
    for record_batch in parquet_file.iter_batches(
        batch_size=1_024, columns=sorted(REQUIRED_COLUMNS)
    ):
        for raw_row in record_batch.to_pylist():
            yield normalize_shot(ArchiveShotRow.model_validate(raw_row))
            yielded += 1
            if row_limit is not None and yielded >= row_limit:
                return


def validate_asset(
    asset: SourceAsset, path: Path, *, sample_size: int = 500
) -> ValidationReport:
    """Verify integrity, required fields, and a bounded sample of domain rows."""
    if sample_size < 1:
        msg = "sample_size must be positive"
        raise ValueError(msg)
    actual_hash = file_sha256(path)
    if actual_hash != asset.sha256:
        raise SourceIntegrityError(
            f"file SHA-256 {actual_hash} does not match {asset.sha256}"
        )

    parquet_file = pq.ParquetFile(path)
    shots = list(iter_normalized_shots(path, row_limit=sample_size))
    if not shots:
        raise SourceSchemaError("source contains no shot rows")

    made = sum(shot.made for shot in shots)
    x_values = [shot.coordinate_x_tenths_ft for shot in shots]
    y_values = [shot.coordinate_y_tenths_ft for shot in shots]
    return ValidationReport(
        path=path,
        sha256=actual_hash,
        total_rows=parquet_file.metadata.num_rows,
        sample_rows=len(shots),
        sample_games=len({shot.game_id for shot in shots}),
        sample_players=len({shot.player_id for shot in shots}),
        sample_teams=len({shot.team_id for shot in shots}),
        made=made,
        missed=len(shots) - made,
        coordinate_x_range=(min(x_values), max(x_values)),
        coordinate_y_range=(min(y_values), max(y_values)),
    )

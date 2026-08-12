"""Version-pinned NBA Data Archive downloader and schema validator."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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

INTEGER_COLUMNS = REQUIRED_COLUMNS.difference(
    {
        "PLAYER_NAME",
        "TEAM_NAME",
        "EVENT_TYPE",
        "ACTION_TYPE",
        "SHOT_TYPE",
        "SHOT_ZONE_BASIC",
        "SHOT_ZONE_AREA",
        "SHOT_ZONE_RANGE",
        "HTM",
        "VTM",
        "_season_type",
    }
)
STRING_COLUMNS = REQUIRED_COLUMNS.difference(INTEGER_COLUMNS)


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
    season_type: Literal["rg", "po"]
    sha256: str
    expected_rows: int | None = None
    repository: str = SOURCE_REPOSITORY
    revision: str = SOURCE_REVISION
    file_format: Literal["parquet"] = "parquet"

    def __post_init__(self) -> None:
        """Reject a moving or malformed source identity."""
        if not 1996 <= self.season_start <= 2100:
            msg = "season_start must be between 1996 and 2100"
            raise ValueError(msg)
        if self.season_type not in {"rg", "po"}:
            msg = "season_type must be 'rg' or 'po'"
            raise ValueError(msg)
        if self.file_format != "parquet":
            msg = "file_format must be 'parquet'"
            raise ValueError(msg)
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            msg = "sha256 must contain exactly 64 lowercase hexadecimal characters"
            raise ValueError(msg)
        if re.fullmatch(r"[0-9a-f]{40}", self.revision) is None:
            msg = "revision must be an immutable 40-character Git commit"
            raise ValueError(msg)
        if self.expected_rows is not None and self.expected_rows < 1:
            msg = "expected_rows must be positive when provided"
            raise ValueError(msg)

    @property
    def season_label(self) -> str:
        """Return the conventional NBA season label."""
        return f"{self.season_start}-{str(self.season_start + 1)[-2:]}"

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
            f"{self.repository}/resolve/{self.revision}/{self.relative_path}"
            "?download=true"
        )

    def cache_path(self, cache_dir: Path) -> Path:
        """Return the ignored local path for this asset."""
        return (
            cache_dir
            / "nba-data-archive"
            / "shotdetail"
            / Path(self.relative_path).name
        )


SOURCE_MANIFEST = (
    SourceAsset(
        2018,
        "rg",
        "b1e90544c0b8438972dc04d40bf505fab3118d04feb793a12b129474bb34c7ff",
        expected_rows=219_458,
    ),
    SourceAsset(
        2019,
        "rg",
        "0e0c6e199434cbbb3b6df5dc694d2b427c45b877a7f9b69725cd7f6c98d36f00",
        expected_rows=188_116,
    ),
    SourceAsset(
        2020,
        "rg",
        "1156d5ff44ad270cb4180f1c9b148009ce16d67262c6c41ca9e25059a0f4029a",
        expected_rows=190_983,
    ),
    SourceAsset(
        2021,
        "rg",
        "4dec7031499178917cfd1fe4ce04971dacb73dd9b3542f4f5a10e2cdcccf7362",
        expected_rows=216_722,
    ),
    SourceAsset(
        2022,
        "rg",
        "919bb13b68b6cdad8c2843144f10606a1a061666c92205c6ac3d1959fcff80fa",
        expected_rows=217_218,
    ),
    SourceAsset(
        2023,
        "rg",
        "93ea6168f5ff925e114c1406906adc931e8d3f2e95403f23a100bd9068417e4d",
        expected_rows=218_701,
    ),
)
VALIDATION_ASSET = SOURCE_MANIFEST[-1]


def validate_manifest(assets: tuple[SourceAsset, ...] = SOURCE_MANIFEST) -> None:
    """Validate cohort completeness and uniqueness."""
    expected_seasons = set(range(2018, 2024))
    actual_seasons = {asset.season_start for asset in assets}
    if actual_seasons != expected_seasons or len(assets) != len(expected_seasons):
        msg = "manifest must contain one asset for every season from 2018 through 2023"
        raise ValueError(msg)
    if len({asset.url for asset in assets}) != len(assets):
        msg = "manifest source URLs must be unique"
        raise ValueError(msg)
    if any(asset.season_type != "rg" for asset in assets):
        msg = "modeling cohort must contain regular-season assets only"
        raise ValueError(msg)


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


def validate_source_schema(parquet_file: pq.ParquetFile) -> None:
    """Validate required columns and their broad physical Arrow types."""
    schema = parquet_file.schema_arrow
    missing_columns = REQUIRED_COLUMNS.difference(schema.names)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise SourceSchemaError(f"missing required columns: {missing}")

    wrong_types = [
        name
        for name in INTEGER_COLUMNS
        if not pa.types.is_integer(schema.field(name).type)
    ]
    wrong_types.extend(
        name
        for name in STRING_COLUMNS
        if not (
            pa.types.is_string(schema.field(name).type)
            or pa.types.is_large_string(schema.field(name).type)
        )
    )
    if wrong_types:
        fields = ", ".join(sorted(wrong_types))
        raise SourceSchemaError(f"columns have incompatible physical types: {fields}")


def iter_normalized_shots(
    path: Path, *, row_limit: int | None = None
) -> Iterator[NormalizedShot]:
    """Yield normalized shots after checking the physical source schema."""
    parquet_file = pq.ParquetFile(path)
    validate_source_schema(parquet_file)

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
    validate_source_schema(parquet_file)
    if (
        asset.expected_rows is not None
        and parquet_file.metadata.num_rows != asset.expected_rows
    ):
        raise SourceIntegrityError(
            f"source has {parquet_file.metadata.num_rows} rows; "
            f"manifest expects {asset.expected_rows}"
        )
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

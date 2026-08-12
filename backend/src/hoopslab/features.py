"""Leakage-safe feature export and chronological game split manifest."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import Engine, text

SplitName = Literal["train", "validation", "test"]

SPLIT_BY_SEASON: dict[int, SplitName] = {
    2018: "train",
    2019: "train",
    2020: "train",
    2021: "train",
    2022: "validation",
    2023: "test",
}

MODEL_INPUT_FIELDS = (
    "coordinate_x_ft",
    "coordinate_y_ft",
    "shot_distance_ft",
    "shot_angle_degrees",
    "period",
    "seconds_remaining",
    "shooter_is_home",
    "action_type",
    "shot_type",
    "shot_zone_basic",
    "shot_zone_area",
    "shot_zone_range",
    "season_type",
)
IDENTIFIER_FIELDS = (
    "game_id",
    "event_id",
    "season_start",
    "game_date",
    "player_id",
    "team_id",
    "opponent_team_id",
)
TARGET_FIELD = "made"
PROHIBITED_MODEL_INPUTS = frozenset(
    {
        *IDENTIFIER_FIELDS,
        TARGET_FIELD,
        "player_name",
        "team_name",
        "home_team_code",
        "away_team_code",
        "points",
        "score",
        "score_margin",
        "event_type",
    }
)

FEATURE_SCHEMA = pa.schema(
    [
        pa.field("game_id", pa.int64(), nullable=False),
        pa.field("event_id", pa.int32(), nullable=False),
        pa.field("season_start", pa.int16(), nullable=False),
        pa.field("game_date", pa.date32(), nullable=False),
        pa.field("player_id", pa.int64(), nullable=False),
        pa.field("team_id", pa.int64(), nullable=False),
        pa.field("opponent_team_id", pa.int64(), nullable=False),
        pa.field("coordinate_x_ft", pa.float64(), nullable=False),
        pa.field("coordinate_y_ft", pa.float64(), nullable=False),
        pa.field("shot_distance_ft", pa.int16(), nullable=False),
        pa.field("shot_angle_degrees", pa.float64(), nullable=False),
        pa.field("period", pa.int16(), nullable=False),
        pa.field("seconds_remaining", pa.int16(), nullable=False),
        pa.field("shooter_is_home", pa.bool_(), nullable=False),
        pa.field("action_type", pa.string(), nullable=False),
        pa.field("shot_type", pa.string(), nullable=False),
        pa.field("shot_zone_basic", pa.string(), nullable=False),
        pa.field("shot_zone_area", pa.string(), nullable=False),
        pa.field("shot_zone_range", pa.string(), nullable=False),
        pa.field("season_type", pa.string(), nullable=False),
        pa.field("made", pa.bool_(), nullable=False),
    ],
    metadata={
        b"contract_version": b"1",
        b"model_input_fields": json.dumps(MODEL_INPUT_FIELDS).encode(),
        b"identifier_fields": json.dumps(IDENTIFIER_FIELDS).encode(),
        b"target_field": TARGET_FIELD.encode(),
    },
)


class FeatureContractError(RuntimeError):
    """Feature rows or splits violate the frozen modeling boundary."""


@dataclass(frozen=True)
class FeatureExportResult:
    """Summary of a deterministic local Parquet export."""

    path: Path
    row_count: int


@dataclass(frozen=True)
class SplitManifestResult:
    """Summary of a deterministic whole-game split artifact."""

    path: Path
    row_counts: dict[SplitName, int]
    game_counts: dict[SplitName, int]


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Evidence that every feature row has one valid whole-game assignment."""

    feature_rows: int
    games: int
    row_counts: dict[SplitName, int]


def validate_feature_contract() -> None:
    """Ensure identifiers, target, raw team codes, and outcomes cannot be inputs."""
    inputs = set(MODEL_INPUT_FIELDS)
    if inputs.intersection(PROHIBITED_MODEL_INPUTS):
        overlap = sorted(inputs.intersection(PROHIBITED_MODEL_INPUTS))
        raise FeatureContractError(f"prohibited model inputs: {overlap}")
    if set(FEATURE_SCHEMA.names) != inputs.union(IDENTIFIER_FIELDS, {TARGET_FIELD}):
        raise FeatureContractError(
            "Arrow schema and declared feature contract disagree"
        )


def assign_split(season_start: int) -> SplitName:
    """Assign a completed season without inspecting outcomes."""
    try:
        return SPLIT_BY_SEASON[season_start]
    except KeyError as error:
        raise FeatureContractError(
            f"season {season_start} is outside the frozen split manifest"
        ) from error


def feature_record_from_mapping(row: Mapping[str, Any]) -> dict[str, object]:
    """Create one typed feature row from normalized database values."""
    coordinate_x_ft = float(row["coordinate_x_tenths_ft"]) / 10.0
    coordinate_y_ft = float(row["coordinate_y_tenths_ft"]) / 10.0
    return {
        "game_id": int(row["game_id"]),
        "event_id": int(row["event_id"]),
        "season_start": int(row["season_start"]),
        "game_date": cast(date, row["game_date"]),
        "player_id": int(row["player_id"]),
        "team_id": int(row["team_id"]),
        "opponent_team_id": int(row["opponent_team_id"]),
        "coordinate_x_ft": coordinate_x_ft,
        "coordinate_y_ft": coordinate_y_ft,
        "shot_distance_ft": int(row["shot_distance_ft"]),
        "shot_angle_degrees": math.degrees(
            math.atan2(coordinate_x_ft, coordinate_y_ft)
        ),
        "period": int(row["period"]),
        "seconds_remaining": int(row["seconds_remaining"]),
        "shooter_is_home": bool(row["shooter_is_home"]),
        "action_type": str(row["action_type"]),
        "shot_type": str(row["shot_type"]),
        "shot_zone_basic": str(row["shot_zone_basic"]),
        "shot_zone_area": str(row["shot_zone_area"]),
        "shot_zone_range": str(row["shot_zone_range"]),
        "season_type": str(row["season_type"]),
        "made": bool(row["made"]),
    }


def export_feature_dataset(
    engine: Engine, path: Path, *, batch_size: int = 10_000
) -> FeatureExportResult:
    """Stream normalized shots to deterministic model-ready Parquet."""
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)
    validate_feature_contract()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(f"{path.suffix}.part")
    query = text(
        """
        SELECT
            s.game_id,
            s.event_id,
            g.season_start,
            g.game_date,
            s.player_id,
            s.team_id,
            s.opponent_team_id,
            s.coordinate_x_tenths_ft,
            s.coordinate_y_tenths_ft,
            s.shot_distance_ft,
            s.period,
            s.seconds_remaining,
            s.shooter_is_home,
            s.action_type,
            s.shot_type,
            s.shot_zone_basic,
            s.shot_zone_area,
            s.shot_zone_range,
            g.season_type,
            s.made
        FROM shots AS s
        JOIN games AS g ON g.source_game_id = s.game_id
        ORDER BY g.game_date, s.game_id, s.event_id
        """
    )
    row_count = 0
    writer: pq.ParquetWriter | None = None
    try:
        with engine.connect() as connection:
            result = connection.execution_options(stream_results=True).execute(query)
            while rows := result.mappings().fetchmany(batch_size):
                records = [
                    feature_record_from_mapping(cast(Mapping[str, Any], row))
                    for row in rows
                ]
                table = pa.Table.from_pylist(records, schema=FEATURE_SCHEMA)
                if writer is None:
                    writer = pq.ParquetWriter(
                        temporary_path, FEATURE_SCHEMA, compression="zstd"
                    )
                writer.write_table(table)
                row_count += len(records)
        if writer is None:
            raise FeatureContractError("cannot export an empty feature dataset")
        writer.close()
        writer = None
        temporary_path.replace(path)
    finally:
        if writer is not None:
            writer.close()
        temporary_path.unlink(missing_ok=True)
    return FeatureExportResult(path=path, row_count=row_count)


def build_split_manifest(engine: Engine, path: Path) -> SplitManifestResult:
    """Write deterministic identifiers assigning every whole game to one split."""
    validate_feature_contract()
    query = text(
        """
        SELECT
            g.source_game_id AS game_id,
            g.season_start,
            g.game_date,
            COUNT(s.event_id) AS row_count,
            COUNT(s.event_id) FILTER (WHERE s.made) AS made_count
        FROM games AS g
        JOIN shots AS s ON s.game_id = g.source_game_id
        GROUP BY g.source_game_id, g.season_start, g.game_date
        ORDER BY g.game_date, g.source_game_id
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(query).mappings().all()
    if not rows:
        raise FeatureContractError("cannot split an empty normalized dataset")

    game_ids: set[int] = set()
    games: list[dict[str, object]] = []
    row_counts: dict[SplitName, int] = {
        "train": 0,
        "validation": 0,
        "test": 0,
    }
    game_counts: dict[SplitName, int] = {
        "train": 0,
        "validation": 0,
        "test": 0,
    }
    dates: dict[SplitName, list[date]] = {
        "train": [],
        "validation": [],
        "test": [],
    }
    made_counts: dict[SplitName, int] = {
        "train": 0,
        "validation": 0,
        "test": 0,
    }
    for row in rows:
        game_id = int(row["game_id"])
        if game_id in game_ids:
            raise FeatureContractError(f"game {game_id} appears more than once")
        game_ids.add(game_id)
        season_start = int(row["season_start"])
        split = assign_split(season_start)
        game_date = cast(date, row["game_date"])
        row_count = int(row["row_count"])
        made_count = int(row["made_count"])
        row_counts[split] += row_count
        game_counts[split] += 1
        dates[split].append(game_date)
        made_counts[split] += made_count
        games.append(
            {
                "game_id": game_id,
                "season_start": season_start,
                "game_date": game_date.isoformat(),
                "split": split,
                "feature_row_count": row_count,
            }
        )

    summaries = {
        split: {
            "seasons": sorted(
                season
                for season, assigned_split in SPLIT_BY_SEASON.items()
                if assigned_split == split
            ),
            "rows": row_counts[split],
            "games": game_counts[split],
            "first_game_date": min(dates[split]).isoformat(),
            "last_game_date": max(dates[split]).isoformat(),
            "made": made_counts[split],
            "target_prevalence": made_counts[split] / row_counts[split],
        }
        for split in cast(tuple[SplitName, ...], ("train", "validation", "test"))
    }
    manifest = {
        "manifest_version": 1,
        "ordering": ["game_date", "game_id"],
        "splits": summaries,
        "games": games,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return SplitManifestResult(
        path=path, row_counts=row_counts, game_counts=game_counts
    )


def validate_feature_split_artifacts(
    feature_path: Path, split_path: Path
) -> ArtifactValidationResult:
    """Verify all exported rows map to the manifest without game overlap."""
    manifest = json.loads(split_path.read_text())
    manifest_games = manifest.get("games")
    if not isinstance(manifest_games, list):
        raise FeatureContractError("split manifest has no game assignment list")

    assignments: dict[int, tuple[int, SplitName]] = {}
    for item in manifest_games:
        if not isinstance(item, dict):
            raise FeatureContractError("split manifest game entry is not an object")
        game_id = int(item["game_id"])
        season_start = int(item["season_start"])
        split = cast(SplitName, str(item["split"]))
        if split != assign_split(season_start):
            raise FeatureContractError(f"game {game_id} has the wrong season split")
        if game_id in assignments:
            raise FeatureContractError(f"game {game_id} crosses split assignments")
        assignments[game_id] = (season_start, split)

    seen_games: set[int] = set()
    row_counts: dict[SplitName, int] = {
        "train": 0,
        "validation": 0,
        "test": 0,
    }
    feature_rows = 0
    for batch in pq.ParquetFile(feature_path).iter_batches(
        batch_size=50_000, columns=["game_id", "season_start"]
    ):
        for row in batch.to_pylist():
            game_id = int(row["game_id"])
            season_start = int(row["season_start"])
            try:
                assigned_season, split = assignments[game_id]
            except KeyError as error:
                raise FeatureContractError(
                    f"feature row references unassigned game {game_id}"
                ) from error
            if season_start != assigned_season:
                raise FeatureContractError(
                    f"game {game_id} feature and manifest seasons disagree"
                )
            row_counts[split] += 1
            seen_games.add(game_id)
            feature_rows += 1
    if seen_games != assignments.keys():
        missing = sorted(assignments.keys() - seen_games)
        raise FeatureContractError(
            f"manifest games have no feature rows: {missing[:5]}"
        )

    expected_counts = {
        cast(SplitName, split): int(summary["rows"])
        for split, summary in manifest["splits"].items()
    }
    if row_counts != expected_counts:
        raise FeatureContractError(
            f"feature split counts {row_counts} do not match {expected_counts}"
        )
    return ArtifactValidationResult(
        feature_rows=feature_rows,
        games=len(seen_games),
        row_counts=row_counts,
    )

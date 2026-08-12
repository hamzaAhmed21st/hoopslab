"""Leakage-safe feature and split contract tests."""

import json
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hoopslab.features import (
    FEATURE_SCHEMA,
    IDENTIFIER_FIELDS,
    MODEL_INPUT_FIELDS,
    PROHIBITED_MODEL_INPUTS,
    FeatureContractError,
    assign_split,
    feature_record_from_mapping,
    validate_feature_contract,
    validate_feature_split_artifacts,
)


def test_feature_contract_separates_inputs_identifiers_and_target() -> None:
    validate_feature_contract()

    assert not set(MODEL_INPUT_FIELDS).intersection(IDENTIFIER_FIELDS)
    assert not set(MODEL_INPUT_FIELDS).intersection(PROHIBITED_MODEL_INPUTS)
    assert "shooter_is_home" in MODEL_INPUT_FIELDS
    assert "home_team_code" not in MODEL_INPUT_FIELDS


def test_feature_geometry_is_deterministic_and_keeps_target_separate() -> None:
    record = feature_record_from_mapping(
        {
            "game_id": 1,
            "event_id": 2,
            "season_start": 2023,
            "game_date": date(2023, 10, 24),
            "player_id": 3,
            "team_id": 4,
            "opponent_team_id": 5,
            "coordinate_x_tenths_ft": 100,
            "coordinate_y_tenths_ft": 100,
            "shot_distance_ft": 14,
            "period": 1,
            "seconds_remaining": 600,
            "shooter_is_home": True,
            "action_type": "Jump Shot",
            "shot_type": "2PT Field Goal",
            "shot_zone_basic": "Mid-Range",
            "shot_zone_area": "Center(C)",
            "shot_zone_range": "8-16 ft.",
            "season_type": "rg",
            "made": False,
        }
    )

    assert record["coordinate_x_ft"] == 10.0
    assert record["shot_angle_degrees"] == pytest.approx(45.0)
    assert record["made"] is False


def test_split_assignment_is_frozen_by_season() -> None:
    assert [assign_split(season) for season in range(2018, 2024)] == [
        "train",
        "train",
        "train",
        "train",
        "validation",
        "test",
    ]
    with pytest.raises(FeatureContractError, match="outside"):
        assign_split(2024)


def test_artifact_validator_maps_every_row_to_one_whole_game(tmp_path: Path) -> None:
    feature_path = tmp_path / "features.parquet"
    split_path = tmp_path / "splits.json"
    base = {
        "game_id": 1,
        "event_id": 1,
        "season_start": 2018,
        "game_date": date(2018, 10, 16),
        "player_id": 10,
        "team_id": 20,
        "opponent_team_id": 30,
        "coordinate_x_ft": 1.0,
        "coordinate_y_ft": 2.0,
        "shot_distance_ft": 2,
        "shot_angle_degrees": 26.5,
        "period": 1,
        "seconds_remaining": 700,
        "shooter_is_home": True,
        "action_type": "Jump Shot",
        "shot_type": "2PT Field Goal",
        "shot_zone_basic": "Mid-Range",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "8-16 ft.",
        "season_type": "rg",
        "made": True,
    }
    rows = [base, {**base, "game_id": 2, "event_id": 2}]
    pq.write_table(pa.Table.from_pylist(rows, schema=FEATURE_SCHEMA), feature_path)
    split_path.write_text(
        json.dumps(
            {
                "splits": {
                    "train": {"rows": 2},
                    "validation": {"rows": 0},
                    "test": {"rows": 0},
                },
                "games": [
                    {"game_id": 1, "season_start": 2018, "split": "train"},
                    {"game_id": 2, "season_start": 2018, "split": "train"},
                ],
            }
        )
    )

    result = validate_feature_split_artifacts(feature_path, split_path)

    assert result.feature_rows == 2
    assert result.games == 2
    assert result.row_counts == {"train": 2, "validation": 0, "test": 0}


def test_artifact_validator_rejects_game_crossing_assignments(tmp_path: Path) -> None:
    feature_path = tmp_path / "features.parquet"
    split_path = tmp_path / "splits.json"
    pq.write_table(pa.Table.from_pylist([], schema=FEATURE_SCHEMA), feature_path)
    split_path.write_text(
        json.dumps(
            {
                "splits": {
                    "train": {"rows": 0},
                    "validation": {"rows": 0},
                    "test": {"rows": 0},
                },
                "games": [
                    {"game_id": 1, "season_start": 2018, "split": "train"},
                    {"game_id": 1, "season_start": 2018, "split": "train"},
                ],
            }
        )
    )

    with pytest.raises(FeatureContractError, match="crosses"):
        validate_feature_split_artifacts(feature_path, split_path)

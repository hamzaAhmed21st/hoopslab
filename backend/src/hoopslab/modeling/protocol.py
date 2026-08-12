"""Frozen development protocol and feature-artifact access guards."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import BinaryIO, Final

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from hoopslab.features import (
    FEATURE_SCHEMA,
    IDENTIFIER_FIELDS,
    MODEL_INPUT_FIELDS,
    TARGET_FIELD,
)

MODELING_CONTRACT_VERSION: Final = 1
SEED: Final = 20260812
BOOTSTRAP_SEED: Final = 20260813
TRAINING_SEASONS: Final = frozenset({2018, 2019, 2020, 2021})
DEVELOPMENT_SEASONS: Final = frozenset({*TRAINING_SEASONS, 2022})
TEST_SEASON: Final = 2023
NUMERIC_FIELDS: Final = MODEL_INPUT_FIELDS[:6]
BOOLEAN_FIELD: Final = "shooter_is_home"
CATEGORICAL_FIELDS: Final = MODEL_INPUT_FIELDS[7:]
CALIBRATION_END: Final = date(2023, 1, 10)
SELECTION_START: Final = date(2023, 1, 11)
SELECTION_END: Final = date(2023, 4, 9)


class ModelingProtocolError(RuntimeError):
    """Raised when data access would violate the frozen modeling protocol."""


@dataclass(frozen=True)
class RollingFold:
    """One chronological, whole-season internal model-selection fold."""

    identifier: str
    train_seasons: tuple[int, ...]
    validation_season: int


ROLLING_FOLDS: Final = (
    RollingFold("fold-1", (2018,), 2019),
    RollingFold("fold-2", (2018, 2019), 2020),
    RollingFold("fold-3", (2018, 2019, 2020), 2021),
)


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for a local artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_identity(feature_path: Path, split_path: Path) -> dict[str, str]:
    """Record artifact identities without reading split target summaries."""
    return {
        "feature_sha256": sha256_file(feature_path),
        "split_manifest_sha256": sha256_file(split_path),
        "feature_contract_version": str(MODELING_CONTRACT_VERSION),
    }


def validate_feature_file(feature_path: Path) -> None:
    """Validate the exact frozen Arrow schema and metadata before loading rows."""
    schema = pq.ParquetFile(feature_path).schema_arrow
    if schema != FEATURE_SCHEMA:
        raise ModelingProtocolError("feature Arrow schema does not match contract")
    metadata = schema.metadata or {}
    if metadata.get(b"contract_version") != b"1":
        raise ModelingProtocolError("unsupported feature contract version")
    if (
        tuple(json.loads(metadata.get(b"model_input_fields", b"[]")))
        != MODEL_INPUT_FIELDS
    ):
        raise ModelingProtocolError("feature model-input metadata disagrees")
    if (
        tuple(json.loads(metadata.get(b"identifier_fields", b"[]")))
        != IDENTIFIER_FIELDS
    ):
        raise ModelingProtocolError("feature identifier metadata disagrees")
    if metadata.get(b"target_field") != TARGET_FIELD.encode():
        raise ModelingProtocolError("feature target metadata disagrees")


def _validate_development_seasons(seasons: Iterable[int]) -> tuple[int, ...]:
    requested = tuple(sorted(set(seasons)))
    if not requested:
        raise ModelingProtocolError("at least one development season is required")
    unauthorized = set(requested).difference(DEVELOPMENT_SEASONS)
    if unauthorized:
        raise ModelingProtocolError(
            "development access is limited to 2018-19 through 2022-23; "
            f"requested {sorted(unauthorized)}"
        )
    return requested


def _normalise_frame(table: pa.Table) -> pd.DataFrame:
    frame = table.to_pandas()
    if not isinstance(frame, pd.DataFrame):
        raise ModelingProtocolError("feature loader did not produce a DataFrame")
    frame["game_date"] = pd.to_datetime(frame["game_date"]).dt.date
    for field in CATEGORICAL_FIELDS:
        frame[field] = frame[field].astype(object)
    frame[BOOLEAN_FIELD] = frame[BOOLEAN_FIELD].astype(bool)
    return frame


def load_development_features(
    feature_path: Path, seasons: Iterable[int]
) -> pd.DataFrame:
    """Load only authorized development rows with a Parquet predicate pushdown."""
    requested = _validate_development_seasons(seasons)
    validate_feature_file(feature_path)
    dataset = ds.dataset(feature_path, format="parquet")
    table = dataset.to_table(filter=ds.field("season_start").isin(requested))
    frame = _normalise_frame(table)
    observed = set(frame["season_start"].astype(int).unique())
    if observed.difference(requested):
        raise ModelingProtocolError(
            "development loader returned an unauthorized season"
        )
    if TEST_SEASON in observed:
        raise ModelingProtocolError("development loader accessed the final test season")
    if frame.empty:
        raise ModelingProtocolError(
            "requested development seasons have no feature rows"
        )
    return frame


def load_final_test_features(feature_path: Path) -> pd.DataFrame:
    """Load the held-out season only after a validated local selection lock."""
    validate_feature_file(feature_path)
    dataset = ds.dataset(feature_path, format="parquet")
    table = dataset.to_table(filter=ds.field("season_start") == TEST_SEASON)
    frame = _normalise_frame(table)
    if frame.empty or set(frame["season_start"].astype(int).unique()) != {TEST_SEASON}:
        raise ModelingProtocolError("final test loader did not return exactly 2023-24")
    return frame


def validate_development_split_assignments(
    split_path: Path, development: pd.DataFrame
) -> None:
    """Stream only authorized game assignments, never deserializing split summaries."""
    expected = {
        int(game_id): int(season)
        for game_id, season in development.loc[:, ["game_id", "season_start"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }
    observed: dict[int, int] = {}
    for raw_item in _stream_manifest_game_objects(split_path):
        season_match = re.search(r'"season_start"\s*:\s*(\d+)', raw_item)
        if season_match is None:
            raise ModelingProtocolError("split manifest assignment omits season_start")
        season = int(season_match.group(1))
        if season not in DEVELOPMENT_SEASONS:
            continue
        try:
            item = json.loads(raw_item)
            game_id = int(item["game_id"])
            split = str(item["split"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ModelingProtocolError(
                "development game assignment is malformed"
            ) from error
        if game_id not in expected:
            continue
        expected_split = "validation" if season == 2022 else "train"
        if (
            season != expected[game_id]
            or split != expected_split
            or game_id in observed
        ):
            raise ModelingProtocolError(
                "development game assignment disagrees with data"
            )
        observed[game_id] = season
        # Production assignments are chronological. Once all expected 2018-2022
        # games are observed, close the generator before it reads a separator or
        # the first held-out 2023 object.
        if observed == expected:
            return
    if observed != expected:
        raise ModelingProtocolError(
            "split manifest does not exactly cover development games"
        )


def _stream_manifest_game_objects(split_path: Path) -> Iterable[str]:
    """Yield ``games`` objects without reading bytes after that top-level array.

    The split writer uses ``sort_keys=True``, making ``games`` the required first
    key. Unbuffered binary single-byte reads ensure no text decoder or bulk buffer
    crosses the closing array bracket into later test-summary bytes.
    """
    whitespace = b" \t\r\n"

    def next_byte(handle: BinaryIO) -> bytes:
        value = handle.read(1)
        if not value:
            raise ModelingProtocolError("split manifest games array is incomplete")
        return value

    def next_non_whitespace(handle: BinaryIO) -> bytes:
        value = next_byte(handle)
        while value in whitespace:
            value = next_byte(handle)
        return value

    with split_path.open("rb", buffering=0) as handle:
        if next_non_whitespace(handle) != b"{":
            raise ModelingProtocolError("split manifest must begin with an object")
        expected_key = b'"games"'
        actual_key = next_non_whitespace(handle) + b"".join(
            next_byte(handle) for _ in expected_key[1:]
        )
        if actual_key != expected_key:
            raise ModelingProtocolError("games must be the first split manifest key")
        if next_non_whitespace(handle) != b":":
            raise ModelingProtocolError("split manifest games key has no value")
        if next_non_whitespace(handle) != b"[":
            raise ModelingProtocolError("split manifest games value is not an array")
        expect_value = True
        while True:
            value = next_non_whitespace(handle)
            if value == b"]":
                return
            if not expect_value:
                if value != b",":
                    raise ModelingProtocolError(
                        "split manifest games entries lack a comma"
                    )
                value = next_non_whitespace(handle)
            if value != b"{":
                raise ModelingProtocolError(
                    "split manifest games entry is not an object"
                )
            raw_item = bytearray(value)
            depth = 1
            in_string = False
            escaped = False
            while depth:
                character = next_byte(handle)
                raw_item.extend(character)
                if in_string:
                    if escaped:
                        escaped = False
                    elif character == b"\\":
                        escaped = True
                    elif character == b'"':
                        in_string = False
                elif character == b'"':
                    in_string = True
                elif character == b"{":
                    depth += 1
                elif character == b"}":
                    depth -= 1
            try:
                yield bytes(raw_item).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ModelingProtocolError(
                    "split manifest game object is not UTF-8"
                ) from error
            expect_value = False


def split_2022_calibration_selection(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide 2022-23 chronologically without splitting any game between uses."""
    if set(frame["season_start"].astype(int).unique()) != {2022}:
        raise ModelingProtocolError(
            "2022 segmentation accepts only the validation season"
        )
    dates = frame.groupby("game_id", sort=False)["game_date"].nunique()
    if int(dates.max()) != 1:
        raise ModelingProtocolError("a game has multiple dates")
    calibration = frame.loc[frame["game_date"] <= CALIBRATION_END].copy()
    selection = frame.loc[
        (frame["game_date"] >= SELECTION_START) & (frame["game_date"] <= SELECTION_END)
    ].copy()
    if calibration.empty or selection.empty:
        raise ModelingProtocolError("2022 calibration or selection segment is empty")
    calibration_games = set(calibration["game_id"].astype(int))
    selection_games = set(selection["game_id"].astype(int))
    if calibration_games.intersection(selection_games):
        raise ModelingProtocolError("a game crosses calibration and selection segments")
    if len(calibration) + len(selection) != len(frame):
        raise ModelingProtocolError("2022 dates fall outside the frozen segmentation")
    return calibration, selection


def frame_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    """Return exactly the frozen model inputs, excluding target and identifiers."""
    unexpected = set(MODEL_INPUT_FIELDS).difference(frame.columns)
    if unexpected:
        raise ModelingProtocolError(
            f"feature rows omit model inputs: {sorted(unexpected)}"
        )
    return frame.loc[:, list(MODEL_INPUT_FIELDS)].copy()


def frame_target(frame: pd.DataFrame) -> pd.Series:
    """Return the binary target separately from the model-input matrix."""
    if TARGET_FIELD not in frame:
        raise ModelingProtocolError("feature rows omit target")
    return frame[TARGET_FIELD].astype(int)

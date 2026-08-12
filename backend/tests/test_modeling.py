"""High-information leakage, protocol, metric, and local artifact tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import hoopslab.modeling.workflow as workflow
from hoopslab.features import FEATURE_SCHEMA
from hoopslab.modeling.artifacts import (
    BUNDLE_FILENAME,
    FINAL_TEST_RESERVATION_FILENAME,
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    TEST_REPORT_FILENAME,
    validate_bundle,
)
from hoopslab.modeling.candidates import (
    HGB_CANDIDATES,
    LOGISTIC_CANDIDATES,
    build_candidate,
)
from hoopslab.modeling.metrics import (
    game_block_bootstrap,
    probability_metrics,
    reliability_summary,
)
from hoopslab.modeling.protocol import (
    CALIBRATION_END,
    CATEGORICAL_FIELDS,
    DEVELOPMENT_SEASONS,
    MODELING_CONTRACT_VERSION,
    ROLLING_FOLDS,
    TEST_SEASON,
    ModelingProtocolError,
    feature_identity,
    frame_inputs,
    load_development_features,
    split_2022_calibration_selection,
    validate_development_split_assignments,
)
from hoopslab.modeling.workflow import (
    format_development_result,
    lock_development,
    run_development,
    run_final_test,
    select_global_variant,
    select_tuned_by_family,
    tune_candidates,
    verify_model_artifacts,
)


def _row(
    season: int, game_id: int, event_id: int, game_date: date
) -> dict[str, object]:
    made = event_id % 2 == 0
    return {
        "game_id": game_id,
        "event_id": event_id,
        "season_start": season,
        "game_date": game_date,
        "player_id": 100 + event_id % 3,
        "team_id": 200 + event_id % 2,
        "opponent_team_id": 300 + event_id % 2,
        "coordinate_x_ft": float((event_id % 11) - 5),
        "coordinate_y_ft": float(2 + event_id % 25),
        "shot_distance_ft": 2 + event_id % 25,
        "shot_angle_degrees": float((event_id % 17) - 8),
        "period": 1 + event_id % 4,
        "seconds_remaining": 100 + event_id % 600,
        "shooter_is_home": bool(event_id % 2),
        "action_type": "Jump Shot" if event_id % 3 else "Layup",
        "shot_type": "2PT Field Goal" if event_id % 2 else "3PT Field Goal",
        "shot_zone_basic": "Mid-Range",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "8-16 ft.",
        "season_type": "rg",
        "made": made,
    }


def _write_features(path: Path, *, full_e2e: bool = False) -> Path:
    rows: list[dict[str, object]] = []
    dates = {
        2018: date(2018, 10, 16),
        2019: date(2019, 10, 22),
        2020: date(2020, 12, 22),
        2021: date(2021, 10, 19),
        2022: date(2023, 1, 10),
        2023: date(2023, 10, 24),
    }
    for season, game_date in dates.items():
        games = 2 if season != 2022 or not full_e2e else 4
        rows_per_game = 12
        if season == 2022 and full_e2e:
            rows_per_game = 1_100
        for game_offset in range(games):
            assigned_date = game_date
            if season == 2022 and game_offset >= games // 2:
                assigned_date = date(2023, 1, 11)
            game_id = season * 100 + game_offset
            rows.extend(
                _row(season, game_id, event_id, assigned_date)
                for event_id in range(1, rows_per_game + 1)
            )
    pq.write_table(pa.Table.from_pylist(rows, schema=FEATURE_SCHEMA), path)
    return path


def _write_split(path: Path) -> Path:
    games = [
        {
            "game_id": season * 100 + game_offset,
            "season_start": season,
            "game_date": "2023-01-10"
            if season == 2022 and game_offset == 0
            else "2023-01-11",
            "split": "validation"
            if season == 2022
            else "test"
            if season == 2023
            else "train",
        }
        for season in range(2018, 2024)
        for game_offset in range(4 if season == 2022 else 2)
    ]
    path.write_text(
        json.dumps({"splits": {"test": {"made": 999}}, "games": games}, sort_keys=True)
    )
    return path


def test_development_loader_rejects_test_scope_and_keeps_identifiers_out(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet")

    frame = load_development_features(feature_path, DEVELOPMENT_SEASONS)

    assert TEST_SEASON not in set(frame["season_start"])
    assert list(frame_inputs(frame).columns) == [
        "coordinate_x_ft",
        "coordinate_y_ft",
        "shot_distance_ft",
        "shot_angle_degrees",
        "period",
        "seconds_remaining",
        "shooter_is_home",
        *CATEGORICAL_FIELDS,
    ]
    with pytest.raises(ModelingProtocolError, match="limited"):
        load_development_features(feature_path, [TEST_SEASON])


def test_rolling_folds_and_validation_segment_keep_whole_games_separate(
    tmp_path: Path,
) -> None:
    frame = load_development_features(
        _write_features(tmp_path / "features.parquet"), DEVELOPMENT_SEASONS
    )
    validation = frame.loc[frame["season_start"] == 2022]
    calibration, selection = split_2022_calibration_selection(validation)

    assert calibration["game_date"].max() == CALIBRATION_END
    assert selection["game_date"].min() > CALIBRATION_END
    assert not set(calibration["game_id"]).intersection(selection["game_id"])
    assert ROLLING_FOLDS[0].train_seasons == (2018,)
    assert ROLLING_FOLDS[-1].validation_season == 2021


def test_split_validation_reads_only_game_assignments_and_requires_exact_coverage(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet")
    split_path = _write_split(tmp_path / "splits.json")
    development = load_development_features(feature_path, DEVELOPMENT_SEASONS)

    validate_development_split_assignments(split_path, development)

    split = json.loads(split_path.read_text())
    split["games"] = split["games"][1:]
    split_path.write_text(json.dumps(split))
    with pytest.raises(ModelingProtocolError, match="exactly cover"):
        validate_development_split_assignments(split_path, development)


def test_split_validation_does_not_deserialize_later_test_summary_payload(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet")
    development = load_development_features(feature_path, DEVELOPMENT_SEASONS)
    normal_split = _write_split(tmp_path / "normal-splits.json")
    games = json.loads(normal_split.read_text())["games"]
    split_path = tmp_path / "sentinel-splits.json"
    split_path.write_text(
        '{"games":' + json.dumps(games) + ',"splits":{"test":UNDECODABLE}}'
    )

    validate_development_split_assignments(split_path, development)


def test_split_validation_does_not_decode_bytes_after_games_array(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet")
    development = load_development_features(feature_path, DEVELOPMENT_SEASONS)
    normal_split = _write_split(tmp_path / "normal-splits.json")
    games = json.loads(normal_split.read_text())["games"]
    split_path = tmp_path / "invalid-utf8-after-games.json"
    split_path.write_bytes(b'{"games":' + json.dumps(games).encode() + b"\xff")

    validate_development_split_assignments(split_path, development)


def test_split_validation_stops_before_first_held_out_game_bytes(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet")
    development = load_development_features(feature_path, DEVELOPMENT_SEASONS)
    normal_split = _write_split(tmp_path / "normal-splits.json")
    games = json.loads(normal_split.read_text())["games"]
    development_games = [game for game in games if game["season_start"] <= 2022]
    split_path = tmp_path / "invalid-held-out-game.json"
    split_path.write_bytes(
        b'{"games":' + json.dumps(development_games).encode()[:-1] + b",\xff"
    )

    validate_development_split_assignments(split_path, development)


def test_logistic_pipeline_handles_unknown_categories_from_validation(
    tmp_path: Path,
) -> None:
    frame = load_development_features(
        _write_features(tmp_path / "features.parquet"), DEVELOPMENT_SEASONS
    )
    train = frame.loc[frame["season_start"] == 2018]
    validation = frame.loc[frame["season_start"] == 2019].copy()
    validation["action_type"] = "Previously unseen action"
    model = build_candidate(LOGISTIC_CANDIDATES[0]).fit(
        frame_inputs(train), train["made"].astype(int)
    )

    probabilities = model.predict_proba(frame_inputs(validation))[:, 1]

    assert len(probabilities) == len(validation)
    assert np.isfinite(probabilities).all()


def test_hgb_pipeline_marks_unknown_categories_without_continuous_codes(
    tmp_path: Path,
) -> None:
    frame = load_development_features(
        _write_features(tmp_path / "features.parquet"), DEVELOPMENT_SEASONS
    )
    train = frame.loc[frame["season_start"] == 2018]
    validation = frame.loc[frame["season_start"] == 2019].copy()
    validation["shot_zone_range"] = "unknown range"
    model = build_candidate(HGB_CANDIDATES[0]).fit(
        frame_inputs(train), train["made"].astype(int)
    )

    probabilities = model.predict_proba(frame_inputs(validation))[:, 1]

    assert np.isfinite(probabilities).all()
    assert model.named_steps["classifier"].categorical_features == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
    ]


def test_metrics_and_game_bootstrap_are_deterministic() -> None:
    frame = pd.DataFrame(
        {
            "game_id": [1, 1, 2, 2, 3, 3],
            "made": [0, 1, 0, 1, 1, 0],
        }
    )
    selected = [0.1, 0.9, 0.3, 0.7, 0.8, 0.2]
    logistic = [0.2, 0.8, 0.4, 0.6, 0.7, 0.3]

    metrics = probability_metrics(frame["made"], selected)
    bins, ece = reliability_summary(frame["made"], selected)
    first = game_block_bootstrap(frame, selected, logistic, replicates=12)
    second = game_block_bootstrap(frame, selected, logistic, replicates=12)

    assert metrics.log_loss > 0
    assert len(bins) == 10
    assert ece >= 0
    assert first == second
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        probability_metrics([0, 1], [0.1, 1.1])


def test_clock_slice_includes_exact_720_seconds() -> None:
    from hoopslab.modeling.metrics import predeclared_slice_metrics

    frame = pd.DataFrame(
        {
            "game_id": [1, 2],
            "made": [0, 1],
            "period": [1, 1],
            "seconds_remaining": [720, 720],
            "shooter_is_home": [True, False],
            "shot_type": ["2PT", "2PT"],
            "shot_zone_range": ["range", "range"],
        }
    )
    slices = predeclared_slice_metrics(frame, [0.2, 0.8], minimum_rows=1)
    assert "[600,720]" in slices["remaining_clock"]


def test_family_selection_uses_unrounded_probability_ordering(tmp_path: Path) -> None:
    frame = load_development_features(
        _write_features(tmp_path / "features.parquet"), range(2018, 2022)
    )
    evidence = tune_candidates(frame)
    selected = select_tuned_by_family(evidence)

    assert set(selected) == {"logistic", "hgb"}
    assert selected["logistic"].config.identifier.startswith("logistic-")
    assert selected["hgb"].config.identifier.startswith("hgb-")


def test_global_selection_prefers_logistic_then_none_on_exact_ties() -> None:
    base_metrics = {"log_loss": 0.5, "brier_score": 0.2, "ece": 0.01, "roc_auc": 0.7}
    chosen = select_global_variant(
        [
            {
                "identifier": "hgb-sigmoid",
                "family": "hgb",
                "calibration_method": "sigmoid",
                "selection_metrics": base_metrics,
                "mean_qualifying_slice_ece": 0.02,
                "tuned_fold_log_loss_sd": 0.03,
            },
            {
                "identifier": "logistic-none",
                "family": "logistic",
                "calibration_method": "none",
                "selection_metrics": base_metrics,
                "mean_qualifying_slice_ece": 0.02,
                "tuned_fold_log_loss_sd": 0.03,
            },
        ]
    )

    assert chosen["identifier"] == "logistic-none"


def test_development_cli_renders_pending_review_without_artifact_io() -> None:
    output = format_development_result(
        {
            "lock": {
                "status": "pending_review",
                "selected_variant": {"identifier": "logistic-c1-none"},
                "artifact_sha256": "abc123",
            }
        }
    )

    assert output == (
        "status=pending_review selected=logistic-c1-none artifact_sha256=abc123"
    )


def test_small_synthetic_end_to_end_lock_bundle_and_one_final_report(
    tmp_path: Path,
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet", full_e2e=True)
    split_path = _write_split(tmp_path / "splits.json")
    output_dir = tmp_path / "artifacts"

    development = run_development(feature_path, split_path, output_dir)
    audit = verify_model_artifacts(output_dir)
    bundle = validate_bundle(
        output_dir / BUNDLE_FILENAME, development["lock"]["artifact_sha256"]
    )
    with pytest.raises(ModelingProtocolError, match="not locked"):
        run_final_test(feature_path, output_dir)
    lock = lock_development(output_dir)
    report = run_final_test(feature_path, output_dir)
    post_test_audit = verify_model_artifacts(output_dir)

    assert development["lock"]["status"] == "pending_review"
    assert development["lock"]["development_elapsed_seconds"] >= 0
    assert len(development["manifest"]["all_calibration_variants"]) == 6
    assert development["lock"]["test_accessed"] is False
    assert audit["lock_status"] == "pending_review"
    assert lock["status"] == "locked"
    assert post_test_audit["lock_status"] == "locked"
    assert (
        report["logistic_comparator_variant"]
        == development["manifest"]["logistic_comparator_variant"]
    )
    assert set(bundle) == {"selected_model", "logistic_comparator"}
    assert report["status"] == "final_test_complete"
    assert report["final_test_segment"] == {
        "rows": 24,
        "games": 2,
        "first_game_date": "2023-10-24",
        "last_game_date": "2023-10-24",
    }
    assert report["feature_sha256"] == development["manifest"]["feature_sha256"]
    assert (
        report["split_manifest_sha256"]
        == development["manifest"]["split_manifest_sha256"]
    )
    assert (output_dir / LOCK_FILENAME).exists()
    assert (output_dir / MANIFEST_FILENAME).exists()
    assert (output_dir / TEST_REPORT_FILENAME).exists()
    identity = feature_identity(feature_path, split_path)
    assert identity["feature_contract_version"] == str(MODELING_CONTRACT_VERSION)
    with pytest.raises(ValueError, match="already exists"):
        run_final_test(feature_path, output_dir)
    with pytest.raises(ValueError, match="final test report"):
        run_development(feature_path, split_path, output_dir)


def test_development_refuses_retraining_a_locked_record(tmp_path: Path) -> None:
    feature_path = _write_features(tmp_path / "features.parquet", full_e2e=True)
    split_path = _write_split(tmp_path / "splits.json")
    output_dir = tmp_path / "artifacts"
    run_development(feature_path, split_path, output_dir)
    lock_development(output_dir)

    with pytest.raises(ValueError, match="selection record is locked"):
        run_development(feature_path, split_path, output_dir)


def test_lock_rejects_tampered_split_manifest_identity(tmp_path: Path) -> None:
    feature_path = _write_features(tmp_path / "features.parquet", full_e2e=True)
    split_path = _write_split(tmp_path / "splits.json")
    output_dir = tmp_path / "artifacts"
    run_development(feature_path, split_path, output_dir)
    lock_path = output_dir / LOCK_FILENAME
    lock = json.loads(lock_path.read_text())
    lock["split_manifest_sha256"] = "tampered"
    lock_path.write_text(json.dumps(lock))

    with pytest.raises(ModelingProtocolError, match="split hashes disagree"):
        lock_development(output_dir)


def test_final_test_reservation_is_fail_closed_after_test_loader_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    feature_path = _write_features(tmp_path / "features.parquet", full_e2e=True)
    split_path = _write_split(tmp_path / "splits.json")
    output_dir = tmp_path / "artifacts"
    run_development(feature_path, split_path, output_dir)
    lock_development(output_dir)
    calls = 0

    def fail_after_access(_: Path) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic post-access failure")

    monkeypatch.setattr(workflow, "load_final_test_features", fail_after_access)
    with pytest.raises(RuntimeError, match="post-access"):
        run_final_test(feature_path, output_dir)
    with pytest.raises(ModelingProtocolError, match="already reserved"):
        run_final_test(feature_path, output_dir)

    assert calls == 1
    assert (output_dir / FINAL_TEST_RESERVATION_FILENAME).exists()


def test_pre_access_final_test_failure_releases_reservation(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"

    with pytest.raises(FileNotFoundError):
        run_final_test(tmp_path / "missing.parquet", output_dir)

    assert not (output_dir / FINAL_TEST_RESERVATION_FILENAME).exists()

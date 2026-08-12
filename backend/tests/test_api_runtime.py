"""Locked-artifact runtime integrity and bounded real-model smoke tests."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pytest
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from hoopslab.api.runtime import (
    EXPECTED_CANDIDATE_CONFIG,
    EXPECTED_FINAL_TEST_SEGMENT,
    EXPECTED_PREPROCESSING,
    EXPECTED_SEGMENTS,
    ModelRuntime,
    ModelRuntimeError,
)
from hoopslab.features import MODEL_INPUT_FIELDS
from hoopslab.modeling.artifacts import (
    BUNDLE_FILENAME,
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    TEST_REPORT_FILENAME,
    write_json,
)
from hoopslab.modeling.candidates import CandidateConfig, build_candidate
from hoopslab.modeling.protocol import sha256_file


class TinyProbabilityModel:
    """Serializable, deterministic estimator implementing the runtime surface."""

    feature_names_in_ = np.asarray(MODEL_INPUT_FIELDS)
    classes_ = np.asarray([0, 1])

    def predict_proba(self, frame: Any) -> np.ndarray:
        distances = np.asarray(frame["shot_distance_ft"], dtype=float)
        positive = np.clip(0.25 + distances / 100.0, 0.0, 1.0)
        return np.column_stack((1.0 - positive, positive))


class SyntheticModelRuntime(ModelRuntime):
    """Keep record tests fast while production uses exact estimator validation."""

    def _validate_estimator(self, model: object) -> None:
        names = getattr(model, "feature_names_in_", None)
        if names is None or tuple(str(item) for item in names) != MODEL_INPUT_FIELDS:
            raise ModelRuntimeError("synthetic estimator feature order is incompatible")


def _write_runtime_records(directory: Path) -> dict[str, Path]:
    artifact_path = directory / BUNDLE_FILENAME
    joblib.dump(
        {
            "selected_model": TinyProbabilityModel(),
            "logistic_comparator": object(),
        },
        artifact_path,
    )
    digest = sha256_file(artifact_path)
    selected = {
        "identifier": "hgb-lr0.05-leaves15-sigmoid",
        "family": "hgb",
        "calibration_method": "sigmoid",
        "tuned_candidate": "hgb-lr0.05-leaves15",
        "candidate_config": EXPECTED_CANDIDATE_CONFIG,
        "preprocessing": EXPECTED_PREPROCESSING,
    }
    logistic = {
        "identifier": "logistic-c1-isotonic",
        "family": "logistic",
        "calibration_method": "isotonic",
    }
    shared: dict[str, Any] = {
        "artifact_file": BUNDLE_FILENAME,
        "artifact_sha256": digest,
        "feature_sha256": "a" * 64,
        "split_manifest_sha256": "b" * 64,
        "selected_variant": selected,
        "logistic_comparator_variant": logistic,
        "protocol": {},
        "segments": EXPECTED_SEGMENTS,
        "folds": [],
        "development_elapsed_seconds": 1.0,
        "training_seasons": [2018, 2019, 2020, 2021],
        "modeling_contract_version": 1,
        "feature_contract_version": "1",
        "feature_fields": list(MODEL_INPUT_FIELDS),
        "package_versions": {"scikit_learn": sklearn.__version__},
        "calibration_end_inclusive": "2023-01-10",
        "selection_date_range": ["2023-01-11", "2023-04-09"],
    }
    manifest = {
        **shared,
        "all_calibration_variants": [],
        "tuned_hgb": {"config": EXPECTED_CANDIDATE_CONFIG},
    }
    lock = {
        **shared,
        "status": "locked",
        "test_accessed": False,
        "test_metrics_generated": False,
    }
    report = {
        "status": "final_test_complete",
        "lock_artifact_sha256": digest,
        "feature_sha256": shared["feature_sha256"],
        "split_manifest_sha256": shared["split_manifest_sha256"],
        "selected_variant": selected,
        "logistic_comparator_variant": logistic,
        "selected_metrics": {
            "log_loss": 0.63,
            "brier_score": 0.22,
            "roc_auc": 0.66,
            "ece": 0.01,
        },
        "final_test_segment": EXPECTED_FINAL_TEST_SEGMENT,
    }
    paths = {
        "artifact": artifact_path,
        "manifest": directory / MANIFEST_FILENAME,
        "lock": directory / LOCK_FILENAME,
        "report": directory / TEST_REPORT_FILENAME,
    }
    write_json(paths["manifest"], manifest)
    write_json(paths["lock"], lock)
    write_json(paths["report"], report)
    return paths


def _runtime(paths: dict[str, Path]) -> SyntheticModelRuntime:
    return SyntheticModelRuntime(
        artifact_path=paths["artifact"],
        manifest_path=paths["manifest"],
        lock_path=paths["lock"],
        report_path=paths["report"],
    )


def test_runtime_validates_loads_once_and_predicts_unknown_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_runtime_records(tmp_path)
    load_calls = 0
    original_load = joblib.load

    def counted_load(*args: Any, **kwargs: Any) -> Any:
        nonlocal load_calls
        load_calls += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr("hoopslab.modeling.artifacts.joblib.load", counted_load)
    runtime = _runtime(paths)
    runtime.initialize()
    runtime.initialize()
    row = {
        "coordinate_x_ft": 1.0,
        "coordinate_y_ft": 2.0,
        "shot_distance_ft": 20,
        "shot_angle_degrees": 26.5,
        "period": 1,
        "seconds_remaining": 100,
        "shooter_is_home": True,
        "action_type": "Previously unseen action",
        "shot_type": "2PT Field Goal",
        "shot_zone_basic": "Previously unseen zone",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "8-16 ft.",
        "season_type": "rg",
    }

    assert load_calls == 1
    assert runtime.is_ready
    assert runtime.metadata["model_version"] == sha256_file(paths["artifact"])[:12]
    assert runtime.metadata["family"] == "hist_gradient_boosting"
    assert runtime.metadata["calibration"] == "sigmoid"
    assert runtime.metadata["training_seasons"] == [2018, 2019, 2020, 2021]
    assert runtime.metadata["calibration_season"] == 2022
    assert runtime.metadata["selection_season"] == 2022
    assert runtime.metadata["heldout_season"] == 2023
    assert runtime.predict([row]) == pytest.approx([0.45])


@pytest.mark.parametrize(
    ("record", "mutate"),
    [
        (
            "manifest",
            lambda value: value["selected_variant"].update(
                {"identifier": "hgb-other-sigmoid"}
            ),
        ),
        (
            "manifest",
            lambda value: value["selected_variant"]["candidate_config"].update(
                {"learning_rate": 0.1}
            ),
        ),
        (
            "manifest",
            lambda value: value.update({"training_seasons": [2019, 2020, 2021]}),
        ),
        (
            "lock",
            lambda value: value["segments"]["selection"].update({"rows": 1}),
        ),
        (
            "report",
            lambda value: value["final_test_segment"].update({"games": 1}),
        ),
    ],
)
def test_runtime_rejects_locked_specification_or_segment_tampering(
    tmp_path: Path, record: str, mutate: Any
) -> None:
    import json

    paths = _write_runtime_records(tmp_path)
    payload = json.loads(paths[record].read_text())
    mutate(payload)
    write_json(paths[record], payload)

    with pytest.raises(ModelRuntimeError, match="artifact validation failed"):
        _runtime(paths).initialize()


def test_runtime_rejects_self_consistent_wrong_selected_specification(
    tmp_path: Path,
) -> None:
    import json

    paths = _write_runtime_records(tmp_path)
    for record in ("manifest", "lock", "report"):
        payload = json.loads(paths[record].read_text())
        payload["selected_variant"]["identifier"] = "hgb-other-sigmoid"
        if record == "manifest":
            payload["tuned_hgb"]["config"]["learning_rate"] = 0.1
        write_json(paths[record], payload)

    with pytest.raises(ModelRuntimeError, match="artifact validation failed"):
        _runtime(paths).initialize()


def test_runtime_rejects_self_consistent_wrong_seasons_and_segments(
    tmp_path: Path,
) -> None:
    import json

    paths = _write_runtime_records(tmp_path)
    for record in ("manifest", "lock"):
        payload = json.loads(paths[record].read_text())
        payload["training_seasons"] = [2019, 2020, 2021]
        payload["segments"]["calibration"]["rows"] = 1
        write_json(paths[record], payload)

    with pytest.raises(ModelRuntimeError, match="artifact validation failed"):
        _runtime(paths).initialize()


def _exact_unfitted_selected_model() -> CalibratedClassifierCV:
    config = CandidateConfig(
        identifier="hgb-lr0.05-leaves15",
        family="hgb",
        learning_rate=0.05,
        max_leaf_nodes=15,
    )
    pipeline = build_candidate(config)
    return CalibratedClassifierCV(estimator=FrozenEstimator(pipeline), method="sigmoid")


def test_estimator_structure_requires_exact_locked_composition_and_parameters() -> None:
    model = _exact_unfitted_selected_model()
    ModelRuntime._validate_estimator_structure(model)

    model.method = "isotonic"
    with pytest.raises(ModelRuntimeError, match="calibrator"):
        ModelRuntime._validate_estimator_structure(model)

    model = _exact_unfitted_selected_model()
    model.estimator.estimator.set_params(classifier__learning_rate=0.1)
    with pytest.raises(ModelRuntimeError, match="HGB parameters"):
        ModelRuntime._validate_estimator_structure(model)

    model = _exact_unfitted_selected_model()
    model.estimator.estimator.set_params(classifier__max_iter=200)
    with pytest.raises(ModelRuntimeError, match="HGB parameters"):
        ModelRuntime._validate_estimator_structure(model)


@pytest.mark.parametrize(
    ("record", "field", "value"),
    [
        ("lock", "status", "pending_review"),
        ("lock", "artifact_file", "other.joblib"),
        ("manifest", "feature_fields", list(reversed(MODEL_INPUT_FIELDS))),
        ("manifest", "modeling_contract_version", 2),
        ("manifest", "package_versions", {"scikit_learn": "0.0"}),
    ],
)
def test_runtime_rejects_unlocked_or_incompatible_records(
    tmp_path: Path, record: str, field: str, value: object
) -> None:
    paths = _write_runtime_records(tmp_path)
    import json

    payload = json.loads(paths[record].read_text())
    payload[field] = value
    write_json(paths[record], payload)
    runtime = _runtime(paths)

    with pytest.raises(ModelRuntimeError, match="artifact validation failed"):
        runtime.initialize()

    assert not runtime.is_ready
    assert runtime.diagnostic is not None


def test_runtime_rejects_missing_or_hash_mismatched_artifact(tmp_path: Path) -> None:
    paths = _write_runtime_records(tmp_path)
    paths["artifact"].write_bytes(b"not the locked bundle")
    runtime = _runtime(paths)

    with pytest.raises(ModelRuntimeError):
        runtime.initialize()

    paths["artifact"].unlink()
    missing_runtime = _runtime(paths)
    with pytest.raises(ModelRuntimeError):
        missing_runtime.initialize()


@pytest.mark.filterwarnings(
    "ignore:Setting the shape on a NumPy array has been deprecated:DeprecationWarning"
)
def test_real_locked_model_has_a_bounded_serving_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOKY_MAX_CPU_COUNT", "1")
    directory = Path("artifacts/modeling")
    required = [
        directory / BUNDLE_FILENAME,
        directory / MANIFEST_FILENAME,
        directory / LOCK_FILENAME,
        directory / TEST_REPORT_FILENAME,
    ]
    if not all(path.exists() for path in required):
        pytest.skip("ignored locked-model artifacts are not present")
    runtime = ModelRuntime(
        artifact_path=required[0],
        manifest_path=required[1],
        lock_path=required[2],
        report_path=required[3],
    )
    runtime.initialize()
    probability = runtime.predict(
        [
            {
                "coordinate_x_ft": 0.0,
                "coordinate_y_ft": 25.0,
                "shot_distance_ft": 25,
                "shot_angle_degrees": 0.0,
                "period": 1,
                "seconds_remaining": 500,
                "shooter_is_home": True,
                "action_type": "Jump Shot",
                "shot_type": "3PT Field Goal",
                "shot_zone_basic": "Above the Break 3",
                "shot_zone_area": "Center(C)",
                "shot_zone_range": "24+ ft.",
                "season_type": "rg",
            }
        ]
    )[0]

    assert 0.0 <= probability <= 1.0
    assert runtime.metadata["model_version"] == "fb075abb1647"


def test_runtime_missing_manifest_does_not_need_an_artifact(tmp_path: Path) -> None:
    paths = _write_runtime_records(tmp_path)
    shutil.rmtree(tmp_path)
    runtime = _runtime(paths)

    with pytest.raises(ModelRuntimeError):
        runtime.initialize()
    assert not runtime.is_ready

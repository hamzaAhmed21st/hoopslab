"""Validated, single-load runtime for the locked shot-quality model."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from hoopslab.features import MODEL_INPUT_FIELDS
from hoopslab.modeling.artifacts import (
    BUNDLE_FILENAME,
    read_json,
    validate_bundle,
    validate_record_schema,
)
from hoopslab.modeling.protocol import (
    BOOLEAN_FIELD,
    CATEGORICAL_FIELDS,
    MODELING_CONTRACT_VERSION,
    NUMERIC_FIELDS,
    SEED,
)

SELECTED_IDENTIFIER = "hgb-lr0.05-leaves15-sigmoid"
TUNED_IDENTIFIER = "hgb-lr0.05-leaves15"
EXPECTED_TRAINING_SEASONS = [2018, 2019, 2020, 2021]
EXPECTED_CANDIDATE_CONFIG = {
    "c": None,
    "family": "hgb",
    "identifier": TUNED_IDENTIFIER,
    "learning_rate": 0.05,
    "max_leaf_nodes": 15,
}
EXPECTED_PREPROCESSING = {
    "numeric": "six numeric fields passthrough",
    "boolean": "shooter_is_home passthrough",
    "categorical": "OrdinalEncoder unknown/missing=NaN with explicit HGB mask",
}
EXPECTED_SEGMENTS = {
    "training": {
        "rows": 815279,
        "games": 4599,
        "first_game_date": "2018-10-16",
        "last_game_date": "2022-04-10",
    },
    "calibration": {
        "rows": 108768,
        "games": 617,
        "first_game_date": "2022-10-18",
        "last_game_date": "2023-01-10",
    },
    "selection": {
        "rows": 108450,
        "games": 613,
        "first_game_date": "2023-01-11",
        "last_game_date": "2023-04-09",
    },
}
EXPECTED_FINAL_TEST_SEGMENT = {
    "rows": 218701,
    "games": 1230,
    "first_game_date": "2023-10-24",
    "last_game_date": "2024-04-14",
}


class ModelRuntimeError(RuntimeError):
    """Raised when the locked model is unavailable or incompatible."""


class PredictionRuntime(Protocol):
    """Small dependency boundary shared by production and API tests."""

    @property
    def is_ready(self) -> bool: ...

    @property
    def diagnostic(self) -> str | None: ...

    @property
    def metadata(self) -> dict[str, Any]: ...

    def initialize(self) -> None: ...

    def mark_unavailable(self, error: Exception) -> None: ...

    def predict(self, rows: Sequence[Mapping[str, object]]) -> list[float]: ...


class ModelRuntime:
    """Own one validated selected estimator for the lifetime of the process."""

    def __init__(
        self,
        *,
        artifact_path: Path,
        manifest_path: Path,
        lock_path: Path,
        report_path: Path,
    ) -> None:
        self._artifact_path = artifact_path
        self._manifest_path = manifest_path
        self._lock_path = lock_path
        self._report_path = report_path
        self._model: Any | None = None
        self._metadata: dict[str, Any] = {}
        self._attempted = False
        self._diagnostic: str | None = None

    @property
    def is_ready(self) -> bool:
        """Return whether the locked model passed every startup check."""
        return self._model is not None

    @property
    def diagnostic(self) -> str | None:
        """Return an internal-only startup diagnostic."""
        return self._diagnostic

    @property
    def metadata(self) -> dict[str, Any]:
        """Return the preselected safe public metadata subset."""
        if not self.is_ready:
            raise ModelRuntimeError("model runtime is unavailable")
        return self._metadata.copy()

    def mark_unavailable(self, error: Exception) -> None:
        """Retain only an internal diagnostic after a failed startup attempt."""
        self._model = None
        self._metadata = {}
        self._diagnostic = f"{type(error).__name__}: {error}"

    def initialize(self) -> None:
        """Validate and deserialize the configured artifact at most once."""
        if self._attempted:
            return
        self._attempted = True
        try:
            self._load()
        except Exception as error:
            self.mark_unavailable(error)
            raise ModelRuntimeError(
                "locked model artifact validation failed"
            ) from error

    def _load(self) -> None:
        manifest = read_json(self._manifest_path)
        lock = read_json(self._lock_path)
        report = read_json(self._report_path)
        validate_record_schema(lock, manifest, report)
        self._validate_records(lock, manifest, report)

        expected_sha256 = manifest["artifact_sha256"]
        if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
            raise ModelRuntimeError("manifest artifact identity is invalid")
        bundle = validate_bundle(self._artifact_path, expected_sha256)
        selected_model = bundle["selected_model"]
        self._validate_estimator(selected_model)

        selected = manifest["selected_variant"]
        metrics = report["selected_metrics"]
        family = str(selected["family"])
        calibration = str(selected["calibration_method"])
        training_seasons = list(manifest["training_seasons"])
        development_season = max(training_seasons) + 1
        final_segment = report["final_test_segment"]
        heldout_season = int(str(final_segment["first_game_date"])[:4])
        self._model = selected_model
        self._metadata = {
            "model_version": expected_sha256[:12],
            "family": {"hgb": "hist_gradient_boosting"}[family],
            "calibration": calibration,
            "feature_names": list(MODEL_INPUT_FIELDS),
            "training_seasons": training_seasons,
            "calibration_season": development_season,
            "selection_season": development_season,
            "heldout_season": heldout_season,
            "held_out_metrics": {
                field: float(metrics[field])
                for field in ("log_loss", "brier_score", "roc_auc", "ece")
            },
            "limitations": [
                "Contextual make probability, not causal player value.",
                "Excludes player, defender, lineup, score, and venue context.",
                "Three-point and midrange discrimination is limited.",
            ],
            "selected_variant": str(selected["identifier"]),
        }

    def _validate_records(
        self,
        lock: dict[str, Any],
        manifest: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        if lock.get("status") != "locked":
            raise ModelRuntimeError("selection record is not locked")
        if (
            lock.get("test_accessed") is not False
            or lock.get("test_metrics_generated") is not False
        ):
            raise ModelRuntimeError("development lock has invalid test flags")
        if manifest.get("artifact_file") != BUNDLE_FILENAME:
            raise ModelRuntimeError("manifest artifact filename is invalid")
        if lock.get("artifact_file") != BUNDLE_FILENAME:
            raise ModelRuntimeError("lock artifact filename is invalid")
        if manifest.get("modeling_contract_version") != MODELING_CONTRACT_VERSION:
            raise ModelRuntimeError("unsupported modeling contract")
        if lock.get("modeling_contract_version") != MODELING_CONTRACT_VERSION:
            raise ModelRuntimeError("lock modeling contract is incompatible")
        if manifest.get("feature_contract_version") != "1":
            raise ModelRuntimeError("unsupported feature contract")
        if lock.get("feature_contract_version") != "1":
            raise ModelRuntimeError("lock feature contract is incompatible")
        expected_fields = list(MODEL_INPUT_FIELDS)
        if manifest.get("feature_fields") != expected_fields:
            raise ModelRuntimeError("manifest feature order is incompatible")
        if lock.get("feature_fields") != expected_fields:
            raise ModelRuntimeError("lock feature order is incompatible")
        versions = manifest.get("package_versions")
        if (
            not isinstance(versions, dict)
            or versions.get("scikit_learn") != sklearn.__version__
        ):
            raise ModelRuntimeError("scikit-learn version is incompatible")
        selected = manifest.get("selected_variant")
        if not isinstance(selected, dict):
            raise ModelRuntimeError("selected variant is missing")
        if (
            selected.get("identifier") != SELECTED_IDENTIFIER
            or selected.get("family") != "hgb"
            or selected.get("calibration_method") != "sigmoid"
            or selected.get("tuned_candidate") != TUNED_IDENTIFIER
            or selected.get("candidate_config") != EXPECTED_CANDIDATE_CONFIG
            or selected.get("preprocessing") != EXPECTED_PREPROCESSING
        ):
            raise ModelRuntimeError("selected locked specification is incompatible")
        tuned_hgb = manifest.get("tuned_hgb")
        if (
            not isinstance(tuned_hgb, dict)
            or tuned_hgb.get("config") != EXPECTED_CANDIDATE_CONFIG
        ):
            raise ModelRuntimeError("tuned HGB specification is incompatible")
        for record in (manifest, lock):
            if record.get("training_seasons") != EXPECTED_TRAINING_SEASONS:
                raise ModelRuntimeError("training seasons are incompatible")
            if record.get("calibration_end_inclusive") != "2023-01-10":
                raise ModelRuntimeError("calibration boundary is incompatible")
            if record.get("selection_date_range") != ["2023-01-11", "2023-04-09"]:
                raise ModelRuntimeError("selection boundary is incompatible")
            if record.get("segments") != EXPECTED_SEGMENTS:
                raise ModelRuntimeError("development segments are incompatible")
        if report.get("selected_variant") != selected:
            raise ModelRuntimeError("report selected variant is incompatible")
        if report.get("final_test_segment") != EXPECTED_FINAL_TEST_SEGMENT:
            raise ModelRuntimeError("held-out segment is incompatible")
        metrics = report.get("selected_metrics")
        if not isinstance(metrics, dict):
            raise ModelRuntimeError("held-out metrics are missing")
        for field in ("log_loss", "brier_score", "roc_auc", "ece"):
            value = metrics.get(field)
            if not isinstance(value, int | float) or not np.isfinite(value):
                raise ModelRuntimeError("held-out metrics are invalid")

    def _validate_estimator(self, model: object) -> None:
        self._validate_estimator_structure(model)
        names = getattr(model, "feature_names_in_", None)
        if names is None or tuple(str(item) for item in names) != MODEL_INPUT_FIELDS:
            raise ModelRuntimeError("runtime estimator feature order is incompatible")
        classes = np.asarray(getattr(model, "classes_", []))
        if classes.shape != (2,) or not np.array_equal(classes, np.array([0, 1])):
            raise ModelRuntimeError("runtime estimator classes are incompatible")
        sanity = {
            "coordinate_x_ft": 0.0,
            "coordinate_y_ft": 5.0,
            "shot_distance_ft": 5,
            "shot_angle_degrees": 0.0,
            "period": 1,
            "seconds_remaining": 600,
            "shooter_is_home": True,
            "action_type": "Jump Shot",
            "shot_type": "2PT Field Goal",
            "shot_zone_basic": "Mid-Range",
            "shot_zone_area": "Center(C)",
            "shot_zone_range": "8-16 ft.",
            "season_type": "rg",
        }
        probabilities = self._predict_with(model, [sanity])
        if len(probabilities) != 1:
            raise ModelRuntimeError("runtime estimator sanity prediction failed")

    @staticmethod
    def _validate_estimator_structure(model: object) -> None:
        """Require the exact public estimator composition of the locked model."""
        if not isinstance(model, CalibratedClassifierCV) or model.method != "sigmoid":
            raise ModelRuntimeError("runtime calibrator is incompatible")
        frozen = model.estimator
        if not isinstance(frozen, FrozenEstimator):
            raise ModelRuntimeError("runtime base estimator is not frozen")
        pipeline = frozen.estimator
        if not isinstance(pipeline, Pipeline) or list(pipeline.named_steps) != [
            "preprocess",
            "classifier",
        ]:
            raise ModelRuntimeError("runtime pipeline composition is incompatible")
        preprocess = pipeline.named_steps["preprocess"]
        classifier = pipeline.named_steps["classifier"]
        if not isinstance(preprocess, ColumnTransformer):
            raise ModelRuntimeError("runtime preprocessor is incompatible")
        transformers = preprocess.transformers
        if len(transformers) != 3:
            raise ModelRuntimeError("runtime preprocessing shape is incompatible")
        numeric_name, numeric_transformer, numeric_fields = transformers[0]
        home_name, home_transformer, home_fields = transformers[1]
        categorical_name, categorical_transformer, categorical_fields = transformers[2]
        if (
            (numeric_name, numeric_transformer, list(numeric_fields))
            != ("numeric", "passthrough", list(NUMERIC_FIELDS))
            or (home_name, home_transformer, list(home_fields))
            != ("home", "passthrough", [BOOLEAN_FIELD])
            or categorical_name != "categorical"
            or list(categorical_fields) != list(CATEGORICAL_FIELDS)
            or preprocess.remainder != "drop"
            or preprocess.verbose_feature_names_out is not False
        ):
            raise ModelRuntimeError("runtime preprocessing contract is incompatible")
        if (
            not isinstance(categorical_transformer, OrdinalEncoder)
            or categorical_transformer.handle_unknown != "use_encoded_value"
            or not np.isnan(categorical_transformer.unknown_value)
            or not np.isnan(categorical_transformer.encoded_missing_value)
        ):
            raise ModelRuntimeError("runtime categorical encoder is incompatible")
        expected_mask = [False] * 7 + [True] * 6
        if not isinstance(classifier, HistGradientBoostingClassifier):
            raise ModelRuntimeError("runtime classifier family is incompatible")
        if (
            classifier.loss != "log_loss"
            or classifier.learning_rate != 0.05
            or classifier.max_leaf_nodes != 15
            or classifier.max_iter != 300
            or classifier.min_samples_leaf != 100
            or classifier.l2_regularization != 1.0
            or classifier.early_stopping is not False
            or list(classifier.categorical_features) != expected_mask
            or classifier.random_state != SEED
        ):
            raise ModelRuntimeError("runtime HGB parameters are incompatible")

    def predict(self, rows: Sequence[Mapping[str, object]]) -> list[float]:
        """Run one vectorized probability invocation in stable input order."""
        if self._model is None:
            raise ModelRuntimeError("model runtime is unavailable")
        if not rows:
            return []
        try:
            return self._predict_with(self._model, rows)
        except ModelRuntimeError:
            raise
        except Exception as error:
            raise ModelRuntimeError("model prediction failed") from error

    @staticmethod
    def _predict_with(
        model: object, rows: Sequence[Mapping[str, object]]
    ) -> list[float]:
        frame = pd.DataFrame.from_records(rows, columns=MODEL_INPUT_FIELDS)
        raw = model.predict_proba(frame)  # type: ignore[attr-defined]
        probabilities = np.asarray(raw, dtype=float)
        if probabilities.shape != (len(rows), 2):
            raise ModelRuntimeError("runtime estimator returned an invalid shape")
        positive = probabilities[:, 1]
        if not np.all(np.isfinite(positive)) or np.any(
            (positive < 0.0) | (positive > 1.0)
        ):
            raise ModelRuntimeError("runtime estimator returned invalid probabilities")
        return [float(value) for value in positive]

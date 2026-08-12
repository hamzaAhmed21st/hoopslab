"""Traceable chronological tuning, calibration selection, locking, and final test."""

from __future__ import annotations

import json
import platform
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

import joblib
import numpy as np
import pandas as pd
import pyarrow
import scipy
import sklearn
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance

from hoopslab.modeling.artifacts import (
    BUNDLE_FILENAME,
    LOCK_FILENAME,
    MANIFEST_FILENAME,
    TEST_REPORT_FILENAME,
    audit_development_records,
    persist_bundle,
    reserve_final_test,
    utc_timestamp,
    validate_lock_for_final_test,
    write_json,
)
from hoopslab.modeling.candidates import (
    ALL_CANDIDATES,
    CandidateConfig,
    build_candidate,
)
from hoopslab.modeling.metrics import (
    game_block_bootstrap,
    mean_qualifying_slice_ece,
    predeclared_slice_metrics,
    probability_metrics,
)
from hoopslab.modeling.protocol import (
    BOOTSTRAP_SEED,
    MODELING_CONTRACT_VERSION,
    ROLLING_FOLDS,
    SEED,
    TRAINING_SEASONS,
    feature_identity,
    frame_inputs,
    frame_target,
    load_development_features,
    load_final_test_features,
    sha256_file,
    split_2022_calibration_selection,
    validate_development_split_assignments,
)
from hoopslab.sources.archive import SOURCE_MANIFEST, SOURCE_REPOSITORY, SOURCE_REVISION

CalibrationMethod = Literal["none", "sigmoid", "isotonic"]
CALIBRATION_METHODS: tuple[CalibrationMethod, ...] = ("none", "sigmoid", "isotonic")


def format_development_result(result: dict[str, object]) -> str:
    """Render a pending-review result without reading generated artifacts."""
    lock = result["lock"]
    if not isinstance(lock, dict):
        raise ValueError("development result has no lock record")
    variant = lock.get("selected_variant")
    if not isinstance(variant, dict) or not isinstance(variant.get("identifier"), str):
        raise ValueError("development lock has no selected variant")
    return (
        f"status={lock.get('status')} selected={variant['identifier']} "
        f"artifact_sha256={lock.get('artifact_sha256')}"
    )


@dataclass(frozen=True)
class TunedCandidate:
    """One candidate's chronological evidence and selected configuration."""

    config: CandidateConfig
    fold_metrics: list[dict[str, Any]]
    mean_log_loss: float
    mean_brier_score: float
    fold_log_loss_sd: float
    mean_roc_auc: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "config": asdict(self.config),
            "fold_metrics": self.fold_metrics,
            "mean_log_loss": self.mean_log_loss,
            "mean_brier_score": self.mean_brier_score,
            "fold_log_loss_sd": self.fold_log_loss_sd,
            "mean_roc_auc": self.mean_roc_auc,
        }


def _predict_probabilities(model: object, frame: pd.DataFrame) -> np.ndarray:
    probabilities = model.predict_proba(frame_inputs(frame))[:, 1]  # type: ignore[attr-defined]
    return np.asarray(probabilities, dtype=float)


def _optional_delta(left: float | None, right: float | None) -> float | None:
    """Preserve undefined ROC-AUC for a one-class diagnostic subset."""
    return left - right if left is not None and right is not None else None


def tune_candidate(
    config: CandidateConfig, development: pd.DataFrame
) -> TunedCandidate:
    """Evaluate one candidate only on the three frozen rolling-origin folds."""
    fold_metrics: list[dict[str, Any]] = []
    for fold in ROLLING_FOLDS:
        train = development.loc[development["season_start"].isin(fold.train_seasons)]
        validation = development.loc[
            development["season_start"] == fold.validation_season
        ]
        train_games = set(train["game_id"].astype(int))
        validation_games = set(validation["game_id"].astype(int))
        if (
            not len(train)
            or not len(validation)
            or train_games.intersection(validation_games)
        ):
            raise ValueError(f"invalid whole-game assignment in {fold.identifier}")
        model = build_candidate(config)
        model.fit(frame_inputs(train), frame_target(train))
        metrics = probability_metrics(
            frame_target(validation), _predict_probabilities(model, validation)
        )
        fold_metrics.append(
            {
                "fold": fold.identifier,
                "train_seasons": list(fold.train_seasons),
                "validation_season": fold.validation_season,
                "train_rows": len(train),
                "validation_rows": len(validation),
                "train_games": int(train["game_id"].nunique()),
                "validation_games": int(validation["game_id"].nunique()),
                **metrics.as_dict(),
            }
        )
    log_losses = [float(item["log_loss"]) for item in fold_metrics]
    briers = [float(item["brier_score"]) for item in fold_metrics]
    aucs = [float(item["roc_auc"]) for item in fold_metrics]
    return TunedCandidate(
        config=config,
        fold_metrics=fold_metrics,
        mean_log_loss=float(np.mean(log_losses)),
        mean_brier_score=float(np.mean(briers)),
        fold_log_loss_sd=float(np.std(log_losses, ddof=0)),
        mean_roc_auc=float(np.mean(aucs)),
    )


def tune_candidates(development: pd.DataFrame) -> dict[str, TunedCandidate]:
    """Run the deliberately small grid and select each family's stable candidate."""
    evidence = {
        config.identifier: tune_candidate(config, development)
        for config in ALL_CANDIDATES
    }
    return evidence


def select_tuned_by_family(
    evidence: dict[str, TunedCandidate],
) -> dict[str, TunedCandidate]:
    """Apply the predeclared unrounded chronological selection ordering per family."""
    result: dict[str, TunedCandidate] = {}
    for family in ("logistic", "hgb"):
        candidates = [
            item for item in evidence.values() if item.config.family == family
        ]
        result[family] = min(
            candidates,
            key=lambda item: (
                item.mean_log_loss,
                item.mean_brier_score,
                item.fold_log_loss_sd,
                -item.mean_roc_auc,
                item.config.complexity_rank,
                item.config.identifier,
            ),
        )
    return result


def fit_base(config: CandidateConfig, training: pd.DataFrame) -> object:
    """Fit a base estimator on the authorized 2018-19 through 2021-22 years only."""
    observed = set(training["season_start"].astype(int).unique())
    if observed != TRAINING_SEASONS:
        raise ValueError(f"base training requires exactly {sorted(TRAINING_SEASONS)}")
    model = build_candidate(config)
    model.fit(frame_inputs(training), frame_target(training))
    return model


def calibrate_base(
    base_model: object, calibration: pd.DataFrame, method: CalibrationMethod
) -> object:
    """Fit a calibrator only on 2022's calibration segment; never refit the base."""
    if method == "none":
        return base_model
    frozen = FrozenEstimator(base_model)
    calibrated = CalibratedClassifierCV(estimator=frozen, method=method)
    calibrated.fit(frame_inputs(calibration), frame_target(calibration))
    return calibrated


def _variant_record(
    family: str,
    tuned: TunedCandidate,
    method: CalibrationMethod,
    model: object,
    calibration: pd.DataFrame,
    selection: pd.DataFrame,
) -> dict[str, Any]:
    calibration_metrics = probability_metrics(
        frame_target(calibration), _predict_probabilities(model, calibration)
    )
    selection_predictions = _predict_probabilities(model, selection)
    selection_metrics = probability_metrics(
        frame_target(selection), selection_predictions
    )
    slices = predeclared_slice_metrics(selection, selection_predictions)
    return {
        "identifier": f"{tuned.config.identifier}-{method}",
        "family": family,
        "calibration_method": method,
        "tuned_candidate": tuned.config.identifier,
        "candidate_config": asdict(tuned.config),
        "preprocessing": _preprocessing_identity(tuned.config.family),
        "tuned_fold_log_loss_sd": tuned.fold_log_loss_sd,
        "calibration_fit_diagnostics_non_independent": calibration_metrics.as_dict(),
        "selection_metrics": selection_metrics.as_dict(),
        "selection_slices": slices,
        "mean_qualifying_slice_ece": mean_qualifying_slice_ece(slices),
    }


def select_global_variant(variants: list[dict[str, Any]]) -> dict[str, Any]:
    """Select from independent 2022 evidence only using the frozen global ordering."""
    if not variants:
        raise ValueError("no model variants available")
    return min(variants, key=_global_selection_key)


def _global_selection_key(item: dict[str, Any]) -> tuple[float, ...] | tuple[Any, ...]:
    family_rank = {"logistic": 0, "hgb": 1}
    calibration_rank = {"none": 0, "sigmoid": 1, "isotonic": 2}
    return (
        float(item["selection_metrics"]["log_loss"]),
        float(item["selection_metrics"]["brier_score"]),
        float(item["selection_metrics"]["ece"]),
        float(item["mean_qualifying_slice_ece"]),
        float(item["tuned_fold_log_loss_sd"]),
        -float(item["selection_metrics"]["roc_auc"]),
        family_rank[str(item["family"])],
        calibration_rank[cast(str, item["calibration_method"])],
        str(item["identifier"]),
    )


def _package_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pyarrow": pyarrow.__version__,
        "scikit_learn": sklearn.__version__,
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "joblib": joblib.__version__,
    }


def _preprocessing_identity(family: str) -> dict[str, Any]:
    """Describe fitted-only transformations without serializing implementation paths."""
    if family == "logistic":
        return {
            "numeric": "StandardScaler on six numeric fields",
            "boolean": "shooter_is_home passthrough",
            "categorical": "OneHotEncoder(handle_unknown=ignore) on six fields",
        }
    return {
        "numeric": "six numeric fields passthrough",
        "boolean": "shooter_is_home passthrough",
        "categorical": "OrdinalEncoder unknown/missing=NaN with explicit HGB mask",
    }


def _segment_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "games": int(frame["game_id"].nunique()),
        "first_game_date": str(frame["game_date"].min()),
        "last_game_date": str(frame["game_date"].max()),
    }


def _distance_sanity(
    frame: pd.DataFrame, probabilities: np.ndarray
) -> list[dict[str, Any]]:
    """Record descriptive selection-only distance behavior; never select with it."""
    work = frame.loc[:, ["shot_distance_ft", "made"]].copy()
    work["prediction"] = probabilities
    work["bucket"] = pd.cut(
        work["shot_distance_ft"],
        bins=[-1, 3, 8, 16, 24, float("inf")],
        labels=["0-3", "4-8", "9-16", "17-24", "25+"],
    )
    return [
        {
            "bucket": str(bucket),
            "rows": len(group),
            "mean_prediction": float(group["prediction"].mean()),
            "observed_rate": float(group["made"].astype(int).mean()),
        }
        for bucket, group in work.groupby("bucket", observed=True)
    ]


def _interpretability_evidence(
    selected: dict[str, Any], model: object, selection: pd.DataFrame
) -> dict[str, Any]:
    """Bounded, selection-only descriptive evidence with no role in selection."""
    predictions = _predict_probabilities(model, selection)
    evidence: dict[str, Any] = {
        "scope": "independent selection segment only; descriptive and noncausal",
        "distance_predicted_observed": _distance_sanity(selection, predictions),
    }
    if selected["family"] == "logistic":
        estimator = model
        if isinstance(model, CalibratedClassifierCV):
            estimator = model.estimator.estimator
        pipeline = cast(Any, estimator)
        names = pipeline.named_steps["preprocess"].get_feature_names_out()
        coefficients = pipeline.named_steps["classifier"].coef_[0]
        order = np.argsort(np.abs(coefficients))[::-1][:12]
        evidence["logistic_coefficients"] = {
            "caveat": (
                "conditional associations after fitted transforms, not causal effects"
            ),
            "largest_absolute": [
                {
                    "feature": str(names[index]),
                    "coefficient": float(coefficients[index]),
                }
                for index in order
            ],
        }
    else:
        sample = selection.sort_values(["game_date", "game_id", "event_id"]).head(
            50_000
        )
        result = permutation_importance(
            model,
            frame_inputs(sample),
            frame_target(sample),
            n_repeats=5,
            random_state=SEED,
            scoring="neg_log_loss",
        )
        evidence["hgb_permutation_importance"] = {
            "scope": (
                "deterministic capped selection sample; descriptive, "
                "not selection input"
            ),
            "rows": len(sample),
            "mean_neg_log_loss_decrease": {
                field: float(value)
                for field, value in zip(
                    frame_inputs(sample).columns, result.importances_mean, strict=True
                )
            },
        }
    return evidence


def _source_identity() -> dict[str, Any]:
    """Attach the six pinned source identities without reading source data."""
    return {
        "source_repository": SOURCE_REPOSITORY,
        "source_revision": SOURCE_REVISION,
        "source_assets": [
            {
                "season_start": asset.season_start,
                "relative_path": asset.relative_path,
                "sha256": asset.sha256,
            }
            for asset in SOURCE_MANIFEST
        ],
    }


def run_development(
    feature_path: Path, split_path: Path, output_dir: Path
) -> dict[str, Any]:
    """Write pending-review development evidence without accessing test data."""
    started_at = time.perf_counter()
    if (output_dir / TEST_REPORT_FILENAME).exists():
        raise ValueError("cannot redevelop after a final test report exists")
    if (output_dir / LOCK_FILENAME).exists():
        from hoopslab.modeling.artifacts import read_json

        existing_lock = read_json(output_dir / LOCK_FILENAME)
        if existing_lock.get("status") == "locked":
            raise ValueError("cannot redevelop after a selection record is locked")
    initial_identity = feature_identity(feature_path, split_path)
    development = load_development_features(feature_path, range(2018, 2023))
    validate_development_split_assignments(split_path, development)
    training = development.loc[
        development["season_start"].isin(TRAINING_SEASONS)
    ].copy()
    validation_2022 = development.loc[development["season_start"] == 2022].copy()
    calibration, selection = split_2022_calibration_selection(validation_2022)
    evidence = tune_candidates(training)
    tuned = select_tuned_by_family(evidence)
    bases = {family: fit_base(item.config, training) for family, item in tuned.items()}
    variants: list[dict[str, Any]] = []
    fitted_variants: dict[str, object] = {}
    for family, item in tuned.items():
        for method in CALIBRATION_METHODS:
            model = calibrate_base(bases[family], calibration, method)
            record = _variant_record(
                family, item, method, model, calibration, selection
            )
            variants.append(record)
            fitted_variants[str(record["identifier"])] = model
    selected = select_global_variant(variants)
    selected_model = fitted_variants[str(selected["identifier"])]
    logistic_variant = select_global_variant(
        [variant for variant in variants if variant["family"] == "logistic"]
    )
    logistic_comparator = fitted_variants[str(logistic_variant["identifier"])]
    bundle_path, bundle_sha256 = persist_bundle(
        output_dir, selected_model=selected_model, logistic_model=logistic_comparator
    )
    final_identity = feature_identity(feature_path, split_path)
    if initial_identity != final_identity:
        raise ValueError("feature or split artifact changed during development")
    segments = {
        "training": _segment_summary(training),
        "calibration": _segment_summary(calibration),
        "selection": _segment_summary(selection),
    }
    ordered_variants = sorted(variants, key=_global_selection_key)
    runner_up = ordered_variants[1]
    selection_reason = {
        "rule": "frozen lexicographic probability-quality key",
        "candidate_count": len(ordered_variants),
        "runner_up": runner_up["identifier"],
        "selected_minus_runner_up": {
            "log_loss": float(selected["selection_metrics"]["log_loss"])
            - float(runner_up["selection_metrics"]["log_loss"]),
            "brier_score": float(selected["selection_metrics"]["brier_score"])
            - float(runner_up["selection_metrics"]["brier_score"]),
        },
    }
    common = {
        "modeling_contract_version": MODELING_CONTRACT_VERSION,
        "feature_fields": list(frame_inputs(development).columns),
        "training_seasons": sorted(TRAINING_SEASONS),
        "calibration_end_inclusive": "2023-01-10",
        "selection_date_range": ["2023-01-11", "2023-04-09"],
        "seeds": {"model": SEED, "bootstrap": BOOTSTRAP_SEED},
        "package_versions": _package_versions(),
        "protocol": {
            "rolling_selection": (
                "mean log loss, Brier, log-loss SD, ROC-AUC, stable complexity"
            ),
            "global_selection": (
                "log loss, Brier, 10-bin ECE, slice ECE, fold stability, ROC-AUC"
            ),
            "calibration_methods": list(CALIBRATION_METHODS),
        },
        "segments": segments,
        "folds": [
            {
                "identifier": fold.identifier,
                "train_seasons": list(fold.train_seasons),
                "validation_season": fold.validation_season,
            }
            for fold in ROLLING_FOLDS
        ],
        "development_elapsed_seconds": time.perf_counter() - started_at,
        **_source_identity(),
        **initial_identity,
    }
    manifest = {
        "manifest_version": 1,
        "created_at": utc_timestamp(),
        "artifact_file": BUNDLE_FILENAME,
        "artifact_sha256": bundle_sha256,
        "selected_variant": selected,
        "logistic_comparator_variant": logistic_variant,
        "selection_reason": selection_reason,
        "selection_only_interpretability": _interpretability_evidence(
            selected, selected_model, selection
        ),
        "tuned_logistic": tuned["logistic"].as_dict(),
        "tuned_hgb": tuned["hgb"].as_dict(),
        "all_tuning_evidence": {key: item.as_dict() for key, item in evidence.items()},
        "all_calibration_variants": variants,
        **common,
    }
    lock = {
        "lock_version": 1,
        "status": "pending_review",
        "created_at": utc_timestamp(),
        "artifact_file": bundle_path.name,
        "artifact_sha256": bundle_sha256,
        "selected_variant": selected,
        "logistic_comparator_variant": logistic_variant,
        "selection_reason": selection_reason,
        "test_accessed": False,
        "test_metrics_generated": False,
        **common,
    }
    write_json(output_dir / MANIFEST_FILENAME, manifest)
    write_json(output_dir / LOCK_FILENAME, lock)
    return {"manifest": manifest, "lock": lock}


def lock_development(output_dir: Path) -> dict[str, Any]:
    """Atomically authorize a reviewed pending development record for final test."""
    from hoopslab.modeling.artifacts import read_json

    report_path = output_dir / TEST_REPORT_FILENAME
    if report_path.exists():
        raise ValueError("cannot lock after a final test report exists")
    lock_path = output_dir / LOCK_FILENAME
    lock = read_json(lock_path)
    manifest = read_json(output_dir / MANIFEST_FILENAME)
    from hoopslab.modeling.artifacts import validate_bundle, validate_record_schema

    validate_record_schema(lock, manifest)
    if lock.get("status") != "pending_review":
        raise ValueError("only a pending-review record can be locked")
    if (
        lock.get("test_accessed") is not False
        or lock.get("test_metrics_generated") is not False
    ):
        raise ValueError("cannot lock development metadata with test access")
    artifact_sha = manifest.get("artifact_sha256")
    if not isinstance(artifact_sha, str):
        raise ValueError("manifest misses artifact SHA-256")
    validate_bundle(output_dir / BUNDLE_FILENAME, artifact_sha)
    locked = {**lock, "status": "locked", "locked_at": utc_timestamp()}
    write_json(lock_path, locked)
    return locked


def run_final_test(feature_path: Path, output_dir: Path) -> dict[str, Any]:
    """Evaluate the locked bundle once on 2023-24 and refuse an existing report."""
    report_path = output_dir / TEST_REPORT_FILENAME
    if report_path.exists():
        raise ValueError(f"final test report already exists at {report_path}")
    reservation = reserve_final_test(output_dir)
    test_data_access_started = False
    try:
        initial_feature_sha256 = sha256_file(feature_path)
        lock, manifest, bundle = validate_lock_for_final_test(
            output_dir, initial_feature_sha256
        )
        test_data_access_started = True
        test = load_final_test_features(feature_path)
        selected_predictions = _predict_probabilities(bundle["selected_model"], test)
        logistic_predictions = _predict_probabilities(
            bundle["logistic_comparator"], test
        )
        selected_metrics = probability_metrics(frame_target(test), selected_predictions)
        logistic_metrics = probability_metrics(frame_target(test), logistic_predictions)
        final_feature_sha256 = sha256_file(feature_path)
        if initial_feature_sha256 != final_feature_sha256:
            raise ValueError("feature artifact changed during final evaluation")
        report = {
            "report_version": 1,
            "created_at": utc_timestamp(),
            "status": "final_test_complete",
            "lock_artifact_sha256": lock["artifact_sha256"],
            "feature_sha256": final_feature_sha256,
            "split_manifest_sha256": manifest["split_manifest_sha256"],
            "final_test_segment": _segment_summary(test),
            "selected_variant": manifest["selected_variant"],
            "logistic_comparator_variant": manifest["logistic_comparator_variant"],
            "selected_metrics": selected_metrics.as_dict(),
            "logistic_baseline_metrics": logistic_metrics.as_dict(),
            "selected_minus_logistic": {
                "log_loss": selected_metrics.log_loss - logistic_metrics.log_loss,
                "brier_score": selected_metrics.brier_score
                - logistic_metrics.brier_score,
                "roc_auc": _optional_delta(
                    selected_metrics.roc_auc, logistic_metrics.roc_auc
                ),
            },
            "selected_slices": predeclared_slice_metrics(test, selected_predictions),
            "bootstrap_300_game_blocks": game_block_bootstrap(
                test, selected_predictions, logistic_predictions
            ),
        }
        write_json(report_path, report)
        return report
    except BaseException:
        if not test_data_access_started:
            reservation.unlink(missing_ok=True)
        raise


def verify_model_artifacts(output_dir: Path) -> dict[str, Any]:
    """Validate bundle identity and pre-test audit without reading any test rows."""
    audit = audit_development_records(output_dir)
    manifest_path = output_dir / MANIFEST_FILENAME
    manifest = cast(dict[str, Any], json.loads(manifest_path.read_text()))
    expected = manifest.get("artifact_sha256")
    if not isinstance(expected, str):
        raise ValueError("manifest artifact SHA-256 is missing")
    from hoopslab.modeling.artifacts import validate_bundle

    validate_bundle(output_dir / BUNDLE_FILENAME, expected)
    return audit

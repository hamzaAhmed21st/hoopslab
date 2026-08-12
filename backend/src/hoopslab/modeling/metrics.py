"""Probability metrics, fixed reliability summaries, slices, and game bootstrap."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from hoopslab.modeling.protocol import BOOTSTRAP_SEED

METRIC_EPSILON = 1e-15


@dataclass(frozen=True)
class ProbabilityMetrics:
    """Predeclared probability-quality metrics and diagnostics."""

    log_loss: float
    brier_score: float
    roc_auc: float | None
    ece: float
    reliability_bins: list[dict[str, float | int]]
    probability_quantiles: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric_arrays(
    y_true: Iterable[int], probabilities: Iterable[float]
) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(list(y_true), dtype=int)
    predicted = np.asarray(list(probabilities), dtype=float)
    if y.ndim != 1 or predicted.ndim != 1 or len(y) != len(predicted) or not len(y):
        raise ValueError(
            "metrics require equally sized non-empty one-dimensional arrays"
        )
    if set(np.unique(y)).difference({0, 1}):
        raise ValueError("target must be binary")
    if not np.isfinite(predicted).all():
        raise ValueError("probabilities must be finite")
    if (predicted < 0.0).any() or (predicted > 1.0).any():
        raise ValueError("probabilities must lie in [0, 1]")
    return y, predicted


def reliability_summary(
    y_true: Iterable[int], probabilities: Iterable[float], *, bins: int = 10
) -> tuple[list[dict[str, float | int]], float]:
    """Calculate fixed equal-width calibration bins and ECE, without rebinning."""
    if bins != 10:
        raise ValueError("the frozen protocol uses exactly 10 equal-width bins")
    y, predicted = _metric_arrays(y_true, probabilities)
    clipped = np.clip(predicted, 0.0, 1.0)
    indices = np.minimum((clipped * bins).astype(int), bins - 1)
    rows: list[dict[str, float | int]] = []
    ece = 0.0
    for index in range(bins):
        mask = indices == index
        count = int(mask.sum())
        lower = index / bins
        upper = (index + 1) / bins
        if count:
            mean_prediction = float(clipped[mask].mean())
            observed_rate = float(y[mask].mean())
            ece += abs(observed_rate - mean_prediction) * count / len(y)
        else:
            mean_prediction = 0.0
            observed_rate = 0.0
        rows.append(
            {
                "lower": lower,
                "upper": upper,
                "count": count,
                "mean_prediction": mean_prediction,
                "observed_rate": observed_rate,
            }
        )
    return rows, float(ece)


def probability_metrics(
    y_true: Iterable[int], probabilities: Iterable[float]
) -> ProbabilityMetrics:
    """Compute frozen selection metrics; clipping is limited to log-loss input."""
    y, predicted = _metric_arrays(y_true, probabilities)
    metric_probabilities = np.clip(predicted, METRIC_EPSILON, 1.0 - METRIC_EPSILON)
    bins, ece = reliability_summary(y, predicted)
    quantiles = np.quantile(predicted, [0.0, 0.01, 0.05, 0.5, 0.95, 0.99, 1.0])
    return ProbabilityMetrics(
        log_loss=float(log_loss(y, metric_probabilities, labels=[0, 1])),
        brier_score=float(brier_score_loss(y, predicted)),
        roc_auc=(
            float(roc_auc_score(y, predicted)) if len(np.unique(y)) == 2 else None
        ),
        ece=ece,
        reliability_bins=bins,
        probability_quantiles={
            label: float(value)
            for label, value in zip(
                ("min", "p01", "p05", "p50", "p95", "p99", "max"),
                quantiles,
                strict=True,
            )
        },
    )


def predeclared_slice_metrics(
    frame: pd.DataFrame, probabilities: Iterable[float], *, minimum_rows: int = 2_000
) -> dict[str, dict[str, dict[str, Any]]]:
    """Evaluate every qualifying predeclared contextual slice without cherry-picking."""
    if minimum_rows < 1:
        raise ValueError("minimum_rows must be positive")
    predicted = np.asarray(list(probabilities), dtype=float)
    if len(frame) != len(predicted):
        raise ValueError("slice frame and probability lengths disagree")
    work = frame.copy()
    work["_prediction"] = predicted
    work["_period_slice"] = np.where(
        work["period"] >= 5, "5+", work["period"].astype(str)
    )
    seconds = work["seconds_remaining"]
    work["_clock_slice"] = pd.cut(
        seconds,
        bins=[0, 120, 360, 600, 721],
        right=False,
        include_lowest=True,
        labels=["[0,120)", "[120,360)", "[360,600)", "[600,720]"],
    ).astype(object)
    work["_home_slice"] = np.where(work["shooter_is_home"], "home", "away")
    specifications = {
        "shot_type": "shot_type",
        "shot_zone_range": "shot_zone_range",
        "period": "_period_slice",
        "home_away": "_home_slice",
        "remaining_clock": "_clock_slice",
    }
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for name, column in specifications.items():
        slices: dict[str, dict[str, Any]] = {}
        for value, group in work.groupby(column, dropna=False, observed=True):
            if len(group) < minimum_rows:
                continue
            metrics = probability_metrics(
                group["made"].astype(int), group["_prediction"]
            )
            slices[str(value)] = {"rows": len(group), **metrics.as_dict()}
        result[name] = slices
    return result


def mean_qualifying_slice_ece(slices: dict[str, dict[str, dict[str, Any]]]) -> float:
    """Return an unweighted mean ECE across all qualifying frozen slices."""
    values = [
        float(metric["ece"])
        for dimension in slices.values()
        for metric in dimension.values()
    ]
    if not values:
        raise ValueError("no qualifying slices available")
    return float(np.mean(values))


def game_block_bootstrap(
    frame: pd.DataFrame,
    selected_probabilities: Iterable[float],
    logistic_probabilities: Iterable[float],
    *,
    replicates: int = 300,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float]]:
    """Use whole-game resampling for percentile-95 metric and paired-delta CIs."""
    if replicates < 1:
        raise ValueError("replicates must be positive")
    selected = np.asarray(list(selected_probabilities), dtype=float)
    logistic = np.asarray(list(logistic_probabilities), dtype=float)
    if len(frame) != len(selected) or len(frame) != len(logistic):
        raise ValueError("bootstrap frame and prediction lengths disagree")
    y, selected = _metric_arrays(frame["made"].astype(int), selected)
    _, logistic = _metric_arrays(y, logistic)
    selected_clipped = np.clip(selected, METRIC_EPSILON, 1.0 - METRIC_EPSILON)
    logistic_clipped = np.clip(logistic, METRIC_EPSILON, 1.0 - METRIC_EPSILON)
    selected_log_losses = -(
        y * np.log(selected_clipped) + (1 - y) * np.log1p(-selected_clipped)
    )
    logistic_log_losses = -(
        y * np.log(logistic_clipped) + (1 - y) * np.log1p(-logistic_clipped)
    )
    selected_brier_losses = (selected - y) ** 2
    logistic_brier_losses = (logistic - y) ** 2
    game_ids = frame["game_id"].astype(int).to_numpy()
    unique_games, inverse = np.unique(game_ids, return_inverse=True)
    counts = np.bincount(inverse)
    grouped = {
        "selected_log_loss": np.bincount(inverse, weights=selected_log_losses),
        "logistic_log_loss": np.bincount(inverse, weights=logistic_log_losses),
        "selected_brier": np.bincount(inverse, weights=selected_brier_losses),
        "logistic_brier": np.bincount(inverse, weights=logistic_brier_losses),
    }
    generator = np.random.default_rng(seed)
    selected_log_loss: list[float] = []
    selected_brier: list[float] = []
    delta_log_loss: list[float] = []
    delta_brier: list[float] = []
    for _ in range(replicates):
        sampled = generator.integers(0, len(unique_games), size=len(unique_games))
        denominator = float(counts[sampled].sum())
        selected_loss = float(grouped["selected_log_loss"][sampled].sum() / denominator)
        logistic_loss = float(grouped["logistic_log_loss"][sampled].sum() / denominator)
        selected_brier_value = float(
            grouped["selected_brier"][sampled].sum() / denominator
        )
        logistic_brier_value = float(
            grouped["logistic_brier"][sampled].sum() / denominator
        )
        selected_log_loss.append(selected_loss)
        selected_brier.append(selected_brier_value)
        delta_log_loss.append(selected_loss - logistic_loss)
        delta_brier.append(selected_brier_value - logistic_brier_value)

    def interval(values: list[float]) -> dict[str, float]:
        lower, upper = np.percentile(values, [2.5, 97.5])
        return {"lower": float(lower), "upper": float(upper)}

    return {
        "selected_log_loss": interval(selected_log_loss),
        "selected_brier_score": interval(selected_brier),
        "selected_minus_logistic_log_loss": interval(delta_log_loss),
        "selected_minus_logistic_brier_score": interval(delta_brier),
    }

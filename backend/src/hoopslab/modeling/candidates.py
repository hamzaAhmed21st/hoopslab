"""Small, explicit candidate families and leakage-safe preprocessing pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from hoopslab.modeling.protocol import (
    BOOLEAN_FIELD,
    CATEGORICAL_FIELDS,
    NUMERIC_FIELDS,
    SEED,
)

Family = Literal["logistic", "hgb"]


@dataclass(frozen=True)
class CandidateConfig:
    """One bounded, stable candidate configuration."""

    identifier: str
    family: Family
    learning_rate: float | None = None
    max_leaf_nodes: int | None = None
    c: float | None = None

    @property
    def complexity_rank(self) -> int:
        """Prefer simpler stable candidates only after probability metrics tie."""
        if self.family == "logistic":
            assert self.c is not None
            return {0.1: 0, 1.0: 1, 10.0: 2}[self.c]
        assert self.max_leaf_nodes is not None and self.learning_rate is not None
        return (self.max_leaf_nodes - 15) * 10 + int(self.learning_rate * 100)


LOGISTIC_CANDIDATES = tuple(
    CandidateConfig(identifier=f"logistic-c{c:g}", family="logistic", c=c)
    for c in (0.1, 1.0, 10.0)
)
HGB_CANDIDATES = tuple(
    CandidateConfig(
        identifier=f"hgb-lr{learning_rate:.2f}-leaves{max_leaf_nodes}",
        family="hgb",
        learning_rate=learning_rate,
        max_leaf_nodes=max_leaf_nodes,
    )
    for learning_rate in (0.05, 0.10)
    for max_leaf_nodes in (15, 31)
)
ALL_CANDIDATES = LOGISTIC_CANDIDATES + HGB_CANDIDATES


def _logistic_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", StandardScaler(), list(NUMERIC_FIELDS)),
            ("home", "passthrough", [BOOLEAN_FIELD]),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                list(CATEGORICAL_FIELDS),
            ),
        ],
        verbose_feature_names_out=False,
    )


def _hgb_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", list(NUMERIC_FIELDS)),
            ("home", "passthrough", [BOOLEAN_FIELD]),
            (
                "categorical",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=np.nan,
                    encoded_missing_value=np.nan,
                ),
                list(CATEGORICAL_FIELDS),
            ),
        ],
        verbose_feature_names_out=False,
    )


def build_candidate(config: CandidateConfig) -> Pipeline:
    """Build an unfitted pipeline; every learned transform fits within ``fit``."""
    if config.family == "logistic":
        if config.c is None:
            raise ValueError("logistic candidate requires C")
        return Pipeline(
            [
                ("preprocess", _logistic_preprocessor()),
                (
                    "classifier",
                    LogisticRegression(
                        C=config.c,
                        l1_ratio=0.0,
                        solver="lbfgs",
                        max_iter=300,
                        random_state=SEED,
                    ),
                ),
            ]
        )
    if config.family == "hgb":
        if config.learning_rate is None or config.max_leaf_nodes is None:
            raise ValueError("HGB candidate requires learning rate and leaf count")
        categorical_mask = [False] * (len(NUMERIC_FIELDS) + 1) + [True] * len(
            CATEGORICAL_FIELDS
        )
        return Pipeline(
            [
                ("preprocess", _hgb_preprocessor()),
                (
                    "classifier",
                    HistGradientBoostingClassifier(
                        loss="log_loss",
                        learning_rate=config.learning_rate,
                        max_leaf_nodes=config.max_leaf_nodes,
                        max_iter=300,
                        min_samples_leaf=100,
                        l2_regularization=1.0,
                        early_stopping=False,
                        categorical_features=categorical_mask,
                        random_state=SEED,
                    ),
                ),
            ]
        )
    raise ValueError(f"unsupported candidate family: {config.family}")

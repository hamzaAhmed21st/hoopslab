"""HTTP contract tests for health, metadata, and strict prediction routes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hoopslab.api.app import create_app
from hoopslab.api.dependencies import get_session
from hoopslab.api.runtime import PredictionRuntime
from hoopslab.features import MODEL_INPUT_FIELDS


class FakeConnection:
    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _statement: object) -> None:
        return None


class FakeEngine:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.disposed = False

    def connect(self) -> FakeConnection:
        if not self.available:
            raise OperationalError("SELECT 1", {}, Exception("private database"))
        return FakeConnection()

    def dispose(self) -> None:
        self.disposed = True


class FakeRuntime:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.initialize_calls = 0
        self.batches: list[list[dict[str, object]]] = []
        self._diagnostic: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.ready

    @property
    def diagnostic(self) -> str | None:
        return self._diagnostic

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "model_version": "abcdef123456",
            "family": "hist_gradient_boosting",
            "calibration": "sigmoid",
            "feature_names": list(MODEL_INPUT_FIELDS),
            "training_seasons": [2018, 2019, 2020, 2021],
            "calibration_season": 2022,
            "selection_season": 2022,
            "heldout_season": 2023,
            "held_out_metrics": {
                "log_loss": 0.63,
                "brier_score": 0.22,
                "roc_auc": 0.66,
                "ece": 0.01,
            },
            "limitations": ["Contextual probability only."],
            "selected_variant": "private-internal-id",
        }

    def initialize(self) -> None:
        self.initialize_calls += 1

    def mark_unavailable(self, error: Exception) -> None:
        self.ready = False
        self._diagnostic = str(error)

    def predict(self, rows: Sequence[Mapping[str, object]]) -> list[float]:
        copied = [dict(row) for row in rows]
        self.batches.append(copied)
        return [
            0.25 + float(cast(Any, row["shot_distance_ft"])) / 100.0 for row in rows
        ]


def _shot(**overrides: object) -> dict[str, object]:
    shot: dict[str, object] = {
        "coordinate_x_ft": 0.0,
        "coordinate_y_ft": 25.0,
        "shot_distance_ft": 25,
        "period": 1,
        "seconds_remaining": 500,
        "shooter_is_home": True,
        "action_type": "Unseen but allowed action",
        "shot_type": "3PT Field Goal",
        "shot_zone_basic": "Above the Break 3",
        "shot_zone_area": "Center(C)",
        "shot_zone_range": "24+ ft.",
        "season_type": "rg",
    }
    shot.update(overrides)
    return shot


def _client(
    runtime: FakeRuntime, engine: FakeEngine | None = None
) -> tuple[TestClient, FakeEngine]:
    selected_engine = engine or FakeEngine()
    application = create_app(
        runtime=cast(PredictionRuntime, runtime),
        engine=cast(Engine, selected_engine),
    )
    return TestClient(application), selected_engine


def test_health_metadata_and_openapi_are_safe_and_complete() -> None:
    runtime = FakeRuntime()
    client, engine = _client(runtime)
    with client:
        assert client.get("/health/live").json() == {"status": "live"}
        assert client.get("/health/ready").json() == {"status": "ready"}
        response = client.get("/api/v1/model")
        openapi = client.get("/openapi.json").json()

    assert runtime.initialize_calls == 1
    assert engine.disposed
    assert response.status_code == 200
    assert "selected_variant" not in response.json()
    assert "artifact" not in response.text
    expected_paths = {
        "/health/live",
        "/health/ready",
        "/api/v1/model",
        "/api/v1/predictions",
        "/api/v1/predictions/batch",
        "/api/v1/players",
        "/api/v1/players/{player_id}/shot-quality",
        "/api/v1/players/{player_id}/shots",
    }
    assert set(openapi["paths"]) == expected_paths


def test_live_survives_unavailable_model_and_ready_hides_database_error() -> None:
    runtime = FakeRuntime(ready=False)
    client, _ = _client(runtime, FakeEngine(available=False))
    with client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        model = client.get("/api/v1/model")
        prediction = client.post("/api/v1/predictions", json=_shot())
        analytics = client.get("/api/v1/players/1/shot-quality")

    assert ready.status_code == 503
    assert ready.json() == {"detail": "service not ready"}
    assert model.json() == {"detail": "model unavailable"}
    assert prediction.json() == {"detail": "model unavailable"}
    assert analytics.json() == {"detail": "model unavailable"}
    assert "private" not in ready.text


def test_ready_requires_database_even_when_model_is_loaded() -> None:
    client, _ = _client(FakeRuntime(), FakeEngine(available=False))
    with client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "service not ready"}


def test_analytics_database_failure_is_generic() -> None:
    client, _ = _client(FakeRuntime())

    class BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("private statement", {}, Exception("private URL"))

    def broken_session() -> Iterator[Session]:
        yield cast(Session, BrokenSession())

    cast(Any, client.app).dependency_overrides[get_session] = broken_session
    with client:
        response = client.get("/api/v1/players")

    assert response.status_code == 503
    assert response.json() == {"detail": "analytics unavailable"}
    assert "private" not in response.text


def test_single_prediction_derives_angle_and_rejects_leakage_fields() -> None:
    runtime = FakeRuntime()
    client, _ = _client(runtime)
    with client:
        response = client.post("/api/v1/predictions", json=_shot())
        leakage = client.post("/api/v1/predictions", json=_shot(player_id=1, made=True))

    assert response.status_code == 200
    assert response.json() == {
        "make_probability": 0.5,
        "model_version": "abcdef123456",
    }
    assert list(runtime.batches[0][0]) == list(MODEL_INPUT_FIELDS)
    assert runtime.batches[0][0]["shot_angle_degrees"] == pytest.approx(0.0)
    assert leakage.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"coordinate_x_ft": 26.0},
        {"coordinate_y_ft": "25"},
        {"shot_distance_ft": -1},
        {"period": 5, "seconds_remaining": 301},
        {"shooter_is_home": 1},
        {"shot_type": "Layup"},
        {"season_type": "pre"},
        {"action_type": " "},
    ],
)
def test_prediction_domain_validation_is_strict(overrides: dict[str, object]) -> None:
    client, _ = _client(FakeRuntime())
    with client:
        response = client.post("/api/v1/predictions", json=_shot(**overrides))
    assert response.status_code == 422


def test_batch_is_bounded_ordered_and_vectorized_once() -> None:
    runtime = FakeRuntime()
    client, _ = _client(runtime)
    with client:
        response = client.post(
            "/api/v1/predictions/batch",
            json={"shots": [_shot(shot_distance_ft=5), _shot(shot_distance_ft=25)]},
        )
        empty = client.post("/api/v1/predictions/batch", json={"shots": []})
        oversized = client.post(
            "/api/v1/predictions/batch", json={"shots": [_shot()] * 501}
        )

    assert response.status_code == 200
    assert [
        item["make_probability"] for item in response.json()["predictions"]
    ] == pytest.approx([0.30, 0.50])
    assert len(runtime.batches) == 1
    assert len(runtime.batches[0]) == 2
    assert empty.status_code == 422
    assert oversized.status_code == 422

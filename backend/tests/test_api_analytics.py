"""Real PostgreSQL API tests for bounded player analytics query behavior."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import cast

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine
from sqlalchemy.orm import Session

from hoopslab.api import analytics
from hoopslab.api.app import create_app
from hoopslab.api.dependencies import get_session
from hoopslab.api.runtime import PredictionRuntime
from hoopslab.features import MODEL_INPUT_FIELDS
from test_api import FakeEngine, FakeRuntime


@pytest.fixture
def analytics_connection() -> Iterator[Connection]:
    database_url = os.environ.get("HOOPSLAB_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("HOOPSLAB_TEST_DATABASE_URL is not configured")
    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            sa.text(
                "INSERT INTO teams (source_team_id, name) VALUES "
                "(980001, 'API Home'), (980002, 'API Away')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO players (source_player_id, full_name) VALUES "
                "(980001, 'ZZZ API Alpha'), (980002, 'ZZZ API Beta')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO games (source_game_id, game_date, season_start, "
                "season_type, home_team_code, away_team_code) VALUES "
                "(9980001, DATE '2024-01-01', 2023, 'rg', 'API', 'TST'), "
                "(9980002, DATE '2023-11-01', 2023, 'rg', 'API', 'TST')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO game_teams (game_id, team_id, team_code, is_home) "
                "VALUES (9980001, 980001, 'API', true), "
                "(9980001, 980002, 'TST', false), "
                "(9980002, 980001, 'API', true), "
                "(9980002, 980002, 'TST', false)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO shots (game_id, event_id, player_id, team_id, "
                "opponent_team_id, shooter_is_home, period, seconds_remaining, "
                "action_type, shot_type, shot_value, shot_zone_basic, "
                "shot_zone_area, shot_zone_range, shot_distance_ft, "
                "coordinate_x_tenths_ft, coordinate_y_tenths_ft, made) VALUES "
                "(9980001, 10, 980001, 980001, 980002, true, 1, 600, "
                "'Layup Shot', '2PT Field Goal', 2, 'Restricted Area', "
                "'Center(C)', 'Less Than 8 ft.', 5, 0, 50, true), "
                "(9980001, 20, 980001, 980001, 980002, true, 2, 300, "
                "'Jump Shot', '3PT Field Goal', 3, 'Above the Break 3', "
                "'Center(C)', '24+ ft.', 25, 0, 250, false), "
                "(9980002, 5, 980001, 980001, 980002, true, 4, 10, "
                "'Hook Shot', '2PT Field Goal', 2, 'In The Paint (Non-RA)', "
                "'Center(C)', '8-16 ft.', 10, 10, 100, false)"
            )
        )
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def _analytics_client(
    connection: Connection, runtime: FakeRuntime
) -> tuple[TestClient, FastAPI]:
    application = create_app(
        runtime=cast(PredictionRuntime, runtime),
        engine=cast(Engine, FakeEngine()),
    )

    def session_override() -> Iterator[Session]:
        session = Session(bind=connection)
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_session] = session_override
    return TestClient(application), application


def test_player_search_is_bounded_stable_and_blank_means_no_filter(
    analytics_connection: Connection,
) -> None:
    client, _ = _analytics_client(analytics_connection, FakeRuntime())
    with client:
        matched = client.get("/api/v1/players?search=zzz%20API&limit=2")
        blank = client.get("/api/v1/players?search=%20%20&limit=1")
        season = client.get(
            "/api/v1/players?search=zzz%20API&season_start=2023&limit=10"
        )
        too_many = client.get("/api/v1/players?limit=51")

    assert matched.json()["items"] == [
        {"player_id": 980001, "name": "ZZZ API Alpha"},
        {"player_id": 980002, "name": "ZZZ API Beta"},
    ]
    assert len(blank.json()["items"]) == 1
    assert season.json()["items"] == [{"player_id": 980001, "name": "ZZZ API Alpha"}]
    assert too_many.status_code == 422


def test_shot_quality_math_filters_zero_and_unknown_player(
    analytics_connection: Connection,
) -> None:
    runtime = FakeRuntime()
    client, _ = _analytics_client(analytics_connection, runtime)
    with client:
        summary = client.get(
            "/api/v1/players/980001/shot-quality?shot_type=2PT%20Field%20Goal"
        )
        zero = client.get("/api/v1/players/980002/shot-quality?season_start=2023")
        unknown = client.get("/api/v1/players/999999999/shot-quality")

    body = summary.json()
    assert summary.status_code == 200
    assert body["attempts"] == 2
    assert body["made"] == 1
    assert body["actual_fg_pct"] == pytest.approx(0.5)
    assert body["expected_makes"] == pytest.approx(0.65)
    assert body["expected_fg_pct"] == pytest.approx(0.325)
    assert body["actual_minus_expected_fg_pct"] == pytest.approx(0.175)
    assert body["actual_minus_expected_makes"] == pytest.approx(0.35)
    assert len(runtime.batches) == 1
    assert len(runtime.batches[0]) == 2
    assert zero.json()["attempts"] == 0
    assert zero.json()["actual_fg_pct"] is None
    assert zero.json()["expected_fg_pct"] is None
    assert zero.json()["expected_makes"] == 0.0
    assert unknown.status_code == 404


def test_shot_quality_cap_rejects_before_model_invocation(
    analytics_connection: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = FakeRuntime()
    client, _ = _analytics_client(analytics_connection, runtime)

    def over_cap(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise analytics.ShotPopulationTooLargeError

    monkeypatch.setattr(analytics, "summary_shots", over_cap)
    with client:
        response = client.get("/api/v1/players/980001/shot-quality")

    assert response.status_code == 422
    assert response.json() == {"detail": "shot selection exceeds 10000 attempts"}
    assert runtime.batches == []


def test_shot_page_is_filtered_ordered_paginated_and_vectorized(
    analytics_connection: Connection,
) -> None:
    runtime = FakeRuntime()
    client, _ = _analytics_client(analytics_connection, runtime)
    with client:
        response = client.get("/api/v1/players/980001/shots?offset=0&limit=2")
        filtered = client.get(
            "/api/v1/players/980001/shots?shot_type=2PT%20Field%20Goal&limit=10"
        )
        invalid = client.get("/api/v1/players/980001/shots?offset=10001")

    body = response.json()
    assert response.status_code == 200
    assert body["pagination"] == {"offset": 0, "limit": 2, "total": 3}
    assert [(item["game_id"], item["event_id"]) for item in body["items"]] == [
        (9980001, 20),
        (9980001, 10),
    ]
    assert [item["make_probability"] for item in body["items"]] == pytest.approx(
        [0.50, 0.30]
    )
    assert [item["event_id"] for item in filtered.json()["items"]] == [10, 5]
    assert [len(batch) for batch in runtime.batches] == [2, 2]
    assert invalid.status_code == 422
    assert set(runtime.batches[0][0]) == set(MODEL_INPUT_FIELDS)

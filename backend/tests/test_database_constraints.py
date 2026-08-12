"""PostgreSQL constraint integration tests."""

import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def database_connection() -> Iterator[Connection]:
    database_url = os.environ.get("HOOPSLAB_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("HOOPSLAB_TEST_DATABASE_URL is not configured")

    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def test_database_rejects_impossible_court_coordinate(
    database_connection: Connection,
) -> None:
    database_connection.execute(
        sa.text("INSERT INTO teams (source_team_id, name) VALUES (2001, 'Comets')")
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO players (source_player_id, full_name) "
            "VALUES (1001, 'Test Shooter')"
        )
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO games "
            "(source_game_id, game_date, season_start, season_type, "
            "home_team_code, away_team_code) VALUES "
            "(22300001, DATE '2023-10-24', 2023, 'rg', 'TST', 'VIS')"
        )
    )

    statement = sa.text(
        "INSERT INTO shots "
        "(game_id, event_id, player_id, team_id, period, seconds_remaining, "
        "action_type, shot_type, shot_value, shot_zone_basic, shot_zone_area, "
        "shot_zone_range, shot_distance_ft, coordinate_x_tenths_ft, "
        "coordinate_y_tenths_ft, made) VALUES "
        "(22300001, 10, 1001, 2001, 1, 605, 'Jump Shot', '3PT Field Goal', 3, "
        "'Above the Break 3', 'Center(C)', '24+ ft.', 25, 251, 248, true)"
    )
    with (
        pytest.raises(IntegrityError, match="ck_shots_coordinate_x_range"),
        database_connection.begin_nested(),
    ):
        database_connection.execute(statement)

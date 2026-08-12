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
        sa.text(
            "INSERT INTO teams (source_team_id, name) VALUES "
            "(2001, 'Comets'), (2002, 'Meteors')"
        )
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
            "(99000001, DATE '2023-10-24', 2023, 'rg', 'TST', 'VIS')"
        )
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO game_teams (game_id, team_id, team_code, is_home) VALUES "
            "(99000001, 2001, 'TST', true), (99000001, 2002, 'VIS', false)"
        )
    )

    statement = sa.text(
        "INSERT INTO shots "
        "(game_id, event_id, player_id, team_id, opponent_team_id, "
        "shooter_is_home, period, seconds_remaining, "
        "action_type, shot_type, shot_value, shot_zone_basic, shot_zone_area, "
        "shot_zone_range, shot_distance_ft, coordinate_x_tenths_ft, "
        "coordinate_y_tenths_ft, made) VALUES "
        "(99000001, 10, 1001, 2001, 2002, true, 1, 605, "
        "'Jump Shot', '3PT Field Goal', 3, "
        "'Above the Break 3', 'Center(C)', '24+ ft.', 25, 251, 248, true)"
    )
    with (
        pytest.raises(IntegrityError, match="ck_shots_coordinate_x_range"),
        database_connection.begin_nested(),
    ):
        database_connection.execute(statement)


def test_database_rejects_shooter_home_role_mismatch(
    database_connection: Connection,
) -> None:
    database_connection.execute(
        sa.text(
            "INSERT INTO teams (source_team_id, name) VALUES "
            "(2101, 'Comets'), (2102, 'Meteors')"
        )
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO players (source_player_id, full_name) "
            "VALUES (1101, 'Test Shooter')"
        )
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO games "
            "(source_game_id, game_date, season_start, season_type, "
            "home_team_code, away_team_code) VALUES "
            "(99000002, DATE '2023-10-24', 2023, 'rg', 'TST', 'VIS')"
        )
    )
    database_connection.execute(
        sa.text(
            "INSERT INTO game_teams (game_id, team_id, team_code, is_home) VALUES "
            "(99000002, 2101, 'TST', true), (99000002, 2102, 'VIS', false)"
        )
    )
    statement = sa.text(
        "INSERT INTO shots "
        "(game_id, event_id, player_id, team_id, opponent_team_id, "
        "shooter_is_home, period, seconds_remaining, action_type, shot_type, "
        "shot_value, shot_zone_basic, shot_zone_area, shot_zone_range, "
        "shot_distance_ft, coordinate_x_tenths_ft, coordinate_y_tenths_ft, made) "
        "VALUES (99000002, 10, 1101, 2101, 2102, false, 1, 605, 'Jump Shot', "
        "'3PT Field Goal', 3, 'Above the Break 3', 'Center(C)', '24+ ft.', "
        "25, 20, 248, true)"
    )

    with (
        pytest.raises(IntegrityError, match="fk_shots_shooting_game_team"),
        database_connection.begin_nested(),
    ):
        database_connection.execute(statement)

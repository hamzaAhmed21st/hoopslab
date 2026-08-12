"""Deterministic quality-report integration tests against PostgreSQL."""

import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from hoopslab.quality import generate_quality_report


@pytest.fixture
def isolated_database_connection() -> Iterator[Connection]:
    """Temporarily replace normalized rows, restoring them by rollback."""
    database_url = os.environ.get("HOOPSLAB_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("HOOPSLAB_TEST_DATABASE_URL is not configured")

    engine = sa.create_engine(database_url)
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(sa.text("DELETE FROM games"))
            yield connection
        finally:
            transaction.rollback()
    engine.dispose()


def test_quality_report_summarizes_fixture_and_marks_exclusions(
    isolated_database_connection: Connection,
) -> None:
    connection = isolated_database_connection
    connection.execute(
        sa.text(
            "INSERT INTO teams (source_team_id, name) VALUES "
            "(900000000001, 'Comets'), (900000000002, 'Meteors')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO players (source_player_id, full_name) VALUES "
            "(900000000101, 'Home Shooter'), (900000000102, 'Away Shooter')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO games "
            "(source_game_id, game_date, season_start, season_type, "
            "home_team_code, away_team_code) VALUES "
            "(9900000001, DATE '2023-10-24', 2023, 'rg', 'TST', 'VIS'), "
            "(9900000002, DATE '2024-10-22', 2024, 'rg', 'TST', 'VIS')"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO game_teams (game_id, team_id, team_code, is_home) VALUES "
            "(9900000001, 900000000001, 'TST', true), "
            "(9900000001, 900000000002, 'VIS', false), "
            "(9900000002, 900000000001, 'TST', true), "
            "(9900000002, 900000000002, 'VIS', false)"
        )
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO shots (
                game_id, event_id, player_id, team_id, opponent_team_id,
                shooter_is_home, period, seconds_remaining, action_type,
                shot_type, shot_value, shot_zone_basic, shot_zone_area,
                shot_zone_range, shot_distance_ft, coordinate_x_tenths_ft,
                coordinate_y_tenths_ft, made
            ) VALUES
                (9900000001, 1, 900000000101, 900000000001, 900000000002,
                 true, 1, 720, 'Jump Shot', '2PT Field Goal', 2, 'Mid-Range',
                 'Center(C)', '8-16 ft.', 12, -30, 120, true),
                (9900000001, 2, 900000000102, 900000000002, 900000000001,
                 false, 5, 300, 'Layup Shot', '2PT Field Goal', 2,
                 'Restricted Area', 'Center(C)', 'Less Than 8 ft.', 2, 20, 10,
                 false),
                (9900000002, 1, 900000000101, 900000000001, 900000000002,
                 true, 1, 600, 'Jump Shot', '3PT Field Goal', 3,
                 'Above the Break 3', 'Center(C)', '24+ ft.', 25, 10, 250,
                 true)
            """
        )
    )

    report = generate_quality_report(connection)

    assert report["seasons"] == [
        {
            "season_start": 2023,
            "shots": 2,
            "games": 1,
            "players": 2,
            "teams": 2,
            "made": 1,
            "missed": 1,
            "min_x": -30,
            "max_x": 20,
            "min_y": 10,
            "max_y": 120,
            "min_distance": 2,
            "max_distance": 12,
            "season_type": "rg",
            "first_game_date": "2023-10-24",
            "last_game_date": "2023-10-24",
        },
        {
            "season_start": 2024,
            "shots": 1,
            "games": 1,
            "players": 1,
            "teams": 1,
            "made": 1,
            "missed": 0,
            "min_x": 10,
            "max_x": 10,
            "min_y": 250,
            "max_y": 250,
            "min_distance": 25,
            "max_distance": 25,
            "season_type": "rg",
            "first_game_date": "2024-10-22",
            "last_game_date": "2024-10-22",
        },
    ]
    assert report["category_cardinality"] == {
        "action_type": 2,
        "shot_type": 2,
        "shot_zone_area": 1,
        "shot_zone_basic": 3,
        "shot_zone_range": 3,
    }
    assert report["integrity"] == {
        "duplicate_shot_keys": 0,
        "required_model_field_nulls": 0,
        "invalid_period_or_clock_rows": 0,
        "participant_relationship_failures": 0,
        "unresolved_games": 0,
        "unexpected_season_type_games": 0,
        "unexpected_shot_type_rows": 0,
        "blank_categorical_rows": 0,
        "excluded_model_rows": 1,
    }
    assert report["clean"] is False

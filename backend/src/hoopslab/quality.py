"""Deterministic quality checks for normalized HoopsLab data."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Connection, text


def _integer(connection: Connection, query: str) -> int:
    return int(connection.execute(text(query)).scalar_one())


def generate_quality_report(connection: Connection) -> dict[str, object]:
    """Calculate source, relationship, and model-readiness quality facts."""
    season_rows = connection.execute(
        text(
            """
            SELECT
                g.season_start,
                g.season_type,
                COUNT(*) AS shots,
                COUNT(DISTINCT s.game_id) AS games,
                COUNT(DISTINCT s.player_id) AS players,
                COUNT(DISTINCT s.team_id) AS teams,
                COUNT(*) FILTER (WHERE s.made) AS made,
                COUNT(*) FILTER (WHERE NOT s.made) AS missed,
                MIN(s.coordinate_x_tenths_ft) AS min_x,
                MAX(s.coordinate_x_tenths_ft) AS max_x,
                MIN(s.coordinate_y_tenths_ft) AS min_y,
                MAX(s.coordinate_y_tenths_ft) AS max_y,
                MIN(s.shot_distance_ft) AS min_distance,
                MAX(s.shot_distance_ft) AS max_distance,
                MIN(g.game_date) AS first_game_date,
                MAX(g.game_date) AS last_game_date
            FROM shots AS s
            JOIN games AS g ON g.source_game_id = s.game_id
            GROUP BY g.season_start, g.season_type
            ORDER BY g.season_start, g.season_type
            """
        )
    ).mappings()
    seasons = [
        {
            **{
                key: int(row[key])
                for key in (
                    "season_start",
                    "shots",
                    "games",
                    "players",
                    "teams",
                    "made",
                    "missed",
                    "min_x",
                    "max_x",
                    "min_y",
                    "max_y",
                    "min_distance",
                    "max_distance",
                )
            },
            "season_type": str(row["season_type"]),
            "first_game_date": row["first_game_date"].isoformat(),
            "last_game_date": row["last_game_date"].isoformat(),
        }
        for row in season_rows
    ]

    duplicate_keys = _integer(
        connection,
        """
        SELECT COUNT(*) FROM (
            SELECT game_id, event_id
            FROM shots
            GROUP BY game_id, event_id
            HAVING COUNT(*) > 1
        ) AS duplicates
        """,
    )
    required_model_nulls = _integer(
        connection,
        """
        SELECT COUNT(*) FROM shots
        WHERE coordinate_x_tenths_ft IS NULL
           OR coordinate_y_tenths_ft IS NULL
           OR shot_distance_ft IS NULL
           OR period IS NULL
           OR seconds_remaining IS NULL
           OR shooter_is_home IS NULL
           OR action_type IS NULL
           OR shot_type IS NULL
           OR shot_zone_basic IS NULL
           OR shot_zone_area IS NULL
           OR shot_zone_range IS NULL
           OR made IS NULL
        """,
    )
    invalid_period_or_clock = _integer(
        connection,
        """
        SELECT COUNT(*) FROM shots
        WHERE period NOT BETWEEN 1 AND 20
           OR (period <= 4 AND seconds_remaining NOT BETWEEN 0 AND 720)
           OR (period >= 5 AND seconds_remaining NOT BETWEEN 0 AND 300)
        """,
    )
    participant_failures = _integer(
        connection,
        """
        SELECT COUNT(*) FROM shots AS s
        LEFT JOIN game_teams AS shooting
          ON shooting.game_id = s.game_id AND shooting.team_id = s.team_id
        LEFT JOIN game_teams AS opponent
          ON opponent.game_id = s.game_id AND opponent.team_id = s.opponent_team_id
        WHERE shooting.team_id IS NULL
           OR opponent.team_id IS NULL
           OR shooting.is_home <> s.shooter_is_home
           OR s.team_id = s.opponent_team_id
        """,
    )
    unresolved_games = _integer(
        connection,
        """
        SELECT COUNT(*) FROM (
            SELECT
                g.source_game_id
            FROM games AS g
            LEFT JOIN game_teams AS gt ON gt.game_id = g.source_game_id
            GROUP BY g.source_game_id
            HAVING COUNT(gt.team_id) <> 2
                OR COUNT(*) FILTER (WHERE gt.is_home) <> 1
                OR COUNT(*) FILTER (WHERE NOT gt.is_home) <> 1
        ) AS invalid_games
        """,
    )
    unexpected_season_types = _integer(
        connection,
        "SELECT COUNT(*) FROM games WHERE season_type <> 'rg'",
    )
    unexpected_shot_types = _integer(
        connection,
        "SELECT COUNT(*) FROM shots WHERE shot_type NOT IN "
        "('2PT Field Goal', '3PT Field Goal')",
    )
    blank_categorical_rows = _integer(
        connection,
        """
        SELECT COUNT(*) FROM shots
        WHERE BTRIM(action_type) = ''
           OR BTRIM(shot_type) = ''
           OR BTRIM(shot_zone_basic) = ''
           OR BTRIM(shot_zone_area) = ''
           OR BTRIM(shot_zone_range) = ''
        """,
    )
    excluded_rows = (
        _integer(
            connection,
            """
        SELECT COUNT(*)
        FROM shots AS s
        JOIN games AS g ON g.source_game_id = s.game_id
        WHERE g.season_start NOT BETWEEN 2018 AND 2023
           OR g.season_type <> 'rg'
        """,
        )
        + required_model_nulls
    )

    cardinality = {
        str(row["field"]): int(row["value_count"])
        for row in connection.execute(
            text(
                """
                SELECT
                    'action_type' AS field,
                    COUNT(DISTINCT action_type) AS value_count
                FROM shots
                UNION ALL
                SELECT 'shot_type', COUNT(DISTINCT shot_type) FROM shots
                UNION ALL
                SELECT 'shot_zone_basic', COUNT(DISTINCT shot_zone_basic) FROM shots
                UNION ALL
                SELECT 'shot_zone_area', COUNT(DISTINCT shot_zone_area) FROM shots
                UNION ALL
                SELECT 'shot_zone_range', COUNT(DISTINCT shot_zone_range) FROM shots
                """
            )
        ).mappings()
    }

    integrity = {
        "duplicate_shot_keys": duplicate_keys,
        "required_model_field_nulls": required_model_nulls,
        "invalid_period_or_clock_rows": invalid_period_or_clock,
        "participant_relationship_failures": participant_failures,
        "unresolved_games": unresolved_games,
        "unexpected_season_type_games": unexpected_season_types,
        "unexpected_shot_type_rows": unexpected_shot_types,
        "blank_categorical_rows": blank_categorical_rows,
        "excluded_model_rows": excluded_rows,
    }
    return {
        "report_version": 1,
        "seasons": seasons,
        "category_cardinality": cardinality,
        "integrity": integrity,
        "clean": all(value == 0 for value in integrity.values()),
    }


def write_quality_report(report: dict[str, object], path: Path) -> None:
    """Write stable machine-readable quality evidence to an ignored path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

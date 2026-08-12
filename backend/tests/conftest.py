"""Shared synthetic fixtures for backend tests."""

from collections.abc import Callable
from typing import Any

import pytest


@pytest.fixture
def archive_row_factory() -> Callable[..., dict[str, Any]]:
    """Build a licensing-independent synthetic shotdetail row."""

    def build(**overrides: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "GAME_ID": 22300001,
            "GAME_EVENT_ID": 10,
            "PLAYER_ID": 1001,
            "PLAYER_NAME": "Test Shooter",
            "TEAM_ID": 2001,
            "TEAM_NAME": "Test Comets",
            "PERIOD": 1,
            "MINUTES_REMAINING": 10,
            "SECONDS_REMAINING": 5,
            "EVENT_TYPE": "Made Shot",
            "ACTION_TYPE": "Jump Shot",
            "SHOT_TYPE": "3PT Field Goal",
            "SHOT_ZONE_BASIC": "Above the Break 3",
            "SHOT_ZONE_AREA": "Center(C)",
            "SHOT_ZONE_RANGE": "24+ ft.",
            "SHOT_DISTANCE": 25,
            "LOC_X": -35,
            "LOC_Y": 248,
            "SHOT_ATTEMPTED_FLAG": 1,
            "SHOT_MADE_FLAG": 1,
            "GAME_DATE": 20231024,
            "HTM": "TST",
            "VTM": "VIS",
            "_season": 2023,
            "_season_type": "rg",
        }
        row.update(overrides)
        return row

    return build


@pytest.fixture
def resolved_season_rows_factory(
    archive_row_factory: Callable[..., dict[str, Any]],
) -> Callable[[int], list[dict[str, Any]]]:
    """Build three synthetic games whose stable team codes are resolvable."""

    def build(season_start: int = 2023) -> list[dict[str, Any]]:
        games = (
            (9001, season_start * 10_000 + 1024, 1, "Alpha", 2, "Beta", "AAA", "BBB"),
            (9002, season_start * 10_000 + 1025, 1, "Alpha", 3, "Gamma", "AAA", "CCC"),
            (9003, season_start * 10_000 + 1026, 2, "Beta", 3, "Gamma", "BBB", "CCC"),
        )
        rows: list[dict[str, Any]] = []
        for (
            game_id,
            game_date,
            home_id,
            home_name,
            away_id,
            away_name,
            home,
            away,
        ) in games:
            rows.extend(
                [
                    archive_row_factory(
                        GAME_ID=game_id,
                        GAME_EVENT_ID=10,
                        GAME_DATE=game_date,
                        TEAM_ID=home_id,
                        TEAM_NAME=home_name,
                        PLAYER_ID=home_id * 100,
                        PLAYER_NAME=f"{home_name} Shooter",
                        HTM=home,
                        VTM=away,
                        _season=season_start,
                    ),
                    archive_row_factory(
                        GAME_ID=game_id,
                        GAME_EVENT_ID=11,
                        GAME_DATE=game_date,
                        TEAM_ID=away_id,
                        TEAM_NAME=away_name,
                        PLAYER_ID=away_id * 100,
                        PLAYER_NAME=f"{away_name} Shooter",
                        HTM=home,
                        VTM=away,
                        _season=season_start,
                        EVENT_TYPE="Missed Shot",
                        SHOT_MADE_FLAG=0,
                    ),
                ]
            )
        return rows

    return build

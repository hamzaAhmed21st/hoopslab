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

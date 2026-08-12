"""Validated raw and normalized shot records."""

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArchiveShotRow(BaseModel):
    """Fields consumed from one NBA Data Archive shotdetail row."""

    model_config = ConfigDict(extra="ignore", strict=True)

    game_id: int = Field(alias="GAME_ID", gt=0)
    game_event_id: int = Field(alias="GAME_EVENT_ID", ge=0)
    player_id: int = Field(alias="PLAYER_ID", gt=0)
    player_name: str = Field(alias="PLAYER_NAME", min_length=1)
    team_id: int = Field(alias="TEAM_ID", gt=0)
    team_name: str = Field(alias="TEAM_NAME", min_length=1)
    period: int = Field(alias="PERIOD", ge=1, le=20)
    minutes_remaining: int = Field(alias="MINUTES_REMAINING", ge=0, le=12)
    seconds_remaining: int = Field(alias="SECONDS_REMAINING", ge=0, le=59)
    event_type: Literal["Made Shot", "Missed Shot"] = Field(alias="EVENT_TYPE")
    action_type: str = Field(alias="ACTION_TYPE", min_length=1)
    shot_type: Literal["2PT Field Goal", "3PT Field Goal"] = Field(alias="SHOT_TYPE")
    shot_zone_basic: str = Field(alias="SHOT_ZONE_BASIC", min_length=1)
    shot_zone_area: str = Field(alias="SHOT_ZONE_AREA", min_length=1)
    shot_zone_range: str = Field(alias="SHOT_ZONE_RANGE", min_length=1)
    shot_distance_ft: int = Field(alias="SHOT_DISTANCE", ge=0, le=94)
    coordinate_x_tenths_ft: int = Field(alias="LOC_X", ge=-250, le=250)
    coordinate_y_tenths_ft: int = Field(alias="LOC_Y", ge=-100, le=940)
    shot_attempted: Literal[1] = Field(alias="SHOT_ATTEMPTED_FLAG")
    shot_made: Literal[0, 1] = Field(alias="SHOT_MADE_FLAG")
    game_date: int = Field(alias="GAME_DATE", ge=19460101, le=21001231)
    home_team_code: str = Field(alias="HTM", min_length=3, max_length=3)
    away_team_code: str = Field(alias="VTM", min_length=3, max_length=3)
    season_start: int = Field(alias="_season", ge=1996, le=2100)
    season_type: Literal["rg", "po"] = Field(alias="_season_type")

    @model_validator(mode="after")
    def outcome_and_clock_are_consistent(self) -> Self:
        """Validate redundant source encodings and NBA period duration."""
        expected_made = int(self.event_type == "Made Shot")
        if self.shot_made != expected_made:
            msg = "EVENT_TYPE and SHOT_MADE_FLAG disagree"
            raise ValueError(msg)

        seconds_remaining = self.minutes_remaining * 60 + self.seconds_remaining
        max_seconds = 720 if self.period <= 4 else 300
        if seconds_remaining > max_seconds:
            msg = "clock exceeds the duration of its period"
            raise ValueError(msg)

        if self.home_team_code == self.away_team_code:
            msg = "home and away teams must differ"
            raise ValueError(msg)
        return self


class NormalizedShot(BaseModel):
    """Application contract for a normalized field-goal attempt."""

    model_config = ConfigDict(frozen=True)

    game_id: int
    event_id: int
    game_date: date
    season_start: int
    season_type: Literal["rg", "po"]
    home_team_code: str
    away_team_code: str
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    period: int
    seconds_remaining: int
    action_type: str
    shot_type: Literal["2PT Field Goal", "3PT Field Goal"]
    shot_value: Literal[2, 3]
    shot_zone_basic: str
    shot_zone_area: str
    shot_zone_range: str
    shot_distance_ft: int
    coordinate_x_tenths_ft: int
    coordinate_y_tenths_ft: int
    made: bool


def normalize_shot(row: ArchiveShotRow) -> NormalizedShot:
    """Convert a validated archive row into the application contract."""
    game_date = datetime.strptime(str(row.game_date), "%Y%m%d").date()
    return NormalizedShot(
        game_id=row.game_id,
        event_id=row.game_event_id,
        game_date=game_date,
        season_start=row.season_start,
        season_type=row.season_type,
        home_team_code=row.home_team_code,
        away_team_code=row.away_team_code,
        player_id=row.player_id,
        player_name=row.player_name,
        team_id=row.team_id,
        team_name=row.team_name,
        period=row.period,
        seconds_remaining=row.minutes_remaining * 60 + row.seconds_remaining,
        action_type=row.action_type,
        shot_type=row.shot_type,
        shot_value=2 if row.shot_type == "2PT Field Goal" else 3,
        shot_zone_basic=row.shot_zone_basic,
        shot_zone_area=row.shot_zone_area,
        shot_zone_range=row.shot_zone_range,
        shot_distance_ft=row.shot_distance_ft,
        coordinate_x_tenths_ft=row.coordinate_x_tenths_ft,
        coordinate_y_tenths_ft=row.coordinate_y_tenths_ft,
        made=bool(row.shot_made),
    )

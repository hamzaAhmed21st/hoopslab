"""Strict public request and response schemas."""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Category128 = Annotated[str, Field(min_length=1, max_length=128)]
Category64 = Annotated[str, Field(min_length=1, max_length=64)]
Category32 = Annotated[str, Field(min_length=1, max_length=32)]
ShotType = Literal["2PT Field Goal", "3PT Field Goal"]
SeasonType = Literal["rg", "po"]


class StrictSchema(BaseModel):
    """Reject coercion and unexpected public fields."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class PredictionInput(StrictSchema):
    """Twelve source/context fields; shot angle is derived server-side."""

    coordinate_x_ft: Annotated[float, Field(ge=-25, le=25, allow_inf_nan=False)]
    coordinate_y_ft: Annotated[float, Field(ge=-10, le=94, allow_inf_nan=False)]
    shot_distance_ft: Annotated[int, Field(ge=0, le=94)]
    period: Annotated[int, Field(ge=1, le=20)]
    seconds_remaining: Annotated[int, Field(ge=0, le=720)]
    shooter_is_home: bool
    action_type: Category128
    shot_type: ShotType
    shot_zone_basic: Category64
    shot_zone_area: Category64
    shot_zone_range: Category32
    season_type: SeasonType

    @model_validator(mode="after")
    def overtime_clock_is_five_minutes(self) -> Self:
        """Match the normalized database clock constraint."""
        if self.period >= 5 and self.seconds_remaining > 300:
            raise ValueError("overtime seconds_remaining must be at most 300")
        return self

    def model_record(self) -> dict[str, object]:
        """Derive the thirteenth feature and preserve locked model order."""
        return {
            "coordinate_x_ft": self.coordinate_x_ft,
            "coordinate_y_ft": self.coordinate_y_ft,
            "shot_distance_ft": self.shot_distance_ft,
            "shot_angle_degrees": math.degrees(
                math.atan2(self.coordinate_x_ft, self.coordinate_y_ft)
            ),
            "period": self.period,
            "seconds_remaining": self.seconds_remaining,
            "shooter_is_home": self.shooter_is_home,
            "action_type": self.action_type,
            "shot_type": self.shot_type,
            "shot_zone_basic": self.shot_zone_basic,
            "shot_zone_area": self.shot_zone_area,
            "shot_zone_range": self.shot_zone_range,
            "season_type": self.season_type,
        }


class PredictionResponse(StrictSchema):
    """One contextual make probability."""

    make_probability: Annotated[float, Field(ge=0, le=1)]
    model_version: str


class BatchPredictionRequest(StrictSchema):
    """A bounded vectorized prediction request."""

    shots: Annotated[list[PredictionInput], Field(min_length=1, max_length=500)]


class BatchPredictionItem(StrictSchema):
    """One stable-order probability within a batch response."""

    make_probability: Annotated[float, Field(ge=0, le=1)]


class BatchPredictionResponse(StrictSchema):
    """Stable-order batch prediction result."""

    model_version: str
    predictions: list[BatchPredictionItem]


class MetricsResponse(StrictSchema):
    """Public held-out metrics for the locked selected model."""

    log_loss: float
    brier_score: float
    roc_auc: float
    ece: float


class ModelMetadataResponse(StrictSchema):
    """Safe model identity and evaluation metadata."""

    model_version: str
    family: Literal["hist_gradient_boosting"]
    calibration: Literal["sigmoid"]
    feature_names: list[str]
    training_seasons: list[int]
    calibration_season: Literal[2022]
    selection_season: Literal[2022]
    heldout_season: Literal[2023]
    held_out_metrics: MetricsResponse
    limitations: list[str]


class PlayerResponse(StrictSchema):
    """Safe player identity used by dashboard selectors."""

    player_id: int
    name: str


class PlayerListResponse(StrictSchema):
    """Bounded player search result."""

    items: list[PlayerResponse]


class ShotFiltersResponse(StrictSchema):
    """Typed echo of the filters applied to a shot population."""

    season_start: int | None
    season_type: SeasonType | None
    shot_type: ShotType | None
    shot_zone_basic: str | None
    shooter_is_home: bool | None


class ShotQualityResponse(StrictSchema):
    """Actual versus contextual expected shooting summary."""

    player: PlayerResponse
    filters: ShotFiltersResponse
    attempts: int
    made: int
    actual_fg_pct: float | None
    expected_fg_pct: float | None
    actual_minus_expected_fg_pct: float | None
    expected_makes: float
    actual_minus_expected_makes: float
    model_version: str


class ShotResponse(StrictSchema):
    """One dashboard-ready shot with a locked-model probability."""

    game_id: int
    event_id: int
    game_date: date
    season_start: int
    season_type: SeasonType
    coordinate_x_ft: float
    coordinate_y_ft: float
    made: bool
    make_probability: Annotated[float, Field(ge=0, le=1)]
    shot_distance_ft: int
    action_type: str
    shot_type: ShotType
    shot_zone_basic: str
    shot_zone_area: str
    shot_zone_range: str
    shooter_is_home: bool
    period: int
    seconds_remaining: int


class PaginationResponse(StrictSchema):
    """Explicit bounded offset pagination metadata."""

    offset: int
    limit: int
    total: int


class PlayerShotsResponse(StrictSchema):
    """A deterministic page of model-scored player shots."""

    player: PlayerResponse
    filters: ShotFiltersResponse
    model_version: str
    pagination: PaginationResponse
    items: list[ShotResponse]

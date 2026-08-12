"""Versioned prediction and player analytics routes."""

from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from hoopslab.api import analytics
from hoopslab.api.analytics import ShotFilters
from hoopslab.api.dependencies import RuntimeDependency, SessionDependency
from hoopslab.api.runtime import ModelRuntimeError
from hoopslab.api.schemas import (
    BatchPredictionItem,
    BatchPredictionRequest,
    BatchPredictionResponse,
    ModelMetadataResponse,
    PaginationResponse,
    PlayerListResponse,
    PlayerResponse,
    PlayerShotsResponse,
    PredictionInput,
    PredictionResponse,
    ShotFiltersResponse,
    ShotQualityResponse,
    ShotResponse,
    ShotType,
)

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1")


@health_router.get("/health/live")
def live() -> dict[str, str]:
    """Report process liveness without checking dependencies."""
    return {"status": "live"}


@health_router.get("/health/ready")
def ready(request: Request) -> dict[str, str]:
    """Require both the locked model and a live PostgreSQL connection."""
    runtime = request.app.state.model_runtime
    if not runtime.is_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service not ready",
        )
    try:
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="service not ready",
        ) from error
    return {"status": "ready"}


@api_router.get("/model", response_model=ModelMetadataResponse, tags=["model"])
def model_metadata(runtime: RuntimeDependency) -> dict[str, Any]:
    """Return only validated, intentionally public model metadata."""
    metadata = runtime.metadata
    metadata.pop("selected_variant", None)
    return metadata


@api_router.post(
    "/predictions", response_model=PredictionResponse, tags=["predictions"]
)
def predict_one(
    request: PredictionInput, runtime: RuntimeDependency
) -> PredictionResponse:
    """Score one strictly validated shot context."""
    try:
        probability = runtime.predict([request.model_record()])[0]
    except ModelRuntimeError as error:
        raise _model_unavailable() from error
    return PredictionResponse(
        make_probability=probability,
        model_version=str(runtime.metadata["model_version"]),
    )


@api_router.post(
    "/predictions/batch",
    response_model=BatchPredictionResponse,
    tags=["predictions"],
)
def predict_batch(
    request: BatchPredictionRequest, runtime: RuntimeDependency
) -> BatchPredictionResponse:
    """Score 1-500 shots in exactly one vectorized runtime invocation."""
    try:
        probabilities = runtime.predict([shot.model_record() for shot in request.shots])
    except ModelRuntimeError as error:
        raise _model_unavailable() from error
    model_version = str(runtime.metadata["model_version"])
    return BatchPredictionResponse(
        model_version=model_version,
        predictions=[
            BatchPredictionItem(make_probability=probability)
            for probability in probabilities
        ],
    )


@api_router.get("/players", response_model=PlayerListResponse, tags=["players"])
def players(
    session: SessionDependency,
    search: Annotated[str | None, Query(max_length=128)] = None,
    season_start: Annotated[int | None, Query(ge=1996, le=2100)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PlayerListResponse:
    """Search players; an empty or whitespace-only search means no name filter."""
    try:
        items = analytics.find_players(
            session, search=search, season_start=season_start, limit=limit
        )
    except SQLAlchemyError as error:
        raise _database_unavailable() from error
    return PlayerListResponse(
        items=[PlayerResponse.model_validate(item) for item in items]
    )


def _filters(
    season_start: int | None,
    season_type: str | None,
    shot_type: str | None,
    shot_zone_basic: str | None,
    shooter_is_home: bool | None,
) -> ShotFilters:
    return ShotFilters(
        season_start=season_start,
        season_type=season_type,
        shot_type=shot_type,
        shot_zone_basic=shot_zone_basic,
        shooter_is_home=shooter_is_home,
    )


@api_router.get(
    "/players/{player_id}/shot-quality",
    response_model=ShotQualityResponse,
    tags=["players"],
)
def player_shot_quality(
    player_id: int,
    session: SessionDependency,
    runtime: RuntimeDependency,
    season_start: Annotated[int | None, Query(ge=1996, le=2100)] = None,
    season_type: Annotated[str | None, Query(pattern="^(rg|po)$")] = None,
    shot_type: Annotated[ShotType | None, Query()] = None,
    shot_zone_basic: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    shooter_is_home: Annotated[bool | None, Query()] = None,
) -> ShotQualityResponse:
    """Summarize actual versus locked-model expected results for up to 10k shots."""
    filters = _filters(
        season_start,
        season_type,
        shot_type,
        shot_zone_basic,
        shooter_is_home,
    )
    try:
        player = analytics.get_player(session, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="player not found"
            )
        shots = analytics.summary_shots(session, player_id, filters)
    except analytics.ShotPopulationTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="shot selection exceeds 10000 attempts",
        ) from error
    except SQLAlchemyError as error:
        raise _database_unavailable() from error

    try:
        probabilities = (
            runtime.predict([analytics.model_record(shot) for shot in shots])
            if shots
            else []
        )
    except ModelRuntimeError as error:
        raise _model_unavailable() from error
    attempts = len(shots)
    made = sum(bool(shot["made"]) for shot in shots)
    expected_makes = float(np.sum(probabilities))
    actual_fg_pct = made / attempts if attempts else None
    expected_fg_pct = expected_makes / attempts if attempts else None
    actual_minus_expected_fg_pct = (
        actual_fg_pct - expected_fg_pct
        if actual_fg_pct is not None and expected_fg_pct is not None
        else None
    )
    return ShotQualityResponse(
        player=PlayerResponse.model_validate(player),
        filters=_filter_response(filters),
        attempts=attempts,
        made=made,
        actual_fg_pct=actual_fg_pct,
        expected_fg_pct=expected_fg_pct,
        actual_minus_expected_fg_pct=actual_minus_expected_fg_pct,
        expected_makes=expected_makes,
        actual_minus_expected_makes=made - expected_makes,
        model_version=str(runtime.metadata["model_version"]),
    )


@api_router.get(
    "/players/{player_id}/shots",
    response_model=PlayerShotsResponse,
    tags=["players"],
)
def player_shots(
    player_id: int,
    session: SessionDependency,
    runtime: RuntimeDependency,
    season_start: Annotated[int | None, Query(ge=1996, le=2100)] = None,
    season_type: Annotated[str | None, Query(pattern="^(rg|po)$")] = None,
    shot_type: Annotated[ShotType | None, Query()] = None,
    shot_zone_basic: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    shooter_is_home: Annotated[bool | None, Query()] = None,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
) -> PlayerShotsResponse:
    """Return a deterministic newest-first, model-scored shot page."""
    filters = _filters(
        season_start,
        season_type,
        shot_type,
        shot_zone_basic,
        shooter_is_home,
    )
    try:
        player = analytics.get_player(session, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="player not found"
            )
        total = analytics.count_shots(session, player_id, filters)
        shots = analytics.shot_page(
            session, player_id, filters, offset=offset, limit=limit
        )
    except SQLAlchemyError as error:
        raise _database_unavailable() from error

    try:
        probabilities = (
            runtime.predict([analytics.model_record(shot) for shot in shots])
            if shots
            else []
        )
    except ModelRuntimeError as error:
        raise _model_unavailable() from error
    items = [
        ShotResponse.model_validate(
            {
                **{
                    key: value
                    for key, value in shot.items()
                    if key != "shot_angle_degrees"
                },
                "make_probability": probability,
            }
        )
        for shot, probability in zip(shots, probabilities, strict=True)
    ]
    return PlayerShotsResponse(
        player=PlayerResponse.model_validate(player),
        filters=_filter_response(filters),
        model_version=str(runtime.metadata["model_version"]),
        pagination=PaginationResponse(offset=offset, limit=limit, total=total),
        items=items,
    )


def _model_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="model unavailable",
    )


def _database_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="analytics unavailable",
    )


def _filter_response(filters: ShotFilters) -> ShotFiltersResponse:
    return ShotFiltersResponse.model_validate(filters.as_dict())

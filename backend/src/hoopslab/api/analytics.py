"""Bounded, read-only SQLAlchemy queries for player shot analytics."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, TypedDict, cast

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session

from hoopslab.db.models import Game, Player, Shot

MAX_SUMMARY_ATTEMPTS = 10_000


class PlayerRecord(TypedDict):
    """Typed result of the safe player identity query."""

    player_id: int
    name: str


class ShotRecord(TypedDict):
    """Typed normalized model/dashboard row selected from PostgreSQL."""

    game_id: int
    event_id: int
    game_date: date
    season_start: int
    season_type: str
    coordinate_x_ft: float
    coordinate_y_ft: float
    shot_distance_ft: int
    shot_angle_degrees: float
    period: int
    seconds_remaining: int
    shooter_is_home: bool
    action_type: str
    shot_type: str
    shot_zone_basic: str
    shot_zone_area: str
    shot_zone_range: str
    made: bool


class ModelShotRecord(TypedDict):
    """Only the locked model fields plus outcome for summary aggregation."""

    coordinate_x_ft: float
    coordinate_y_ft: float
    shot_distance_ft: int
    shot_angle_degrees: float
    period: int
    seconds_remaining: int
    shooter_is_home: bool
    action_type: str
    shot_type: str
    shot_zone_basic: str
    shot_zone_area: str
    shot_zone_range: str
    season_type: str
    made: bool


@dataclass(frozen=True)
class ShotFilters:
    """The intentionally small shared analytics filter set."""

    season_start: int | None = None
    season_type: str | None = None
    shot_type: str | None = None
    shot_zone_basic: str | None = None
    shooter_is_home: bool | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "season_start": self.season_start,
            "season_type": self.season_type,
            "shot_type": self.shot_type,
            "shot_zone_basic": self.shot_zone_basic,
            "shooter_is_home": self.shooter_is_home,
        }


class ShotPopulationTooLargeError(RuntimeError):
    """Raised before scoring an analytics population above the hard cap."""


def find_players(
    session: Session,
    *,
    search: str | None,
    season_start: int | None,
    limit: int,
) -> list[PlayerRecord]:
    """Return a stable, bounded player search without loading shot history."""
    statement = select(Player.source_player_id, Player.full_name)
    normalized_search = search.strip() if search is not None else ""
    if normalized_search:
        statement = statement.where(
            Player.full_name.icontains(normalized_search, autoescape=True)
        )
    if season_start is not None:
        season_shot = (
            select(1)
            .select_from(Shot)
            .join(Game, Game.source_game_id == Shot.game_id)
            .where(
                Shot.player_id == Player.source_player_id,
                Game.season_start == season_start,
            )
        )
        statement = statement.where(exists(season_shot))
    statement = statement.order_by(
        func.lower(Player.full_name), Player.source_player_id
    ).limit(limit)
    return [
        {"player_id": int(row.source_player_id), "name": str(row.full_name)}
        for row in session.execute(statement)
    ]


def get_player(session: Session, player_id: int) -> PlayerRecord | None:
    """Look up identity separately so players with zero matching shots still exist."""
    row = session.execute(
        select(Player.source_player_id, Player.full_name).where(
            Player.source_player_id == player_id
        )
    ).one_or_none()
    if row is None:
        return None
    return {"player_id": int(row.source_player_id), "name": str(row.full_name)}


def _filter_conditions(player_id: int, filters: ShotFilters) -> list[Any]:
    conditions: list[Any] = [Shot.player_id == player_id]
    if filters.season_start is not None:
        conditions.append(Game.season_start == filters.season_start)
    if filters.season_type is not None:
        conditions.append(Game.season_type == filters.season_type)
    if filters.shot_type is not None:
        conditions.append(Shot.shot_type == filters.shot_type)
    if filters.shot_zone_basic is not None:
        conditions.append(Shot.shot_zone_basic == filters.shot_zone_basic)
    if filters.shooter_is_home is not None:
        conditions.append(Shot.shooter_is_home == filters.shooter_is_home)
    return conditions


def _shot_columns() -> tuple[Any, ...]:
    return (
        Shot.game_id,
        Shot.event_id,
        Game.game_date,
        Game.season_start,
        Game.season_type,
        Shot.coordinate_x_tenths_ft,
        Shot.coordinate_y_tenths_ft,
        Shot.shot_distance_ft,
        Shot.period,
        Shot.seconds_remaining,
        Shot.shooter_is_home,
        Shot.action_type,
        Shot.shot_type,
        Shot.shot_zone_basic,
        Shot.shot_zone_area,
        Shot.shot_zone_range,
        Shot.made,
    )


def _summary_columns() -> tuple[Any, ...]:
    return (
        Shot.coordinate_x_tenths_ft,
        Shot.coordinate_y_tenths_ft,
        Shot.shot_distance_ft,
        Shot.period,
        Shot.seconds_remaining,
        Shot.shooter_is_home,
        Shot.action_type,
        Shot.shot_type,
        Shot.shot_zone_basic,
        Shot.shot_zone_area,
        Shot.shot_zone_range,
        Game.season_type,
        Shot.made,
    )


def _base_shot_statement(player_id: int, filters: ShotFilters) -> Select[Any]:
    return (
        select(*_shot_columns())
        .select_from(Shot)
        .join(Game, Game.source_game_id == Shot.game_id)
        .where(*_filter_conditions(player_id, filters))
    )


def summary_shots(
    session: Session, player_id: int, filters: ShotFilters
) -> list[ModelShotRecord]:
    """Fetch at most cap-plus-one rows, failing before any model invocation."""
    statement = (
        select(*_summary_columns())
        .select_from(Shot)
        .join(Game, Game.source_game_id == Shot.game_id)
        .where(*_filter_conditions(player_id, filters))
        .order_by(Game.game_date, Shot.game_id, Shot.event_id)
        .limit(MAX_SUMMARY_ATTEMPTS + 1)
    )
    rows = session.execute(statement).mappings().all()
    if len(rows) > MAX_SUMMARY_ATTEMPTS:
        raise ShotPopulationTooLargeError
    return [_normalize_model_shot(cast(Mapping[str, Any], row)) for row in rows]


def count_shots(session: Session, player_id: int, filters: ShotFilters) -> int:
    """Count the filtered population without materializing it."""
    statement = (
        select(func.count())
        .select_from(Shot)
        .join(Game, Game.source_game_id == Shot.game_id)
        .where(*_filter_conditions(player_id, filters))
    )
    return int(session.scalar(statement) or 0)


def shot_page(
    session: Session,
    player_id: int,
    filters: ShotFilters,
    *,
    offset: int,
    limit: int,
) -> list[ShotRecord]:
    """Fetch one deterministic newest-first dashboard page."""
    rows = (
        session.execute(
            _base_shot_statement(player_id, filters)
            .order_by(Game.game_date.desc(), Shot.game_id.desc(), Shot.event_id.desc())
            .offset(offset)
            .limit(limit)
        )
        .mappings()
        .all()
    )
    return [_normalize_shot(cast(Mapping[str, Any], row)) for row in rows]


def _normalize_shot(row: Mapping[str, Any]) -> ShotRecord:
    coordinate_x_ft = float(row["coordinate_x_tenths_ft"]) / 10.0
    coordinate_y_ft = float(row["coordinate_y_tenths_ft"]) / 10.0
    return {
        "game_id": int(row["game_id"]),
        "event_id": int(row["event_id"]),
        "game_date": cast(date, row["game_date"]),
        "season_start": int(row["season_start"]),
        "season_type": str(row["season_type"]),
        "coordinate_x_ft": coordinate_x_ft,
        "coordinate_y_ft": coordinate_y_ft,
        "shot_distance_ft": int(row["shot_distance_ft"]),
        "shot_angle_degrees": math.degrees(
            math.atan2(coordinate_x_ft, coordinate_y_ft)
        ),
        "period": int(row["period"]),
        "seconds_remaining": int(row["seconds_remaining"]),
        "shooter_is_home": bool(row["shooter_is_home"]),
        "action_type": str(row["action_type"]),
        "shot_type": str(row["shot_type"]),
        "shot_zone_basic": str(row["shot_zone_basic"]),
        "shot_zone_area": str(row["shot_zone_area"]),
        "shot_zone_range": str(row["shot_zone_range"]),
        "made": bool(row["made"]),
    }


def _normalize_model_shot(row: Mapping[str, Any]) -> ModelShotRecord:
    coordinate_x_ft = float(row["coordinate_x_tenths_ft"]) / 10.0
    coordinate_y_ft = float(row["coordinate_y_tenths_ft"]) / 10.0
    return {
        "coordinate_x_ft": coordinate_x_ft,
        "coordinate_y_ft": coordinate_y_ft,
        "shot_distance_ft": int(row["shot_distance_ft"]),
        "shot_angle_degrees": math.degrees(
            math.atan2(coordinate_x_ft, coordinate_y_ft)
        ),
        "period": int(row["period"]),
        "seconds_remaining": int(row["seconds_remaining"]),
        "shooter_is_home": bool(row["shooter_is_home"]),
        "action_type": str(row["action_type"]),
        "shot_type": str(row["shot_type"]),
        "shot_zone_basic": str(row["shot_zone_basic"]),
        "shot_zone_area": str(row["shot_zone_area"]),
        "shot_zone_range": str(row["shot_zone_range"]),
        "season_type": str(row["season_type"]),
        "made": bool(row["made"]),
    }


def model_record(shot: Mapping[str, object]) -> dict[str, object]:
    """Select only the exact ordered runtime fields from a normalized DB row."""
    return {
        "coordinate_x_ft": shot["coordinate_x_ft"],
        "coordinate_y_ft": shot["coordinate_y_ft"],
        "shot_distance_ft": shot["shot_distance_ft"],
        "shot_angle_degrees": shot["shot_angle_degrees"],
        "period": shot["period"],
        "seconds_remaining": shot["seconds_remaining"],
        "shooter_is_home": shot["shooter_is_home"],
        "action_type": shot["action_type"],
        "shot_type": shot["shot_type"],
        "shot_zone_basic": shot["shot_zone_basic"],
        "shot_zone_area": shot["shot_zone_area"],
        "shot_zone_range": shot["shot_zone_range"],
        "season_type": shot["season_type"],
    }

"""Normalized relational model for NBA shot analytics."""

from datetime import date

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from hoopslab.db.base import Base


class Team(Base):
    """A team identified by its upstream NBA source identifier."""

    __tablename__ = "teams"

    source_team_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class Player(Base):
    """A player identified by the archive's upstream identifier."""

    __tablename__ = "players"

    source_player_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)


class Game(Base):
    """A game and its chronological/source context."""

    __tablename__ = "games"
    __table_args__ = (
        CheckConstraint(
            "season_start BETWEEN 1996 AND 2100", name="season_start_range"
        ),
        CheckConstraint("season_type IN ('rg', 'po')", name="season_type_value"),
        CheckConstraint("home_team_code <> away_team_code", name="different_teams"),
        Index("ix_games_game_date_source_game_id", "game_date", "source_game_id"),
    )

    source_game_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False
    )
    game_date: Mapped[date] = mapped_column(Date, nullable=False)
    season_start: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    season_type: Mapped[str] = mapped_column(String(2), nullable=False)
    home_team_code: Mapped[str] = mapped_column(String(3), nullable=False)
    away_team_code: Mapped[str] = mapped_column(String(3), nullable=False)


class Shot(Base):
    """One normalized field-goal attempt."""

    __tablename__ = "shots"
    __table_args__ = (
        CheckConstraint("period BETWEEN 1 AND 20", name="period_range"),
        CheckConstraint(
            "((period <= 4 AND seconds_remaining BETWEEN 0 AND 720) "
            "OR (period >= 5 AND seconds_remaining BETWEEN 0 AND 300))",
            name="period_clock_range",
        ),
        CheckConstraint(
            "coordinate_x_tenths_ft BETWEEN -250 AND 250", name="coordinate_x_range"
        ),
        CheckConstraint(
            "coordinate_y_tenths_ft BETWEEN -100 AND 940", name="coordinate_y_range"
        ),
        CheckConstraint(
            "shot_distance_ft BETWEEN 0 AND 94", name="shot_distance_range"
        ),
        CheckConstraint("shot_value IN (2, 3)", name="shot_value_value"),
        CheckConstraint(
            "((shot_value = 2 AND shot_type = '2PT Field Goal') OR "
            "(shot_value = 3 AND shot_type = '3PT Field Goal'))",
            name="shot_type_value_consistency",
        ),
        Index("ix_shots_team_id_game_id", "team_id", "game_id"),
        Index("ix_shots_player_id_game_id", "player_id", "game_id"),
    )

    game_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("games.source_game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("players.source_player_id"), nullable=False
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.source_team_id"), nullable=False
    )
    period: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    seconds_remaining: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    action_type: Mapped[str] = mapped_column(String(128), nullable=False)
    shot_type: Mapped[str] = mapped_column(String(32), nullable=False)
    shot_value: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    shot_zone_basic: Mapped[str] = mapped_column(String(64), nullable=False)
    shot_zone_area: Mapped[str] = mapped_column(String(64), nullable=False)
    shot_zone_range: Mapped[str] = mapped_column(String(32), nullable=False)
    shot_distance_ft: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    coordinate_x_tenths_ft: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    coordinate_y_tenths_ft: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    made: Mapped[bool] = mapped_column(Boolean, nullable=False)

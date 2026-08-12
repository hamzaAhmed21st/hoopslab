"""Normalized relational model for NBA shot analytics."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
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


class GameTeam(Base):
    """One source team occupying a home or away role in a game."""

    __tablename__ = "game_teams"
    __table_args__ = (
        CheckConstraint("team_code ~ '^[A-Z]{3}$'", name="team_code_format"),
        UniqueConstraint("game_id", "is_home", name="uq_game_teams_game_home_role"),
        UniqueConstraint("game_id", "team_code", name="uq_game_teams_game_team_code"),
        UniqueConstraint(
            "game_id",
            "team_id",
            "is_home",
            name="uq_game_teams_game_team_home_role",
        ),
    )

    game_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("games.source_game_id", ondelete="CASCADE"),
        primary_key=True,
    )
    team_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("teams.source_team_id"),
        primary_key=True,
    )
    team_code: Mapped[str] = mapped_column(String(3), nullable=False)
    is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)


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
        CheckConstraint("team_id <> opponent_team_id", name="different_teams"),
        ForeignKeyConstraint(
            ["game_id", "team_id", "shooter_is_home"],
            ["game_teams.game_id", "game_teams.team_id", "game_teams.is_home"],
            name="fk_shots_shooting_game_team",
        ),
        ForeignKeyConstraint(
            ["game_id", "opponent_team_id"],
            ["game_teams.game_id", "game_teams.team_id"],
            name="fk_shots_opponent_game_team",
        ),
        Index("ix_shots_team_id_game_id", "team_id", "game_id"),
        Index("ix_shots_player_id_game_id", "player_id", "game_id"),
        Index("ix_shots_opponent_team_id_game_id", "opponent_team_id", "game_id"),
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
    opponent_team_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("teams.source_team_id"), nullable=False
    )
    shooter_is_home: Mapped[bool] = mapped_column(Boolean, nullable=False)
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


class IngestionRun(Base):
    """Audit record for one attempted source-season ingestion."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name="status_value",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="source_sha256_format"
        ),
        CheckConstraint(
            "source_revision ~ '^[0-9a-f]{40}$'", name="source_revision_format"
        ),
        CheckConstraint("source_row_count >= 0", name="source_row_count_nonnegative"),
        CheckConstraint(
            "normalized_shot_count IS NULL OR normalized_shot_count >= 0",
            name="normalized_count_nonnegative",
        ),
        CheckConstraint("rejected_count >= 0", name="rejected_count_nonnegative"),
        CheckConstraint(
            "((status = 'running' AND completed_at IS NULL) OR "
            "(status <> 'running' AND completed_at IS NOT NULL))",
            name="completion_time_consistency",
        ),
        CheckConstraint(
            "(status <> 'completed' OR "
            "(normalized_shot_count = source_row_count AND rejected_count = 0))",
            name="completed_count_consistency",
        ),
        Index("ix_ingestion_runs_season_status", "season_start", "status"),
    )

    run_id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, autoincrement=True
    )
    season_start: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    season_type: Mapped[str] = mapped_column(String(2), nullable=False)
    source_repository: Mapped[str] = mapped_column(String(128), nullable=False)
    source_revision: Mapped[str] = mapped_column(String(40), nullable=False)
    source_path: Mapped[str] = mapped_column(String(256), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_shot_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    game_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    team_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rejected_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

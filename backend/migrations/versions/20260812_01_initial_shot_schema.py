"""Create the normalized shot analytics schema.

Revision ID: 20260812_01
Revises: None
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create entity and attempt tables with source-level safeguards."""
    op.create_table(
        "games",
        sa.Column(
            "source_game_id", sa.BigInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("game_date", sa.Date(), nullable=False),
        sa.Column("season_start", sa.SmallInteger(), nullable=False),
        sa.Column("season_type", sa.String(length=2), nullable=False),
        sa.Column("home_team_code", sa.String(length=3), nullable=False),
        sa.Column("away_team_code", sa.String(length=3), nullable=False),
        sa.CheckConstraint(
            "home_team_code <> away_team_code",
            name=op.f("ck_games_different_teams"),
        ),
        sa.CheckConstraint(
            "season_start BETWEEN 1996 AND 2100",
            name=op.f("ck_games_season_start_range"),
        ),
        sa.CheckConstraint(
            "season_type IN ('rg', 'po')",
            name=op.f("ck_games_season_type_value"),
        ),
        sa.PrimaryKeyConstraint("source_game_id", name="pk_games"),
    )
    op.create_index(
        "ix_games_game_date_source_game_id",
        "games",
        ["game_date", "source_game_id"],
        unique=False,
    )
    op.create_table(
        "players",
        sa.Column(
            "source_player_id", sa.BigInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("source_player_id", name="pk_players"),
    )
    op.create_table(
        "teams",
        sa.Column(
            "source_team_id", sa.BigInteger(), autoincrement=False, nullable=False
        ),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.PrimaryKeyConstraint("source_team_id", name="pk_teams"),
    )
    op.create_table(
        "shots",
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("period", sa.SmallInteger(), nullable=False),
        sa.Column("seconds_remaining", sa.SmallInteger(), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("shot_type", sa.String(length=32), nullable=False),
        sa.Column("shot_value", sa.SmallInteger(), nullable=False),
        sa.Column("shot_zone_basic", sa.String(length=64), nullable=False),
        sa.Column("shot_zone_area", sa.String(length=64), nullable=False),
        sa.Column("shot_zone_range", sa.String(length=32), nullable=False),
        sa.Column("shot_distance_ft", sa.SmallInteger(), nullable=False),
        sa.Column("coordinate_x_tenths_ft", sa.SmallInteger(), nullable=False),
        sa.Column("coordinate_y_tenths_ft", sa.SmallInteger(), nullable=False),
        sa.Column("made", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "coordinate_x_tenths_ft BETWEEN -250 AND 250",
            name=op.f("ck_shots_coordinate_x_range"),
        ),
        sa.CheckConstraint(
            "coordinate_y_tenths_ft BETWEEN -100 AND 940",
            name=op.f("ck_shots_coordinate_y_range"),
        ),
        sa.CheckConstraint(
            "period BETWEEN 1 AND 20", name=op.f("ck_shots_period_range")
        ),
        sa.CheckConstraint(
            "((period <= 4 AND seconds_remaining BETWEEN 0 AND 720) "
            "OR (period >= 5 AND seconds_remaining BETWEEN 0 AND 300))",
            name=op.f("ck_shots_period_clock_range"),
        ),
        sa.CheckConstraint(
            "shot_distance_ft BETWEEN 0 AND 94",
            name=op.f("ck_shots_shot_distance_range"),
        ),
        sa.CheckConstraint(
            "((shot_value = 2 AND shot_type = '2PT Field Goal') OR "
            "(shot_value = 3 AND shot_type = '3PT Field Goal'))",
            name=op.f("ck_shots_shot_type_value_consistency"),
        ),
        sa.CheckConstraint(
            "shot_value IN (2, 3)", name=op.f("ck_shots_shot_value_value")
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.source_game_id"],
            name="fk_shots_game_id_games",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.source_player_id"],
            name="fk_shots_player_id_players",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.source_team_id"],
            name="fk_shots_team_id_teams",
        ),
        sa.PrimaryKeyConstraint("game_id", "event_id", name="pk_shots"),
    )
    op.create_index(
        "ix_shots_player_id_game_id",
        "shots",
        ["player_id", "game_id"],
        unique=False,
    )
    op.create_index(
        "ix_shots_team_id_game_id",
        "shots",
        ["team_id", "game_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the initial schema in reverse dependency order."""
    op.drop_index("ix_shots_team_id_game_id", table_name="shots")
    op.drop_index("ix_shots_player_id_game_id", table_name="shots")
    op.drop_table("shots")
    op.drop_table("teams")
    op.drop_table("players")
    op.drop_index("ix_games_game_date_source_game_id", table_name="games")
    op.drop_table("games")

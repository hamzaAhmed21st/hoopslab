"""Add ingestion provenance and resolved game-team context.

Revision ID: 20260812_02
Revises: 20260812_01
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_02"
down_revision: str | None = "20260812_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create provenance, participants, and leakage-safe team context."""
    op.create_table(
        "game_teams",
        sa.Column("game_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("team_code", sa.String(length=3), nullable=False),
        sa.Column("is_home", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "team_code ~ '^[A-Z]{3}$'", name=op.f("ck_game_teams_team_code_format")
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.source_game_id"],
            name="fk_game_teams_game_id_games",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.source_team_id"],
            name="fk_game_teams_team_id_teams",
        ),
        sa.PrimaryKeyConstraint("game_id", "team_id", name="pk_game_teams"),
        sa.UniqueConstraint("game_id", "is_home", name="uq_game_teams_game_home_role"),
        sa.UniqueConstraint(
            "game_id", "team_code", name="uq_game_teams_game_team_code"
        ),
        sa.UniqueConstraint(
            "game_id",
            "team_id",
            "is_home",
            name="uq_game_teams_game_team_home_role",
        ),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
        sa.Column("season_start", sa.SmallInteger(), nullable=False),
        sa.Column("season_type", sa.String(length=2), nullable=False),
        sa.Column("source_repository", sa.String(length=128), nullable=False),
        sa.Column("source_revision", sa.String(length=40), nullable=False),
        sa.Column("source_path", sa.String(length=256), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("normalization_version", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_row_count", sa.Integer(), nullable=False),
        sa.Column("normalized_shot_count", sa.Integer(), nullable=True),
        sa.Column("game_count", sa.Integer(), nullable=True),
        sa.Column("player_count", sa.Integer(), nullable=True),
        sa.Column("team_count", sa.Integer(), nullable=True),
        sa.Column("rejected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "((status = 'running' AND completed_at IS NULL) OR "
            "(status <> 'running' AND completed_at IS NOT NULL))",
            name=op.f("ck_ingestion_runs_completion_time_consistency"),
        ),
        sa.CheckConstraint(
            "(status <> 'completed' OR "
            "(normalized_shot_count = source_row_count AND rejected_count = 0))",
            name=op.f("ck_ingestion_runs_completed_count_consistency"),
        ),
        sa.CheckConstraint(
            "normalized_shot_count IS NULL OR normalized_shot_count >= 0",
            name=op.f("ck_ingestion_runs_normalized_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "rejected_count >= 0",
            name=op.f("ck_ingestion_runs_rejected_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_revision ~ '^[0-9a-f]{40}$'",
            name=op.f("ck_ingestion_runs_source_revision_format"),
        ),
        sa.CheckConstraint(
            "source_row_count >= 0",
            name=op.f("ck_ingestion_runs_source_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_ingestion_runs_source_sha256_format"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'skipped')",
            name=op.f("ck_ingestion_runs_status_value"),
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_ingestion_runs"),
    )
    op.create_index(
        "ix_ingestion_runs_season_status",
        "ingestion_runs",
        ["season_start", "status"],
        unique=False,
    )

    op.add_column("shots", sa.Column("opponent_team_id", sa.BigInteger()))
    op.add_column("shots", sa.Column("shooter_is_home", sa.Boolean()))
    op.alter_column("shots", "opponent_team_id", nullable=False)
    op.alter_column("shots", "shooter_is_home", nullable=False)
    op.create_check_constraint(
        op.f("ck_shots_different_teams"), "shots", "team_id <> opponent_team_id"
    )
    op.create_foreign_key(
        "fk_shots_opponent_team_id_teams",
        "shots",
        "teams",
        ["opponent_team_id"],
        ["source_team_id"],
    )
    op.create_foreign_key(
        "fk_shots_opponent_game_team",
        "shots",
        "game_teams",
        ["game_id", "opponent_team_id"],
        ["game_id", "team_id"],
    )
    op.create_foreign_key(
        "fk_shots_shooting_game_team",
        "shots",
        "game_teams",
        ["game_id", "team_id", "shooter_is_home"],
        ["game_id", "team_id", "is_home"],
    )
    op.create_index(
        "ix_shots_opponent_team_id_game_id",
        "shots",
        ["opponent_team_id", "game_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove ingestion provenance and resolved team context."""
    op.drop_index("ix_shots_opponent_team_id_game_id", table_name="shots")
    op.drop_constraint("fk_shots_shooting_game_team", "shots", type_="foreignkey")
    op.drop_constraint("fk_shots_opponent_game_team", "shots", type_="foreignkey")
    op.drop_constraint("fk_shots_opponent_team_id_teams", "shots", type_="foreignkey")
    op.drop_constraint(op.f("ck_shots_different_teams"), "shots", type_="check")
    op.drop_column("shots", "shooter_is_home")
    op.drop_column("shots", "opponent_team_id")
    op.drop_index("ix_ingestion_runs_season_status", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")
    op.drop_table("game_teams")

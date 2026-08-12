"""Atomic, idempotent ingestion for one pinned shotdetail season."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter

import pyarrow.parquet as pq
from sqlalchemy import Engine, Select, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from hoopslab.db.models import Game, GameTeam, IngestionRun, Player, Shot, Team
from hoopslab.sources.archive import (
    SourceAsset,
    SourceIntegrityError,
    file_sha256,
    iter_normalized_shots,
    validate_source_schema,
)

NORMALIZATION_VERSION = "2"


class IngestionError(RuntimeError):
    """Base error for a season that cannot be trusted or persisted."""


class SourceDataError(IngestionError):
    """Normalized source rows violate a season-level invariant."""


class IngestionConflictError(IngestionError):
    """A completed season exists with a different source identity."""


@dataclass
class _GameAccumulator:
    game_date: date
    season_start: int
    season_type: str
    home_team_code: str
    away_team_code: str
    team_ids: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class GameResolution:
    """Resolved source identities and roles for one game."""

    game_date: date
    season_start: int
    season_type: str
    home_team_code: str
    away_team_code: str
    home_team_id: int
    away_team_id: int


@dataclass(frozen=True)
class SeasonContext:
    """Small season-level entity and game context retained in memory."""

    teams: dict[int, str]
    players: dict[int, str]
    team_codes: dict[int, str]
    games: dict[int, GameResolution]


@dataclass(frozen=True)
class IngestionResult:
    """Result of one completed or safely skipped ingestion attempt."""

    run_id: int
    season_start: int
    status: str
    source_rows: int
    normalized_shots: int
    games: int
    players: int
    teams: int
    elapsed_seconds: float


def _consistent_value(
    values: dict[int, str], source_id: int, value: str, *, entity: str
) -> None:
    existing = values.setdefault(source_id, value)
    if existing != value:
        raise SourceDataError(
            f"{entity} {source_id} has conflicting names: {existing!r} and {value!r}"
        )


def build_season_context(path: Path, asset: SourceAsset) -> SeasonContext:
    """Resolve team codes to stable IDs using whole-season game structure."""
    games: dict[int, _GameAccumulator] = {}
    teams: dict[int, str] = {}
    players: dict[int, str] = {}
    team_code_candidates: dict[int, set[str]] = {}

    for shot in iter_normalized_shots(path):
        if (
            shot.season_start != asset.season_start
            or shot.season_type != asset.season_type
        ):
            raise SourceDataError(
                f"row season {shot.season_start}/{shot.season_type} does not match "
                f"manifest {asset.season_start}/{asset.season_type}"
            )
        if shot.game_date.year not in {asset.season_start, asset.season_start + 1}:
            raise SourceDataError(
                f"game {shot.game_id} date {shot.game_date} is outside its NBA season"
            )
        if (
            re.fullmatch(r"[A-Z]{3}", shot.home_team_code) is None
            or re.fullmatch(r"[A-Z]{3}", shot.away_team_code) is None
        ):
            raise SourceDataError(
                f"game {shot.game_id} contains a noncanonical team code"
            )

        _consistent_value(teams, shot.team_id, shot.team_name, entity="team")
        _consistent_value(players, shot.player_id, shot.player_name, entity="player")

        game = games.setdefault(
            shot.game_id,
            _GameAccumulator(
                game_date=shot.game_date,
                season_start=shot.season_start,
                season_type=shot.season_type,
                home_team_code=shot.home_team_code,
                away_team_code=shot.away_team_code,
            ),
        )
        expected_game_values = (
            game.game_date,
            game.season_start,
            game.season_type,
            game.home_team_code,
            game.away_team_code,
        )
        actual_game_values = (
            shot.game_date,
            shot.season_start,
            shot.season_type,
            shot.home_team_code,
            shot.away_team_code,
        )
        if actual_game_values != expected_game_values:
            raise SourceDataError(
                f"game {shot.game_id} has inconsistent source metadata"
            )
        game.team_ids.add(shot.team_id)

        game_codes = {shot.home_team_code, shot.away_team_code}
        candidates = team_code_candidates.setdefault(shot.team_id, set(game_codes))
        candidates.intersection_update(game_codes)

    if not games:
        raise SourceDataError("source contains no games")

    unresolved = {
        team_id: sorted(codes)
        for team_id, codes in team_code_candidates.items()
        if len(codes) != 1
    }
    if unresolved:
        raise SourceDataError(f"team codes are not uniquely resolvable: {unresolved}")
    team_codes = {
        team_id: next(iter(codes)) for team_id, codes in team_code_candidates.items()
    }
    code_to_team = {code: team_id for team_id, code in team_codes.items()}
    if len(code_to_team) != len(team_codes):
        raise SourceDataError("multiple team IDs resolved to the same source code")

    resolved_games: dict[int, GameResolution] = {}
    for game_id, game in games.items():
        if len(game.team_ids) != 2:
            raise SourceDataError(
                f"game {game_id} has {len(game.team_ids)} shooting teams instead of two"
            )
        try:
            home_team_id = code_to_team[game.home_team_code]
            away_team_id = code_to_team[game.away_team_code]
        except KeyError as error:
            raise SourceDataError(
                f"game {game_id} code {error.args[0]} has no stable team ID"
            ) from error
        if {home_team_id, away_team_id} != game.team_ids:
            raise SourceDataError(
                f"game {game_id} source codes and shooting team IDs disagree"
            )
        resolved_games[game_id] = GameResolution(
            game_date=game.game_date,
            season_start=game.season_start,
            season_type=game.season_type,
            home_team_code=game.home_team_code,
            away_team_code=game.away_team_code,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
        )

    return SeasonContext(
        teams=teams,
        players=players,
        team_codes=team_codes,
        games=resolved_games,
    )


def _verify_file(asset: SourceAsset, path: Path) -> int:
    actual_hash = file_sha256(path)
    if actual_hash != asset.sha256:
        raise SourceIntegrityError(
            f"file SHA-256 {actual_hash} does not match manifest {asset.sha256}"
        )
    parquet_file = pq.ParquetFile(path)
    validate_source_schema(parquet_file)
    source_rows = parquet_file.metadata.num_rows
    if asset.expected_rows is not None and source_rows != asset.expected_rows:
        raise SourceIntegrityError(
            f"source has {source_rows} rows; manifest expects {asset.expected_rows}"
        )
    return int(source_rows)


def _completed_runs_query(
    asset: SourceAsset,
) -> Select[tuple[int, str, str, str, str]]:
    return select(
        IngestionRun.run_id,
        IngestionRun.source_sha256,
        IngestionRun.source_repository,
        IngestionRun.source_revision,
        IngestionRun.source_path,
    ).where(
        IngestionRun.season_start == asset.season_start,
        IngestionRun.season_type == asset.season_type,
        IngestionRun.status == "completed",
    )


def _insert_run(
    engine: Engine,
    asset: SourceAsset,
    source_rows: int,
    *,
    status: str,
    completed_at: datetime | None = None,
    normalized_shot_count: int | None = None,
    game_count: int | None = None,
    player_count: int | None = None,
    team_count: int | None = None,
    error_message: str | None = None,
) -> int:
    with engine.begin() as connection:
        statement = (
            insert(IngestionRun)
            .values(
                season_start=asset.season_start,
                season_type=asset.season_type,
                source_repository=asset.repository,
                source_revision=asset.revision,
                source_path=asset.relative_path,
                source_sha256=asset.sha256,
                normalization_version=NORMALIZATION_VERSION,
                status=status,
                completed_at=completed_at,
                source_row_count=source_rows,
                normalized_shot_count=normalized_shot_count,
                game_count=game_count,
                player_count=player_count,
                team_count=team_count,
                rejected_count=0,
                error_message=error_message,
            )
            .returning(IngestionRun.run_id)
        )
        return int(connection.execute(statement).scalar_one())


def _shot_rows(
    path: Path, context: SeasonContext
) -> Iterator[dict[str, int | str | bool]]:
    for shot in iter_normalized_shots(path):
        game = context.games[shot.game_id]
        if shot.team_id == game.home_team_id:
            opponent_team_id = game.away_team_id
            shooter_is_home = True
        elif shot.team_id == game.away_team_id:
            opponent_team_id = game.home_team_id
            shooter_is_home = False
        else:
            raise SourceDataError(
                f"shot {shot.game_id}/{shot.event_id} team is not a game participant"
            )
        yield {
            "game_id": shot.game_id,
            "event_id": shot.event_id,
            "player_id": shot.player_id,
            "team_id": shot.team_id,
            "opponent_team_id": opponent_team_id,
            "shooter_is_home": shooter_is_home,
            "period": shot.period,
            "seconds_remaining": shot.seconds_remaining,
            "action_type": shot.action_type,
            "shot_type": shot.shot_type,
            "shot_value": shot.shot_value,
            "shot_zone_basic": shot.shot_zone_basic,
            "shot_zone_area": shot.shot_zone_area,
            "shot_zone_range": shot.shot_zone_range,
            "shot_distance_ft": shot.shot_distance_ft,
            "coordinate_x_tenths_ft": shot.coordinate_x_tenths_ft,
            "coordinate_y_tenths_ft": shot.coordinate_y_tenths_ft,
            "made": shot.made,
        }


def _chunks[T](rows: Iterator[T], batch_size: int) -> Iterator[list[T]]:
    chunk: list[T] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) == batch_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def ingest_season(
    engine: Engine,
    asset: SourceAsset,
    path: Path,
    *,
    batch_size: int = 5_000,
) -> IngestionResult:
    """Atomically persist one verified season or skip an exact re-ingestion."""
    if batch_size < 1:
        msg = "batch_size must be positive"
        raise ValueError(msg)
    started = perf_counter()
    source_rows = _verify_file(asset, path)

    with engine.begin() as connection:
        completed_runs = (
            connection.execute(_completed_runs_query(asset)).mappings().all()
        )
        exact_run = next(
            (
                run
                for run in completed_runs
                if run["source_sha256"] == asset.sha256
                and run["source_repository"] == asset.repository
                and run["source_revision"] == asset.revision
                and run["source_path"] == asset.relative_path
            ),
            None,
        )
        conflicting_run = next(
            (run for run in completed_runs if run != exact_run), None
        )

    if exact_run is not None:
        now = datetime.now(UTC)
        run_id = _insert_run(
            engine,
            asset,
            source_rows,
            status="skipped",
            completed_at=now,
            normalized_shot_count=0,
            game_count=0,
            player_count=0,
            team_count=0,
            error_message=f"already ingested by run {exact_run['run_id']}",
        )
        return IngestionResult(
            run_id=run_id,
            season_start=asset.season_start,
            status="skipped",
            source_rows=source_rows,
            normalized_shots=0,
            games=0,
            players=0,
            teams=0,
            elapsed_seconds=perf_counter() - started,
        )

    if conflicting_run is not None:
        message = (
            f"season already completed from hash {conflicting_run['source_sha256']}; "
            f"refusing {asset.sha256}"
        )
        _insert_run(
            engine,
            asset,
            source_rows,
            status="failed",
            completed_at=datetime.now(UTC),
            error_message=message,
        )
        raise IngestionConflictError(message)

    with engine.begin() as connection:
        connection.execute(
            update(IngestionRun)
            .where(
                IngestionRun.season_start == asset.season_start,
                IngestionRun.season_type == asset.season_type,
                IngestionRun.source_sha256 == asset.sha256,
                IngestionRun.status == "running",
            )
            .values(
                status="failed",
                completed_at=datetime.now(UTC),
                error_message="superseded by a restart",
            )
        )
    run_id = _insert_run(engine, asset, source_rows, status="running")

    try:
        context = build_season_context(path, asset)
        with engine.begin() as connection:
            team_rows = [
                {"source_team_id": team_id, "name": name}
                for team_id, name in sorted(context.teams.items())
            ]
            player_rows = [
                {"source_player_id": player_id, "full_name": name}
                for player_id, name in sorted(context.players.items())
            ]
            team_insert = pg_insert(Team).values(team_rows)
            connection.execute(
                team_insert.on_conflict_do_update(
                    index_elements=[Team.source_team_id],
                    set_={"name": team_insert.excluded.name},
                )
            )
            player_insert = pg_insert(Player).values(player_rows)
            connection.execute(
                player_insert.on_conflict_do_update(
                    index_elements=[Player.source_player_id],
                    set_={"full_name": player_insert.excluded.full_name},
                )
            )
            connection.execute(
                insert(Game),
                [
                    {
                        "source_game_id": game_id,
                        "game_date": game.game_date,
                        "season_start": game.season_start,
                        "season_type": game.season_type,
                        "home_team_code": game.home_team_code,
                        "away_team_code": game.away_team_code,
                    }
                    for game_id, game in sorted(context.games.items())
                ],
            )
            game_team_rows: list[dict[str, int | str | bool]] = []
            for game_id, game in sorted(context.games.items()):
                game_team_rows.extend(
                    [
                        {
                            "game_id": game_id,
                            "team_id": game.home_team_id,
                            "team_code": game.home_team_code,
                            "is_home": True,
                        },
                        {
                            "game_id": game_id,
                            "team_id": game.away_team_id,
                            "team_code": game.away_team_code,
                            "is_home": False,
                        },
                    ]
                )
            connection.execute(insert(GameTeam), game_team_rows)

            normalized_count = 0
            for shot_batch in _chunks(_shot_rows(path, context), batch_size):
                connection.execute(insert(Shot), shot_batch)
                normalized_count += len(shot_batch)
            if normalized_count != source_rows:
                raise SourceDataError(
                    f"normalized {normalized_count} rows from {source_rows} source rows"
                )
            connection.execute(
                update(IngestionRun)
                .where(IngestionRun.run_id == run_id)
                .values(
                    status="completed",
                    completed_at=datetime.now(UTC),
                    normalized_shot_count=normalized_count,
                    game_count=len(context.games),
                    player_count=len(context.players),
                    team_count=len(context.teams),
                    rejected_count=0,
                )
            )
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(
                update(IngestionRun)
                .where(IngestionRun.run_id == run_id)
                .values(
                    status="failed",
                    completed_at=datetime.now(UTC),
                    error_message=str(error)[:4_000],
                )
            )
        raise

    return IngestionResult(
        run_id=run_id,
        season_start=asset.season_start,
        status="completed",
        source_rows=source_rows,
        normalized_shots=source_rows,
        games=len(context.games),
        players=len(context.players),
        teams=len(context.teams),
        elapsed_seconds=perf_counter() - started,
    )

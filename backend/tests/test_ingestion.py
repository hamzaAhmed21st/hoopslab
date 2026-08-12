"""Season-level team resolution tests."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hoopslab.ingestion import SourceDataError, build_season_context
from hoopslab.sources.archive import SourceAsset, file_sha256


def test_team_codes_resolve_from_stable_ids_and_game_structure(
    tmp_path: Path,
    resolved_season_rows_factory: Callable[[int], list[dict[str, Any]]],
) -> None:
    path = tmp_path / "season.parquet"
    pq.write_table(pa.Table.from_pylist(resolved_season_rows_factory(2023)), path)
    asset = SourceAsset(2023, "rg", file_sha256(path), expected_rows=6)

    context = build_season_context(path, asset)

    assert context.team_codes == {1: "AAA", 2: "BBB", 3: "CCC"}
    assert context.games[9001].home_team_id == 1
    assert context.games[9001].away_team_id == 2
    assert all(
        game.home_team_id != game.away_team_id for game in context.games.values()
    )


def test_ambiguous_team_codes_fail_instead_of_using_display_names(
    tmp_path: Path,
    resolved_season_rows_factory: Callable[[int], list[dict[str, Any]]],
) -> None:
    path = tmp_path / "ambiguous.parquet"
    rows = resolved_season_rows_factory(2023)[:2]
    pq.write_table(pa.Table.from_pylist(rows), path)
    asset = SourceAsset(2023, "rg", file_sha256(path), expected_rows=2)

    with pytest.raises(SourceDataError, match="not uniquely resolvable"):
        build_season_context(path, asset)

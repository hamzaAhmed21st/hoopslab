"""NBA Data Archive boundary tests using synthetic Parquet data."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from hoopslab.sources.archive import (
    SourceAsset,
    SourceIntegrityError,
    SourceSchemaError,
    fetch_asset,
    file_sha256,
    iter_normalized_shots,
    validate_asset,
)


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_parquet_adapter_validates_and_normalizes_rows(
    tmp_path: Path,
    archive_row_factory: Callable[..., dict[str, Any]],
) -> None:
    path = tmp_path / "shots.parquet"
    rows = [
        archive_row_factory(),
        archive_row_factory(
            GAME_EVENT_ID=11,
            EVENT_TYPE="Missed Shot",
            SHOT_MADE_FLAG=0,
            SHOT_TYPE="2PT Field Goal",
            SHOT_DISTANCE=7,
        ),
    ]
    _write_parquet(path, rows)
    asset = SourceAsset(2023, "rg", file_sha256(path))

    report = validate_asset(asset, path, sample_size=10)
    normalized = list(iter_normalized_shots(path))

    assert report.total_rows == 2
    assert (report.made, report.missed) == (1, 1)
    assert [shot.event_id for shot in normalized] == [10, 11]
    assert [shot.shot_value for shot in normalized] == [3, 2]


def test_parquet_adapter_rejects_schema_drift(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.parquet"
    _write_parquet(path, [{"GAME_ID": 1, "GAME_EVENT_ID": 2}])

    with pytest.raises(SourceSchemaError, match="missing required columns"):
        list(iter_normalized_shots(path))


def test_downloader_writes_only_hash_verified_bytes(tmp_path: Path) -> None:
    content = b"bounded parquet stand-in"
    source_file = tmp_path / "expected.bin"
    source_file.write_bytes(content)
    asset = SourceAsset(2023, "rg", file_sha256(source_file))
    destination = tmp_path / "cache" / "2023.parquet"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))
    )

    fetched = fetch_asset(asset, destination, client=client)

    assert fetched.read_bytes() == content
    assert not destination.with_suffix(".parquet.part").exists()
    client.close()


def test_downloader_does_not_publish_bad_bytes(tmp_path: Path) -> None:
    asset = SourceAsset(2023, "rg", "0" * 64)
    destination = tmp_path / "2023.parquet"
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"bad"))
    )

    with pytest.raises(SourceIntegrityError, match="does not match"):
        fetch_asset(asset, destination, client=client)

    assert not destination.exists()
    assert not destination.with_suffix(".parquet.part").exists()
    client.close()

"""Fetch and atomically ingest pinned HoopsLab source seasons."""

from argparse import ArgumentParser

from sqlalchemy import create_engine

from hoopslab.config import get_settings
from hoopslab.ingestion import ingest_season
from hoopslab.sources.archive import SOURCE_MANIFEST, fetch_asset, validate_manifest


def main() -> None:
    """Ingest selected seasons in chronological order."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        type=int,
        action="append",
        help="season start year to ingest; repeat as needed (default: all)",
    )
    parser.add_argument("--batch-size", type=int, default=5_000)
    args = parser.parse_args()

    validate_manifest()
    requested = set(args.season or (asset.season_start for asset in SOURCE_MANIFEST))
    assets = [asset for asset in SOURCE_MANIFEST if asset.season_start in requested]
    unknown = requested.difference(asset.season_start for asset in assets)
    if unknown:
        parser.error(f"seasons are not in the pinned manifest: {sorted(unknown)}")

    settings = get_settings()
    engine = create_engine(settings.database_url)
    try:
        for asset in assets:
            path = fetch_asset(asset, asset.cache_path(settings.source_cache_dir))
            result = ingest_season(engine, asset, path, batch_size=args.batch_size)
            rate = (
                result.normalized_shots / result.elapsed_seconds
                if result.elapsed_seconds > 0
                else 0.0
            )
            print(
                f"season={asset.season_label} status={result.status} "
                f"run={result.run_id} rows={result.normalized_shots} "
                f"games={result.games} players={result.players} teams={result.teams} "
                f"seconds={result.elapsed_seconds:.3f} rows_per_second={rate:.1f}"
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

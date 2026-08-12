"""Download and validate the pinned bounded source-validation asset."""

from argparse import ArgumentParser

from hoopslab.config import get_settings
from hoopslab.sources.archive import (
    SOURCE_MANIFEST,
    fetch_asset,
    validate_asset,
    validate_manifest,
)


def main() -> None:
    """Fetch the manifest asset and print reproducible validation evidence."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help="rows per season to parse through the domain contract (default: 500)",
    )
    args = parser.parse_args()

    settings = get_settings()
    validate_manifest()
    print(f"source_revision={SOURCE_MANIFEST[0].revision}")
    for asset in SOURCE_MANIFEST:
        path = fetch_asset(asset, asset.cache_path(settings.source_cache_dir))
        report = validate_asset(asset, path, sample_size=args.sample_size)
        print(
            f"season={asset.season_label} path={report.path} sha256={report.sha256} "
            f"rows={report.total_rows} sample={report.sample_rows} "
            f"games={report.sample_games} players={report.sample_players} "
            f"teams={report.sample_teams} made={report.made} missed={report.missed} "
            f"x={report.coordinate_x_range} y={report.coordinate_y_range}"
        )
    print("validation=ok")


if __name__ == "__main__":
    main()

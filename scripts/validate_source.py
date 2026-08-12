"""Download and validate the pinned bounded source-validation asset."""

from argparse import ArgumentParser

from hoopslab.config import get_settings
from hoopslab.sources.archive import VALIDATION_ASSET, fetch_asset, validate_asset


def main() -> None:
    """Fetch the manifest asset and print reproducible validation evidence."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help="number of rows to parse through the domain contract (default: 500)",
    )
    args = parser.parse_args()

    settings = get_settings()
    destination = (
        settings.source_cache_dir / "nba-data-archive" / "shotdetail" / "2023.parquet"
    )
    path = fetch_asset(VALIDATION_ASSET, destination)
    report = validate_asset(VALIDATION_ASSET, path, sample_size=args.sample_size)

    print(f"source_revision={VALIDATION_ASSET.url.split('/resolve/')[1].split('/')[0]}")
    print(f"path={report.path}")
    print(f"sha256={report.sha256}")
    print(f"total_rows={report.total_rows}")
    print(f"sample_rows={report.sample_rows}")
    print(
        "sample_entities="
        f"games:{report.sample_games},players:{report.sample_players},"
        f"teams:{report.sample_teams}"
    )
    print(f"sample_outcomes=made:{report.made},missed:{report.missed}")
    print(f"sample_loc_x_tenths_ft={report.coordinate_x_range}")
    print(f"sample_loc_y_tenths_ft={report.coordinate_y_range}")
    print("validation=ok")


if __name__ == "__main__":
    main()

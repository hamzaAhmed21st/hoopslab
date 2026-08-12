"""Generate the local normalized-data quality report."""

from argparse import ArgumentParser
from typing import cast

from sqlalchemy import create_engine

from hoopslab.config import get_settings
from hoopslab.quality import generate_quality_report, write_quality_report


def main() -> None:
    """Run deterministic database quality checks and write JSON."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="output JSON path")
    args = parser.parse_args()
    settings = get_settings()
    output = settings.artifact_dir / "quality-report.json"
    if args.output:
        output = type(output)(args.output)

    engine = create_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            report = generate_quality_report(connection)
        write_quality_report(report, output)
    finally:
        engine.dispose()

    print(f"output={output}")
    seasons = cast(list[dict[str, object]], report["seasons"])
    for season in seasons:
        print(
            f"season={season['season_start']} shots={season['shots']} "
            f"games={season['games']} made={season['made']} missed={season['missed']}"
        )
    print(f"integrity={report['integrity']}")
    print(f"clean={report['clean']}")


if __name__ == "__main__":
    main()

"""Build local leakage-safe feature and whole-game split artifacts."""

from argparse import ArgumentParser
from pathlib import Path

from sqlalchemy import create_engine

from hoopslab.config import get_settings
from hoopslab.features import (
    build_split_manifest,
    export_feature_dataset,
    validate_feature_split_artifacts,
)


def main() -> None:
    """Export deterministic Parquet features and JSON game assignments."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--features", help="feature Parquet output path")
    parser.add_argument("--splits", help="split-manifest JSON output path")
    parser.add_argument("--batch-size", type=int, default=10_000)
    args = parser.parse_args()
    settings = get_settings()
    feature_path = (
        Path(args.features)
        if args.features
        else settings.artifact_dir / "features.parquet"
    )
    split_path = (
        Path(args.splits)
        if args.splits
        else settings.artifact_dir / "split-manifest.json"
    )

    engine = create_engine(settings.database_url)
    try:
        feature_result = export_feature_dataset(
            engine, feature_path, batch_size=args.batch_size
        )
        split_result = build_split_manifest(engine, split_path)
    finally:
        engine.dispose()

    validation = validate_feature_split_artifacts(feature_path, split_path)

    print(f"features={feature_result.path} rows={feature_result.row_count}")
    print(
        f"splits={split_result.path} rows={split_result.row_counts} "
        f"games={split_result.game_counts}"
    )
    print(
        f"validation=ok feature_rows={validation.feature_rows} "
        f"games={validation.games} rows={validation.row_counts}"
    )


if __name__ == "__main__":
    main()

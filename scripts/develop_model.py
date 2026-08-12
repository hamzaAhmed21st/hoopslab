"""Tune, calibrate, select, and lock HoopsLab models without test-season access."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from hoopslab.config import get_settings
from hoopslab.modeling.workflow import format_development_result, run_development


def main() -> None:
    """Run the frozen development procedure on only 2018-19 through 2022-23."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--features", help="feature Parquet path")
    parser.add_argument(
        "--splits", help="split manifest path (development assignments only)"
    )
    parser.add_argument("--output-dir", help="local ignored model artifact directory")
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
    output_dir = (
        Path(args.output_dir) if args.output_dir else settings.modeling_artifact_dir
    )
    result = run_development(feature_path, split_path, output_dir)
    print(format_development_result(result))


if __name__ == "__main__":
    main()

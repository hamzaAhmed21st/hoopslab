"""Run the single guarded final 2023-24 evaluation for a locked model bundle."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from hoopslab.config import get_settings
from hoopslab.modeling.workflow import run_final_test


def main() -> None:
    """Evaluate once; this command refuses existing reports and unlocked artifacts."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--features", help="feature Parquet path")
    parser.add_argument("--output-dir", help="local ignored model artifact directory")
    args = parser.parse_args()
    settings = get_settings()
    feature_path = (
        Path(args.features)
        if args.features
        else settings.artifact_dir / "features.parquet"
    )
    output_dir = (
        Path(args.output_dir) if args.output_dir else settings.modeling_artifact_dir
    )
    report = run_final_test(feature_path, output_dir)
    metrics = report["selected_metrics"]
    print(
        f"final_test=complete log_loss={metrics['log_loss']:.6f} "
        f"brier={metrics['brier_score']:.6f} auc={metrics['roc_auc']:.6f}"
    )


if __name__ == "__main__":
    main()

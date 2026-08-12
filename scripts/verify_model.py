"""Validate a local selected-model bundle and prove no development test access."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from hoopslab.config import get_settings
from hoopslab.modeling.workflow import verify_model_artifacts


def main() -> None:
    """Verify generated model metadata and binary identity without reading test rows."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="local ignored model artifact directory")
    args = parser.parse_args()
    settings = get_settings()
    output_dir = (
        Path(args.output_dir) if args.output_dir else settings.modeling_artifact_dir
    )
    audit = verify_model_artifacts(output_dir)
    print(
        f"verification=ok lock={audit['lock_status']} sha256={audit['artifact_sha256']}"
    )


if __name__ == "__main__":
    main()

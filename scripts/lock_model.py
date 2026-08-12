"""Authorize a reviewed pending HoopsLab selection record before final test use."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from hoopslab.config import get_settings
from hoopslab.modeling.workflow import lock_development


def main() -> None:
    """Change only a valid pending-review local record to locked."""
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="local ignored model artifact directory")
    args = parser.parse_args()
    settings = get_settings()
    output_dir = (
        Path(args.output_dir) if args.output_dir else settings.modeling_artifact_dir
    )
    lock = lock_development(output_dir)
    print(f"lock=authorized selected={lock['selected_variant']['identifier']}")


if __name__ == "__main__":
    main()

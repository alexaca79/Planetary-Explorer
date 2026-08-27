"""Download and verify the pinned PlanAura checkpoint for image builds."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

from .model import verify_checkpoint
from .policy import PLAN_AURA_HLS


def create_parser() -> argparse.ArgumentParser:
    """Create the checkpoint-download argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="Verified checkpoint output path")
    return parser


def main() -> int:
    """Download the exact model revision, verify it, and copy it to the image."""
    args = create_parser().parse_args()
    args.target.parent.mkdir(parents=True, exist_ok=True)
    cached = Path(
        hf_hub_download(
            repo_id=PLAN_AURA_HLS.model_id,
            filename=PLAN_AURA_HLS.checkpoint_filename,
            revision=PLAN_AURA_HLS.model_revision,
        )
    )
    verify_checkpoint(
        cached,
        PLAN_AURA_HLS.checkpoint_sha256,
        PLAN_AURA_HLS.checkpoint_size_bytes,
    )
    if cached.resolve() != args.target.resolve():
        shutil.copy2(cached, args.target)
    verify_checkpoint(
        args.target,
        PLAN_AURA_HLS.checkpoint_sha256,
        PLAN_AURA_HLS.checkpoint_size_bytes,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
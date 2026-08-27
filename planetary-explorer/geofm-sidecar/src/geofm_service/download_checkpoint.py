"""Download and verify pinned PlanAura artefacts for image builds."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

from .model import verify_checkpoint
from .policy import PLAN_AURA_HLS, list_models


def create_parser() -> argparse.ArgumentParser:
    """Create the checkpoint-download argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="Verified checkpoint output path")
    parser.add_argument(
        "--classifier-head-dir",
        type=Path,
        default=None,
        help="Directory to receive every pinned classifier head artefact",
    )
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
    if args.classifier_head_dir is not None:
        download_classifier_heads(args.classifier_head_dir)
    return 0


def download_classifier_heads(target_dir: Path) -> list[Path]:
    """Download and hash-verify every classifier head the registry pins."""
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    for descriptor in list_models():
        head = descriptor.classifier_head
        if head is None:
            continue
        cached = Path(
            hf_hub_download(
                repo_id=head.head_id,
                filename=head.filename,
                revision=head.head_revision,
            )
        )
        verify_checkpoint(cached, head.sha256, head.size_bytes)
        target = target_dir / head.filename
        if cached.resolve() != target.resolve():
            shutil.copy2(cached, target)
        verify_checkpoint(target, head.sha256, head.size_bytes)
        downloaded.append(target)
    if not downloaded:
        print(
            "No classifier head is pinned; only unsupervised classification is available.",
        )
    return downloaded


if __name__ == "__main__":
    sys.exit(main())
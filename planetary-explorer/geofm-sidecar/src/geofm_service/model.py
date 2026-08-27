"""PlanAura model adapter isolated from the MCP control process."""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path

import numpy as np

from .policy import PLAN_AURA_HLS, ModelDescriptor


class ModelRuntimeError(RuntimeError):
    """Raised when pinned model execution cannot remain reproducible."""


def verify_checkpoint(
    path: Path,
    expected_sha256: str,
    expected_size_bytes: int | None = None,
) -> None:
    """Fail before model construction when checkpoint bytes differ from policy."""
    if not path.is_file():
        raise ModelRuntimeError(f"Checkpoint '{path}' does not exist.")
    if expected_size_bytes is not None and path.stat().st_size != expected_size_bytes:
        raise ModelRuntimeError(
            f"Checkpoint size mismatch: expected {expected_size_bytes}, "
            f"received {path.stat().st_size}."
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual.casefold() != expected_sha256.casefold():
        raise ModelRuntimeError(
            f"Checkpoint hash mismatch: expected {expected_sha256}, received {actual}."
        )


def build_planaura_config(
    descriptor: ModelDescriptor,
    checkpoint_path: Path,
    *,
    num_frames: int = 2,
    return_change_map: bool = True,
    return_feature_maps: bool = False,
) -> dict:
    """Build the exact upstream configuration for PlanAura inference."""
    return {
        "num_frames": num_frames,
        "change_map": {"return": return_change_map},
        "feature_maps": {"return": return_feature_maps},
        "model_params": {
            "load_params": {
                "source": "local",
                "checkpoint_path": str(checkpoint_path),
                "repo_id": descriptor.model_id,
                "model_name": descriptor.checkpoint_filename,
            },
            "keep_pos_embedding": True,
            "restore_weights_only": True,
            "backbone": "planaura_reconstruction",
            "bands": ["B02", "B03", "B04", "B8A", "B11", "B12"],
            "img_size": descriptor.tile_size_pixels,
            "depth": 12,
            "decoder_depth": 8,
            "patch_size": 16,
            "patch_stride": descriptor.patch_stride_pixels,
            "embed_attention": True,
            "embed_dim": 768,
            "decoder_embed_dim": 512,
            "num_heads": 12,
            "decoder_num_heads": 16,
            "mask_ratio": 0.75,
            "tubelet_size": 1,
            "no_data": descriptor.source_no_data_value,
            "no_data_float": descriptor.model_no_data_value,
            "data_mean": list(descriptor.normalization_mean),
            "data_std": list(descriptor.normalization_std),
        },
    }


def normalize_epochs(raw_values: np.ndarray, descriptor: ModelDescriptor) -> np.ndarray:
    """Normalize a two-epoch ``B,C,T,H,W`` tensor using PlanAura training stats."""
    return normalize_frames(raw_values, descriptor, frames=2)


def normalize_frames(
    raw_values: np.ndarray,
    descriptor: ModelDescriptor,
    *,
    frames: int,
) -> np.ndarray:
    """Normalize a ``B,C,T,H,W`` source tensor using PlanAura training stats."""
    expected_shape = (
        1,
        len(descriptor.normalization_mean),
        frames,
        descriptor.tile_size_pixels,
        descriptor.tile_size_pixels,
    )
    if raw_values.shape != expected_shape:
        raise ModelRuntimeError(
            f"PlanAura input shape must be {expected_shape}, received {raw_values.shape}."
        )
    values = raw_values.astype(np.float32, copy=True)
    means = np.asarray(descriptor.normalization_mean, dtype=np.float32).reshape(
        1, -1, 1, 1, 1
    )
    deviations = np.asarray(descriptor.normalization_std, dtype=np.float32).reshape(
        1, -1, 1, 1, 1
    )
    invalid = ~np.isfinite(values) | (values == descriptor.source_no_data_value)
    values = (values - means) / deviations
    values[invalid] = descriptor.model_no_data_value
    return values


def similarity_to_distance(similarity: np.ndarray) -> np.ndarray:
    """Convert PlanAura cosine similarity to bounded change distance."""
    result = np.full(similarity.shape, np.nan, dtype=np.float32)
    valid = np.isfinite(similarity) & (similarity != -100.0)
    result[valid] = np.clip(1.0 - similarity[valid], 0.0, 2.0)
    return result


class PlanAuraAdapter:
    """Lazy GPU adapter around the pinned upstream PlanAura implementation."""

    def __init__(self, descriptor: ModelDescriptor = PLAN_AURA_HLS) -> None:
        self._descriptor = descriptor
        self._models: dict[bool, object] = {}

    def infer(self, normalized_values: np.ndarray) -> np.ndarray:
        """Return a full-resolution cosine-distance map for two HLS epochs."""
        model = self._get_model()
        try:
            import torch
            import torch.nn.functional as functional
        except ImportError as exc:
            raise ModelRuntimeError("The PlanAura worker requires PyTorch.") from exc
        if not torch.cuda.is_available():
            raise ModelRuntimeError("PlanAura inference requires an available CUDA GPU.")

        tensor = torch.from_numpy(normalized_values).to(device="cuda", dtype=torch.float32)
        use_autocast = os.getenv("GEOFM_AUTOCAST_FLOAT16", "true").casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=use_autocast):
            _, (similarity, _), _ = model(tensor)
            similarity = similarity.float()
            valid = similarity != -100.0
            numerator = functional.interpolate(
                torch.where(valid, similarity, torch.zeros_like(similarity))[:, None],
                size=(self._descriptor.tile_size_pixels, self._descriptor.tile_size_pixels),
                mode="bilinear",
                align_corners=False,
            )
            denominator = functional.interpolate(
                valid.float()[:, None],
                size=(self._descriptor.tile_size_pixels, self._descriptor.tile_size_pixels),
                mode="bilinear",
                align_corners=False,
            )
            upsampled = torch.where(
                denominator > 0.9,
                numerator / denominator.clamp_min(1e-6),
                torch.full_like(numerator, -100.0),
            )[0, 0]
        return similarity_to_distance(upsampled.detach().cpu().numpy())


    def embed(self, normalized_values: np.ndarray) -> np.ndarray:
        """Return ``(embed_dim, patch_rows, patch_cols)`` PlanAura patch embeddings."""
        model = self._get_model(return_feature_maps=True)
        try:
            import torch
        except ImportError as exc:
            raise ModelRuntimeError("The PlanAura worker requires PyTorch.") from exc
        if not torch.cuda.is_available():
            raise ModelRuntimeError("PlanAura inference requires an available CUDA GPU.")

        tensor = torch.from_numpy(normalized_values).to(device="cuda", dtype=torch.float32)
        use_autocast = os.getenv("GEOFM_AUTOCAST_FLOAT16", "true").casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        with torch.inference_mode(), torch.cuda.amp.autocast(enabled=use_autocast):
            outputs = model(tensor)
            features = _select_feature_maps(outputs)
        return _to_patch_grid(features)

    def _get_model(self, *, return_feature_maps: bool = False):
        cached = self._models.get(return_feature_maps)
        if cached is not None:
            return cached
        try:
            import torch
            from huggingface_hub import hf_hub_download
            from planaura.networks.network_generator import resume_pretrained_network
        except ImportError as exc:
            raise ModelRuntimeError(
                "The GPU image must contain the pinned PlanAura runtime and PyTorch stack."
            ) from exc
        if not torch.cuda.is_available():
            raise ModelRuntimeError("PlanAura inference requires an available CUDA GPU.")

        configured_path = (os.getenv("GEOFM_CHECKPOINT_PATH") or "").strip()
        checkpoint = Path(configured_path) if configured_path else Path(
            hf_hub_download(
                repo_id=self._descriptor.model_id,
                filename=self._descriptor.checkpoint_filename,
                revision=self._descriptor.model_revision,
            )
        )
        verify_checkpoint(
            checkpoint,
            self._descriptor.checkpoint_sha256,
            self._descriptor.checkpoint_size_bytes,
        )
        config = build_planaura_config(
            self._descriptor,
            checkpoint,
            num_frames=1 if return_feature_maps else 2,
            return_change_map=not return_feature_maps,
            return_feature_maps=return_feature_maps,
        )
        model, _, _, _, _ = resume_pretrained_network(config=config)
        model = model.to("cuda").eval()
        model.prepare_to_infer()
        self._models[return_feature_maps] = model
        return model


def _select_feature_maps(outputs: object) -> object:
    """Pull the encoder feature maps out of the upstream model's return tuple."""
    candidate = outputs
    while isinstance(candidate, (tuple, list)):
        if not candidate:
            raise ModelRuntimeError("PlanAura returned no feature maps.")
        candidate = candidate[-1]
    if candidate is None or not hasattr(candidate, "shape"):
        raise ModelRuntimeError("PlanAura returned no feature maps.")
    return candidate


def _to_patch_grid(features: object) -> np.ndarray:
    """Reduce PlanAura feature maps to a ``(embed_dim, rows, cols)`` numpy grid."""

    tensor = features.detach().float()
    while tensor.dim() > 4 and tensor.shape[0] == 1:
        tensor = tensor[0]
    if tensor.dim() == 4:
        tensor = tensor.mean(dim=0) if tensor.shape[0] != 1 else tensor[0]
    if tensor.dim() == 3:
        first, second, third = tensor.shape
        if second == third:
            return tensor.cpu().numpy().astype(np.float32)
        tokens, embed_dim = (second, third) if first == 1 else (first, second)
        flat = tensor.reshape(-1, tensor.shape[-1])[-tokens:]
        side = math.isqrt(tokens)
        if side * side != tokens:
            flat = flat[1:]
            tokens -= 1
            side = math.isqrt(tokens)
            if side * side != tokens:
                raise ModelRuntimeError(
                    f"PlanAura returned {tokens} tokens, which is not a square grid."
                )
        return (
            flat.reshape(side, side, embed_dim)
            .permute(2, 0, 1)
            .cpu()
            .numpy()
            .astype(np.float32)
        )
    raise ModelRuntimeError(
        f"PlanAura feature maps have unsupported rank {tensor.dim()}."
    )


def verify_classifier_head(descriptor: ModelDescriptor) -> Path:
    """Resolve and hash-verify the pinned classifier head, or fail closed."""
    head = descriptor.classifier_head
    if head is None:
        raise ModelRuntimeError(
            f"Profile '{descriptor.profile.value}' has no pinned classifier head."
        )
    configured_path = (os.getenv("GEOFM_CLASSIFIER_HEAD_PATH") or "").strip()
    if configured_path:
        path = Path(configured_path)
    else:
        from huggingface_hub import hf_hub_download

        path = Path(
            hf_hub_download(
                repo_id=head.head_id,
                filename=head.filename,
                revision=head.head_revision,
            )
        )
    verify_checkpoint(path, head.sha256, head.size_bytes)
    return path

"""PyTorch helpers: checksum-verified, pickle-safe weight loading and inference.

Checkpoints are loaded with ``torch.load(weights_only=True)``, which refuses
arbitrary Python objects. Only if the registry entry explicitly sets
``allow_pickle: true`` (an audited admin decision for a checksum-verified
file) is the unrestricted loader used.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.modules.weights import load_registry, resolve


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def load_checkpoint(name: str) -> tuple[Any, str, Path]:
    """Verify and load a checkpoint from the registry. Returns (object, sha256, path)."""
    import torch

    path, sha = resolve(name)
    if path.suffix == ".pt" and _is_torchscript(path):
        obj = torch.jit.load(str(path), map_location="cpu").state_dict()  # type: ignore[no-untyped-call]
        return obj, sha, path
    allow_pickle = bool(load_registry()[name].validation.get("allow_pickle", False))
    try:
        obj = torch.load(str(path), map_location="cpu", weights_only=True)
    except Exception as exc:
        if not allow_pickle:
            raise RuntimeError(
                f"{name}: checkpoint is not loadable with weights_only=True ({exc.__class__.__name__}). "
                "Refusing to unpickle. An admin may set allow_pickle: true in models/registry.yaml "
                "for this checksum-verified file."
            ) from exc
        obj = torch.load(str(path), map_location="cpu", weights_only=False)
    return obj, sha, path


def _is_torchscript(path: Path) -> bool:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            return any(n.endswith("constants.pkl") or "/code/" in n for n in zf.namelist())
    except zipfile.BadZipFile:
        return False


def strip_prefix(state: dict[str, Any], prefix: str = "module.") -> dict[str, Any]:
    return {k[len(prefix):] if k.startswith(prefix) else k: v for k, v in state.items()}


def deterministic_forward(fn: Callable[[], Any]) -> tuple[Any, str]:
    """Run inference in no-grad mode with deterministic kernels.

    If the device has no deterministic implementation for an op, retry with
    ``warn_only=True`` and say so in the returned mode string (recorded in the
    finding's provenance).
    """
    import torch

    with torch.inference_mode():
        try:
            return fn(), "strict"
        except RuntimeError as exc:
            if "deterministic" not in str(exc).lower():
                raise
    torch.use_deterministic_algorithms(True, warn_only=True)
    try:
        with torch.inference_mode():
            return fn(), "warn_only (an op has no deterministic implementation on this device)"
    finally:
        torch.use_deterministic_algorithms(True, warn_only=False)


def device() -> Any:
    import torch

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")

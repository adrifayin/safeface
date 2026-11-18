"""Execution-environment capture and deterministic settings (NFR-R1, NFR-R2)."""

from __future__ import annotations

import os
import platform
import random
import socket
import sys
from functools import lru_cache
from typing import Any

import numpy as np

from app import __version__
from app.core.config import get_settings


def set_deterministic(seed: int) -> dict[str, Any]:
    """Fix all seeds and request deterministic kernels. Returns what was applied."""
    random.seed(seed)
    np.random.seed(seed)
    applied: dict[str, Any] = {"seed": seed}
    try:
        import cv2

        cv2.setRNGSeed(seed)
        cv2.setNumThreads(1)  # thread scheduling can change float summation order
        applied["opencv_threads"] = 1
    except ImportError:
        pass
    try:
        import torch

        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True, warn_only=False)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        applied["torch_deterministic_algorithms"] = True
    except ImportError:
        pass
    return applied


@lru_cache
def static_environment() -> dict[str, Any]:
    """Facts about this process that do not change between jobs."""
    settings = get_settings()
    env: dict[str, Any] = {
        "app_version": __version__,
        "container_image_digest": settings.image_digest,
        "host": socket.gethostname(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "numpy": np.__version__,
    }
    for name in ("cv2", "PIL", "scipy", "skimage", "pywt", "torch", "torchvision", "onnxruntime"):
        try:
            mod = __import__(name)
            env[name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            continue
    env["gpu"] = gpu_info()
    return env


def gpu_info() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return f"{torch.cuda.get_device_name(0)} (CUDA {torch.version.cuda})"
    except ImportError:
        pass
    return "none (CPU)"


def torch_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"

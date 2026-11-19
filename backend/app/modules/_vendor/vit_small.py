"""Minimal ViT-Small/16 (384 px), parameter-compatible with timm's
``vit_small_patch16_384.augreg_in21k_ft_in1k`` as used by Community Forensics
(Park & Owens, CVPR 2025; github.com/JeongsooP/Community-Forensics, MIT):
the timm model with its head replaced by ``nn.Linear(384, 1)``.

Written for SafeFace so no timm dependency is needed. Also provides a reader
for the ``.safetensors`` format (a JSON header plus raw little-endian tensors;
no code is executed when loading, unlike pickle).
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

_DTYPES = {"F32": np.float32, "F16": np.float16, "BF16": None, "I64": np.int64}


def read_safetensors(path: Path) -> dict[str, torch.Tensor]:
    """Read a .safetensors file into CPU tensors (format: u64 header size, JSON header, data)."""
    raw = path.read_bytes()
    (n,) = struct.unpack("<Q", raw[:8])
    header: dict[str, Any] = json.loads(raw[8:8 + n])
    base = 8 + n
    out: dict[str, torch.Tensor] = {}
    for name, meta in header.items():
        if name == "__metadata__":
            continue
        start, end = meta["data_offsets"]
        buf = raw[base + start:base + end]
        if meta["dtype"] == "BF16":
            u16 = np.frombuffer(buf, dtype=np.uint16).astype(np.uint32) << 16
            arr = u16.view(np.float32)
        else:
            dt = _DTYPES.get(meta["dtype"])
            if dt is None:
                raise ValueError(f"unsupported dtype {meta['dtype']} for {name}")
            arr = np.frombuffer(buf, dtype=dt)
        out[name] = torch.from_numpy(arr.reshape(meta["shape"]).copy()).float()
    return out


class Attention(nn.Module):
    def __init__(self, dim: int, heads: int) -> None:
        super().__init__()
        self.heads = heads
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, n, c = x.shape
        qkv = self.qkv(x).reshape(b, n, 3, self.heads, c // self.heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0)
        x = nn.functional.scaled_dot_product_attention(q, k, v)
        return self.proj(x.transpose(1, 2).reshape(b, n, c))


class Mlp(nn.Module):
    def __init__(self, dim: int, hidden: int) -> None:
        super().__init__()
        self.fc1 = nn.Linear(dim, hidden)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.act(self.fc1(x)))


class Block(nn.Module):
    def __init__(self, dim: int, heads: int) -> None:
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-6)
        self.attn = Attention(dim, heads)
        self.norm2 = nn.LayerNorm(dim, eps=1e-6)
        self.mlp = Mlp(dim, dim * 4)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x))
        return x + self.mlp(self.norm2(x))


class PatchEmbed(nn.Module):
    def __init__(self, dim: int, patch: int) -> None:
        super().__init__()
        self.proj = nn.Conv2d(3, dim, kernel_size=patch, stride=patch)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.proj(x).flatten(2).transpose(1, 2)


class ViTSmall384(nn.Module):
    """timm VisionTransformer(img_size=384, patch_size=16, embed_dim=384, depth=12, num_heads=6), token pooling."""

    def __init__(self, dim: int = 384, depth: int = 12, heads: int = 6, patch: int = 16, img: int = 384) -> None:
        super().__init__()
        self.patch_embed = PatchEmbed(dim, patch)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, (img // patch) ** 2 + 1, dim))
        self.blocks = nn.Sequential(*[Block(dim, heads) for _ in range(depth)])
        self.norm = nn.LayerNorm(dim, eps=1e-6)
        self.head = nn.Linear(dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.patch_embed(x)
        x = torch.cat([self.cls_token.expand(x.shape[0], -1, -1), x], dim=1) + self.pos_embed
        x = self.norm(self.blocks(x))
        return self.head(x[:, 0])


def load_commfor(path: Path) -> ViTSmall384:
    """Build the model and load the Community Forensics checkpoint strictly (keys prefixed ``vit.``)."""
    state = read_safetensors(path)
    state = {k.removeprefix("vit."): v for k, v in state.items()}
    model = ViTSmall384()
    model.load_state_dict(state, strict=True)
    return model.eval()

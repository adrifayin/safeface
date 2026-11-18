"""Minimal stand-ins for the only ``yacs`` and ``timm`` symbols the upstream
TruFor inference code imports:

- ``yacs.config.CfgNode``      (configuration tree)
- ``timm.models.layers.DropPath``, ``to_2tuple``, ``trunc_normal_``

They are installed into ``sys.modules`` only if the real packages are absent,
and only while the TruFor module builds its network.
"""

from __future__ import annotations

import ast
import collections.abc
import copy
import sys
import types
from pathlib import Path
from typing import Any

import yaml


def _decode(value: Any) -> Any:
    """yacs decodes string literals such as "('RGB','NP++')" into Python values."""
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


class CfgNode(dict):  # type: ignore[type-arg]
    def __init__(self, init: dict[str, Any] | None = None, new_allowed: bool = False) -> None:
        super().__init__()
        self.__dict__["_frozen"] = False
        self.__dict__["_new_allowed"] = new_allowed
        for k, v in (init or {}).items():
            self[k] = CfgNode(v, new_allowed) if isinstance(v, dict) else v

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        if self.__dict__.get("_frozen"):
            raise AttributeError(f"config is frozen; cannot set {name}")
        self[name] = value

    def freeze(self) -> None:
        self._set_frozen(True)

    def defrost(self) -> None:
        self._set_frozen(False)

    def is_frozen(self) -> bool:
        return bool(self.__dict__["_frozen"])

    def _set_frozen(self, flag: bool) -> None:
        self.__dict__["_frozen"] = flag
        for v in self.values():
            if isinstance(v, CfgNode):
                v._set_frozen(flag)

    def clone(self) -> CfgNode:
        return copy.deepcopy(self)

    def _merge(self, other: dict[str, Any]) -> None:
        for k, v in other.items():
            if k not in self and not self.__dict__["_new_allowed"]:
                raise KeyError(f"unknown config key {k}")
            if isinstance(v, dict):
                if not isinstance(self.get(k), CfgNode):
                    dict.__setitem__(self, k, CfgNode(new_allowed=True))
                self[k]._merge(v)
            else:
                dict.__setitem__(self, k, _decode(v))

    def merge_from_file(self, path: str | Path) -> None:
        self._merge(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})

    def merge_from_list(self, items: list[Any]) -> None:
        for key, value in zip(items[0::2], items[1::2], strict=True):
            node: CfgNode = self
            *parents, leaf = str(key).split(".")
            for p in parents:
                node = node[p]
            dict.__setitem__(node, leaf, _decode(value))


def _to_2tuple(x: Any) -> Any:
    if isinstance(x, collections.abc.Iterable) and not isinstance(x, str):
        return tuple(x)
    return (x, x)


def _drop_path_class() -> type:
    import torch
    from torch import nn

    class DropPath(nn.Module):
        """Stochastic depth; identity at inference (eval mode)."""

        def __init__(self, drop_prob: float = 0.0, scale_by_keep: bool = True) -> None:
            super().__init__()
            self.drop_prob = drop_prob
            self.scale_by_keep = scale_by_keep

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            if self.drop_prob == 0.0 or not self.training:
                return x
            keep = 1 - self.drop_prob
            mask = x.new_empty((x.shape[0],) + (1,) * (x.ndim - 1)).bernoulli_(keep)
            return x * mask / keep if self.scale_by_keep else x * mask

    return DropPath


def install() -> list[str]:
    """Register shim modules where the real packages are missing. Returns names installed."""
    import importlib.util

    from torch import nn

    installed: list[str] = []
    if importlib.util.find_spec("yacs") is None and "yacs" not in sys.modules:
        yacs = types.ModuleType("yacs")
        cfg = types.ModuleType("yacs.config")
        cfg.CfgNode = CfgNode  # type: ignore[attr-defined]
        yacs.config = cfg  # type: ignore[attr-defined]
        sys.modules.update({"yacs": yacs, "yacs.config": cfg})
        installed.append("yacs.config (SafeFace shim)")
    if importlib.util.find_spec("timm") is None and "timm" not in sys.modules:
        timm = types.ModuleType("timm")
        models = types.ModuleType("timm.models")
        layers = types.ModuleType("timm.models.layers")
        layers.DropPath = _drop_path_class()  # type: ignore[attr-defined]
        layers.to_2tuple = _to_2tuple  # type: ignore[attr-defined]
        layers.trunc_normal_ = nn.init.trunc_normal_  # type: ignore[attr-defined]
        models.layers = layers  # type: ignore[attr-defined]
        timm.models = models  # type: ignore[attr-defined]
        sys.modules.update({"timm": timm, "timm.models": models, "timm.models.layers": layers})
        installed.append("timm.models.layers (SafeFace shim)")
    return installed

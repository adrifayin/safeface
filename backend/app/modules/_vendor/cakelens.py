"""CakeLens v5 network, vendored from github.com/LaunchPlatform/cakelens-v5 (cakelens/model.py,
datasets.py, data_types.py, constants.py; branch master, 2025).

MIT License

Copyright (c) 2025 Launch Platform

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

SafeFace changes: removed the Hugging Face download path, gradient
checkpointing, unused classes and logging; frames are prepared from NumPy
(PyAV decode) instead of torchcodec, with the same crop / pad / scaling.
"""

from __future__ import annotations

import functools
from collections import OrderedDict

import numpy as np
import torch
from torch import nn

FRAMESET_COUNT = 9
WINDOW = 512
NORMALIZATION_MEAN = [0.4016435146331787, 0.380405455827713, 0.3688599765300751]
NORMALIZATION_STD = [0.28864356875419617, 0.2775335907936096, 0.27996501326560974]
LABELS = ["AI_GEN", "ANIME_2D", "ANIME_3D", "VIDEO_GAME", "KLING", "HIGGSFIELD", "WAN", "MIDJOURNEY", "HAILUO",
          "RAY", "VEO", "RUNWAY", "SORA", "CHATGPT", "PIKA", "HUNYUAN", "VIDU"]

AffineInstanceNorm3d = functools.partial(nn.InstanceNorm3d, affine=True)


class SkipConnection(nn.Module):
    def __init__(self, main: nn.Module, bypass: nn.Module) -> None:
        super().__init__()
        self.add_module("main", main)
        self.add_module("bypass", bypass)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.main(x) + self.bypass(x)


class Checkpointed(nn.Module):
    """Kept for state-dict key compatibility (``seq.main``); checkpointing removed."""

    def __init__(self, module: nn.Module) -> None:
        super().__init__()
        self.add_module("main", module)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.main(x)


class ZeroPad(nn.Module):
    def __init__(self, pad: tuple[int, ...]) -> None:
        super().__init__()
        self.pad = pad

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return nn.functional.pad(x, self.pad, mode="constant", value=0)


class SpaceTimeConvBlock(nn.Module):
    def __init__(self, in_channels: int, depth: int, channels_step: int = 32) -> None:
        super().__init__()
        self.in_channels, self.depth, self.channels_step = in_channels, depth, channels_step
        modules: OrderedDict[str, nn.Module] = OrderedDict()
        prev = in_channels
        for idx in range(depth):
            space = prev + channels_step
            time = prev + channels_step * 2
            modules[f"space_conv{idx}"] = nn.Conv3d(prev, space, kernel_size=(1, 3, 3), padding="same")
            modules[f"space_relu{idx}"] = nn.LeakyReLU()
            modules[f"space_norm{idx}"] = AffineInstanceNorm3d(space)
            modules[f"time_conv{idx}"] = nn.Conv3d(space, time, kernel_size=(3, 1, 1), padding="same")
            modules[f"time_relu{idx}"] = nn.LeakyReLU()
            modules[f"time_norm{idx}"] = AffineInstanceNorm3d(time)
            prev = time
        to_pad = self.out_channels - in_channels
        half = to_pad // 2
        bypass: nn.Module = ZeroPad((0, 0) * 3 + (half, to_pad - half)) if to_pad else nn.Identity()
        self.add_module("seq", SkipConnection(main=nn.Sequential(modules), bypass=bypass))

    @property
    def out_channels(self) -> int:
        return self.in_channels + self.depth * self.channels_step * 2

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.seq(x)


class ConvGroup(nn.Module):
    def __init__(self, in_channels: int, block_count: int, channels_step: int, depth: int) -> None:
        super().__init__()
        modules: OrderedDict[str, nn.Module] = OrderedDict()
        prev = in_channels
        for idx in range(block_count):
            block = SpaceTimeConvBlock(prev, depth=depth, channels_step=channels_step)
            modules[f"block{idx}"] = block
            prev = block.out_channels
        self.out_channels = prev
        self.add_module("seq", Checkpointed(nn.Sequential(modules)))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.seq(x)


class FullyConnected(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.add_module("seq", nn.Sequential(OrderedDict([
            ("maxpool", nn.MaxPool3d(kernel_size=5)),
            ("flatten", nn.Flatten(start_dim=1)),
            ("linear0", nn.LazyLinear(out_features=512)),
            ("relu0", nn.LeakyReLU()),
            ("linear1", nn.LazyLinear(out_features=256)),
            ("relu1", nn.LeakyReLU()),
            ("linear2", nn.LazyLinear(out_features=128)),
            ("relu2", nn.LeakyReLU()),
            ("relu3", nn.LazyLinear(out_features=len(LABELS))),  # (sic) upstream name of the output layer
        ])))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.seq(x)


class Model(nn.Module):
    def __init__(self, initial_channels: int = 64, block_count: int = 6, block_depth: int = 1,
                 channels_step: int = 32) -> None:
        super().__init__()
        self.add_module("seq", nn.Sequential(OrderedDict([
            ("input_conv0", nn.Conv3d(1, initial_channels, kernel_size=3, stride=3)),
            ("input_relu0", nn.LeakyReLU()),
            ("input_norm0", AffineInstanceNorm3d(initial_channels)),
            ("spacetime_conv_group", ConvGroup(initial_channels, block_count, channels_step, block_depth)),
            ("fully_connected", FullyConnected()),
        ])))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.seq(x)


def frameset_tensor(frames: list[np.ndarray]) -> torch.Tensor:
    """Up to 9 RGB uint8 frames (H, W, 3) -> (1, 27, 512, 512), as upstream read_frames + transform:
    top-left 512x512 crop, zero padding split before/after (space and time), /255, normalise,
    stack RGB of each frame into the depth axis."""
    x = torch.from_numpy(np.stack(frames)).permute(0, 3, 1, 2).float() / 255.0  # (T, 3, H, W)
    x = x[:, :, :WINDOW, :WINDOW]
    t, _, h, w = x.shape
    ph, pw, pt = WINDOW - h, WINDOW - w, FRAMESET_COUNT - t
    x = nn.functional.pad(x, (pw // 2, pw - pw // 2, ph // 2, ph - ph // 2, 0, 0, pt // 2, pt - pt // 2))
    mean = torch.tensor(NORMALIZATION_MEAN).view(1, 3, 1, 1)
    std = torch.tensor(NORMALIZATION_STD).view(1, 3, 1, 1)
    x = (x - mean) / std
    return x.reshape(1, -1, WINDOW, WINDOW)


def build(state: dict[str, torch.Tensor]) -> Model:
    model = Model()
    with torch.no_grad():  # materialise the lazy linear layers with the checkpoint's shapes
        model(torch.zeros(1, 1, FRAMESET_COUNT * 3, WINDOW, WINDOW))
    model.load_state_dict(state, strict=True)
    return model.eval()

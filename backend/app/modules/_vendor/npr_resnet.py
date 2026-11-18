"""NPR detector network (Tan et al., "Rethinking the Up-Sampling Operations in
CNN-based Generative Network for Generalizable Deepfake Detection", CVPR 2024).

Re-implemented from the paper and the authors' published architecture
(github.com/chuangchuangtan/NPR-DeepfakeDetection, networks/resnet50.py): a
ResNet-50 truncated after ``layer2`` whose input is the Neighbouring Pixel
Relationships residual  NPR = x - up(down(x)), with nearest-neighbour
down/up-sampling by a factor of 2. Parameter names follow the upstream
checkpoint so it loads with ``strict=True``; any mismatch fails loudly.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F
from torchvision.models.resnet import Bottleneck


class NPRNet(nn.Module):
    def __init__(self, layers: tuple[int, int] = (3, 4)) -> None:
        super().__init__()
        self.inplanes = 64
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=2, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)
        self.layer1 = self._make_layer(64, layers[0])
        self.layer2 = self._make_layer(128, layers[1], stride=2)
        self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
        self.fc1 = nn.Linear(512, 1)

    def _make_layer(self, planes: int, blocks: int, stride: int = 1) -> nn.Sequential:
        downsample = None
        if stride != 1 or self.inplanes != planes * Bottleneck.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes * Bottleneck.expansion, 1, stride=stride, bias=False),
                nn.BatchNorm2d(planes * Bottleneck.expansion),
            )
        mods = [Bottleneck(self.inplanes, planes, stride, downsample)]
        self.inplanes = planes * Bottleneck.expansion
        mods += [Bottleneck(self.inplanes, planes) for _ in range(1, blocks)]
        return nn.Sequential(*mods)

    @staticmethod
    def npr(x: torch.Tensor) -> torch.Tensor:
        down = F.interpolate(x, scale_factor=0.5, mode="nearest", recompute_scale_factor=True)
        up = F.interpolate(down, scale_factor=2.0, mode="nearest", recompute_scale_factor=True)
        return x - up

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv1(self.npr(x) * 2.0 / 3.0)
        x = self.maxpool(self.relu(self.bn1(x)))
        x = self.layer2(self.layer1(x))
        return self.fc1(torch.flatten(self.avgpool(x), 1))

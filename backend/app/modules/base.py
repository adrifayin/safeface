"""The analysis-module contract.

Every forensic test is a package under ``app/modules/`` exposing a ``MODULE``
object that satisfies :class:`AnalysisModule`. The core never imports a module
by name: modules are discovered by :mod:`app.modules.registry`, so adding a
module requires no change to core code.

A module returns one :class:`Finding`. Findings are independent: nothing in
the system combines them into a single verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class Family(StrEnum):
    INTEGRITY = "INTEGRITY"
    PROVENANCE = "PROVENANCE"
    COMPARISON = "COMPARISON"
    CLASSICAL = "CLASSICAL"
    AI_DETECTOR = "AI_DETECTOR"
    AV = "AV"
    AUDIO = "AUDIO"


# Display order: most court-defensible first (TDD §3.5).
FAMILY_ORDER: list[Family] = [
    Family.INTEGRITY, Family.PROVENANCE, Family.COMPARISON, Family.CLASSICAL,
    Family.AI_DETECTOR, Family.AV, Family.AUDIO,
]

FAMILY_LABELS: dict[Family, str] = {
    Family.INTEGRITY: "Integrity",
    Family.PROVENANCE: "Provenance",
    Family.COMPARISON: "Comparison",
    Family.CLASSICAL: "Classical forensics",
    Family.AI_DETECTOR: "AI detectors (triage indicators)",
    Family.AV: "Audio-visual",
    Family.AUDIO: "Audio",
}


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


@dataclass(frozen=True)
class WorkingCopy:
    """A local, hash-verified copy of an evidence item handed to a module."""

    evidence_id: str
    path: Path
    sha256: str
    md5: str
    media_type: MediaType
    original_filename: str
    kind: str
    # Hashes recorded for the original at ingest, for integrity checks.
    original_sha256: str
    original_md5: str
    # Scratch directory the module may write artefacts into.
    workdir: Path


@dataclass(frozen=True)
class Score:
    """One named number with the information needed to read it correctly."""

    name: str
    value: float | None
    range: tuple[float, float] | None
    meaning: str
    unit: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "range": list(self.range) if self.range else None,
            "meaning": self.meaning,
            "unit": self.unit,
        }


class ArtefactKind(StrEnum):
    HEATMAP = "heatmap"  # same pixel grid as the item; can be overlaid
    IMAGE = "image"      # stand-alone figure (e.g. side-by-side)
    PLOT = "plot"        # Plotly JSON spec
    JSON = "json"        # raw structured output


@dataclass(frozen=True)
class Artefact:
    name: str            # file name, e.g. "ela.png"
    path: Path
    kind: ArtefactKind
    description: str
    content_type: str = "image/png"


@dataclass
class Finding:
    scores: list[Score]
    summary: str
    limitations: str
    artefacts: list[Artefact] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    # Module-specific provenance (weights hashes, library versions). The worker
    # adds the common fields (container digest, hardware, runtime, inputs).
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str = ""


class ModuleUnavailable(Exception):
    """Raised when a module cannot run (missing weights, tool, or refs)."""


@runtime_checkable
class AnalysisModule(Protocol):
    id: str
    version: str
    name: str
    description: str
    family: Family
    media_types: set[MediaType]
    tier: int
    requires_gpu: bool
    requires_reference: bool
    limitations: str
    # Weight names from models/registry.yaml this module needs (may be empty).
    required_weights: list[str]
    default_params: dict[str, Any]
    triage_indicator: bool

    def availability(self) -> Availability: ...

    def merged_params(self, params: dict[str, Any]) -> dict[str, Any]: ...

    def run(self, item: WorkingCopy, refs: list[WorkingCopy], params: dict[str, Any]) -> Finding: ...


class ModuleBase:
    """Convenience defaults; subclasses set the class attributes."""

    id: str = ""
    version: str = "0.0.0"
    name: str = ""
    description: str = ""
    family: Family = Family.CLASSICAL
    media_types: set[MediaType] = {MediaType.IMAGE}  # noqa: RUF012
    tier: int = 1
    requires_gpu: bool = False
    requires_reference: bool = False
    limitations: str = ""
    required_weights: list[str] = []  # noqa: RUF012
    default_params: dict[str, Any] = {}  # noqa: RUF012
    triage_indicator: bool = False

    def availability(self) -> Availability:
        from app.modules.weights import weights_availability

        return weights_availability(self.required_weights)

    def merged_params(self, params: dict[str, Any]) -> dict[str, Any]:
        unknown = set(params) - set(self.default_params)
        if unknown:
            raise ValueError(f"unknown parameters for {self.id}: {sorted(unknown)}")
        return {**self.default_params, **params}

"""Domain objects for raw frames and cycles."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class RawFrame:
    """One binary/hex frame decoded from an e-mail payload."""

    payload: bytes
    cycle: int
    profile: int
    received_at: datetime | None = None
    sensor_id: int | None = None
    #: Source file when the frame was discovered on disk. Decoders that
    #: need sibling files (ARVOR-I ``.eml`` payloads live in a ``.sbd``
    #: sidecar resolved from the path) use this; payload-only decoders
    #: ignore it.
    path: Path | None = None


@dataclass
class CycleData:
    """Raw frames for a single cycle of a float."""

    wmo: int
    cycle: int
    frames: list[RawFrame] = field(default_factory=list)

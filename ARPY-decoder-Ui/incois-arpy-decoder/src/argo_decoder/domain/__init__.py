"""Pure domain model. No I/O, no NumPy dependency, no framework imports."""

from __future__ import annotations

from argo_decoder.domain.frames import CycleData, RawFrame
from argo_decoder.domain.qc import QcFlag, QcTestResult

__all__ = ["CycleData", "QcFlag", "QcTestResult", "RawFrame"]

"""Abstract metadata loader protocol.

All backends (CSV, SQLite, Postgres, ...) implement this interface. The decoder
imports only against :class:`MetadataLoader` so it stays backend-agnostic.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from argo_decoder.metadata.models import FloatInfo, FloatMeta, FloatRegistryRow


@runtime_checkable
class MetadataLoader(Protocol):
    """Interface every metadata backend must satisfy."""

    def get_float(self, wmo: int) -> FloatRegistryRow | None:
        """Return the registry row for a WMO, or ``None`` if unknown."""

    def iter_floats(self, wmos: Iterable[int] | None = None) -> Iterable[FloatRegistryRow]:
        """Iterate over registry rows, optionally restricted to a WMO set."""

    def load_info(self, wmo: int) -> FloatInfo:  # pragma: no cover - protocol
        """Materialize the ``FloatInfo`` (decoding parameters) for a WMO."""

    def load_meta(self, wmo: int) -> FloatMeta:  # pragma: no cover - protocol
        """Materialize the ``FloatMeta`` (Argo metadata) for a WMO."""

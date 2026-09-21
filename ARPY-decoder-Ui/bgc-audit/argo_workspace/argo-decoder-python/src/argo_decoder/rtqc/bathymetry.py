"""GEBCO bathymetry lookup for RTQC TEST004 (position on land).

The GEBCO global grid is a single netCDF holding ``lon``, ``lat`` and
``elevation`` (metres, **positive up**), so ``elevation > 0`` is land and
``elevation < 0`` is seabed. At 15 arc-seconds the global array is
43 200 x 86 400 cells -- about 7 GB uncompressed -- so it must never be
read into memory in full.

This module mirrors the approach Coriolis uses in
``decArgo_soft/soft/util/sub/get_gebco_elev_zone.m``: open the file once,
keep only the two coordinate vectors resident, and read a small window
out of ``elevation`` per query. Memory stays flat regardless of grid
size.

The grid is an **external dependency**: it is never committed, and the
path comes from configuration (``rtqc.reference_files.gebco_file`` /
``TEST004_GEBCO_FILE``). When the file is absent the loader raises and
callers fall back to "test not run" rather than guessing -- an
unavailable reference must never silently become a passing test.
"""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

#: Elevation at or above this (metres, positive up) is treated as land.
#: GEBCO's zero is mean sea level, so the shoreline is the natural cut.
LAND_ELEVATION_M = 0.0

#: Names accepted for the elevation variable. GEBCO ships ``elevation``;
#: some redistributions rename it, so a small alias list avoids failing
#: on an otherwise valid grid.
_ELEVATION_NAMES = ("elevation", "z", "Band1")
_LON_NAMES = ("lon", "longitude", "x")
_LAT_NAMES = ("lat", "latitude", "y")


class BathymetryUnavailableError(RuntimeError):
    """Raised when the GEBCO grid cannot be opened or has no usable variables."""


def _first_present(ds: Any, names: tuple[str, ...], kind: str, path: Path) -> str:
    for name in names:
        if name in ds.variables:
            return name
    raise BathymetryUnavailableError(
        f"{path}: no {kind} variable found (looked for {', '.join(names)})"
    )


class GebcoGrid:
    """Point lookups against a global GEBCO netCDF grid.

    Only the ``lon``/``lat`` vectors are held in memory (a few MB); the
    ``elevation`` array stays on disk and is sampled one cell at a time.

    Use as a context manager, or call :meth:`close` when finished::

        with GebcoGrid(path) as grid:
            elev = grid.elevation_at(-53.1, 68.2)
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise BathymetryUnavailableError(f"GEBCO grid not found: {self.path}")
        try:
            import netCDF4
        except ImportError as exc:  # pragma: no cover - netCDF4 is a hard dep
            raise BathymetryUnavailableError("netCDF4 is required to read GEBCO") from exc
        try:
            self._ds = netCDF4.Dataset(self.path)
        except OSError as exc:
            raise BathymetryUnavailableError(f"cannot open GEBCO grid {self.path}: {exc}") from exc
        try:
            lon_name = _first_present(self._ds, _LON_NAMES, "longitude", self.path)
            lat_name = _first_present(self._ds, _LAT_NAMES, "latitude", self.path)
            self._elev_name = _first_present(self._ds, _ELEVATION_NAMES, "elevation", self.path)
            self._lon = np.asarray(self._ds.variables[lon_name][:], dtype=np.float64)
            self._lat = np.asarray(self._ds.variables[lat_name][:], dtype=np.float64)
        except Exception:
            self._ds.close()
            raise
        self._elev = self._ds.variables[self._elev_name]
        # Reading a fill-valued cell must yield the raw number, not a
        # masked constant that later coerces to 0 -- the failure mode
        # already recorded for GROUNDED and STARTUP_DATE_QC.
        self._elev.set_auto_maskandscale(False)

    def __enter__(self) -> GebcoGrid:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._ds.close()
        except (OSError, RuntimeError):  # pragma: no cover - already closed
            pass

    def elevation_at(self, latitude: float, longitude: float) -> float | None:
        """Return grid elevation in metres (positive up) at a position.

        Longitudes are normalised into the grid's own range, so callers
        may pass either ``0..360`` or ``-180..180``. Returns ``None``
        when the position is not finite or falls outside the grid.
        """
        if not (np.isfinite(latitude) and np.isfinite(longitude)):
            return None
        if not (-90.0 <= latitude <= 90.0):
            return None
        lon = float(longitude)
        lon_min, lon_max = float(self._lon[0]), float(self._lon[-1])
        # GEBCO is -180..180; accept 0..360 input by wrapping.
        if lon > lon_max:
            lon -= 360.0
        elif lon < lon_min:
            lon += 360.0
        if not (lon_min - 1.0 <= lon <= lon_max + 1.0):
            return None
        i = int(np.abs(self._lat - float(latitude)).argmin())
        j = int(np.abs(self._lon - lon).argmin())
        try:
            value = float(np.asarray(self._elev[i, j]).reshape(-1)[0])
        except (IndexError, OSError):  # pragma: no cover - defensive
            return None
        return value if np.isfinite(value) else None

    def is_on_land(self, latitude: float, longitude: float) -> bool | None:
        """True when the position sits at or above sea level.

        Returns ``None`` when the grid cannot answer -- "unknown" is not
        the same as "at sea", and the caller must be able to tell them
        apart so the test can report as not run.
        """
        elevation = self.elevation_at(latitude, longitude)
        if elevation is None:
            return None
        return elevation >= LAND_ELEVATION_M


def open_gebco(path: Path | str | None) -> GebcoGrid | None:
    """Open the grid, or return ``None`` when it is not configured/present.

    Callers use ``None`` to mean "TEST004 cannot run", which is recorded
    as a test that did not execute rather than one that passed.
    """
    if path is None:
        return None
    try:
        return GebcoGrid(path)
    except BathymetryUnavailableError:
        return None

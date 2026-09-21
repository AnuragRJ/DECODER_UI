"""Profile-scalar RTQC tests (TEST001, TEST002, TEST003).

These operate on whole-profile scalar metadata (JULD, LATITUDE, LONGITUDE,
platform identification) rather than on N_LEVELS vertical arrays.  They
mirror the MATLAB ``add_rtqc_to_profile_file.m`` scalar tests:

* **TEST001 — Platform identification:** the float's WMO / decoder id /
  platform family must be known to the decoder table (trivial in the
  Python pipeline because a profile cannot exist unless ``can_handle()``
  succeeded; kept for API completeness so callers can mark unknown
  platforms).
* **TEST002 — Impossible date:** JULD must be after 1997-01-01 00:00 UTC
  (Argo programme start) and before ``now_utc``.  Failed samples set
  JULD_QC = BAD (4).
* **TEST003 — Impossible location:** LATITUDE must be in [-90, 90] and
  LONGITUDE in [-180, 180].  Failed samples set POSITION_QC = BAD (4).

* **TEST004 — Position on land:** runs only when a bathymetry grid is
  supplied via ``bathymetry``. GEBCO elevation is positive up, so a
  position at or above 0 m is land and sets POSITION_QC = BAD (4).
  Without a grid the test is reported as *not run* rather than passed.

TEST005 (impossible speed) needs the prior cycle fix and lives in
:mod:`argo_decoder.rtqc.cross_cycle`.

All routines are pure numpy / Python functions so they can be unit
tested in isolation.  ``QcFlag`` bytes are returned as ``|S1`` numpy
scalars to match the Argo NetCDF on-disk convention used elsewhere in
the decoder; ``None`` inputs are treated as fill and flagged BAD.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np

from argo_decoder.domain.qc import QcFlag

# Argo epoch: 1997-01-01 00:00 UTC (datenum ref for TEST002 lower bound)
_ARGO_START_JULD = (
    datetime(1997, 1, 1, tzinfo=UTC) - datetime(1950, 1, 1, tzinfo=UTC)
).total_seconds() / 86400.0
# JULD fill value used by our NetCDF writer
_JULD_FILL = 999999.0
# Lat/Lon fill values
_LAT_FILL = 99999.0
_LON_FILL = 99999.0


class LandCheck(Protocol):
    """Minimal surface TEST004 needs from a bathymetry source.

    Kept structural so the tests can substitute a trivial stub and the
    RTQC layer never imports netCDF4 just to describe a dependency.
    ``None`` means the grid cannot answer for that position.
    """

    def is_on_land(self, latitude: float, longitude: float) -> bool | None: ...


@dataclass(frozen=True)
class ScalarQcOutcome:
    """Result of running the profile-scalar RTQC tests."""

    juld_qc: bytes
    position_qc: bytes
    tests_done: tuple[str, ...]
    tests_failed: tuple[str, ...]
    messages: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "juld_qc": self.juld_qc,
            "position_qc": self.position_qc,
            "tests_done": list(self.tests_done),
            "tests_failed": list(self.tests_failed),
            "messages": list(self.messages),
        }


def _qchar(flag: QcFlag) -> bytes:
    """Return single-byte QC char matching Argo NetCDF on-disk convention."""
    return str(int(flag)).encode("ascii")


def run_profile_scalar_tests(
    *,
    juld: float | None,
    latitude: float | None,
    longitude: float | None,
    platform_known: bool = True,
    now_utc: datetime | None = None,
    juld_qc_in: bytes | None = None,
    position_qc_in: bytes | None = None,
    bathymetry: LandCheck | None = None,
) -> ScalarQcOutcome:
    """Run TEST001/002/003 against profile scalar metadata.

    Parameters mirror the scalars set by
    :func:`argo_decoder.platforms.provor_ir_sbd.profile._assign_profile_scalars`.
    The incoming ``*_qc_in`` flags are taken as the pre-RTQC values
    (``b'1'`` for a valid GPS fix, ``b'0'`` for ``NO_QC``, etc.).  If
    ``None`` we default to ``b'1'`` for known-located samples and
    ``b'4'`` when the coordinate itself is missing.

    The merge rule is worst-flag wins: an existing GOOD (``1``) can be
    downgraded to BAD (``4``); a NO_QC (``0``) or already-BAD (``4``) is
    preserved.
    """
    tests_done: list[str] = []
    tests_failed: list[str] = []
    messages: list[str] = []

    # ---- TEST001: platform identification ----
    tests_done.append("TEST001_PLATFORM_IDENTIFICATION")
    if not platform_known:
        tests_failed.append("TEST001_PLATFORM_IDENTIFICATION")
        messages.append("platform unknown to decoder table")
    # Platform failure does NOT downgrade JULD/POSITION QC by itself;
    # it only sets the profile QC hex mask.

    # ---- Default incoming QC ----
    if juld_qc_in is None:
        juld_qc = _qchar(QcFlag.GOOD) if juld is not None else _qchar(QcFlag.MISSING)
    else:
        juld_qc = bytes(juld_qc_in)[0:1]
    if position_qc_in is None:
        if latitude is not None and longitude is not None:
            position_qc = _qchar(QcFlag.GOOD)
        else:
            position_qc = _qchar(QcFlag.MISSING)
    else:
        position_qc = bytes(position_qc_in)[0:1]

    def _worst(existing: bytes, new: QcFlag) -> bytes:
        old_val = int(existing) if existing.isdigit() else int(QcFlag.NO_QC)
        return _qchar(QcFlag(max(old_val, int(new))))

    # ---- TEST002: impossible date ----
    tests_done.append("TEST002_IMPOSSIBLE_DATE")
    if juld is None or not np.isfinite(juld) or juld >= _JULD_FILL:
        juld_qc = _worst(juld_qc, QcFlag.MISSING)
    else:
        now_juld = (
            (datetime.now(UTC) - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0
            if now_utc is None
            else (now_utc - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0
        )
        if juld < _ARGO_START_JULD or juld > now_juld:
            juld_qc = _worst(juld_qc, QcFlag.BAD)
            tests_failed.append("TEST002_IMPOSSIBLE_DATE")
            messages.append(f"JULD={juld:.3f} outside [1997-01-01, now]")

    # ---- TEST003: impossible location ----
    tests_done.append("TEST003_IMPOSSIBLE_LOCATION")
    if (
        latitude is None
        or longitude is None
        or not np.isfinite(latitude)
        or not np.isfinite(longitude)
        or latitude >= _LAT_FILL
        or longitude >= _LON_FILL
    ):
        position_qc = _worst(position_qc, QcFlag.MISSING)
    else:
        if latitude < -90.0 or latitude > 90.0 or longitude < -180.0 or longitude > 180.0:
            position_qc = _worst(position_qc, QcFlag.BAD)
            tests_failed.append("TEST003_IMPOSSIBLE_LOCATION")
            messages.append(f"LAT={latitude:.4f} LON={longitude:.4f} outside valid range")

    # ---- TEST004: position on land ----
    # Only runs when a bathymetry grid is supplied. "Grid absent" is
    # recorded as *not run*, never as a pass: an unavailable reference
    # must not silently certify a position as at sea. A position already
    # rejected by TEST003 is not re-tested -- there is no sensible cell
    # to look up for an out-of-range coordinate.
    if (
        bathymetry is not None
        and latitude is not None
        and longitude is not None
        and "TEST003_IMPOSSIBLE_LOCATION" not in tests_failed
        and np.isfinite(latitude)
        and np.isfinite(longitude)
        and latitude < _LAT_FILL
        and longitude < _LON_FILL
    ):
        on_land = bathymetry.is_on_land(float(latitude), float(longitude))
        if on_land is not None:
            tests_done.append("TEST004_POSITION_ON_LAND")
            if on_land:
                position_qc = _worst(position_qc, QcFlag.BAD)
                tests_failed.append("TEST004_POSITION_ON_LAND")
                messages.append(f"LAT={latitude:.4f} LON={longitude:.4f} is on land per bathymetry")

    return ScalarQcOutcome(
        juld_qc=juld_qc,
        position_qc=position_qc,
        tests_done=tuple(tests_done),
        tests_failed=tuple(tests_failed),
        messages=tuple(messages),
    )


__all__ = [
    "LandCheck",
    "ScalarQcOutcome",
    "run_profile_scalar_tests",
]

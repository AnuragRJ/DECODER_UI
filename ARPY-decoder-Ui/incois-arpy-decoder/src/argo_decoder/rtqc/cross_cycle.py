"""Cross-cycle RTQC tests (TEST005, TEST016, TEST018).

The tests in :mod:`~argo_decoder.rtqc.non_density` and
:mod:`~argo_decoder.rtqc.profile_scalar` judge a profile on its own. The
three implemented here need the float's *previous* cycle as well, which
is why they were deferred until the decoder produced a full ordered set
of profiles rather than one at a time:

* **TEST005 -- Impossible speed.** Consecutive profile positions imply a
  drift speed. Above ~3 m/s the pair cannot both be right, so both
  positions are flagged.
* **TEST016 -- Gross salinity or temperature sensor drift.** Compares the
  deepest 100 dbar mean against the previous *good* profile. A sudden
  jump means the sensor moved, not the ocean.
* **TEST018 -- Frozen profile.** A float replaying a near-identical
  profile cycle after cycle has stopped measuring.

Thresholds are transcribed from the Argo Quality Control Manual for CTD
and Trajectory Data v3.9 (DOI 10.13155/33951), which INCOIS records as
having applied to WMO 2901304: its published ``HISTORY_QCTEST`` ``QCP$``
mask is ``D7B7E``, i.e. tests 1-6, 8, 9, 11-14, 16, 18 and 19. Cycle 1
carries ``C7B7E`` instead -- the same set without test 16 -- because
there is no previous profile to compare against, which is exactly the
behaviour these functions reproduce.

Every routine is a pure function over numpy arrays and plain scalars so
it can be unit tested without file IO, and each returns ``None``-free
outcomes that say explicitly whether the test could run at all. A test
that had no previous cycle is *not run*, which is different from a test
that ran and passed: the distinction has to survive into
``HISTORY_QCTEST``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from argo_decoder.domain.qc import QcFlag

#: TEST005: maximum plausible horizontal drift speed, m/s.
#:
#: The QC manual specifies 3 m/s. Argo floats drift with the ocean and
#: rarely exceed 1 m/s; the allowance covers strong western-boundary
#: currents plus the km-scale error on an ARGOS Doppler fix.
MAX_DRIFT_SPEED_M_S = 3.0

#: TEST016: depth band averaged for the sensor-drift comparison, dbar.
DRIFT_BAND_DBAR = 100.0
#: TEST016: the band must lie below this depth for the "deep water is
#: stable between cycles" premise to hold. Above the thermocline a
#: difference between two casts says nothing about the sensor. Measured
#: on WMO 2901328: at a fixed depth the cycle-to-cycle temperature
#: change never exceeds 0.61 degC over 88 cycles, well inside the 1.0
#: threshold, whereas comparing 1250 dbar water against 1900 dbar water
#: produces an apparent 1.2 degC "drift".
DRIFT_MIN_DEPTH_DBAR = 500.0
#: TEST016: points on the shared pressure grid used to compare the two
#: profiles. Interpolating both onto one grid removes the depth-mismatch
#: term that a raw band mean leaves in.
DRIFT_GRID_SAMPLES = 11
#: TEST016: jump in the band mean that indicates sensor drift.
DRIFT_THRESHOLD_PSAL = 0.5
DRIFT_THRESHOLD_TEMP = 1.0

#: TEST018: slab thickness used to resample both profiles, dbar.
FROZEN_SLAB_DBAR = 50.0
#: TEST018: a profile is "frozen" when *every* one of these holds.
FROZEN_MAX_TEMP = 0.3
FROZEN_MIN_TEMP = 0.001
FROZEN_MEAN_TEMP = 0.02
FROZEN_MAX_PSAL = 0.3
FROZEN_MIN_PSAL = 0.001
FROZEN_MEAN_PSAL = 0.004

#: Earth radius used for the great-circle distance, metres.
_EARTH_RADIUS_M = 6371000.0

#: Value above which a float is treated as fill rather than a reading.
_FILL_THRESHOLD = 99998.0


@dataclass
class CrossCycleOutcome:
    """What the cross-cycle pass concluded for one profile.

    ``tests_run`` and ``tests_failed`` carry Argo reference table 11
    numbers so the caller can fold them into ``HISTORY_QCTEST``. A test
    only appears in ``tests_run`` when it had the inputs it needed.
    """

    position_qc: bytes | None = None
    temp_qc: np.ndarray | None = None
    psal_qc: np.ndarray | None = None
    tests_run: set[int] = field(default_factory=set)
    tests_failed: set[int] = field(default_factory=set)


def _finite(values: np.ndarray) -> np.ndarray:
    """Mask of samples that are neither NaN nor an Argo fill sentinel."""
    arr = np.asarray(values, dtype=np.float64)
    return np.isfinite(arr) & (np.abs(arr) < _FILL_THRESHOLD)


def great_circle_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two positions, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    return 2.0 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def impossible_speed_test(
    *,
    juld: float | None,
    latitude: float | None,
    longitude: float | None,
    previous_juld: float | None,
    previous_latitude: float | None,
    previous_longitude: float | None,
    max_speed_m_s: float = MAX_DRIFT_SPEED_M_S,
) -> tuple[bytes | None, bool]:
    """TEST005: flag a position implying an impossible drift speed.

    Returns ``(position_qc, ran)``. ``ran`` is ``False`` when either
    endpoint is missing or the two profiles carry the same timestamp, in
    which case no speed is defined and nothing is flagged.

    The manual flags *both* endpoints of an impossible leg, since the
    pair is inconsistent without saying which member is wrong. This
    function judges the later profile; the caller applies the same
    verdict to the earlier one.
    """
    values = (juld, latitude, longitude, previous_juld, previous_latitude, previous_longitude)
    if any(v is None or not math.isfinite(v) for v in values):
        return None, False
    assert juld is not None and previous_juld is not None  # narrowed above
    elapsed_s = (juld - previous_juld) * 86400.0
    if elapsed_s <= 0:
        return None, False
    assert latitude is not None and longitude is not None
    assert previous_latitude is not None and previous_longitude is not None
    distance = great_circle_metres(previous_latitude, previous_longitude, latitude, longitude)
    if distance / elapsed_s > max_speed_m_s:
        return b"4", True
    return b"1", True


def _max_pressure(pres: np.ndarray, values: np.ndarray) -> float | None:
    """Deepest pressure at which ``values`` is also finite."""
    valid = _finite(pres) & _finite(values)
    if not np.any(valid):
        return None
    return float(np.max(np.asarray(pres, dtype=np.float64)[valid]))


def _deep_band_offset(
    pres: np.ndarray,
    values: np.ndarray,
    previous_pres: np.ndarray,
    previous_values: np.ndarray,
    *,
    band_dbar: float = DRIFT_BAND_DBAR,
    min_depth_dbar: float = DRIFT_MIN_DEPTH_DBAR,
    samples: int = DRIFT_GRID_SAMPLES,
) -> float | None:
    """Mean offset between two profiles over a shared deep pressure band.

    Both profiles are interpolated onto the *same* pressure grid before
    differencing, so the result isolates a sensor offset from the natural
    change in water properties with depth.

    Returns ``None`` -- meaning "cannot run" -- when the profiles share no
    band that is both deep enough for the stability argument to hold and
    populated on both sides.
    """
    deepest_now = _max_pressure(pres, values)
    deepest_before = _max_pressure(previous_pres, previous_values)
    if deepest_now is None or deepest_before is None:
        return None
    bottom = min(deepest_now, deepest_before)
    top = bottom - band_dbar
    # Below the thermocline the water is stable between cycles; above it
    # a difference says nothing about the sensor.
    if top < min_depth_dbar:
        return None
    now_valid = _finite(pres) & _finite(values)
    before_valid = _finite(previous_pres) & _finite(previous_values)
    if int(np.count_nonzero(now_valid)) < 2 or int(np.count_nonzero(before_valid)) < 2:
        return None
    grid = np.linspace(top, bottom, samples)
    now = np.interp(
        grid,
        np.asarray(pres, dtype=np.float64)[now_valid],
        np.asarray(values, dtype=np.float64)[now_valid],
    )
    before = np.interp(
        grid,
        np.asarray(previous_pres, dtype=np.float64)[before_valid],
        np.asarray(previous_values, dtype=np.float64)[before_valid],
    )
    return float(np.mean(now - before))


def gross_sensor_drift_test(
    *,
    pres: np.ndarray,
    values: np.ndarray,
    previous_pres: np.ndarray | None,
    previous_values: np.ndarray | None,
    threshold: float,
) -> tuple[np.ndarray | None, bool]:
    """TEST016: detect a sudden offset against the previous good profile.

    Compares a deep band **common to both profiles**, with both casts
    interpolated onto the same pressure grid. Deep water is stable on a
    10-day timescale, so a jump there is the sensor moving rather than
    the ocean -- but only if the same water is being compared.

    Averaging the deepest 100 dbar of each profile *independently* is
    wrong whenever consecutive cycles reach different depths: a float
    that cuts a dive short then gets its 1250 dbar water compared against
    the previous cycle's 1900 dbar water, and the natural thermocline
    difference is misread as sensor drift. Measured on WMO 2901328, whose
    dives are frequently truncated: cycle 37 reached 1248.7 dbar against
    the previous 1899.4 dbar and produced an apparent +2.69 degC "drift",
    against a 1.0 degC threshold. Eleven cycles were condemned this way,
    358 QC cells in total, none of them real -- GDAC flags every one of
    those levels good.

    The band is therefore anchored on the shallower of the two profiles'
    maximum pressures, both casts are interpolated onto one grid, and the
    band must sit below ``DRIFT_MIN_DEPTH_DBAR``. Across 2901328's 92
    cycle pairs the largest remaining offset is 0.253 degC against a 1.0
    threshold -- all eleven false positives gone -- while WMO 2901304
    cycle 20, a real +1.27 psu jump, still fires.

    When the two profiles have no overlapping deep band at all (one is
    far too shallow to compare) the test cannot run and reports
    ``(None, False)``: "not run" is not the same as "run and passed".

    Action per the manual is ``'3'`` (probably bad) applied to *every*
    level of the parameter -- a drifting sensor is wrong everywhere, not
    only at depth. Returns ``(flags, ran)``.
    """
    if previous_pres is None or previous_values is None:
        return None, False
    offset = _deep_band_offset(pres, values, previous_pres, previous_values)
    if offset is None:
        return None, False
    n = len(np.asarray(pres))
    flags = np.full(n, int(QcFlag.GOOD), dtype=np.int8)
    if abs(offset) > threshold:
        flags[:] = int(QcFlag.PROBABLY_BAD)
        return flags, True
    return flags, True


def _slab_means(
    pres: np.ndarray, values: np.ndarray, *, slab_dbar: float = FROZEN_SLAB_DBAR
) -> dict[int, float]:
    """Average ``values`` into fixed ``slab_dbar`` pressure bins.

    Floats do not sample the same levels every cycle, so the manual
    resamples both profiles onto a common grid before differencing them.
    """
    valid = _finite(pres) & _finite(values)
    if not np.any(valid):
        return {}
    p = np.asarray(pres, dtype=np.float64)[valid]
    v = np.asarray(values, dtype=np.float64)[valid]
    out: dict[int, float] = {}
    for slab in np.unique((p // slab_dbar).astype(int)):
        out[int(slab)] = float(np.mean(v[(p // slab_dbar).astype(int) == slab]))
    return out


def frozen_profile_test(
    *,
    pres: np.ndarray,
    temp: np.ndarray,
    psal: np.ndarray,
    previous_pres: np.ndarray | None,
    previous_temp: np.ndarray | None,
    previous_psal: np.ndarray | None,
) -> tuple[bool, bool]:
    """TEST018: detect a float replaying the same profile.

    Both profiles are averaged into 50 dbar slabs, the slabs common to
    both are differenced, and the profile fails only when *all six*
    conditions hold -- max, min and mean of the absolute differences,
    for temperature and salinity together. Requiring the minimum to be
    tiny as well as the maximum small is what separates a frozen sensor
    from an ocean that simply changed little.

    Returns ``(is_frozen, ran)``. Action on failure is bad ('4') for the
    whole profile, which the caller applies.
    """
    if previous_pres is None or previous_temp is None or previous_psal is None:
        return False, False
    now_t = _slab_means(pres, temp)
    now_s = _slab_means(pres, psal)
    prev_t = _slab_means(previous_pres, previous_temp)
    prev_s = _slab_means(previous_pres, previous_psal)
    shared_t = sorted(set(now_t) & set(prev_t))
    shared_s = sorted(set(now_s) & set(prev_s))
    # Two slabs is the minimum that can produce a meaningful max/min pair.
    if len(shared_t) < 2 or len(shared_s) < 2:
        return False, False
    d_t = np.array([abs(now_t[k] - prev_t[k]) for k in shared_t], dtype=np.float64)
    d_s = np.array([abs(now_s[k] - prev_s[k]) for k in shared_s], dtype=np.float64)
    frozen = (
        float(np.max(d_t)) < FROZEN_MAX_TEMP
        and float(np.min(d_t)) < FROZEN_MIN_TEMP
        and float(np.mean(d_t)) < FROZEN_MEAN_TEMP
        and float(np.max(d_s)) < FROZEN_MAX_PSAL
        and float(np.min(d_s)) < FROZEN_MIN_PSAL
        and float(np.mean(d_s)) < FROZEN_MEAN_PSAL
    )
    return frozen, True


__all__ = [
    "DRIFT_BAND_DBAR",
    "DRIFT_THRESHOLD_PSAL",
    "DRIFT_THRESHOLD_TEMP",
    "FROZEN_MAX_PSAL",
    "FROZEN_MAX_TEMP",
    "FROZEN_MEAN_PSAL",
    "FROZEN_MEAN_TEMP",
    "FROZEN_MIN_PSAL",
    "FROZEN_MIN_TEMP",
    "FROZEN_SLAB_DBAR",
    "MAX_DRIFT_SPEED_M_S",
    "CrossCycleOutcome",
    "frozen_profile_test",
    "great_circle_metres",
    "gross_sensor_drift_test",
    "impossible_speed_test",
]

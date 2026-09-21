"""Common profile RTQC orchestration over decoded mono-profile datasets.

This module is the product-facing entry point of the **common** RTQC
engine (``argo_decoder.rtqc``). It applies the applicable automatic
real-time QC set to a float's ordered mono-profile datasets --
test-by-test, with truthful provenance:

* per profile: TEST001-004 (scalar, bathymetry-gated), TEST006, 008,
  009, 011 (INCOIS parity), 012, 013, 019 (configuration-gated) and
  TEST014 (position-gated);
* across profiles: TEST005/016/018 via
  :func:`argo_decoder.rtqc.cross_cycle_pass.apply_cross_cycle_rtqc`.

Every test is recorded as *executed* in the ``QCP$`` mask only when it
actually ran on that profile; a test that could not run (no bathymetry
grid for TEST004, no CONFIG_ProfilePressure_dbar for TEST019, no
previous cycle for TEST005/016/018, no position for TEST014) is simply
absent from the mask -- skipped is never counted as passed. Failed
tests populate ``QCF$``. Both masks use the Coriolis
``get_qctest_flag.m`` convention (bit *n* = test *n*), which the mono
writer already emits as ``HISTORY`` ``QCP$``/``QCF$`` records.

Datasets are mutated in place: ``PRES/TEMP/PSAL_QC`` (and ``CNDC_QC``
when present) are degraded worst-flag-wins, ``JULD_QC``/``POSITION_QC``
scalars are folded, and the pre-RTQC flags are captured in the
``qc_previous_values`` attribute so the writer's ``CF`` history records
carry truthful previous values. The caller keeps responsibility for
product shaping (e.g. re-deriving ``PROFILE_<PARAM>_QC`` letters).

The record contract is deliberately small so any platform decoder can
adopt it: objects exposing ``.cycle`` (int), ``.dataset``
(:class:`xarray.Dataset` with ADMT-style ``PRES``/``TEMP``/``PSAL``/
``*_QC``/``JULD``/``LATITUDE``/``LONGITUDE`` variables and Argo fill
sentinels) and optionally ``.direction``. No platform module is
imported here and no WMO/cycle-specific logic exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import xarray as xr

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.cross_cycle_pass import apply_cross_cycle_rtqc
from argo_decoder.rtqc.density_inversion import density_inversion_test
from argo_decoder.rtqc.non_density import run_non_density_tests
from argo_decoder.rtqc.profile_scalar import LandCheck, run_profile_scalar_tests

#: Argo reference table 11 numbers for the per-profile tests.
_SCALAR_TEST_NUMBERS = {
    "TEST001_PLATFORM_IDENTIFICATION": 1,
    "TEST002_IMPOSSIBLE_DATE": 2,
    "TEST003_IMPOSSIBLE_LOCATION": 3,
    "TEST004_POSITION_ON_LAND": 4,
}
_DENSITY_TEST = 14
#: run_non_density_tests covers these; 19 is conditional on the
#: configuration pressure being known (see below).
_NON_DENSITY_TESTS = {6, 8, 9, 11, 12, 13}
_DEEPEST_PRESSURE_TEST = 19

_FILL = 99998.0  # Argo sentinel threshold (99999/999999-class are fills)


def _levels(ds: xr.Dataset, name: str) -> np.ndarray:
    """Level array with Argo fill sentinels mapped to NaN."""
    v = np.asarray(ds[name].values, dtype=np.float64).reshape(-1)
    v[np.abs(v) >= _FILL] = np.nan
    return v


def _scalar(ds: xr.Dataset, name: str) -> float | None:
    raw = np.asarray(ds[name].values, dtype=np.float64).reshape(-1)
    if raw.size == 0:
        return None
    value = float(raw[0])
    return value if np.isfinite(value) and abs(value) < _FILL else None


def _flags_to_int(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values).reshape(-1)
    if arr.dtype.kind in ("S", "O"):
        out = np.full(arr.size, int(QcFlag.NO_QC), dtype=np.int8)
        for i, item in enumerate(arr):
            raw = bytes(item).strip() if isinstance(item, (bytes, np.bytes_)) else b""
            if raw.isdigit():
                out[i] = int(raw)
        return out
    return arr.astype(np.int8)


def _flags_to_chars(values: np.ndarray) -> np.ndarray:
    return np.array([str(int(v)).encode("ascii") for v in values], dtype="S1")


def _worsen_level_qc(ds: xr.Dataset, name: str, extra: np.ndarray) -> bool:
    qc_name = f"{name}_QC"
    if qc_name not in ds:
        return False
    stored = np.asarray(ds[qc_name].values).reshape(-1)
    current = _flags_to_int(stored)
    if current.shape != extra.shape:
        return False
    merged = np.maximum(current, extra).astype(np.int8)
    if np.array_equal(merged, current):
        return False
    final = _flags_to_chars(merged) if stored.dtype.kind == "S" else merged
    attrs = dict(ds[qc_name].attrs)
    ds[qc_name] = (ds[qc_name].dims, final.reshape(ds[qc_name].shape))
    ds[qc_name].attrs.update(attrs)  # long_name/conventions/_FillValue survive
    return True


def _worsen_scalar_qc(ds: xr.Dataset, name: str, flag: bytes) -> None:
    if name not in ds:
        return
    stored = np.asarray(ds[name].values).reshape(-1)
    current = _flags_to_int(stored)
    new = _flags_to_int(np.array([flag], dtype="S1"))[0]
    merged = int(max(current[0], new)) if current.size else int(new)
    final = np.array([str(merged).encode("ascii")], dtype="S1")
    attrs = dict(ds[name].attrs)
    ds[name] = (ds[name].dims, final.reshape(ds[name].shape))
    ds[name].attrs.update(attrs)


def _merge_mask(ds: xr.Dataset, key: str, numbers: set[int]) -> None:
    raw = ds.attrs.get(key)
    mask = 0
    if isinstance(raw, str) and raw:
        try:
            mask = int(raw, 16)
        except ValueError:
            mask = 0
    for number in numbers:
        mask |= 1 << int(number)
    ds.attrs[key] = format(mask, "X") if mask else "0"


def apply_rtqc_to_profiles(
    records: list[Any],
    *,
    bathymetry: LandCheck | None = None,
    profile_pressure_dbar: float | None = None,
    platform_known: bool = True,
    now_utc: datetime | None = None,
) -> dict[int, dict[str, Any]]:
    """Run the applicable real-time QC set over one float's profiles.

    ``records`` must be ordered products of one float; each exposes
    ``.cycle``, ``.dataset`` and optionally ``.direction`` (only
    ascending profiles participate, matching the publication policy --
    pass a pre-filtered list for decoders that publish both). Returns a
    per-cycle summary ``{cycle: {"executed": [...], "failed": [...],
    "skipped": {test: reason}}}`` so callers can report executed /
    passed / failed / skipped without re-deriving it.
    """
    summaries: dict[int, dict[str, Any]] = {}
    datasets: dict[int, xr.Dataset] = {}

    for record in sorted(records, key=lambda r: r.cycle):
        ds = record.dataset
        executed: set[int] = set()
        failed: set[int] = set()
        skipped: dict[int, str] = {}

        # Capture the pre-RTQC flags for truthful CF history records.
        # Stored as a JSON string: netCDF global attributes cannot hold
        # Python dicts, and the mono writer parses this attr either way.
        import json as _json

        ds.attrs["qc_previous_values"] = _json.dumps(
            {
                name: [int(v) for v in _flags_to_int(np.asarray(ds[f"{name}_QC"].values))]
                for name in ("PRES", "TEMP", "PSAL")
                if f"{name}_QC" in ds
            }
        )

        pres = _levels(ds, "PRES")
        temp = _levels(ds, "TEMP")
        psal = _levels(ds, "PSAL")
        juld = _scalar(ds, "JULD")
        lat = _scalar(ds, "LATITUDE")
        lon = _scalar(ds, "LONGITUDE")

        # ---- TEST001-004 (scalar tests; 4 bathymetry-gated) ----
        scalar = run_profile_scalar_tests(
            juld=juld,
            latitude=lat,
            longitude=lon,
            platform_known=platform_known,
            bathymetry=bathymetry,
            now_utc=now_utc,
        )
        for name, number in _SCALAR_TEST_NUMBERS.items():
            if name in scalar.tests_done:
                executed.add(number)
                if name in scalar.tests_failed:
                    failed.add(number)
        if "TEST004_POSITION_ON_LAND" not in scalar.tests_done:
            skipped[4] = "no bathymetry grid supplied"
        _worsen_scalar_qc(ds, "JULD_QC", scalar.juld_qc)
        _worsen_scalar_qc(ds, "POSITION_QC", scalar.position_qc)

        # ---- TEST006/008/009/011/012/013 (+019 when configured) ----
        non_density_failures: set[int] = set()
        qc_map = run_non_density_tests(
            pres=pres,
            temp=temp,
            psal=psal,
            failed_tests=non_density_failures,
            profile_pressure_dbar=profile_pressure_dbar,
        )
        executed |= _NON_DENSITY_TESTS
        if profile_pressure_dbar is not None and np.isfinite(profile_pressure_dbar):
            executed.add(_DEEPEST_PRESSURE_TEST)
        else:
            skipped[19] = "CONFIG_ProfilePressure_dbar unavailable"
        failed |= non_density_failures
        for name, flags in qc_map.items():
            _worsen_level_qc(ds, name, flags)

        # ---- TEST014 (density inversion; needs a position) ----
        if lat is not None and lon is not None:
            t_outcome, s_outcome = density_inversion_test(
                pres=pres,
                temp=temp,
                psal=psal,
                lat=lat,
                lon=lon,
                pres_qc=_flags_to_int(np.asarray(ds["PRES_QC"].values)),
                temp_qc=_flags_to_int(np.asarray(ds["TEMP_QC"].values)),
                psal_qc=_flags_to_int(np.asarray(ds["PSAL_QC"].values)),
            )
            executed.add(_DENSITY_TEST)
            if t_outcome.n_flagged or s_outcome.n_flagged:
                failed.add(_DENSITY_TEST)
            _worsen_level_qc(ds, "TEMP", t_outcome.per_level)
            _worsen_level_qc(ds, "PSAL", s_outcome.per_level)
        else:
            skipped[14] = "profile position unavailable (Absolute Salinity undefined)"

        _merge_mask(ds, "rtqc_tests_done_hex", executed)
        if failed:
            _merge_mask(ds, "rtqc_tests_failed_hex", failed)
        else:
            ds.attrs.setdefault("rtqc_tests_failed_hex", "0")
        datasets[int(record.cycle)] = ds
        summaries[int(record.cycle)] = {
            "executed": sorted(executed),
            "failed": sorted(failed),
            "skipped": dict(skipped),
        }

    # ---- TEST005/016/018 across cycles (masks merged in place) ----
    cross_failures = apply_cross_cycle_rtqc(datasets)
    for cycle, numbers in cross_failures.items():
        entry = summaries.setdefault(cycle, {"executed": [], "failed": [], "skipped": {}})
        entry["failed"] = sorted(set(entry["failed"]) | set(numbers))
    for cycle, ds in datasets.items():
        first = min(datasets)
        if cycle == first and len(datasets) > 1:
            # The first profile has no previous cycle to compare against.
            summaries[cycle]["skipped"].setdefault(
                5, "no previous cycle (first profile of the run)"
            )
            summaries[cycle]["skipped"].setdefault(
                16, "no previous cycle (first profile of the run)"
            )
            summaries[cycle]["skipped"].setdefault(
                18, "no previous cycle (first profile of the run)"
            )
        done = _decode_mask_set(ds.attrs.get("rtqc_tests_done_hex"))
        for number in (5, 16, 18):
            if number not in done and number not in summaries[cycle]["skipped"]:
                summaries[cycle]["skipped"][number] = _CROSS_SKIP_REASONS[number]
    return summaries


_CROSS_SKIP_REASONS = {
    5: "speed undefined (equal/reversed reception timestamps or missing endpoint)",
    16: "no previous good profile available as drift reference",
    18: "insufficient overlap with previous profile",
}


def _decode_mask_set(raw: Any) -> set[int]:
    if not isinstance(raw, str) or not raw or raw == "0":
        return set()
    try:
        mask = int(raw, 16)
    except ValueError:
        return set()
    return {n for n in range(64) if mask & (1 << n)}


__all__ = ["apply_rtqc_to_profiles"]

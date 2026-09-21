"""Apply the cross-cycle RTQC tests over a float's ordered profiles.

The per-profile tests run while each cycle is decoded. TEST005, TEST016
and TEST018 cannot: they compare a profile against its predecessor, so
they need the whole ordered set. This module is that second pass.

It mutates the mono-profile datasets in place -- degrading QC flags,
never improving them -- and updates the ``rtqc_tests_done_hex`` /
``rtqc_tests_failed_hex`` attributes so ``HISTORY_QCTEST`` stays a
truthful record of what actually ran.

Ordering matters twice over:

* Cycles are visited in ascending order so "previous" means what it says.
* TEST016 compares against the previous *good* profile, not merely the
  previous one, per the manual. A profile already condemned by TEST018
  or by its own per-profile tests is skipped as a reference, otherwise
  one bad cycle would drag its successor down with it.
"""

from __future__ import annotations

import numpy as np
import xarray as xr

from argo_decoder.domain.qc import QcFlag
from argo_decoder.rtqc.cross_cycle import (
    DRIFT_THRESHOLD_PSAL,
    DRIFT_THRESHOLD_TEMP,
    frozen_profile_test,
    gross_sensor_drift_test,
    impossible_speed_test,
)

#: Argo reference table 11 numbers for the tests applied here.
IMPOSSIBLE_SPEED_TEST = 5
SENSOR_DRIFT_TEST = 16
FROZEN_PROFILE_TEST = 18

_FILL_THRESHOLD = 99998.0


def _values(ds: xr.Dataset, name: str) -> np.ndarray | None:
    """Values with Argo fill sentinels (>= 99998) mapped to NaN.

    Products that store fills as 99999/999999-class sentinels must not
    have those read as real deep pressures or warm temperatures by the
    cross-cycle tests.
    """
    if name not in ds:
        return None
    v = np.asarray(ds[name].values, dtype=np.float64).reshape(-1)
    v[np.abs(v) >= _FILL_THRESHOLD] = np.nan
    return v


def _scalar(ds: xr.Dataset, name: str) -> float | None:
    if name not in ds:
        return None
    raw = np.asarray(ds[name].values).reshape(-1)
    if raw.size == 0:
        return None
    value = float(raw[0])
    if not np.isfinite(value) or abs(value) > _FILL_THRESHOLD:
        return None
    return value


def _decode_mask(ds: xr.Dataset, key: str) -> set[int]:
    raw = ds.attrs.get(key)
    if not raw or raw == "0":
        return set()
    try:
        mask = int(str(raw), 16)
    except ValueError:
        return set()
    return {n for n in range(64) if mask & (1 << n)}


def _encode_mask(tests: set[int]) -> str:
    mask = 0
    for number in tests:
        mask |= 1 << int(number)
    return format(mask, "X") if mask else "0"


def _flags_as_int(values: np.ndarray) -> np.ndarray:
    """Per-level QC flags as int8, whether stored as digits or S1 chars."""
    arr = np.asarray(values).reshape(-1)
    if arr.dtype.kind in ("S", "O"):
        out = np.full(arr.size, int(QcFlag.NO_QC), dtype=np.int8)
        for i, item in enumerate(arr):
            raw = bytes(item).strip() if isinstance(item, (bytes, np.bytes_)) else b""
            if raw.isdigit():
                out[i] = int(raw)
        return out
    return arr.astype(np.int8)


def _worsen_flags(ds: xr.Dataset, name: str, flags: np.ndarray) -> bool:
    """Merge ``flags`` into ``<name>_QC``, keeping the worse of the two."""
    qc_name = f"{name}_QC"
    if qc_name not in ds:
        return False
    stored = np.asarray(ds[qc_name].values).reshape(-1)
    current = _flags_as_int(stored)
    keep_chars = stored.dtype.kind == "S"
    if current.shape != flags.shape:
        return False
    merged = np.maximum(current, flags).astype(np.int8)
    if np.array_equal(merged, current):
        return False
    final = merged
    if keep_chars:
        final = np.array([str(int(v)).encode("ascii") for v in merged], dtype="S1")
    attrs = dict(ds[qc_name].attrs)
    ds[qc_name] = (ds[qc_name].dims, final.reshape(ds[qc_name].shape))
    ds[qc_name].attrs.update(attrs)  # variable attributes survive in-place QC edits
    return True


def _profile_is_usable_reference(ds: xr.Dataset) -> bool:
    """True when a profile is clean enough to compare the next one against."""
    for name in ("TEMP_QC", "PSAL_QC"):
        if name not in ds:
            continue
        flags = _flags_as_int(np.asarray(ds[name].values).reshape(-1))
        if flags.size and np.all(flags >= int(QcFlag.PROBABLY_BAD)):
            return False
    return True


def apply_cross_cycle_rtqc(datasets: dict[int, xr.Dataset]) -> dict[int, set[int]]:
    """Run TEST005/016/018 across ``datasets``, keyed by cycle number.

    Returns the set of test numbers that *failed* per cycle. Datasets are
    updated in place: QC flags are degraded where a test fires, and the
    ``rtqc_tests_done_hex`` / ``rtqc_tests_failed_hex`` attributes are
    rewritten to include whichever of the three actually ran.
    """
    failures: dict[int, set[int]] = {}
    previous_cycle: int | None = None
    previous_good: int | None = None

    for cycle in sorted(datasets):
        ds = datasets[cycle]
        ran: set[int] = set()
        failed: set[int] = set()

        pres = _values(ds, "PRES")
        temp = _values(ds, "TEMP")
        psal = _values(ds, "PSAL")

        prev_ds = datasets[previous_cycle] if previous_cycle is not None else None
        ref_ds = datasets[previous_good] if previous_good is not None else None

        # ---- TEST005: impossible speed (immediately preceding cycle) ----
        if prev_ds is not None:
            position_qc, did_run = impossible_speed_test(
                juld=_scalar(ds, "JULD"),
                latitude=_scalar(ds, "LATITUDE"),
                longitude=_scalar(ds, "LONGITUDE"),
                previous_juld=_scalar(prev_ds, "JULD"),
                previous_latitude=_scalar(prev_ds, "LATITUDE"),
                previous_longitude=_scalar(prev_ds, "LONGITUDE"),
            )
            if did_run:
                ran.add(IMPOSSIBLE_SPEED_TEST)
                if position_qc == b"4":
                    failed.add(IMPOSSIBLE_SPEED_TEST)
                    # The manual condemns both ends of an impossible leg.
                    _set_position_bad(ds)
                    _set_position_bad(prev_ds)
                    failures.setdefault(previous_cycle or cycle, set()).add(IMPOSSIBLE_SPEED_TEST)

        # ---- TEST018: frozen profile (previous cycle) ----
        if prev_ds is not None and pres is not None and temp is not None and psal is not None:
            frozen, did_run = frozen_profile_test(
                pres=pres,
                temp=temp,
                psal=psal,
                previous_pres=_values(prev_ds, "PRES"),
                previous_temp=_values(prev_ds, "TEMP"),
                previous_psal=_values(prev_ds, "PSAL"),
            )
            if did_run:
                ran.add(FROZEN_PROFILE_TEST)
                if frozen:
                    failed.add(FROZEN_PROFILE_TEST)
                    bad = np.full(len(pres), int(QcFlag.BAD), dtype=np.int8)
                    for name in ("PRES", "TEMP", "PSAL", "CNDC"):
                        _worsen_flags(ds, name, bad)

        # ---- TEST016: gross sensor drift (previous *good* cycle) ----
        if ref_ds is not None and pres is not None:
            ref_pres = _values(ref_ds, "PRES")
            for name, threshold in (
                ("TEMP", DRIFT_THRESHOLD_TEMP),
                ("PSAL", DRIFT_THRESHOLD_PSAL),
            ):
                values = _values(ds, name)
                if values is None:
                    continue
                flags, did_run = gross_sensor_drift_test(
                    pres=pres,
                    values=values,
                    previous_pres=ref_pres,
                    previous_values=_values(ref_ds, name),
                    threshold=threshold,
                )
                if did_run:
                    ran.add(SENSOR_DRIFT_TEST)
                    if flags is not None and np.any(flags > int(QcFlag.GOOD)):
                        failed.add(SENSOR_DRIFT_TEST)
                        _worsen_flags(ds, name, flags)

        if ran:
            ds.attrs["rtqc_tests_done_hex"] = _encode_mask(
                _decode_mask(ds, "rtqc_tests_done_hex") | ran
            )
        if failed:
            ds.attrs["rtqc_tests_failed_hex"] = _encode_mask(
                _decode_mask(ds, "rtqc_tests_failed_hex") | failed
            )
            failures.setdefault(cycle, set()).update(failed)

        previous_cycle = cycle
        if _profile_is_usable_reference(ds):
            previous_good = cycle

    return failures


def _set_position_bad(ds: xr.Dataset) -> None:
    """Degrade POSITION_QC to '4', tolerating scalar or (N_PROF,) layouts."""
    if "POSITION_QC" not in ds:
        return
    var = ds["POSITION_QC"]
    value = np.array(b"4", dtype="|S1")
    attrs = dict(var.attrs)
    ds["POSITION_QC"] = (var.dims, value.reshape(var.shape))
    ds["POSITION_QC"].attrs.update(attrs)


__all__ = [
    "FROZEN_PROFILE_TEST",
    "IMPOSSIBLE_SPEED_TEST",
    "SENSOR_DRIFT_TEST",
    "apply_cross_cycle_rtqc",
]

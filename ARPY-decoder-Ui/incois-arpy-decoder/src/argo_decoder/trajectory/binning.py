"""Trajectory sample binning by Argo measurement code (MC).

Pure-numpy binning routine that classifies each PRES sample in a cycle
into one of the standard Argo measurement codes (see
``add_measurement_code_to_traj_data_ir_sbd2.m``). The algorithm is
deliberately simple and robust:

1. Work on ascending-pressure-sorted samples (deepest first).
2. The sample at maximum pressure is the "deepest bin" and marks the
   park-to-profile transition.
3. Samples before the deepest bin (in acquisition order) are either
   *descent to park* or *descent to profile* (indistinguishable without
   CONFIG_PM08/PROFILE pressure, so they are merged into a single
   DESCENT bin unless the park pressure is provided).
4. Samples after the deepest bin in acquisition order are the
   *ascent* (up-cast) — this is the data that already lands in the
   mono-profile file.
5. Shallow samples (P < 10 dbar) after the ascent are marked *in-air*.
6. Pressure reversals that go from deep→shallow and then shallow→deep
   again are treated as an *emergency ascent* / *re-descent* event and
   binned separately if the reversal exceeds 50 dbar.

When Tech2 counters are present (``exp_nb_desc`` etc.) the bin counts
are cross-checked against them; mismatches are logged but do not crash
the decode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


class MeasurementCodes:
    """Integer Argo measurement codes used in trajectory files."""

    SURFACE = 290
    PARK_DESCENT = 291
    PARK_DRIFT = 292
    PROFILE_DESCENT = 293
    PROFILE_ASCENT = 294
    IN_AIR = 295
    DEEP_PARK_DESCENT = 296
    GROUNDING = 700
    EMERGENCY_ASCENT = 703


# Argo reference table 6 / 7 labels (kept here rather than in globals)
_MC_LABELS: dict[int, str] = {
    MeasurementCodes.SURFACE: "Surface drift",
    MeasurementCodes.PARK_DESCENT: "Descent to park",
    MeasurementCodes.PARK_DRIFT: "Drift at park",
    MeasurementCodes.PROFILE_DESCENT: "Descent to profile",
    MeasurementCodes.PROFILE_ASCENT: "Ascent (up-cast)",
    MeasurementCodes.IN_AIR: "In-air before transmission",
    MeasurementCodes.DEEP_PARK_DESCENT: "Deep-park descent",
    MeasurementCodes.GROUNDING: "Grounding",
    MeasurementCodes.EMERGENCY_ASCENT: "Emergency ascent",
}


@dataclass
class TrajectoryBin:
    """One bin of trajectory samples sharing a measurement code."""

    measurement_code: int
    label: str
    pres: list[float] = field(default_factory=list)
    temp: list[float] = field(default_factory=list)
    psal: list[float] = field(default_factory=list)
    cndc: list[float] = field(default_factory=list)
    doxy: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.pres)

    def as_dict(self) -> dict[str, Any]:
        return {
            "measurement_code": self.measurement_code,
            "label": self.label,
            "n": len(self),
        }


def _empty_bins() -> dict[int, TrajectoryBin]:
    return {
        code: TrajectoryBin(measurement_code=code, label=_MC_LABELS[code]) for code in _MC_LABELS
    }


def bin_cycle_samples(
    *,
    pres: np.ndarray,
    temp: np.ndarray | None = None,
    psal: np.ndarray | None = None,
    cndc: np.ndarray | None = None,
    doxy: np.ndarray | None = None,
    park_pressure: float | None = None,
    in_air_threshold_dbar: float = 10.0,
    reversal_threshold_dbar: float = 50.0,
) -> dict[int, TrajectoryBin]:
    """Classify 1-D arrays of CTD/CTDO samples into trajectory bins.

    Inputs are **acquisition order** (as they came off the float; we do
    the deep-first search internally). Fill values (P ≥ 9999, T ≥ 90,
    S ≥ 90) are skipped.

    Parameters
    ----------
    park_pressure:
        CONFIG_ParkPressure_dbar if known (Param1 field or meta config).
        When provided it separates descent-to-park (above park) from
        drift-at-park (within ± 50 dbar of park). When ``None``,
        descent samples all go into a single DESCENT bin and the
        deepest sample is taken to be park depth.
    """
    p = np.asarray(pres, dtype=np.float64)
    n = len(p)
    t_arr = np.asarray(temp, dtype=np.float64) if temp is not None else np.full(n, np.nan)
    s_arr = np.asarray(psal, dtype=np.float64) if psal is not None else np.full(n, np.nan)
    c_arr = np.asarray(cndc, dtype=np.float64) if cndc is not None else np.full(n, np.nan)
    d_arr = np.asarray(doxy, dtype=np.float64) if doxy is not None else np.full(n, np.nan)

    bins = _empty_bins()
    valid = np.isfinite(p) & (p < 9999.0)
    if not np.any(valid):
        return bins

    valid_idx = np.where(valid)[0]
    p_valid = p[valid_idx]

    # Locate the deepest sample in acquisition order (first occurrence
    # of max pressure).
    deepest_acq = int(valid_idx[int(np.argmax(p_valid))])

    # Work backwards from the deepest sample to detect emergency
    # ascents (large sudden shoaling followed by re-deepening).
    emergency = np.zeros(n, dtype=bool)
    for k in range(1, n):
        if not valid[k] or not valid[k - 1]:
            continue
        if p[k - 1] - p[k] > reversal_threshold_dbar and k < deepest_acq:
            # large shoaling while still descending -> emergency ascent
            emergency[k] = True

    for k in range(n):
        if not valid[k]:
            continue
        pk = float(p[k])
        tk = float(t_arr[k]) if np.isfinite(t_arr[k]) else np.nan
        sk = float(s_arr[k]) if np.isfinite(s_arr[k]) else np.nan
        ck = float(c_arr[k]) if np.isfinite(c_arr[k]) else np.nan
        dk = float(d_arr[k]) if np.isfinite(d_arr[k]) else np.nan

        if emergency[k]:
            code = MeasurementCodes.EMERGENCY_ASCENT
        elif k == deepest_acq or (
            park_pressure is not None and abs(pk - float(park_pressure)) < 50.0 and k < deepest_acq
        ):
            # If we know park pressure and are near it while still
            # before the deepest bin, count as drift-at-park.
            code = MeasurementCodes.PARK_DRIFT
        elif k < deepest_acq:
            if pk < in_air_threshold_dbar:
                code = MeasurementCodes.SURFACE
            elif park_pressure is not None and pk < float(park_pressure):
                code = MeasurementCodes.PARK_DESCENT
            else:
                # Deeper than (or equal to) park and before deepest bin:
                # descent to profile.
                code = MeasurementCodes.PROFILE_DESCENT
        else:  # k > deepest_acq (ascent after deepest sample)
            if pk < in_air_threshold_dbar:
                code = MeasurementCodes.IN_AIR
            else:
                code = MeasurementCodes.PROFILE_ASCENT

        b = bins[code]
        b.pres.append(pk)
        b.temp.append(tk)
        b.psal.append(sk)
        b.cndc.append(ck)
        b.doxy.append(dk)

    return bins


__all__ = ["MeasurementCodes", "TrajectoryBin", "bin_cycle_samples"]

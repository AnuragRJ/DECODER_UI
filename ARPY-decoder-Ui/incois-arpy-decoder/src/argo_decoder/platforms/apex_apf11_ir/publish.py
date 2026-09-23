"""APF11 product assembly: decoded cycle content -> mono-profile inputs.

Builds the writer-level ``CycleProductInput`` from the decoded cycle
products (:class:`~argo_decoder.platforms.apex_apf11_ir.products.CycleProfiles`),
the authoritative calibration sheets and the computed mission number.
Everything here is a documented publication rule established against the
live INCOIS files of this fleet (evidence in the stage reports and the
parity tests), never a float-specific branch:

* profile layout: R files carry the averaged (CTD_CP) and discrete (CTD_PTS)
  profiles with ``PRES, TEMP, PSAL``; B files carry PRES-only on the
  averaged grid and the discrete co-sampled BGC set on profile 1;
* level content: per-node BGC values come from the paired records; DOXY via
  :func:`doxy_from_telemetry_o2`, CHLA/BBP700 via the authoritative
  bio-optical calibration sheet, NITRATE only when NO3 records exist;
* honest real-time state: ``DATA_MODE='R'``, ``DATA_STATE_INDICATOR='1A'``,
  per-level QC ``'0'`` (RTQC stage not yet run; Argo table 2 value for
  "No QC was performed"), blank ``SCIENTIFIC_CALIB_*`` (nothing calibrated
  downstream yet);
* position rule: best fix within the surface window carried at ``JULD``
  yields QC '1'; linear interpolation between the two bracketing fixes at
  ``JULD`` yields QC '8'; no usable fix yields FillValue + QC '9'
  (established: cycle-189 interpolation reproduces the publication at
  1e-3 deg; cycle-39 fix-at-JULD matches the publication).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

from argo_decoder.platforms.apex_apf11_ir.calibration import BgcCalibration
from argo_decoder.platforms.apex_apf11_ir.equations import (
    bbp700_m1,
    doxy_from_telemetry_o2,
    nitrate_from_suna,
)
from argo_decoder.platforms.apex_apf11_ir.products import CycleProfiles
from argo_decoder.writer.apf11_nc import CycleProductInput, LevelBlock


class GpsFix(NamedTuple):
    """One GPS record of the science stream (timestamp/latitude/longitude)."""

    timestamp: str
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class CyclePosition:
    """Station position + Argo table-2 flag, per the observed DAC rule."""

    latitude: float | None
    longitude: float | None
    qc: str  # '1' fix, '8' interpolated, '9' none
    juld_location: float | None = None  # QC-1 anchor time; None -> use JULD


def _sec(ts: str) -> float:
    import datetime as dt

    return dt.datetime.strptime(ts, "%Y%m%dT%H%M%S").timestamp()


def _juld_to_sec(juld: float) -> float:
    import datetime as dt

    epoch = dt.datetime(1950, 1, 1).timestamp()
    return epoch + juld * 86400.0


def resolve_cycle_position(
    fixes: list[GpsFix],
    juld: float,
    surface_window: tuple[str, str] | None,
) -> CyclePosition:
    """Best position for a cycle, with the established QC semantics.

    ``fixes`` are the float's GPS records, ``juld`` the profile JULD; the
    ``surface_window`` argument is kept for call-site compatibility (it is
    not consulted by the measured publication rule).
    """
    # Measured publication rule (the parity float's 138 published cycles):
    #  - QC '1' (79 cycles): the first valid GPS fix AFTER the profile JULD,
    #    observed deltas 0.0088..0.0457 days; JULD_LOCATION = fix time.
    #  - QC '8' (1 cycle, 189): no fix within that window; linear
    #    interpolation between the bracketing fixes; JULD_LOCATION = JULD.
    #  - QC '9' (58 cycles): no position written (0/0 fill); our consortium's
    #    GPS table holds valid fixes for many of these, so our product keeps
    #    the data (classified DATA-COVERAGE in the parity report).
    # The acceptance bound (0.0457 d observed < 0.05 d applied) is the
    # publication-consistent conservative window: no QC-1 anchor farther from
    # JULD has been observed anywhere in the float's published file set.
    qc1_window_days = 0.05
    valid = [
        f
        for f in fixes
        if f.latitude is not None
        and f.longitude is not None
        and not (f.latitude == 0.0 and f.longitude == 0.0)
    ]
    t0 = _juld_to_sec(juld)
    after = [f for f in valid if _sec(f.timestamp) > t0]
    if after:
        first = min(after, key=lambda f: f.timestamp)
        if (_sec(first.timestamp) - t0) <= qc1_window_days * 86400.0:
            # Measured anchor (79 published cycles): first fix inside the
            # window. For the 7 late duplex-broadcast cycles (190-192, 225,
            # 229, 234-235) the publication used the RETRY fix minutes later
            # with identical content; those deviations are enumerated in the
            # parity matrix as EXPECTED, with evidence.
            return CyclePosition(
                first.latitude,
                first.longitude,
                "1",
                juld_location=juld + (_sec(first.timestamp) - t0) / 86400.0,
            )
    before = [f for f in valid if _sec(f.timestamp) <= t0]
    if before and after:
        fb = max(before, key=lambda f: f.timestamp)
        fa = min(after, key=lambda f: f.timestamp)
        tb, ta = _sec(fb.timestamp), _sec(fa.timestamp)
        if ta == tb:
            return CyclePosition(fb.latitude, fb.longitude, "1", juld_location=juld)
        w = (t0 - tb) / (ta - tb)
        return CyclePosition(
            fb.latitude + w * (fa.latitude - fb.latitude),
            fb.longitude + w * (fa.longitude - fb.longitude),
            "8",
        )
    return CyclePosition(None, None, "9", juld_location=juld)


def _qc_array(n: int) -> np.ndarray:
    return np.array([b"0"] * n, dtype="S1")


def _block_core(
    pressures,
    temps,
    sals,
    vss: str,
    *,
    longitude: float | None = None,
    latitude: float | None = None,
    profile_pressure_dbar: float | None = None,
) -> LevelBlock:
    """One core profile with genuine RTQC per-level + profile flags.

    QC flags come from the executed test set of the RTQC stage
    (:func:`run_core_rtqc`); the profile letters are computed from those
    flags. Nothing is defaulted to '0' or forced to '1'.  ``longitude`` /
    ``latitude`` feed test 14 (density inversion) and ``profile_pressure_dbar``
    the float's own configured profile pressure, which feeds test 19.
    """
    from argo_decoder.platforms.apex_apf11_ir.rtqc import (
        profile_quality_letter,
        run_core_rtqc,
    )

    n = len(pressures)
    t32 = np.asarray(
        [np.float32(t) if t is not None else np.float32(99999.0) for t in temps],
        dtype=np.float32,
    )
    s32 = np.asarray(
        [np.float32(s) if s is not None else np.float32(99999.0) for s in sals],
        dtype=np.float32,
    )
    pres32 = np.asarray(pressures, dtype=np.float32)
    rtqc = run_core_rtqc(
        pres32,
        t32,
        s32,
        longitude=longitude,
        latitude=latitude,
        profile_pressure_dbar=profile_pressure_dbar,
    )
    return LevelBlock(
        params=["TEMP", "PSAL"],
        pres=np.asarray(pressures, dtype=np.float64),
        values={"TEMP": t32, "PSAL": s32},
        qc={
            "PRES": rtqc.qc["PRES"],
            "TEMP": rtqc.qc["TEMP"],
            "PSAL": rtqc.qc["PSAL"],
        },
        profile_qc={
            "PRES": profile_quality_letter(rtqc.qc["PRES"]),
            "TEMP": profile_quality_letter(rtqc.qc["TEMP"]),
            "PSAL": profile_quality_letter(rtqc.qc["PSAL"]),
        },
        vertical_sampling_scheme=vss,
    )


def build_core_product(
    profiles: CycleProfiles,
    *,
    position: CyclePosition,
    config_mission_number: int,
    profile_pressure_dbar: float | None = None,
) -> CycleProductInput | None:
    """R-file content for one cycle (None when no core content exists)."""
    if not profiles.averaged:
        return None
    # The RTQC tests use the decoded position of the cycle -- the publication
    # may withhold the fix (POSITION_QC 9) for its own reasons, but quality
    # control is not part of that decision.
    lon, lat = position.longitude, position.latitude
    averaged = _block_core(
        [l.pressure for l in profiles.averaged],
        [l.temperature for l in profiles.averaged],
        [l.salinity for l in profiles.averaged],
        "Primary sampling: averaged []",
        longitude=lon,
        latitude=lat,
        profile_pressure_dbar=profile_pressure_dbar,
    )
    discrete = _block_core(
        [l.pressure for l in profiles.discrete_core],
        [l.temperature for l in profiles.discrete_core],
        [l.salinity for l in profiles.discrete_core],
        "Secondary sampling: discrete []",
        longitude=lon,
        latitude=lat,
        profile_pressure_dbar=profile_pressure_dbar,
    )
    return CycleProductInput(
        cycle_number=profiles.cycle,
        juld=profiles.juld,
        latitude=position.latitude,
        longitude=position.longitude,
        position_qc=position.qc,
        juld_location=position.juld_location,
        config_mission_number=config_mission_number,
        averaged=averaged,
        discrete=discrete,
    )


def build_bgc_product(
    profiles: CycleProfiles,
    calibration: BgcCalibration | None,
    *,
    position: CyclePosition,
    config_mission_number: int,
    profile_pressure_dbar: float | None = None,
    core_discrete: LevelBlock | None = None,
) -> CycleProductInput | None:
    """BR-file content for one cycle (None when no BGC content exists).

    ``core_discrete`` is the *core* discrete profile of the same cycle (the
    CTD TEMP/PSAL block that the R file publishes).  The chain's TEST057 reads
    the CTD flags - not the BGC record's own temperature - when it decides
    whether a DOXY level is bad, so the BGC QC is derived from the core block
    whenever it is available (:func:`core_qc_at`).
    """
    if not profiles.averaged or not profiles.discrete_bgc:
        return None

    levels = profiles.discrete_bgc
    n = len(levels)

    pres = np.asarray([l.pressure for l in levels], dtype=np.float64)
    fill = np.full(n, np.float32(99999.0), dtype=np.float32)
    values: dict[str, np.ndarray] = {}
    params: list[str] = []

    def put(name: str, arr: np.ndarray) -> None:
        params.append(name)
        values[name] = arr

    has_o2 = any(l.o2 is not None for l in levels)
    has_no3 = any(l.no3 is not None for l in levels)
    has_flbb = any(l.flbb is not None for l in levels)

    # Parameter order follows the published BGC station-parameter convention:
    # PRES, DOXY, NITRATE, TPHASE_DOXY, CHLA, FLUORESCENCE_CHLA, BBP700,
    # BETA_BACKSCATTERING700, TEMP_CPU_CHLA.  Verified on every published BGC
    # product of the fleet: the floats without a nitrate sensor list the eight
    # parameters above minus NITRATE, and the nitrate float inserts NITRATE
    # directly after DOXY and before TPHASE_DOXY.  The order is a property of
    # the product, not of the assembly order, so values are computed here and
    # published in that order.
    doxy = tphase = nitrate = None
    if has_o2:
        doxy, tphase = fill.copy(), fill.copy()
        for i, l in enumerate(levels):
            if l.o2 is None:
                continue
            res = doxy_from_telemetry_o2(l.o2.o2, l.pressure, l.temperature, l.salinity)
            if res is not None:
                doxy[i] = np.float32(res.doxy_umol_per_kg)
            if l.o2.tc_phase is not None:
                tphase[i] = np.float32(l.o2.tc_phase)
        put("DOXY", doxy)

    if has_no3:
        # Verified publication rule (5 cycles / 299 levels, exact): the
        # GDAC's NITRATE column carries the SUNA's already bromide-corrected
        # ``nitrate`` concentration field unchanged.
        nitrate = fill.copy()
        for i, l in enumerate(levels):
            if l.no3 is None:
                continue
            res = nitrate_from_suna(l.no3.nitrate, l.salinity)
            if math.isfinite(res.nitrate_umol_per_l):
                nitrate[i] = np.float32(res.nitrate_umol_per_l)
        put("NITRATE", nitrate)

    if has_o2:
        put("TPHASE_DOXY", tphase)

    if has_flbb:
        chla = fill.copy()
        fluo = fill.copy()
        bbp = fill.copy()
        beta = fill.copy()
        tcpu = fill.copy()
        for i, l in enumerate(levels):
            f = l.flbb
            if f is None:
                continue
            fluo[i] = np.float32(f.chl_sig)
            beta[i] = np.float32(f.bsc_sig)
            if f.therm_sig is not None:
                tcpu[i] = np.float32(f.therm_sig)
            if calibration is not None:
                c = calibration.chla(f.chl_sig)
                if c is not None:
                    chla[i] = np.float32(c)
                if (
                    f.bsc_wave == 700
                    and l.temperature is not None
                    and l.salinity is not None
                ):
                    r = bbp700_m1(
                        f.bsc_sig,
                        l.temperature,
                        l.salinity,
                        dark=(
                            calibration.flbb700_dark
                            if calibration.flbb700_dark is not None
                            else float("nan")
                        ),
                        scale=(
                            calibration.flbb700_scale
                            if calibration.flbb700_scale is not None
                            else float("nan")
                        ),
                        khi=(
                            calibration.bbp700_chi
                            if calibration.bbp700_chi is not None
                            else float("nan")
                        ),
                        theta_deg=(
                            calibration.bbp700_angle
                            if calibration.bbp700_angle is not None
                            else 140.0
                        ),
                    )
                    if math.isfinite(r.bbp700):
                        bbp[i] = np.float32(r.bbp700)
        put("CHLA", chla)
        put("FLUORESCENCE_CHLA", fluo)
        put("BBP700", bbp)
        put("BETA_BACKSCATTERING700", beta)
        put("TEMP_CPU_CHLA", tcpu)

    if not params:
        return None

    # BGC real-time QC (tests 57/63): DOXY and CHLA may not be published good
    # in real time, their raw channels keep the "no QC performed" state, and
    # the profile letters are derived from the flags exactly as for the core
    # parameters (table 2a / compute_profile_quality_flag.m).
    from argo_decoder.platforms.apex_apf11_ir.rtqc import (
        core_qc_at,
        profile_quality_letter,
        run_bgc_rtqc,
    )

    temp_arr = np.asarray(
        [
            np.float32(l.temperature) if l.temperature is not None else np.float32(99999.0)
            for l in levels
        ],
        dtype=np.float32,
    )
    psal_arr = np.asarray(
        [
            np.float32(l.salinity) if l.salinity is not None else np.float32(99999.0)
            for l in levels
        ],
        dtype=np.float32,
    )
    # TEST057 second part: the flags of the CJT CTD profile are carried onto
    # these pressures; the BGC record's own temperature/salinity are used for
    # the DOXY computation (oxygen solubility) but not for the QC decision.
    pres_qc = temp_qc = psal_qc = None
    if core_discrete is not None and core_discrete.pres is not None:
        core_pres = np.asarray(core_discrete.pres, dtype=np.float64)
        if len(core_pres) == n:
            pres_qc = core_qc_at(core_pres, core_discrete.qc.get("PRES"), pres)
            temp_qc = core_qc_at(core_pres, core_discrete.qc.get("TEMP"), pres)
            psal_qc = core_qc_at(core_pres, core_discrete.qc.get("PSAL"), pres)
    bgc_qc = run_bgc_rtqc(
        pres=np.asarray(pres, dtype=np.float32),
        temp=temp_arr,
        psal=psal_arr,
        pres_qc=pres_qc,
        temp_qc=temp_qc,
        psal_qc=psal_qc,
        doxy=values.get("DOXY"),
        tphase_doxy=values.get("TPHASE_DOXY"),
        chla=values.get("CHLA"),
        fluorescence_chla=values.get("FLUORESCENCE_CHLA"),
        bbp700=values.get("BBP700"),
        beta_backscattering700=values.get("BETA_BACKSCATTERING700"),
        temp_cpu_chla=values.get("TEMP_CPU_CHLA"),
        nitrate=values.get("NITRATE"),
        longitude=position.longitude,
        latitude=position.latitude,
        profile_pressure_dbar=profile_pressure_dbar,
        park_pres=1000.0,
    )
    qc = {p: bgc_qc.get(p, _qc_array(n)) for p in params}
    discrete = LevelBlock(
        params=params,
        pres=pres,
        values=values,
        qc=qc,
        profile_qc={p: profile_quality_letter(qc[p]) for p in params},
        vertical_sampling_scheme="Secondary sampling: discrete []",
    )
    averaged = LevelBlock(
        params=[],
        pres=np.asarray([l.pressure for l in profiles.averaged], dtype=np.float64),
        values={},
        qc={},
        profile_qc={},
        vertical_sampling_scheme="Primary sampling: averaged []",
    )
    return CycleProductInput(
        cycle_number=profiles.cycle,
        juld=profiles.juld,
        latitude=position.latitude,
        longitude=position.longitude,
        position_qc=position.qc,
        juld_location=position.juld_location,
        config_mission_number=config_mission_number,
        averaged=averaged,
        discrete=discrete,
    )


__all__ = [
    "CyclePosition",
    "build_bgc_product",
    "build_core_product",
    "resolve_cycle_position",
]

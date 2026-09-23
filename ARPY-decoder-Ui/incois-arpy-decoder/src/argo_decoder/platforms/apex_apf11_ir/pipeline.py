"""APF11 real-time product generation.

One generic chain, no per-float branches::

    raw .gz -> decoded records -> cycle/profile -> calibrated science
            -> R/BR -> meta -> accumulating tech -> accumulating Rtraj

Every input is either decoded telemetry or an authoritative metadata row. Where
a quantity cannot be determined the corresponding parameter is published as
unavailable rather than filled in; the reason is recorded in the returned
:class:`FloatProducts` rather than silently dropped.

Cycle attribution comes from the file name (see ``attribution``) and from
``CTD_bins``, never from a WMO or a float name.
"""

from __future__ import annotations

import bisect
import csv
import datetime
import gzip
import lzma
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from argo_decoder.platforms.apex_apf11_ir.association import associate_o2_with_ctd
from argo_decoder.platforms.apex_apf11_ir.attribution import (
    attribute_cycles,
    parse_filename,
)
from argo_decoder.platforms.apex_apf11_ir.calibration import (
    load_bgc_calibration,
    load_optode_calibration_by_serial,
    resolve_optode,
)
from argo_decoder.platforms.apex_apf11_ir.equations import bbp700_m1
from argo_decoder.platforms.apex_apf11_ir.science import (
    decode_ctd,
    decode_ctd_bins,
    decode_flbb,
    decode_o2,
    decode_no3,
    select_ctd,
)

#: Value the Argo format uses for a missing measurement.
FILL = 99999.0

#: Memoised ``YYYYMMDDTHHMMSS`` -> epoch seconds. Telemetry timestamps repeat
#: heavily across records in a cycle, so parsing each one once keeps the
#: pressure association linear instead of quadratic.
_STAMP_CACHE: dict[str, float] = {}


@dataclass(frozen=True)
class CycleScience:
    """One cycle's calibrated science, ready to be written as a profile.

    Arrays are aligned on the CTD sample grid; BGC quantities that were not
    sampled at a given level carry :data:`FILL`.
    """

    cycle: int
    pressure: np.ndarray
    temperature: np.ndarray
    salinity: np.ndarray
    chla: np.ndarray
    fluorescence_chla: np.ndarray
    temp_cpu_chla: np.ndarray
    beta_backscattering700: np.ndarray
    bbp700: np.ndarray
    nitrate: np.ndarray
    doxy: np.ndarray
    tphase_doxy: np.ndarray
    timestamp: str
    latitude: float | None
    longitude: float | None
    is_launch_test: bool


@dataclass
class FloatProducts:
    """What a full run produced, and why anything was left unavailable."""

    wmo: str
    cycles: list[CycleScience] = field(default_factory=list)
    #: Parameter -> human-readable reason it could not be produced.
    unavailable: dict[str, str] = field(default_factory=dict)
    #: Parameter -> where its calibration came from.
    calibration_source: dict[str, str] = field(default_factory=dict)
    n_cycles_attributed: int = 0
    n_launch_test: int = 0


def read_raw_records(source_dir: Path) -> list[dict[str, str]]:
    """Read the consolidated per-record-type CSVs for one float.

    Rows are passed through **unchanged**. The consolidated tables have a
    four-column header while the payload is comma-joined, so ``csv.DictReader``
    puts the first payload value under ``payload`` and the remainder under the
    ``None`` rest-key. :func:`argo_decoder.platforms.apex_apf11_ir.science._payload`
    reassembles both parts itself.

    Merging the rest-key back into ``payload`` here would duplicate it and make
    every multi-field record decode to nothing -- which is exactly the failure
    this function must not reintroduce.
    """
    rows: list[dict[str, str]] = []
    for path in sorted(source_dir.glob("*_science_log_*.csv.xz")):
        with lzma.open(path, "rt") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def read_raw_records_for(source_dir: Path, prefix: str) -> list[dict[str, str]]:
    """Read one float's consolidated records, selected by file-name prefix."""
    rows: list[dict[str, str]] = []
    for path in sorted(source_dir.glob(f"{prefix}_science_log_*.csv.xz")):
        with lzma.open(path, "rt") as handle:
            rows.extend(csv.DictReader(handle))
    return rows


def build_cycle_science(
    rows: list[dict[str, str]],
    wmo: str,
    metadata_dir: Path,
    positions: dict[int, tuple[float, float]] | None = None,
) -> FloatProducts:
    """Decode, attribute and calibrate one float's telemetry.

    ``positions`` maps a cycle number to ``(latitude, longitude)``. It is
    optional because the raw files are the science source; position comes from
    the GPS records or from the trajectory stage.
    """
    products = FloatProducts(wmo=wmo)
    positions = positions or {}

    ctd = sorted(decode_ctd(rows), key=lambda s: s.timestamp)
    bins = list(decode_ctd_bins(rows))
    flbb = list(decode_flbb(rows))
    o2 = list(decode_o2(rows))
    no3 = list(decode_no3(rows))

    # --- cycle attribution, from the data ---------------------------------
    info: dict[int, dict] = {}
    for sample in ctd:
        entry = info.setdefault(sample.cycle, {"record_types": set(), "timestamps": set()})
        entry["record_types"].add(sample.record_type)
        entry["timestamps"].add(sample.timestamp)
        if sample.has_salinity:
            entry["has_salinity"] = True
    for cycle, _ts, samples, nbins, maxpress in bins:
        entry = info.setdefault(cycle, {"record_types": set(), "timestamps": set()})
        entry["record_types"].add("CTD_bins")
        entry["timestamps"].add(_ts)
        entry["bins"] = (samples, nbins, maxpress)
    profiles = attribute_cycles(info)
    products.n_cycles_attributed = len(profiles)
    products.n_launch_test = sum(1 for p in profiles.values() if p.is_launch_test)

    # --- calibration, keyed by serial -------------------------------------
    bgc = load_bgc_calibration(str(metadata_dir)).get(wmo)
    supplied = load_optode_calibration_by_serial(str(metadata_dir))

    # --- O2 -> pressure/salinity ------------------------------------------
    associations = associate_o2_with_ctd(o2, ctd)
    o2_by_ts = {a.timestamp: a for a in associations}

    flbb_by_cycle: dict[int, list] = {}
    for sample in flbb:
        flbb_by_cycle.setdefault(sample.cycle, []).append(sample)
    no3_by_cycle: dict[int, list] = {}
    for sample in no3:
        no3_by_cycle.setdefault(sample.cycle, []).append(sample)

    selected = select_ctd(ctd)
    by_cycle: dict[int, list] = {}
    for sample in selected:
        by_cycle.setdefault(sample.cycle, []).append(sample)

    for cycle in sorted(by_cycle):
        samples = sorted(by_cycle[cycle], key=lambda s: s.timestamp)
        n = len(samples)
        pressure = np.array([s.pressure for s in samples], dtype=float)
        temperature = np.array(
            [s.temperature if s.temperature is not None else FILL for s in samples],
            dtype=float,
        )
        salinity = np.array(
            [s.salinity if s.salinity is not None else FILL for s in samples],
            dtype=float,
        )

        products.unavailable.setdefault(
            "PSAL" if not any(s.has_salinity for s in samples) else "",
            "no salinity-bearing CTD record in telemetry" if not any(
                s.has_salinity for s in samples
            ) else "",
        )

        chla = np.full(n, FILL)
        fluorescence = np.full(n, FILL)
        temp_cpu = np.full(n, FILL)
        beta = np.full(n, FILL)
        bbp = np.full(n, FILL)

        cycle_flbb = sorted(flbb_by_cycle.get(cycle, []), key=lambda s: s.timestamp)
        # One index per cycle: FLBB and NO3 samples carry no pressure of their
        # own, so each is placed at the CTD sample nearest in time.
        pindex = _PressureIndex(samples)
        if cycle_flbb and bgc is not None:
            # FLBB samples are not co-timed with the CTD grid; place each at the
            # nearest CTD pressure.
            for sample in cycle_flbb:
                idx = int(np.argmin(np.abs(pressure - _flbb_pressure(sample, pindex))))
                fluorescence[idx] = sample.chl_sig
                temp_cpu[idx] = sample.therm_sig
                beta[idx] = sample.bsc_sig
                if bgc.chl_scale:
                    chla[idx] = (sample.chl_sig - bgc.chl_dark) * bgc.chl_scale
                if bgc.bbp700_chi and temperature[idx] != FILL and salinity[idx] != FILL:
                    res = bbp700_m1(
                        sample.bsc_sig,
                        float(temperature[idx]),
                        float(salinity[idx]),
                        bgc.flbb700_dark,
                        bgc.flbb700_scale,
                        bgc.bbp700_chi,
                        700.0,
                        bgc.bbp700_angle,
                    )
                    bbp[idx] = res.bbp700
            products.calibration_source["CHLA"] = (
                f"bio-cal.csv FLBB serial {bgc.flbb_serial}"
            )
            products.calibration_source["BBP700"] = (
                f"bio-cal.csv FLBB serial {bgc.flbb_serial} + betasw_ZHH2009"
            )

        nitrate = np.full(n, FILL)
        for sample in no3_by_cycle.get(cycle, []):
            if not pressure.size:
                continue
            idx = int(np.argmin(np.abs(pressure - _sample_pressure(sample, pindex))))
            nitrate[idx] = sample.nitrate

        doxy = np.full(n, FILL)
        tphase = np.full(n, FILL)
        for ts, assoc in o2_by_ts.items():
            if assoc.cycle != cycle or not assoc.is_associated:
                continue
            if not pressure.size:
                continue
            idx = int(np.argmin(np.abs(pressure - assoc.pressure_dbar)))
            tphase[idx] = assoc.cal_phase
            doxy[idx] = assoc.o2_umol_per_l

        latlon = positions.get(cycle)
        products.cycles.append(
            CycleScience(
                cycle=cycle,
                pressure=pressure,
                temperature=temperature,
                salinity=salinity,
                chla=chla,
                fluorescence_chla=fluorescence,
                temp_cpu_chla=temp_cpu,
                beta_backscattering700=beta,
                bbp700=bbp,
                nitrate=nitrate,
                doxy=doxy,
                tphase_doxy=tphase,
                timestamp=samples[0].timestamp,
                latitude=latlon[0] if latlon else None,
                longitude=latlon[1] if latlon else None,
                is_launch_test=profiles[cycle].is_launch_test
                if cycle in profiles
                else False,
            )
        )

    # --- record what could not be produced, and why ------------------------
    if bgc is None:
        products.unavailable["CHLA"] = "no bio-cal.csv row for this float's FLBB"
        products.unavailable["BBP700"] = "no bio-cal.csv row for this float's FLBB"
    if not o2:
        products.unavailable["DOXY"] = "no O2 records in telemetry"
    elif supplied is not None:
        products.unavailable.setdefault("DOXY", "")
    if not no3:
        products.unavailable["NITRATE"] = "no SUNA nitrate records in telemetry"
    products.unavailable = {k: v for k, v in products.unavailable.items() if k}
    return products


class _PressureIndex:
    """Sorted, timestamp-keyed index over one float's CTD samples.

    A non-sensor record such as an FLBB measurement carries no pressure of its
    own, so its depth is taken from the CTD sample nearest in time.  Scanning
    the whole CTD list for every such sample is quadratic in the number of
    samples and re-parses the same timestamps millions of times; the index
    parses each timestamp once and then answers by bisection.

    Only CTD samples that actually carry a pressure are indexed.  Ties resolve
    to the earlier sample, which keeps the answer stable.
    """

    def __init__(self, ctd_samples) -> None:
        parsed: list[tuple[float, object]] = []
        for sample in ctd_samples:
            stamp = _parse_stamp(sample.timestamp)
            if stamp is None or getattr(sample, "pressure", None) is None:
                continue
            parsed.append((stamp, sample))
        parsed.sort(key=lambda item: item[0])
        self._keys = [k for k, _ in parsed]
        self._items = [s for _, s in parsed]

    def nearest(self, timestamp: str) -> float | None:
        """Pressure of the nearest CTD sample in time, or ``None``."""
        if not self._items:
            return None
        target = _parse_stamp(timestamp)
        if target is None:
            return float(self._items[0].pressure)
        idx = bisect.bisect_left(self._keys, target)
        best = None
        for candidate in (idx - 1, idx):
            if 0 <= candidate < len(self._keys):
                delta = abs(self._keys[candidate] - target)
                if best is None or delta < best[0]:
                    best = (delta, candidate)
        if best is None:
            return None
        return float(self._items[best[1]].pressure)


def _parse_stamp(timestamp: str) -> float | None:
    """Epoch seconds for an ``YYYYMMDDTHHMMSS`` telemetry stamp, else ``None``."""
    if not timestamp or not isinstance(timestamp, str):
        return None
    stamp = _STAMP_CACHE.get(timestamp)
    if stamp is not None:
        return stamp
    try:
        parsed = datetime.datetime.strptime(timestamp, "%Y%m%dT%H%M%S")
    except (ValueError, TypeError):
        return None
    value = parsed.timestamp()
    _STAMP_CACHE[timestamp] = value
    return value


def _flbb_pressure(sample, index: _PressureIndex) -> float:
    """Pressure proxy for an FLBB sample: nearest CTD sample in time."""
    return _sample_pressure(sample, index)


def _sample_pressure(sample, index: _PressureIndex) -> float:
    pressure = index.nearest(sample.timestamp)
    return 0.0 if pressure is None else float(pressure)


__all__ = [
    "FILL",
    "CycleScience",
    "FloatProducts",
    "build_cycle_science",
    "read_raw_records",
    "read_raw_records_for",
]

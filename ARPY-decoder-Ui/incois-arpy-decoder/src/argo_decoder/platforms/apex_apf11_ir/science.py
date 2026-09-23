"""APF11 science-log decoding: CTD, FLBB, O2 and SUNA/nitrate.

Everything here dispatches on **record type** and **cycle**. No WMO, float
name, serial or IMEI is read anywhere in this module, and no float-specific
branch exists.

The raw inputs are the consolidated tables produced from the vendor
``apf11dec.py`` record tables, which carry one row per binary science record as
``src_cycle, record_type, timestamp, <payload fields...>``.

CTD handling
------------
The five CTD record types observed in this corpus (``CTD_P``, ``CTD_PT``,
``CTD_PTS``, ``CTD_CP``, ``CTD_bins``) plus the vendor's ``CTD_PTSH`` and
``CTD_CP_H`` variants are all handled by one code path. A cycle may contain
several of them; :func:`select_ctd` picks the richest per cycle by information
content. Salinity is ``None`` whenever the chosen record does not carry it --
it is never synthesised. ``CTD_bins`` is a per-cycle summary rather than a
sample, so it is used as the cycle anchor and not as profile data.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from argo_decoder.platforms.apex_apf11_ir.records import (
    CTD_BINS_ID,
    CTD_PREFERENCE,
    CTD_WITH_SALINITY,
    SCIENCE_RECORDS,
)

#: Record-type name -> the sample kinds it can contribute.
CTD_NAMES = frozenset(
    spec.name
    for spec in SCIENCE_RECORDS.values()
    if spec.record_id in CTD_PREFERENCE
)

FLBB_NAMES = frozenset({"FLBB", "FLBB_BB", "FLBB_CD", "FLBB_FL3"})

#: Field aliases across the FLBB variants, so one code path serves all four.
#: ``FLBB_FL3`` orders backscatter before chlorophyll; ``FLBB_CD``/``FLBB_BB``
#: rename the backscatter signal. Mapping to a canonical pair avoids a
#: per-record-type branch at every use site.
_FLBB_CHL_FIELDS = ("chl_sig",)
_FLBB_BSC_FIELDS = ("bsc_sig", "bcs_sig")


@dataclass(frozen=True)
class CtdSample:
    """One CTD measurement.

    ``salinity`` is ``None`` when the source record does not carry it. This is
    a real state, not a missing value to be filled: two of the four APF11
    floats emit no salinity-bearing record at all.
    """

    cycle: int
    timestamp: str
    pressure: float
    temperature: float | None
    salinity: float | None
    record_type: str
    samples: int | None = None

    @property
    def has_salinity(self) -> bool:
        return self.salinity is not None


@dataclass(frozen=True)
class FlbbSample:
    """One FLBB measurement, in raw counts plus the declared wavelengths.

    ``chl_sig`` and ``bsc_sig`` are telemetry-original counts. Conversion to
    CHLA / BBP700 happens in the calibration layer, not here, so the raw and
    corrected quantities stay distinguishable.
    """

    cycle: int
    timestamp: str
    chl_wave: int | None
    chl_sig: int
    bsc_wave: int | None
    bsc_sig: int
    therm_sig: int | None
    record_type: str


@dataclass(frozen=True)
class O2Sample:
    """One optode measurement from record id 40.

    ``O2`` and ``AirSat`` are computed on the float; the phase and amplitude
    terms are what a Stern-Volmer recomputation consumes. ``TPHASE_DOXY`` as
    published by the GDAC corresponds to ``TCPhase`` -- established by exact
    multiset agreement on 897 published levels (894 exact, 3 within one
    float32 ULP of the third decimal); ``C1RPh - C2RPh == TCPhase``.
    """

    cycle: int
    timestamp: str
    o2: float
    air_sat: float
    temp: float
    cal_phase: float
    tc_phase: float
    c1_rph: float
    c2_rph: float
    c1_amp: float
    c2_amp: float
    raw_temp: float
    record_type: str


@dataclass(frozen=True)
class No3Sample:
    """One nitrate measurement from record id 100 (SUNA).

    ``nitrate`` is the float's own fitted value. It was cross-validated against
    field [20] of ``suna_log.txt`` and matches on every compared sample. The
    final nitrate product additionally depends on the bromide term, which the
    instrument is configured to take from an external CTD value; that dependency
    is deliberately not resolved here.
    """

    cycle: int
    timestamp: str
    nitrate: float
    record_type: str


def _f(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: str) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _payload(row: Mapping[str, str]) -> list[str]:
    """Return the payload fields of a consolidated row.

    The consolidated tables have a four-column header
    (``src_cycle, record_type, timestamp, payload``) but the payload itself is
    comma-joined, so it overruns the header. ``csv.DictReader`` therefore puts
    the first payload value under ``payload`` and every remaining value in the
    ``None`` rest-key. Both parts are reassembled here.

    Named-column layouts are also accepted, so the decoder does not depend on
    the consolidation layout.
    """
    if "payload" in row:
        parts = [row["payload"]]
        rest = row.get(None) or row.get("None")  # type: ignore[arg-type]
        if rest:
            parts.extend(rest)
        return [str(c).strip() for c in parts]
    skip = {"src_cycle", "record_type", "timestamp"}
    return [v for k, v in row.items() if k not in skip and k is not None]


def _cycle(row: Mapping[str, str]) -> int:
    c = _i(row.get("src_cycle", ""))
    return c if c is not None else -1


def decode_ctd(rows: Iterable[Mapping[str, str]]) -> Iterator[CtdSample]:
    """Yield :class:`CtdSample` for every CTD sample record.

    ``CTD_bins`` is skipped here: it is a per-cycle summary (sample count, bin
    count, max pressure), not a measurement. Use :func:`decode_ctd_bins` for it.
    """
    for row in rows:
        name = row.get("record_type", "")
        if name not in CTD_NAMES:
            continue
        spec = next(s for s in SCIENCE_RECORDS.values() if s.name == name)
        p = _payload(row)
        if len(p) < 1:
            continue
        vals: dict[str, float | int | None] = {}
        # Field order follows the vendor table, minus the leading timestamp
        # which the consolidated table already carries in its own column.
        for key, raw in zip(spec.fields[1:], p):
            vals[key] = _f(raw)
        pres = vals.get("pressure")
        if pres is None:
            continue
        yield CtdSample(
            cycle=_cycle(row),
            timestamp=row.get("timestamp", ""),
            pressure=pres,
            temperature=vals.get("temperature"),
            salinity=vals.get("salinity"),
            record_type=name,
            samples=_i(str(vals.get("samples"))) if vals.get("samples") is not None else None,
        )


def decode_ctd_bins(rows: Iterable[Mapping[str, str]]) -> Iterator[tuple[int, str, int, int, float]]:
    """Yield ``(cycle, timestamp, samples, bins, maxpress)`` per cycle summary."""
    bins_name = next(
        s.name for s in SCIENCE_RECORDS.values() if s.record_id == CTD_BINS_ID
    )
    for row in rows:
        if row.get("record_type", "") != bins_name:
            continue
        p = _payload(row)
        if len(p) < 3:
            continue
        samples, bins, maxpress = _i(p[0]), _i(p[1]), _f(p[2])
        if samples is None or bins is None or maxpress is None:
            continue
        yield (_cycle(row), row.get("timestamp", ""), samples, bins, maxpress)


def select_ctd(samples: Sequence[CtdSample]) -> list[CtdSample]:
    """Pick the richest CTD record type per cycle.

    Precedence is :data:`CTD_PREFERENCE`, ordered by information content, so a
    cycle carrying both ``CTD_P`` and ``CTD_PTS`` yields the salinity-bearing
    one. Cycles whose richest record has no salinity simply have no salinity --
    nothing is inferred.
    """
    by_cycle: dict[int, list[CtdSample]] = defaultdict(list)
    for s in samples:
        by_cycle[s.cycle].append(s)

    out: list[CtdSample] = []
    # ``CTD_PREFERENCE`` is a tuple of record **ids** in preference order, so
    # the rank is looked up by id. A record type absent from the list sorts
    # last, so it is only used when nothing better exists in the cycle.
    id_of = {spec.name: spec.record_id for spec in SCIENCE_RECORDS.values()}
    rank = {rid: i for i, rid in enumerate(CTD_PREFERENCE)}
    fallback = len(CTD_PREFERENCE)

    def rank_of(sample: CtdSample) -> int:
        return rank.get(id_of.get(sample.record_type, -1), fallback)

    for cycle in sorted(by_cycle):
        rows = by_cycle[cycle]
        best = min(rank_of(r) for r in rows)
        chosen = [r for r in rows if rank_of(r) == best]
        # Keep the chosen records in timestamp order so the profile stays
        # monotonic in time regardless of how the source file was ordered.
        chosen.sort(key=lambda r: r.timestamp)
        out.extend(chosen)
    return out


def decode_flbb(rows: Iterable[Mapping[str, str]]) -> Iterator[FlbbSample]:
    """Yield :class:`FlbbSample` for every FLBB variant record.

    One path serves ``FLBB``, ``FLBB_BB``, ``FLBB_CD`` and ``FLBB_FL3`` by
    matching on the vendor field names rather than on the record type, so a
    variant that orders backscatter before chlorophyll needs no special case.
    """
    for row in rows:
        name = row.get("record_type", "")
        if name not in FLBB_NAMES:
            continue
        spec = SCIENCE_RECORDS[
            next(k for k, v in SCIENCE_RECORDS.items() if v.name == name)
        ]
        p = _payload(row)
        vals: dict[str, int | None] = {}
        for key, raw in zip(spec.fields[1:], p):
            vals[key] = _i(raw)

        chl = next((vals[k] for k in _FLBB_CHL_FIELDS if vals.get(k) is not None), None)
        bsc = next((vals[k] for k in _FLBB_BSC_FIELDS if vals.get(k) is not None), None)
        if chl is None or bsc is None:
            continue
        yield FlbbSample(
            cycle=_cycle(row),
            timestamp=row.get("timestamp", ""),
            chl_wave=vals.get("chl_wave"),
            chl_sig=chl,
            bsc_wave=next(
                (vals[k] for k in ("bsc_wave", "bsc_wave0") if vals.get(k) is not None),
                None,
            ),
            bsc_sig=bsc,
            therm_sig=vals.get("therm_sig"),
            record_type=name,
        )


def decode_o2(rows: Iterable[Mapping[str, str]]) -> Iterator[O2Sample]:
    """Yield :class:`O2Sample` for record id 40 (Aanderaa optode).

    Record id 90 is the RINKO-FT variant with a different field set and is
    intentionally not handled here; it does not occur in this corpus.
    """
    for row in rows:
        if row.get("record_type", "") != "O2":
            continue
        spec = SCIENCE_RECORDS[40]
        p = _payload(row)
        # The RINKO variant (id 90) has 8 fields, the Aanderaa (id 40) has 11.
        if len(p) < len(spec.fields) - 1:
            continue
        vals = [_f(x) for x in p[: len(spec.fields) - 1]]
        if any(v is None for v in vals):
            continue
        yield O2Sample(
            cycle=_cycle(row),
            timestamp=row.get("timestamp", ""),
            o2=vals[0],
            air_sat=vals[1],
            temp=vals[2],
            cal_phase=vals[3],
            tc_phase=vals[4],
            c1_rph=vals[5],
            c2_rph=vals[6],
            c1_amp=vals[7],
            c2_amp=vals[8],
            raw_temp=vals[9],
            record_type="O2",
        )


def decode_no3(rows: Iterable[Mapping[str, str]]) -> Iterator[No3Sample]:
    """Yield :class:`No3Sample` for record id 100 (SUNA nitrate)."""
    for row in rows:
        if row.get("record_type", "") != "NO3":
            continue
        p = _payload(row)
        if not p:
            continue
        nitrate = _f(p[0])
        if nitrate is None:
            continue
        yield No3Sample(
            cycle=_cycle(row),
            timestamp=row.get("timestamp", ""),
            nitrate=nitrate,
            record_type="NO3",
        )


def deduplicate_samples(samples):
    """Collapse records that arrive twice with identical content.

    An APF11 cycle may be transmitted more than once (Iridium duplex
    delivery: the same ``science_log.bin`` re-sent hours later). The
    consolidated tables merge both transmissions, so every decoded record of
    that cycle appears twice, byte-identical.

    The dedup key is the FULL decoded record (every dataclass field): two
    records are merged only when record type, timestamp and every measured
    value agree exactly, so a partial retransmission with even one changed
    value is kept in full rather than silently discarded. Ordering is
    preserved (first occurrence wins). Nothing is inferred about which
    transmission is "right"; they are provably the same observation.

    Publication evidence (fleet-agnostic): after this dedup, duplex cycles of
    the primary parity float yield exactly the sample counts of the
    transmitted-once set, and the GDAC mono-profile level counts and value
    multisets match the deduplicated sets at float32-ULP level; without it,
    either interleaved half of the doubled stream matches the published
    content equally far below it (even/odd subsequences were both verified
    to under-cover).
    """
    seen: set = set()
    out = []
    for s in samples:
        # Full-content key; dataclass instances hash over all fields.
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


@dataclass(frozen=True)
class ScienceDecoded:
    """Everything decoded from one float's science-log tables."""

    ctd: tuple[CtdSample, ...]
    ctd_selected: tuple[CtdSample, ...]
    ctd_bins: tuple[tuple[int, str, int, int, float], ...]
    flbb: tuple[FlbbSample, ...]
    o2: tuple[O2Sample, ...]
    no3: tuple[No3Sample, ...]

    def cycles(self) -> tuple[int, ...]:
        seen = {s.cycle for s in self.ctd}
        seen |= {s.cycle for s in self.flbb}
        seen |= {s.cycle for s in self.o2}
        seen |= {s.cycle for s in self.no3}
        seen |= {c for c, *_ in self.ctd_bins}
        return tuple(sorted(seen))


def decode_science_records(rows: Iterable[Mapping[str, str]]) -> ScienceDecoded:
    """Decode every science parameter from consolidated rows in one pass.

    The rows are consumed once and demultiplexed by ``record_type``, so the
    cost is independent of how many parameter kinds the float carries.
    """
    materialised = list(rows)
    ctd = tuple(decode_ctd(materialised))
    return ScienceDecoded(
        ctd=ctd,
        ctd_selected=tuple(select_ctd(ctd)),
        ctd_bins=tuple(decode_ctd_bins(materialised)),
        flbb=tuple(decode_flbb(materialised)),
        o2=tuple(decode_o2(materialised)),
        no3=tuple(decode_no3(materialised)),
    )

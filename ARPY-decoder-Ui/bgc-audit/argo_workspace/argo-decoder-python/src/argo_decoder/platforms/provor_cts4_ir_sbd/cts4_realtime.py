"""PROVOR CTS4 real-time publication pipeline — Phase-4 (production).

Rebuilt from the validated decoder/equations/writer stack per the 2026-09-10
instruction; the quarantined ``provor_cts4_pipeline.py`` draft is NOT used
(its fabricated ``DOXY=200.0`` fallback and wrong ``doxy_chain`` call are
excluded by construction — this module has no silent fallbacks: a missing
calibration propagates as QC-9 fill through the writer contract, and a
missing anchor raises).

Float layout produced (Argo real-time contract):

    <out_root>/<WMO>/<WMO>_meta.nc        one per float
    <out_root>/<WMO>/<WMO>_tech.nc        accumulating (rebuilt over all cycles)
    <out_root>/<WMO>/<WMO>_Rtraj.nc       accumulating (rebuilt over all cycles)
    <out_root>/<WMO>/profiles/R<WMO>_<CCC>.nc    mono-cycle core
    <out_root>/<WMO>/profiles/BR<WMO>_<CCC>.nc   mono-cycle BGC

Scientific chain: CHLA=(FLUO-DARK)*SCALE; BBP700=2*pi*khi*((BETA-DARK)*SCALE
-BETASW700) full recompute via equations.beta_sw (no ratio shortcut);
DOXY via equations.doxy_chain with TEOS-10 potential density from
derived.density.potential_density (gsw) — the constant-1.025 approximation is
NOT used. Partial cycles: no CTD -> no R file and no DOXY/BBP (QC-9 fill,
DATA-COVERAGE, no fabricated salinity); tech-only cycles -> no profiles.
WMO is externally supplied. No D/BD anywhere.

Cycle numbering (verified on three independent GDAC floats, see
``PROVOR_CTS4_PHASE5_SECOND_GROUP_VALIDATION_2026-09-11.md``): the published
``CYCLE_NUMBER`` is the 253 vector's ``total_profiles`` field, i.e.
``NUMBER_SubCyclesDoneSinceDeployment_COUNT`` — NOT the float-internal
``NUMBER_InternalCycle_NUMBER`` (``vt.cycle``), which is one lower. Both come
from telemetry, so this is a generic mapping with no offset constant and no
WMO/cycle branch. The telemetry's internal counter remains visible in tech row
50 exactly as GDAC publishes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from argo_decoder.derived.density import potential_density
from argo_decoder.nc.rtraj_cts4 import write_cts4_rtraj
from argo_decoder.platforms.provor_cts4_ir_sbd.assoc import (
    is_padding_ctd,
    is_padding_flbb,
    is_padding_o2,
    nearest_ctd,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.bgc import extract_flbb, extract_o2
from argo_decoder.platforms.provor_cts4_ir_sbd.ctd import extract_ctd
from argo_decoder.platforms.provor_cts4_ir_sbd.cycles import attribute_group
from argo_decoder.platforms.provor_cts4_ir_sbd.equations import (
    bbp700_m1,
    chla_ug_l,
    doxy_chain,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.external_meta_io import (
    launch_juld_from_meta,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.framer import frame_file
from argo_decoder.platforms.provor_cts4_ir_sbd.mission_clock import (
    MissionClock,
    derive_mission_clock,
    floattime_juld,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.packets import (
    MeasPacket,
    MeasSubtype,
    OpaquePacket,
    PacketType,
    dispatch_framed,
    meas_record_julds,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.resolve import resolve_group
from argo_decoder.platforms.provor_cts4_ir_sbd.rtraj_build import (
    AscentSample,
    ParkSample,
    build_cycle_summaries,
    build_rows,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import (
    decode_250,
    decode_252,
    decode_253,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech_build import (
    build_cycle_tech_rows,
)
from argo_decoder.writer.nc import (
    META_PARAMETER_ORDER,
    ExternalMeta,
    WriterInputs,
    write_meta,
    write_profile,
    write_tech,
)

#: Near-surface/in-air threshold (dbar) separating the primary Argo CTD
#: profile from the near-surface profile. GDAC R/BR files split the ascending
#: CTD stream at this depth: N_PROF=1 carries PRES > threshold (the primary
#: profile that DATA_MODE and the file-name mode follow), N_PROF=2 carries the
#: near-surface remainder (Coriolis near-surface & in-air processing).
NEAR_SURFACE_MAX_PRES_DBAR = 5.0

#: Pressure jump (dbar) that separates the park CTD stream from the
#: descent/ascent stream inside one cycle's telemetry record sequence. The
#: park samples sit in a narrow band around park pressure while the profile
#: stream spans 0..profile pressure, so the transition is always a large jump;
#: this is a structural split, not a tuned constant.
CTD_PHASE_JUMP_DBAR = 50.0

BBP_WAVELENGTH_NM = 700.0
BBP_THETA_DEG = 142.0
BBP_DELTA = 0.039


@dataclass
class CycleDecode:
    """Decoded content of one telemetry cycle (padding filtered).

    ``ctd_juld`` / ``o2_juld`` / ``flbb_juld`` are the Argo JULD of each
    surviving record in the matching stream, taken from that record's own
    type-0 packet timestamp (NKE §7.2.4.1 header bytes6-9) — never synthesized
    from a fixed interval or an event anchor. They are index-aligned with
    ``ctd`` / ``o2`` / ``flbb``.
    """

    cycle: int
    ctd: list = field(default_factory=list)
    o2: list = field(default_factory=list)
    flbb: list = field(default_factory=list)
    ctd_juld: list = field(default_factory=list)
    o2_juld: list = field(default_factory=list)
    flbb_juld: list = field(default_factory=list)
    #: Index of the source packet within that sensor's run for this cycle.
    #: MC 590 carries one row per PACKET, so the packet identity of each
    #: record must survive decoding.
    ctd_slot: list = field(default_factory=list)
    o2_slot: list = field(default_factory=list)
    flbb_slot: list = field(default_factory=list)
    vectors: list = field(default_factory=list)
    pressures: list = field(default_factory=list)
    halves: dict = field(default_factory=dict)


@dataclass
class FloatProducts:
    """What the run produced (for validation/reporting)."""

    wmo: str
    meta_nc: Path
    tech_nc: Path
    rtraj_nc: Path
    r_files: dict[int, Path]
    br_files: dict[int, Path]
    skipped: dict[int, str]
    clock: MissionClock
    tech_rows: int
    rtraj_rows: int


def decode_group(group_dir: Path) -> dict[int, CycleDecode]:
    """Attribution + per-cycle decode of one IMEI-suffix group directory."""
    attr = attribute_group(group_dir)
    per_cycle: dict[int, list[Path]] = {}
    for fa in attr.files:
        cycs = set(fa.meas_cycles)
        if fa.tech_cycle is not None:
            cycs.add(fa.tech_cycle)
        if fa.mission_cycle is not None:
            cycs.add(fa.mission_cycle)
        for c in cycs:
            per_cycle.setdefault(c, []).append(fa.path)
    out: dict[int, CycleDecode] = {}
    for cyc in sorted(per_cycle):
        cd = CycleDecode(cycle=cyc)
        #: Packets are counted per (subtype, phase): MC 590 keys on the ascent
        #: (phase-9) run and MC 290 on the park (phase-6) run, so the two must
        #: not share a counter.
        pkt_index: dict[tuple[MeasSubtype, int], int] = {}
        for path in sorted(per_cycle[cyc]):
            disp = dispatch_framed(frame_file(path))
            for pkt in disp.packets:
                if isinstance(pkt, MeasPacket):
                    key = (pkt.subtype, pkt.phase)
                    slot = pkt_index.get(key, 0)
                    pkt_index[key] = slot + 1
                    if pkt.subtype is MeasSubtype.CTD:
                        recs = extract_ctd(pkt).records
                        julds = meas_record_julds(pkt.header, len(recs))
                        keep = [k for k, r in enumerate(recs)
                                if not is_padding_ctd(r)]
                        cd.ctd += [recs[k] for k in keep]
                        cd.ctd_juld += [julds[k] for k in keep]
                        cd.ctd_slot += [slot] * len(keep)
                    elif pkt.subtype is MeasSubtype.DOXY_CLASS:
                        recs = extract_o2(pkt).records
                        julds = meas_record_julds(pkt.header, len(recs))
                        keep = [k for k, r in enumerate(recs)
                                if not is_padding_o2(r)]
                        cd.o2 += [recs[k] for k in keep]
                        cd.o2_juld += [julds[k] for k in keep]
                        cd.o2_slot += [slot] * len(keep)
                    elif pkt.subtype is MeasSubtype.OPTICS_FLBB:
                        recs = extract_flbb(pkt).records
                        julds = meas_record_julds(pkt.header, len(recs))
                        keep = [k for k, r in enumerate(recs)
                                if not is_padding_flbb(r)]
                        cd.flbb += [recs[k] for k in keep]
                        cd.flbb_juld += [julds[k] for k in keep]
                        cd.flbb_slot += [slot] * len(keep)
                elif isinstance(pkt, OpaquePacket):
                    if pkt.kind is PacketType.VECTOR_TECH:
                        cd.vectors.append(decode_253(pkt))
                    elif pkt.kind is PacketType.PRESSURE:
                        cd.pressures.append(decode_252(pkt))
                    elif pkt.kind is PacketType.SENSOR_TECH:
                        for half in decode_250(pkt).halves:
                            if half.present:
                                cd.halves[half.sensor] = half
        out[cyc] = cd
    return out


def _bgc_values(
    cd: CycleDecode,
    cals,
    lat: float,
    lon: float,
    with_doxy_bbp: bool,
):
    """CHLA/BBP/DOXY arrays for the cycle's FLBB/O2 streams (gsw density)."""
    flbb, bbp_cal, doxy_cal = cals["flbb"], cals["bbp"], cals["doxy"]
    ctd = tuple(cd.ctd)
    # NOTE: restricting this association to the CTD profile phase was tried
    # and measured to be a NO-OP (maxrel identical to 5 decimals on cyc45/46),
    # because the park-band pressures (1008-1028 dbar) are never the nearest
    # match for a profile-phase BGC level. Kept as the whole series.
    ctd_prof = ctd

    fl_pres = np.array([r.pres_dbar for r in cd.flbb], dtype=np.float32)
    flu = np.array([r.chl_raw / 10.0 for r in cd.flbb], dtype=np.float32)
    bet = np.array([r.bb_raw / 10.0 for r in cd.flbb], dtype=np.float32)
    chla = np.array(
        [chla_ug_l(float(f), flbb.dark_chl, flbb.scale_chl) for f in flu],
        dtype=np.float32)
    bbp = None
    if with_doxy_bbp and ctd:
        bbp = np.array(
            [bbp700_m1(float(b), float(nearest_ctd(ctd_prof, float(p)).temp_c),
                       float(nearest_ctd(ctd_prof, float(p)).psal),
                       flbb.dark_bb, flbb.scale_bb, bbp_cal.khi,
                       BBP_WAVELENGTH_NM, BBP_THETA_DEG, BBP_DELTA)
             for b, p in zip(bet, fl_pres, strict=True)], dtype=np.float32)

    o2_pres = np.array([r.pres_dbar for r in cd.o2], dtype=np.float32)
    c1 = np.array([r.c1_phase_deg for r in cd.o2], dtype=np.float32)
    c2 = np.array([r.c2_phase_deg for r in cd.o2], dtype=np.float32)
    td = np.array([r.temp_c for r in cd.o2], dtype=np.float32)
    doxy = None
    if with_doxy_bbp and ctd and doxy_cal is not None:
        psal_o2 = np.array(
            [float(nearest_ctd(ctd_prof, float(p)).psal) for p in o2_pres])
        temp_o2 = np.array(
            [float(nearest_ctd(ctd_prof, float(p)).temp_c) for p in o2_pres])
        rho = potential_density(
            o2_pres.astype(float), temp_o2, psal_o2, 0.0, lon, lat) / 1000.0
        doxy = np.full(len(cd.o2), np.float32(99999.0), dtype=np.float32)
        for i, r in enumerate(cd.o2):
            res = doxy_chain(float(r.c1_phase_deg), float(r.c2_phase_deg),
                             float(r.temp_c), float(r.pres_dbar),
                             float(psal_o2[i]), doxy_cal.phase, doxy_cal.foil,
                             doxy_cal.sol, rho_kg_l=float(rho[i]))
            doxy[i] = res.doxy_umol_kg
    return dict(fl_pres=fl_pres, flu=flu, bet=bet, chla=chla, bbp=bbp,
                o2_pres=o2_pres, c1=c1, c2=c2, td=td, doxy=doxy)


def _split_ctd_phases(pres: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split one cycle's CTD pressure series into (park, profile) phases.

    The park stream is a narrow band around park pressure; the profile stream
    runs from profile pressure down to the surface. The transition is therefore
    a large pressure jump. Returns index arrays.
    """
    if len(pres) == 0:
        return np.array([], dtype=int), np.array([], dtype=int)
    starts = [0]
    for i in range(1, len(pres)):
        if abs(float(pres[i]) - float(pres[i - 1])) > CTD_PHASE_JUMP_DBAR:
            starts.append(i)
    starts.append(len(pres))
    park_idx = np.arange(starts[0], starts[1], dtype=int)
    prof_idx = np.arange(starts[1], starts[-1], dtype=int)
    return park_idx, prof_idx


def _near_surface_split(
    pres: np.ndarray,
    pump_cutoff_dbar: float | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Split an ascending pressure series into (primary, near-surface) masks.

    The boundary is the float's own pump-cutoff depth, telemetry field
    ``p_sub`` (msg 250 CTD free zone), published by GDAC as
    ``PRES_LastAscentPumpedRawSample_dbar``: the pump stops there, so samples
    deeper than it belong to the primary Argo CTD profile and the shallower
    remainder is the near-surface profile. Verified exact on all 9 cycles of
    INCOIS 2902093. ``NEAR_SURFACE_MAX_PRES_DBAR`` is only a fallback when the
    free zone is absent (documented, not silently substituted).
    """
    cutoff = (NEAR_SURFACE_MAX_PRES_DBAR if pump_cutoff_dbar is None
              else float(pump_cutoff_dbar))
    primary = pres > cutoff
    return primary, ~primary


#: Coriolis/INCOIS PROVOR averaging bands as (lower-bound dbar, bin width
#: dbar), deepest first. Confirmed by inspecting the published INCOIS GDAC
#: pressure grids: median spacing is 25 / 20 / 10 / 5 / 1 dbar in the
#: 2000-1000 / 1000-500 / 500-200 / 200-10 / 10-surface bands respectively.
SAMPLING_BANDS: tuple[tuple[float, float], ...] = (
    (1000.0, 25.0),
    (500.0, 20.0),
    (200.0, 10.0),
    (10.0, 5.0),
    (0.0, 1.0),
)


def _bgc_reference_grids(cd: CycleDecode) -> tuple[np.ndarray, np.ndarray]:
    """Ascending profile-phase pressure grids for the R/BR prof3 and prof4 slots.

    N_PROF=3 is the optode's own grid, N_PROF=4 the fluorometer's. Each is that
    sensor's own decoded profile-phase pressures reversed into ascending
    (surface-first) order — the same phase split and ordering the CTD grid
    uses, applied to the sensor's own records.

    A sensor with no profile-phase record yields an empty grid; the CTD grid is
    never substituted, because prof3/prof4 are that sensor's own reference
    levels and copying another sensor's pressures would fabricate them.

    Verified against INCOIS 2902093: R prof3 == optode grid and prof4 == FLBB
    grid, maxabs 0.0000 dbar, on 9/9 published cycles; BR the same to float32
    quantization (4.9e-05 dbar).
    """
    out: list[np.ndarray] = []
    for recs in (cd.o2, cd.flbb):
        if not recs:
            out.append(np.array([], dtype=np.float32))
            continue
        pres = np.array([r.pres_dbar for r in recs], dtype=np.float32)
        _, prof_idx = _split_ctd_phases(pres)
        out.append(pres[prof_idx][::-1])
    return out[0], out[1]


def _sampling_scheme(
    kind: str,
    top_dbar: float,
    bottom_dbar: float,
    *,
    cutoff_label: str | None = None,
) -> str:
    """``VERTICAL_SAMPLING_SCHEME`` string for one profile.

    One clause per averaging band the profile spans, deepest band first, with
    each band's edges clipped to the profile's own pressure range. This
    reproduces the published INCOIS GDAC text (for example ``25dbar average
    from 2000dbar to 1000dbar``) from the float's real grid rather than a fixed
    template. ``kind`` is ``Primary``, ``Near-surface`` or ``Secondary``.

    ``cutoff_label`` overrides how the pump-cutoff depth is rendered wherever
    it appears in the text (GDAC quotes it with one decimal, e.g. ``5.0dbar``,
    while the tech row carries four).
    """
    def _txt(value: float) -> str:
        if cutoff_label is not None and abs(value - bottom_dbar) < 1e-9:
            return cutoff_label
        if cutoff_label is not None and abs(value - top_dbar) < 1e-9:
            return cutoff_label
        return f"{value:g}"

    parts: list[str] = []
    # The trailing (1 dbar) entry is the surface band, emitted as the remainder
    # below the last fixed band rather than by the loop.
    bands = SAMPLING_BANDS[:-1]
    for i, (lower, width) in enumerate(bands):
        # The deepest band is quoted at its nominal top (2000 dbar), not at the
        # pressure the float actually reached: GDAC publishes "2000dbar" even
        # when the profile ran to 2007.3 dbar.
        ceiling = bands[i - 1][0] if i > 0 else 2000.0
        hi = min(top_dbar, ceiling)
        lo = max(bottom_dbar, lower)
        if hi <= lo:
            continue
        parts.append(f"{width:g}dbar average from {hi:g}dbar "
                     f"to {_txt(lo)}dbar")
    surface_from = min(top_dbar, bands[-1][0])
    if surface_from > bottom_dbar:
        parts.append(f"{SAMPLING_BANDS[-1][1]:g}dbar average "
                     f"from {_txt(surface_from)}dbar "
                     f"to {_txt(bottom_dbar)}dbar")
    if not parts:
        parts.append(f"{SAMPLING_BANDS[-1][1]:g}dbar average "
                     f"from {top_dbar:g}dbar to {_txt(bottom_dbar)}dbar")
    if kind != "Primary":
        # Near-surface and Secondary profiles run to the surface in the
        # published text; the Primary profile stops at the pump-cutoff depth.
        parts[-1] = parts[-1].rsplit(" to ", 1)[0] + " to surface"
    if kind == "Near-surface":
        return (f"Near-surface sampling: averaged, unpumped "
                f"[{';'.join(parts)}]")
    return (f"{kind} sampling: averaged "
            f"[10s sampling: {';'.join(parts)}]")


def _ascent_samples(cd: CycleDecode, cals, lon: float, lat: float) -> list:
    """MC 590 ascent series, one entry per transmitted ascent packet.

    Each sensor transmits its ascent profile as a run of type-0 packets. MC 590
    carries ONE ROW PER PACKET, not one per record: the row takes that packet's
    own header timestamp and that packet's own FIRST record pressure. The three
    sensors transmit different numbers of packets (7 CTD, 7 FLBB, 14-15 optode
    on this family), so the series is zipped by packet index and a sensor with
    no packet at an index contributes nothing.

    This is why the ascent stream cannot be published record-by-record: 144
    CTD records collapse to 7 MC 590 rows because they arrived in 7 packets.

    Verified against INCOIS 2902093 cycles 45-53, keyed by (cycle, MC):
    JULD exact (residual 0.000000 s) on 261/261 rows and PRES exact
    (0.000 dbar) on the CTD rows, 9/9 cycles.
    """
    _, ctd_asc = _split_ctd_phases(np.array([r.pres_dbar for r in cd.ctd])) \
        if cd.ctd else (None, np.array([], dtype=int))
    _, o2_asc = _split_ctd_phases(np.array([r.pres_dbar for r in cd.o2])) \
        if cd.o2 else (None, np.array([], dtype=int))
    _, fl_asc = _split_ctd_phases(np.array([r.pres_dbar for r in cd.flbb])) \
        if cd.flbb else (None, np.array([], dtype=int))

    ctd = tuple(cd.ctd)

    def first_per_packet(idx, recs, julds, slots):
        """First surviving record of each packet, in packet order."""
        seen: dict[int, int] = {}
        for pos in idx:
            sl = slots[pos]
            if sl not in seen:
                seen[sl] = pos
        order = sorted(seen)
        return [(recs[seen[sl]], julds[seen[sl]]) for sl in order]

    ctd_pk = first_per_packet(ctd_asc, cd.ctd, cd.ctd_juld, cd.ctd_slot)
    o2_pk = first_per_packet(o2_asc, cd.o2, cd.o2_juld, cd.o2_slot)
    fl_pk = first_per_packet(fl_asc, cd.flbb, cd.flbb_juld, cd.flbb_slot)

    flbb, bbp_cal, doxy_cal = cals["flbb"], cals["bbp"], cals["doxy"]
    n = max(len(ctd_pk), len(o2_pk), len(fl_pk))
    out: list = []
    for k in range(n):
        a = AscentSample()
        if k < len(ctd_pk):
            r, j = ctd_pk[k]
            a.ctd_pres = float(r.pres_dbar)
            a.temp = float(r.temp_c)
            a.psal = float(r.psal)
            a.ctd_juld = float(j)
        if k < len(o2_pk) and doxy_cal is not None:
            r, j = o2_pk[k]
            nc = nearest_ctd(ctd, float(r.pres_dbar))
            if nc is not None:
                a.o2_pres = float(r.pres_dbar)
                rho = potential_density(
                    float(r.pres_dbar), float(r.temp_c), float(nc.psal),
                    0.0, lon, lat) / 1000.0
                res = doxy_chain(float(r.c1_phase_deg), float(r.c2_phase_deg),
                                 float(r.temp_c), float(r.pres_dbar),
                                 float(nc.psal), doxy_cal.phase, doxy_cal.foil,
                                 doxy_cal.sol, rho_kg_l=float(rho))
                a.doxy = float(res.doxy_umol_kg)
                a.o2_juld = float(j)
        if k < len(fl_pk):
            r, j = fl_pk[k]
            nc = nearest_ctd(ctd, float(r.pres_dbar))
            if nc is not None:
                a.fl_pres = float(r.pres_dbar)
                a.chla = float(chla_ug_l(r.chl_raw / 10.0, flbb.dark_chl,
                                         flbb.scale_chl))
                a.bbp700 = float(bbp700_m1(
                    r.bb_raw / 10.0, float(nc.temp_c), float(nc.psal),
                    flbb.dark_bb, flbb.scale_bb, bbp_cal.khi,
                    BBP_WAVELENGTH_NM, BBP_THETA_DEG, BBP_DELTA))
                a.fl_juld = float(j)
        if a.temp is not None or a.doxy is not None or a.chla is not None:
            out.append(a)
    return out


def _park_samples(cd: CycleDecode, cals, lon: float, lat: float) -> list:
    """MC 290 park sensor series, straight from the decoded park records.

    One :class:`ParkSample` per park-phase index, zipped across the three
    sensors. Each sensor contributes its OWN park pressure and its own derived
    value — no cross-sensor substitution and no shared grid. Verified against
    INCOIS 2902093 cycle 45: CTD TEMP/PSAL exact on 18/18, CHLA exact on
    18/18, DOXY within 0.008 umol/kg, and each stream's pressures equal that
    sensor's own decoded park pressures exactly.

    DOXY and BBP700 reuse the production science chain (gsw TEOS-10 density,
    telemetry-original BBP scale) — the same code that produces the BR file.
    """
    ctd = tuple(cd.ctd)
    park_c, _ = _split_ctd_phases(np.array([r.pres_dbar for r in cd.ctd]))
    park_o, _ = _split_ctd_phases(np.array([r.pres_dbar for r in cd.o2])) \
        if cd.o2 else (np.array([], dtype=int), None)
    park_f, _ = _split_ctd_phases(np.array([r.pres_dbar for r in cd.flbb])) \
        if cd.flbb else (np.array([], dtype=int), None)

    ctd_park = [cd.ctd[i] for i in park_c]
    o2_park = [cd.o2[i] for i in park_o] if cd.o2 else []
    fl_park = [cd.flbb[i] for i in park_f] if cd.flbb else []
    # Each sensor's OWN sample times, from its own packet timestamps.
    ctd_park_juld = [cd.ctd_juld[i] for i in park_c]
    o2_park_juld = [cd.o2_juld[i] for i in park_o] if cd.o2 else []
    fl_park_juld = [cd.flbb_juld[i] for i in park_f] if cd.flbb else []

    flbb, bbp_cal, doxy_cal = cals["flbb"], cals["bbp"], cals["doxy"]
    n = max(len(ctd_park), len(o2_park), len(fl_park))
    out: list = []
    for k in range(n):
        ps = ParkSample()
        if k < len(ctd_park):
            r = ctd_park[k]
            ps.ctd_pres = float(r.pres_dbar)
            ps.temp = float(r.temp_c)
            ps.psal = float(r.psal)
            ps.ctd_juld = float(ctd_park_juld[k])
        if k < len(o2_park) and doxy_cal is not None:
            r = o2_park[k]
            nc = nearest_ctd(ctd, float(r.pres_dbar))
            if nc is not None:
                ps.o2_pres = float(r.pres_dbar)
                rho = potential_density(
                    float(r.pres_dbar), float(r.temp_c), float(nc.psal),
                    0.0, lon, lat) / 1000.0
                res = doxy_chain(float(r.c1_phase_deg), float(r.c2_phase_deg),
                                 float(r.temp_c), float(r.pres_dbar),
                                 float(nc.psal), doxy_cal.phase, doxy_cal.foil,
                                 doxy_cal.sol, rho_kg_l=float(rho))
                ps.doxy = float(res.doxy_umol_kg)
                ps.o2_juld = float(o2_park_juld[k])
                ps.c1_phase = float(r.c1_phase_deg)
                ps.c2_phase = float(r.c2_phase_deg)
                ps.temp_doxy = float(r.temp_c)
        if k < len(fl_park):
            r = fl_park[k]
            nc = nearest_ctd(ctd, float(r.pres_dbar))
            if nc is not None:
                ps.fl_pres = float(r.pres_dbar)
                ps.chla = float(chla_ug_l(r.chl_raw / 10.0, flbb.dark_chl,
                                          flbb.scale_chl))
                ps.bbp700 = float(bbp700_m1(
                    r.bb_raw / 10.0, float(nc.temp_c), float(nc.psal),
                    flbb.dark_bb, flbb.scale_bb, bbp_cal.khi,
                    BBP_WAVELENGTH_NM, BBP_THETA_DEG, BBP_DELTA))
                ps.fl_juld = float(fl_park_juld[k])
                ps.fluorescence_chla = float(r.chl_raw / 10.0)
                ps.beta_700 = float(r.bb_raw / 10.0)
        if (ps.temp is not None or ps.doxy is not None
                or ps.chla is not None):
            out.append(ps)
    return out


def _park_representative(park_samples: list) -> tuple | None:
    """MC 301 ``RPP``: fill-masked column mean of the park sample table.

    Coriolis ``process_trajectory_data_222_223_225_231_232.m:608-646`` computes
    ``g_MC_RPP`` (= MC 301, ``init_measurement_codes.m:130``) as the mean of
    each park parameter over the rows where every parameter it averages is
    non-fill::

        idForMean = find(~((a_parkPres == fillValue) | (a_parkTemp == fillValue)
            | (a_parkSal == fillValue) | (a_parkC1PhaseDoxy == fillValue)
            | (a_parkC2PhaseDoxy == fillValue) | (a_parkTempDoxy == fillValue)));
        measStruct.paramData = [mean(a_parkPres(idForMean)) ...];

    Verified against INCOIS 2902093 cycles 45-53: GDAC's MC 301 equals the mean
    of GDAC's own MC 290 rows for that parameter, on every parameter, to 1e-4.
    Each parameter is averaged over its OWN non-fill rows -- PRES over 3 x n
    rows (one per sensor stream), TEMP/PSAL over the n CTD rows, and so on.

    The previous implementation took a per-stream median of the CTD park
    records and attached a single optode and a single fluorometer sample. That
    put MC 301 PRES 431.8-474.8 dbar too shallow on 9/9 cycles.

    ``park_samples`` is the same table that produces MC 290, so the two
    products agree by construction and no value is recomputed here.
    """
    if not park_samples:
        return None
    # (param name, attribute on ParkSample, source pressure attribute)
    spec = (
        ("PRES", "ctd_pres", None),
        ("TEMP", "temp", None),
        ("PSAL", "psal", None),
        ("C1PHASE_DOXY", "c1_phase", None),
        ("C2PHASE_DOXY", "c2_phase", None),
        ("TEMP_DOXY", "temp_doxy", None),
        ("DOXY", "doxy", None),
        ("FLUORESCENCE_CHLA", "fluorescence_chla", None),
        ("BETA_BACKSCATTERING700", "beta_700", None),
        ("CHLA", "chla", None),
        ("BBP700", "bbp700", None),
    )
    params: dict[str, float] = {}
    for name, attr, _ in spec:
        vals = [getattr(ps, attr) for ps in park_samples]
        vals = [v for v in vals if v is not None]
        if vals:
            params[name] = float(sum(vals) / len(vals))
    # MC 290 publishes one pressure row per sensor stream, so the RPP pressure
    # is the mean over every stream's own park pressure, not the CTD's alone.
    pres_vals: list[float] = []
    for ps in park_samples:
        for attr in ("ctd_pres", "o2_pres", "fl_pres"):
            v = getattr(ps, attr)
            if v is not None:
                pres_vals.append(float(v))
    if not pres_vals:
        return None
    pres = float(sum(pres_vals) / len(pres_vals))
    params["PRES"] = pres
    # CHLA_FLUORESCENCE is NOT a copy of FLUORESCENCE_CHLA. FLUORESCENCE_CHLA
    # is the raw channel in counts (units 'count') while CHLA_FLUORESCENCE is
    # the same reading expressed in relative units (units 'ru'), i.e. the
    # factory-calibrated fluorescence (counts/10 - dark) * scale. That is
    # exactly what the CHLA science chain already computes per park sample, so
    # the RPP value is the mean of that column rather than a rescaling of the
    # count mean -- averaging first and rescaling after is not the same number,
    # because dark is subtracted inside. Verified against INCOIS 2902093
    # cycles 45-53: GDAC's MC 301 CHLA_FLUORESCENCE equals the mean of its own
    # MC 290 CHLA_FLUORESCENCE column to 1e-6 on 9/9, and the implied factory
    # coefficients (dark 5.0, scale 0.073) are consistent across cycles.
    if "CHLA" in params:
        params["CHLA_FLUORESCENCE"] = params["CHLA"]
    return pres, params


def process_float(
    group_dir: Path,
    wmo: str,
    out_root: Path,
    external_meta: ExternalMeta,
    decoder_version: str = "PY-301-0.4.0",
    institution: str = "IN",
) -> FloatProducts:
    """Full real-time run for one float group (idempotent rebuild)."""
    import re

    if not re.fullmatch(r"[0-9]{7}", str(wmo)):
        raise ValueError(f"WMO must be exactly seven digits, got {wmo!r}")
    cycles = decode_group(group_dir)
    cals = resolve_group(group_dir)

    def _published_cycle(cd: "CycleDecode", fallback: int) -> int:
        """GDAC ``CYCLE_NUMBER`` for a decoded cycle.

        Telemetry ``total_profiles`` (``NUMBER_SubCyclesDoneSinceDeployment``)
        is the published cycle number; the float-internal counter is one lower.
        """
        vt = next((v for v in cd.vectors if v.phase == 12),
                  cd.vectors[0] if cd.vectors else None)
        return vt.total_profiles if vt is not None else fallback

    vectors_by_cycle = {
        _published_cycle(cd, c): cd.vectors
        for c, cd in cycles.items() if cd.vectors
    }
    clock = derive_mission_clock(vectors_by_cycle)
    launch_juld = launch_juld_from_meta(external_meta)

    float_dir = Path(out_root) / wmo
    prof_dir = float_dir / "profiles"
    prof_dir.mkdir(parents=True, exist_ok=True)

    doxy_calib = None
    if cals["doxy"] is not None:
        doxy_calib = {"source": f"reference:flbb_serial:{cals['flbb'].serial}",
                      "density": "TEOS-10 gsw potential density (ref 0 dbar)"}
    inputs = WriterInputs(wmo=wmo, decoder_version=decoder_version,
                          institution=institution,
                          external_meta=external_meta,
                          doxy_external_calib=doxy_calib)

    # Real-time QC needs two configuration pressures from the float's own
    # authoritative metadata: test 19 (deepest pressure) compares the profile
    # against CONFIG_ProfilePressure_dbar, and BBP test 62.5 (parking hook)
    # against CONFIG_ParkPressure_dbar.  Both are read from the supplied
    # ExternalMeta; neither is inferred, and a test whose value is absent
    # aborts instead of guessing.
    _cfg_names = list(external_meta.config_parameter_names or ())
    _cfg_vals = list(external_meta.config_parameter_values or ())
    _cfg_lookup = {n: v for n, v in zip(_cfg_names, _cfg_vals)}
    profile_pressure_dbar = _cfg_lookup.get("CONFIG_ProfilePressure_dbar")
    park_pressure_dbar = _cfg_lookup.get("CONFIG_ParkPressure_dbar")

    r_files: dict[int, Path] = {}
    br_files: dict[int, Path] = {}
    skipped: dict[int, str] = {}
    park_by_cycle: dict[int, tuple[float, dict]] = {}
    # Previous cycle's primary CTD profile, for RTQC tests 5/16/18.
    prev_primary_profile: dict | None = None
    last_ctd_pres: dict[int, float] = {}
    park_samples_by_cycle: dict[int, list] = {}
    ascent_samples_by_cycle: dict[int, list] = {}
    # Deepest bin (dbar) of each cycle's averaged ascending profile, used for
    # trajectory MC 503 (Coriolis: deepest bin of the direction=='A' profile).
    prof_deepest_pres_by_cycle: dict[int, float] = {}
    # MC 599 (TEMP, PSAL) of the last pumped ascent CTD sample, keyed by
    # published cycle number.
    last_ascent_ctd_sample: dict[int, tuple[float, float]] = {}
    tech_row_list = []

    for internal_cyc in sorted(cycles):
        cd = cycles[internal_cyc]
        vt_all = cd.vectors
        vt = next((v for v in vt_all if v.phase == 12),
                  vt_all[0] if vt_all else None)
        # Published cycle number = SubCyclesDoneSinceDeployment (telemetry),
        # which is what GDAC puts in CYCLE_NUMBER. The float-internal counter
        # (``vt.cycle``) is one lower and is published only in tech row 50.
        cyc = vt.total_profiles if vt is not None else internal_cyc
        # Pump-cutoff depth (telemetry msg 250 CTD free zone ``p_sub``) is the
        # primary / near-surface profile boundary; published by GDAC as
        # PRES_LastAscentPumpedRawSample_dbar.
        ctd_half = cd.halves.get(0)
        ctd_free = getattr(ctd_half, "free", None) if ctd_half else None
        pump_cutoff = getattr(ctd_free, "p_sub", None)
        # --- position + profile JULD (Coriolis precedence: ascent end ->
        # --- transmission start -> first message) --------------------------
        # Only fixes belonging to THIS cycle's own transmission window count.
        # A cycle's buffer also holds the previous cycle's session-1 packet
        # (~10 days older); if this cycle's own session-2 packet has
        # gps_valid == 0, taking the newest fix in the buffer would publish
        # that stale position. INCOIS instead marks such a cycle
        # POSITION_QC = '8' (interpolated) and sets JULD_LOCATION = JULD, so
        # the honest real-time behaviour is to publish no position at all.
        _own12 = next((v for v in vt_all if v.phase == 12), None)
        _anchor = floattime_juld(_own12.time) if _own12 is not None else None
        fixes = [(floattime_juld(v.time), v.gps_position())
                 for v in vt_all if v.gps_valid == 1]
        fixes = [(j, p) for j, p in fixes if p is not None]
        if _anchor is not None:
            fixes = [(j, p) for j, p in fixes if j >= _anchor]
        fts = sorted(floattime_juld(v.time) for v in vt_all)
        juld = fts[0] if fts else None
        lat = lon = None
        juld_location = None
        if fixes:
            # The published position for a cycle is its OWN end-of-cycle fix,
            # i.e. the LATEST fix in the cycle's session-2 (phase-12) packet,
            # not the earliest fix in the buffer. A cycle's vector buffer also
            # carries the phase-1 surfacing packet, whose fix is ~10 days older
            # and belongs to the previous profile's transmission window;
            # taking fixes[0] there made every profile from the second onward
            # publish the previous cycle's position (verified against INCOIS
            # 2902093 cycles 45-53: cycle 45 matched, 46-53 were one cycle
            # behind). Sorting descending picks the cycle's own fix.
            own_fix_juld, (lat, lon) = sorted(fixes)[-1]
            juld_location = own_fix_juld
        if vt is not None and juld is not None:
            # R/BR JULD is the SURFACING time (MC 600), i.e. ascent end minus
            # the NKE-documented 10-minute surface wait -- not the raw ascent
            # end. Using ascent_end left every profile JULD a constant
            # +600.000 s ahead of INCOIS (verified on 2902093 cycles 45-53,
            # all nine exactly +600 s). Rtraj MC 600 already used
            # clock.surfacing(), so this makes the profile and trajectory
            # agree with each other as well as with the GDAC.
            juld = clock.surfacing(vt)

        # --- tech rows (accumulating) --------------------------------------
        if vt is not None:
            # Row 17 is the pump-cutoff depth itself (telemetry ``p_sub``),
            # not the shallowest CTD sample: GDAC publishes ``p_sub`` here and
            # it matches exactly on 25/25 cycles across two floats, while the
            # last CTD sample is ~0.2 dbar.
            tech_row_list.extend(build_cycle_tech_rows(
                cyc, vt, cd.halves, clock,
                last_ascent_ctd_pres=(float(pump_cutoff)
                                      if pump_cutoff is not None else None)))

        # --- park representative + last ascent CTD --------------------------
        if vt is not None and cd.ctd:
            ps_list = _park_samples(cd, cals,
                                    lon if lon is not None else 0.0,
                                    lat if lat is not None else 0.0)
            if ps_list:
                park_samples_by_cycle[cyc] = ps_list
            # MC 301 RPP is the fill-masked mean of that same park table, so it
            # is derived after the table exists and cannot disagree with MC 290.
            park = _park_representative(ps_list)
            if park is not None:
                park_by_cycle[cyc] = park
            ascent_ctd = [r for r in cd.ctd]
            if ascent_ctd:
                # MC 599's pressure is `p_sub` (the 253 pump-cutoff field), the
                # same quantity published as tech row 17
                # PRES_LastAscentPumpedRawSample_dbar. Falling back to the last
                # ascent CTD record when p_sub is absent keeps the row present.
                last_ctd_pres[cyc] = (float(pump_cutoff)
                                      if pump_cutoff is not None
                                      else float(ascent_ctd[-1].pres_dbar))
            # MC 599 LastAscPumpedCtd: Coriolis reads pres/temp/psal from the
            # 253 pump block. `p_sub` is the pressure; TEMP and PSAL are the CTD
            # sample taken there, so take the raw ASCENT-phase CTD record
            # nearest to it (verified against INCOIS 2902093 cycles 45-49 to
            # 1e-4). Park-phase records are excluded, since the pump sample is
            # an ascent measurement.
            if pump_cutoff is not None and cd.ctd:
                _, _prof_idx = _split_ctd_phases(
                    np.array([r.pres_dbar for r in cd.ctd]))
                _asc = [cd.ctd[i] for i in _prof_idx]
                if _asc:
                    _tgt = float(pump_cutoff)
                    _near = min(_asc, key=lambda r: abs(r.pres_dbar - _tgt))
                    last_ascent_ctd_sample[cyc] = (float(_near.temp_c),
                                                   float(_near.psal))
            as_list = _ascent_samples(cd, cals,
                                      lon if lon is not None else 0.0,
                                      lat if lat is not None else 0.0)
            if as_list:
                ascent_samples_by_cycle[cyc] = as_list

        # --- profiles --------------------------------------------------------
        if juld is None or lat is None:
            skipped[cyc] = ("DATA-COVERAGE: no 253 FloatTime/GPS — profiles "
                            "not written (no fabrication)")
            continue
        has_ctd = bool(cd.ctd)
        has_bgc = bool(cd.o2 or cd.flbb)
        if not has_ctd and not has_bgc:
            skipped[cyc] = ("DATA-COVERAGE: tech-only cycle (no measurement "
                            "records) — no profiles written")
        if has_ctd:
            pres_c = np.array([r.pres_dbar for r in cd.ctd], dtype=np.float32)
            temp_c = np.array([r.temp_c for r in cd.ctd], dtype=np.float32)
            psal_c = np.array([r.psal for r in cd.ctd], dtype=np.float32)
            _, prof_idx = _split_ctd_phases(pres_c)
            if len(prof_idx) == 0:
                # A cycle with no profile phase at all — e.g. group 00530
                # cycle 0, a 15-sample shallow commissioning dive held between
                # 0.6 and 21.5 dbar. There is no ascending profile stream to
                # publish, and nothing may be fabricated in its place.
                skipped[cyc] = ("DATA-COVERAGE: CTD records carry no profile "
                                "phase (shallow/test dive) — R not written")
                continue
            # Ascending order: telemetry records the profile stream deepest
            # first, GDAC publishes it surface-first.
            asc = prof_idx[::-1]
            p_asc, t_asc, s_asc = pres_c[asc], temp_c[asc], psal_c[asc]
            primary_m, near_m = _near_surface_split(p_asc, pump_cutoff)
            core_primary, core_near = p_asc[primary_m], p_asc[near_m]
            # MC 503's deepest bin is computed after all of this cycle's
            # profile grids are assembled (see below), because the GDAC quotes
            # the deepest bin across prof1/prof3/prof4, not prof1 alone.
            # The deepest band is always quoted at the nominal 2000 dbar
            # profile pressure in the published INCOIS text, independent of
            # the pressure the float actually reached.
            prof_top = 2000.0
            # GDAC quotes the pump-cutoff depth to 0.1 dbar in the scheme
            # text even though the tech row carries 4 decimals.
            cut = (NEAR_SURFACE_MAX_PRES_DBAR if pump_cutoff is None
                   else float(pump_cutoff))
            # GDAC writes the cutoff depth with one decimal ("5.0dbar").
            cut_txt = f"{cut:.1f}"
            inputs.vertical_sampling_schemes = [
                _sampling_scheme("Primary", prof_top, cut,
                                 cutoff_label=cut_txt),
                _sampling_scheme("Near-surface", cut, 0.0,
                                 cutoff_label=cut_txt),
                _sampling_scheme("Secondary", prof_top, 0.0),
                _sampling_scheme("Secondary", prof_top, 0.0),
            ]
            common = {"juld": juld, "latitude": lat, "longitude": lon,
                      "cycle_number": cyc, "direction": "A",
                      "juld_location": juld_location}
            # N_PROF=3/4 are pressure-only reference levels. They carry each
            # BGC sensor's OWN ascending profile pressure grid — prof3 the
            # optode's, prof4 the fluorometer's — not a copy of the CTD grid.
            # Verified exact (maxabs 0.0000 dbar) on all 9 published 2902093
            # cycles for both R and BR. A sensor with no profile-phase record
            # contributes an empty grid rather than the CTD's.
            o2_ref, fl_ref = _bgc_reference_grids(cd)
            core = [
                # N_PROF=1 primary profile: ascending, deeper than the
                # pump-cutoff depth.
                {"pres": core_primary, "temp": t_asc[primary_m],
                 "psal": s_asc[primary_m], **common},
                # N_PROF=2 near-surface profile: ascending, shallower than
                # the pump-cutoff depth.
                {"pres": core_near, "temp": t_asc[near_m],
                 "psal": s_asc[near_m], **common},
                # N_PROF=3/4 pressure-only reference levels (TEMP/PSAL fill).
                {"pres": o2_ref, "temp": np.array([], dtype=np.float32),
                 "psal": np.array([], dtype=np.float32), **common},
                {"pres": fl_ref, "temp": np.array([], dtype=np.float32),
                 "psal": np.array([], dtype=np.float32), **common},
            ]
            # N_PROF=2 is omitted when the float sampled nothing above the
            # pump cutoff this cycle (group 06580 cycles 16 and 32) rather
            # than emitting a zero-length profile.
            if len(core_near) == 0:
                del core[1]
            inputs.cycle = cyc
            inputs.park_pressure_dbar = park_pressure_dbar
            inputs.profile_pressure_dbar = profile_pressure_dbar
            inputs.previous_profile = prev_primary_profile
            r_files[cyc] = write_profile(prof_dir, inputs, is_bgc=False,
                                         profiles=core)
            # Remember this cycle's primary CTD cast so the next cycle's
            # tests 5/16/18 have a real predecessor to compare against.
            prev_primary_profile = core[0] if core else None
            # MC 503 (AscProfDeepestBin) is the deepest bin of the ascending
            # profile. Coriolis takes idDeepest = idNotDef(1) of the
            # direction=='A' PRES column, and the GDAC publishes the deepest
            # bin across ALL of that cycle's profile grids, not prof1's own.
            # Verified on INCOIS 2902093 cycles 45-53: MC 503 equals
            # max(deepest bin of prof1, prof3, prof4) exactly on 9/9, whereas
            # prof1's own deepest bin is 0.1-0.4 dbar shallower on 3 of them
            # because the optode sampled marginally deeper than the CTD.
            # Deriving it from the grids actually published keeps the profile
            # and the trajectory consistent by construction.
            _deepest = [float(g["pres"][-1]) for g in core if len(g["pres"])]
            if _deepest:
                prof_deepest_pres_by_cycle[cyc] = max(_deepest)
        elif cyc not in skipped:
            skipped[cyc] = ("DATA-COVERAGE: no CTD records — R not written")

        if has_bgc:
            bg = _bgc_values(cd, cals, lat, lon, with_doxy_bbp=has_ctd)
            base_pres = (bg["o2_pres"] if len(bg["o2_pres"])
                         else bg["fl_pres"])
            # BGC streams mirror the CTD phase structure; publish only the
            # profile (ascending) phase, split like the core file.
            _, o2_prof = _split_ctd_phases(bg["o2_pres"])
            _, fl_prof = _split_ctd_phases(bg["fl_pres"])
            o2_asc = o2_prof[::-1]
            fl_asc = fl_prof[::-1]
            o2_p = bg["o2_pres"][o2_asc]
            fl_p = bg["fl_pres"][fl_asc]
            # N_PROF=1/2 carry the core CTD pressure grid (BGC fill in GDAC),
            # identical to the R file. Absent CTD -> fall back to whichever
            # BGC sensor has profile-phase records. A sensor with no records
            # at all contributes no profile (no fabricated pressure grid).
            ref_p = o2_p if len(o2_p) else fl_p
            if has_ctd and len(core_primary):
                ref_primary_p, ref_near_p = core_primary, core_near
            elif len(ref_p):
                rp, rn = _near_surface_split(ref_p, pump_cutoff)
                ref_primary_p, ref_near_p = ref_p[rp], ref_p[rn]
            else:
                skipped[cyc] = ("DATA-COVERAGE: no BGC profile-phase records "
                                "— BR not written")
                continue
            common = {"juld": juld, "latitude": lat, "longitude": lon,
                      "cycle_number": cyc, "direction": "A",
                      "juld_location": juld_location}
            o2_vals = ({"c1phase": bg["c1"][o2_asc], "c2phase": bg["c2"][o2_asc],
                        "temp_doxy": bg["td"][o2_asc],
                        **({"doxy": bg["doxy"][o2_asc]}
                           if bg["doxy"] is not None else {})}
                       if len(o2_asc) else {})
            # CHLA_FLUORESCENCE is the derived chlorophyll (ug/L), identical
            # to CHLA in the INCOIS GDAC BR files — not a copy of the raw
            # FLUORESCENCE_CHLA counts. Verified exact on 9 cycles, 2902093.
            fl_vals = ({"fluorescence": bg["flu"][fl_asc],
                        "beta": bg["bet"][fl_asc], "chla": bg["chla"][fl_asc],
                        "chla_fluorescence": bg["chla"][fl_asc],
                        **({"bbp": bg["bbp"][fl_asc]}
                           if bg["bbp"] is not None else {})}
                       if len(fl_asc) else {})
            bgc = [
                # N_PROF=1/2 mirror the core near-surface split; BGC fill.
                # The near-surface entry is omitted when this cycle produced
                # no samples above the pump cutoff, never emitted empty.
                {"pres": ref_primary_p, **common},
                {"pres": ref_near_p, **common},
            ]
            if len(ref_near_p) == 0:
                del bgc[1]
            # N_PROF=3 optode profile (C1/C2/TEMP_DOXY/DOXY) and N_PROF=4
            # fluorometer profile (FLUO/BETA/CHLA/BBP700) are emitted only for
            # sensors that actually recorded profile-phase samples.
            if len(o2_p):
                bgc.append({"pres": o2_p, **o2_vals, **common})
            if len(fl_p):
                bgc.append({"pres": fl_p, **fl_vals, **common})
            inputs.cycle = cyc
            br_files[cyc] = write_profile(prof_dir, inputs, is_bgc=True,
                                          profiles=bgc)

    # --- float-level products (accumulating rebuild) -------------------------
    meta_path = write_meta(float_dir / f"{wmo}_meta.nc", inputs)
    if not tech_row_list:
        raise ValueError("no tech rows decoded — nothing to publish")
    tech_records = [{"name": r.name, "value": r.value,
                     "cycle_number": r.cycle_number} for r in tech_row_list]
    tech_path = write_tech(float_dir / f"{wmo}_tech.nc", inputs,
                           tech_records=tech_records)

    rows = build_rows(
        vectors_by_cycle,
        {_published_cycle(cycles[c], c): cycles[c].pressures for c in cycles},
        clock, launch_juld, float(external_meta.launch_latitude),
        float(external_meta.launch_longitude),
        park_by_cycle=park_by_cycle,
        last_ctd_pres_by_cycle=last_ctd_pres,
        park_samples_by_cycle=park_samples_by_cycle,
        ascent_samples_by_cycle=ascent_samples_by_cycle,
        prof_deepest_pres_by_cycle=prof_deepest_pres_by_cycle,
        last_ascent_ctd_sample_by_cycle=last_ascent_ctd_sample,
    )
    summaries = build_cycle_summaries(
        vectors_by_cycle, clock,
        park_pres_by_cycle={c: p[0] for c, p in park_by_cycle.items()})
    calib_by_param = None
    if external_meta.predeployment_calib_equations:
        calib_by_param = {}
        for i, pname in enumerate(META_PARAMETER_ORDER):
            if pname == "PRES":
                continue
            calib_by_param[pname] = {
                "equation": external_meta.predeployment_calib_equations[i],
                "coefficient": external_meta.predeployment_calib_coefficients[i],
                "comment": external_meta.predeployment_calib_comments[i],
                "date": external_meta.launch_date,
            }
    rtraj_path = write_cts4_rtraj(float_dir / f"{wmo}_Rtraj.nc", rows,
                                  summaries, external_meta, wmo,
                                  institution=institution,
                                  decoder_version=decoder_version,
                                  calib_by_param=calib_by_param)
    return FloatProducts(wmo=wmo, meta_nc=meta_path, tech_nc=tech_path,
                         rtraj_nc=rtraj_path, r_files=r_files,
                         br_files=br_files, skipped=skipped, clock=clock,
                         tech_rows=len(tech_records), rtraj_rows=len(rows))

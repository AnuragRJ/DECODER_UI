"""Provor / Arvor Iridium SBD :class:`PlatformDecoder` plugin.

Routing is driven entirely by :mod:`argo_decoder.config.decoder_table`
(Guardrails §7 "tables not code"): the plugin handles a float when the
matching decoder-table entry has ``transmission == "IRIDIUM_SBD"`` AND
``platform_type`` is a known NKE Provor-family type.

Phase 2 Slice 4: adds rich Tech#2 / PARAM packet decoding, MissionConfig
accumulation seeded from FloatMeta CONFIG_PARAMETER_*, and MATLAB-parity
JULD computed as ``ascentEndDate`` (transmission-start minus buoyancy /
in-air acquisition offsets per CONFIG_PT04/PT31/PT32/PT33).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as _date
from datetime import datetime as _dt
from typing import Any

import numpy as np
import xarray as xr

from argo_decoder.config import DecoderTable, get_decoder_table
from argo_decoder.config.models import DecoderConfig
from argo_decoder.domain.frames import CycleData
from argo_decoder.io.sbd_email import parse_sbd_bytes
from argo_decoder.metadata.models import FloatInfo, FloatMeta
from argo_decoder.platforms.base import DecodeResult, PlatformDecoder, register_decoder
from argo_decoder.platforms.provor_ir_sbd.frames import (
    CtdoPacket,
    CtdPacket,
    Param1Packet,
    Param2Packet,
    SbdPacket,
    Tech1Packet,
    Tech2Packet,
    unpack_packet,
)
from argo_decoder.platforms.provor_ir_sbd.mission import MissionConfig
from argo_decoder.platforms.provor_ir_sbd.profile import ProfileMeta, assemble_profile_meta
from argo_decoder.sensors import attach_doxy, profile_to_dataset
from argo_decoder.sensors import convert_counts as ctd_convert_counts
from argo_decoder.trajectory import bin_cycle_samples
from argo_decoder.util.logging import get_logger

_log = get_logger()

# Platform types handled by this plugin (keys into decoder_table.yaml).
_PROVOR_PLATFORM_TYPES = {
    "PROVOR",
    "ARVOR",
    "ARVOR_D",
    "ARVOR_C",
    "ARVOR_I",
    "ARVOR_I_ICE",
    "ARVOR_N",
    "PROVOR_CTS4",
}


@dataclass
class CycleDecodeState:
    """Accumulated packets decoded for one cycle."""

    cycle_number: int
    tech1_packets: list[Tech1Packet] = field(default_factory=list)
    tech2_packets: list[Tech2Packet] = field(default_factory=list)
    param1_packets: list[Param1Packet] = field(default_factory=list)
    param2_packets: list[Param2Packet] = field(default_factory=list)
    ctd_packets: list[CtdPacket] = field(default_factory=list)
    ctdo_packets: list[CtdoPacket] = field(default_factory=list)
    other_packets: list[SbdPacket] = field(default_factory=list)
    sbd_messages: int = 0
    empty_sbd_messages: int = 0
    gps_fixes: list[tuple[float, float]] = field(default_factory=list)
    email_session_fixes: list[tuple[float, float, datetime | None]] = field(default_factory=list)

    def ctd_counts(self) -> tuple[list[int], list[int], list[int]]:
        """Return concatenated (pres, temp, sal) count lists from CTD + CTDO."""
        pres: list[int] = []
        temp: list[int] = []
        sal: list[int] = []

        def _collect(p_pkts: list[Any]) -> None:
            for pk in p_pkts:
                for k in range(len(pk.pres_counts)):
                    pc, tc, sc = pk.pres_counts[k], pk.temp_counts[k], pk.sal_counts[k]
                    if pc == 0 and tc == 0 and sc == 0:
                        continue
                    pres.append(int(pc))
                    temp.append(int(tc))
                    sal.append(int(sc))

        _collect(self.ctd_packets)
        _collect(self.ctdo_packets)
        return pres, temp, sal

    def ctdo_optode_counts(self) -> tuple[list[int], list[int], list[int]]:
        """Return concatenated (c1phase, c2phase, temp_doxy) count lists from CTDO."""
        c1: list[int] = []
        c2: list[int] = []
        tdoxy: list[int] = []
        for pk in self.ctdo_packets:
            for k in range(len(pk.pres_counts)):
                pc, tc, sc = pk.pres_counts[k], pk.temp_counts[k], pk.sal_counts[k]
                if pc == 0 and tc == 0 and sc == 0:
                    continue
                c1.append(int(pk.c1phase_counts[k]) if k < len(pk.c1phase_counts) else 99999)
                c2.append(int(pk.c2phase_counts[k]) if k < len(pk.c2phase_counts) else 99999)
                tdoxy.append(int(pk.tdoxy_counts[k]) if k < len(pk.tdoxy_counts) else 99999)
        return c1, c2, tdoxy


def _profile_dataset_from_state(
    state: CycleDecodeState,
    *,
    wmo: int,
    info: FloatInfo,
    meta: FloatMeta | None,
    pmeta: ProfileMeta,
    mission: MissionConfig | None = None,
) -> xr.Dataset:
    """Build the mono-profile xr.Dataset for one cycle state."""
    from argo_decoder.derived.doxy import OptodeCalibration, compute_doxy

    extra_attrs: dict[str, Any] = {
        "frame_length": info.frame_length,
        "n_sbd_messages": state.sbd_messages,
        "n_empty_sbd_messages": state.empty_sbd_messages,
        "n_tech1_packets": len(state.tech1_packets),
        "n_tech2_packets": len(state.tech2_packets),
        "n_param1_packets": len(state.param1_packets),
        "n_param2_packets": len(state.param2_packets),
        "n_ctd_packets": len(state.ctd_packets),
        "n_ctdo_packets": len(state.ctdo_packets),
        "n_other_packets": len(state.other_packets),
        "n_gps_fixes": len(state.gps_fixes),
        "first_gps_lat": state.gps_fixes[0][0] if state.gps_fixes else float("nan"),
        "first_gps_lon": state.gps_fixes[0][1] if state.gps_fixes else float("nan"),
        "pres_offset_dbar": pmeta.pres_offset_dbar,
        "juld_source": pmeta.juld_source,
    }
    if state.tech2_packets:
        t2 = state.tech2_packets[-1]
        extra_attrs["exp_nb_desc"] = t2.exp_nb_desc
        extra_attrs["exp_nb_drift"] = t2.exp_nb_drift
        extra_attrs["exp_nb_asc"] = t2.exp_nb_asc
        extra_attrs["exp_nb_near_surface"] = t2.exp_nb_near_surface
        extra_attrs["exp_nb_in_air"] = t2.exp_nb_in_air
        if t2.reset_date is not None:
            extra_attrs["last_reset_date"] = t2.reset_date.isoformat()

    p_counts, t_counts, s_counts = state.ctd_counts()
    if not p_counts:
        ds = xr.Dataset(
            attrs={
                "wmo": wmo,
                "cycle": state.cycle_number,
                "decoder": "provor_ir_sbd",
                "platform_type": info.float_type,
                "decoder_version": info.decoder_version,
                "decoder_id": info.decoder_id,
                **extra_attrs,
            }
        )
    else:
        ctd_prof = ctd_convert_counts(
            pres_counts=p_counts,
            temp_counts=t_counts,
            sal_counts=s_counts,
        )
        ctd_prof.pressure_dbar = pmeta.apply_pres_offset(ctd_prof.pressure_dbar)
        ds = profile_to_dataset(
            ctd_prof,
            wmo=wmo,
            cycle=state.cycle_number,
            platform_type=info.float_type,
            decoder_version=info.decoder_version,
            decoder_id=info.decoder_id,
            latitude=pmeta.latitude,
            longitude=pmeta.longitude,
            extra_attrs=extra_attrs,
        )
        extra_attrs["n_ctd_bins"] = len(p_counts)

        # Compute DOXY if optode (CTDO) data exist for this cycle. The
        # optode counts are aligned with CTD bins in acquisition order;
        # profile_to_dataset sorts ascending by pressure, so we re-sort
        # DOXY with the same permutation. The permutation is reproduced
        # here (identical to ctd.py) rather than leaking it out to keep
        # the profile_to_dataset signature simple.
        if state.ctdo_packets:
            try:
                opt_cal = OptodeCalibration.from_meta_dict(
                    (
                        (getattr(meta, "model_extra", None) or {}).get(
                            "CALIBRATION_COEFFICIENT", [None]
                        )
                        or [None]
                    )[0].get("OPTODE")
                    if meta is not None
                    else None
                )
            except (AttributeError, IndexError, TypeError, KeyError):
                opt_cal = OptodeCalibration()
            c1, c2, tdoxy = state.ctdo_optode_counts()
            # Match CTD count order: CTD packets first (CTD-only have no
            # optode -> fill), then CTDO packets (all channels present).
            # ctd_counts returns CTD-then-CTDO concatenation; CTD packets
            # have no optode, so prepend fill for them.
            n_ctd = sum(
                sum(
                    1
                    for k in range(len(pk.pres_counts))
                    if not (pk.pres_counts[k] == pk.temp_counts[k] == pk.sal_counts[k] == 0)
                )
                for pk in state.ctd_packets
            )
            # Trim optode counts to match CTDO pressure/temp/sal length
            n_ctdo = len(p_counts) - n_ctd
            c1_full = [99999] * n_ctd + list(c1[:n_ctdo])
            c2_full = [99999] * n_ctd + list(c2[:n_ctdo])
            tdoxy_full = [99999] * n_ctd + list(tdoxy[:n_ctdo])
            # Sort into ascending-pressure order (same permutation as
            # profile_to_dataset uses on ctd_prof.pressure_dbar).
            order = np.argsort(ctd_prof.pressure_dbar)
            c1_sorted = np.array([c1_full[i] for i in order], dtype=np.float64)
            c2_sorted = np.array([c2_full[i] for i in order], dtype=np.float64)
            tdoxy_sorted = np.array([tdoxy_full[i] for i in order], dtype=np.float64)
            lat = pmeta.latitude if pmeta.latitude is not None else 0.0
            lon = pmeta.longitude if pmeta.longitude is not None else 0.0
            try:
                doxy_vals = compute_doxy(
                    c1phase_counts=c1_sorted,
                    c2phase_counts=c2_sorted,
                    temp_doxy_counts=tdoxy_sorted,
                    pres=ds["PRES"].values,
                    temp_ctd=ds["TEMP"].values,
                    psal=ds["PSAL"].values,
                    latitude=float(lat),
                    longitude=float(lon),
                    cal=opt_cal,
                )
                attach_doxy(ds, doxy_vals)
            except Exception as exc:  # pragma: no cover - defensive
                _log.warning("doxy_compute_failed", cycle=state.cycle_number, error=str(exc))

    # M5 trajectory binning: classify every CTD/CTDO sample into the
    # standard Argo measurement codes (descent / drift / ascent / in-air
    # / emergency). Park pressure is carried in MissionConfig once
    # CONFIG_PT19 is decoded (currently placeholder; bins route via
    # deepest-sample heuristic when None). Full trajectory NetCDF
    # emission lands in a follow-up slice once a Tech2-bearing float is
    # available for oracle validation.
    #
    # Bin counts are stored as a JSON-encoded STRING attribute because
    # NetCDF4 (and xarray's to_netcdf) does not allow dict-valued
    # attributes; JSON round-trips unambiguously and is easy for
    # downstream tooling to parse.
    if "PRES" in ds.data_vars:
        import json as _json

        bins = bin_cycle_samples(
            pres=ds["PRES"].values,
            temp=ds["TEMP"].values,
            psal=ds["PSAL"].values,
            cndc=ds["CNDC"].values if "CNDC" in ds.data_vars else None,
            doxy=ds["DOXY"].values if "DOXY" in ds.data_vars else None,
            park_pressure=None,
        )
        bin_counts = {str(int(code)): len(b) for code, b in bins.items() if len(b) > 0}
        ds.attrs["trajectory_bin_counts"] = _json.dumps(bin_counts, sort_keys=True)

    _assign_profile_scalars(ds, pmeta)
    return ds


def _assign_profile_scalars(ds: xr.Dataset, pmeta: ProfileMeta) -> None:
    """Add Argo-standard profile scalars (0-d variables) to ``ds``.

    Applies profile-scalar RTQC (TEST001 platform id, TEST002 impossible
    date, TEST003 impossible location) so the on-disk JULD_QC /
    POSITION_QC reflect real-time plausibility checks rather than the
    raw fix source (GPS=1 / Iridium=0) alone.
    """
    from argo_decoder.rtqc.profile_scalar import run_profile_scalar_tests

    juld = np.float64(pmeta.juld) if pmeta.juld is not None else np.float64(np.nan)
    lat = np.float64(pmeta.latitude) if pmeta.latitude is not None else np.float64(np.nan)
    lon = np.float64(pmeta.longitude) if pmeta.longitude is not None else np.float64(np.nan)
    scalar_qc = run_profile_scalar_tests(
        juld=float(juld) if np.isfinite(juld) else None,
        latitude=float(lat) if np.isfinite(lat) else None,
        longitude=float(lon) if np.isfinite(lon) else None,
        platform_known=True,
        juld_qc_in=pmeta.juld_qc if pmeta.juld_qc else None,
        position_qc_in=pmeta.position_qc if pmeta.position_qc else None,
    )
    ds["JULD"] = (
        (),
        juld,
        {
            "long_name": "Julian day (UTC) of the profile since 1950-01-01 00:00:00",
            "units": "days since 1950-01-01 00:00:00 UTC",
            "conventions": "Argo reference table 10",
            "_FillValue": np.float64(999999.0),
        },
    )
    ds["JULD_QC"] = (
        (),
        np.array(scalar_qc.juld_qc, dtype="|S1"),
        {"long_name": "Quality on JULD", "conventions": "Argo reference table 2"},
    )
    ds["LATITUDE"] = (
        (),
        lat,
        {
            "long_name": "Latitude of the profile, N>0",
            "units": "degrees_north",
            "valid_min": -90.0,
            "valid_max": 90.0,
            "_FillValue": np.float64(99999.0),
        },
    )
    ds["LONGITUDE"] = (
        (),
        lon,
        {
            "long_name": "Longitude of the profile, E>0",
            "units": "degrees_east",
            "valid_min": -180.0,
            "valid_max": 180.0,
            "_FillValue": np.float64(99999.0),
        },
    )
    ds["POSITION_QC"] = (
        (),
        np.array(scalar_qc.position_qc, dtype="|S1"),
        {"long_name": "Quality on position", "conventions": "Argo reference table 2"},
    )
    ds["DIRECTION"] = (
        (),
        np.array(pmeta.direction.encode("ascii"), dtype="|S1"),
        {"long_name": "Direction of the profile"},
    )
    ds["DATA_MODE"] = (
        (),
        np.array(pmeta.data_mode.encode("ascii"), dtype="|S1"),
        {
            "long_name": "Delayed mode or real time data",
            "conventions": "Argo reference table 20",
        },
    )
    if pmeta.position_system:
        ds.attrs["positioning_system"] = pmeta.position_system


def _seed_mission_from_meta(meta: FloatMeta | None) -> MissionConfig:
    """Build a MissionConfig seeded from FloatMeta CONFIG_PARAMETER_* extras."""
    cfg = MissionConfig()
    if meta is None:
        return cfg
    extras = getattr(meta, "model_extra", None) or {}
    names = extras.get("CONFIG_PARAMETER_NAME", {})
    values = extras.get("CONFIG_PARAMETER_VALUE", {})
    if isinstance(names, dict) and isinstance(values, dict):
        kv: dict[str, Any] = {}
        # names/values are parallel dicts with matching numeric suffixes
        for k, name_v in names.items():
            key_id = k.split("_")[-1]
            v = values.get(f"CONFIG_PARAMETER_VALUE_{key_id}")
            if isinstance(name_v, str) and v is not None:
                kv[name_v.split("_", 1)[0] if "_" in name_v else name_v] = v
                # Also map the long name prefix to the value for short lookup.
                short = name_v[:11]
                kv[short] = v
        cfg.seed_from_meta(kv)
    return cfg


@register_decoder
class ProvorIridiumSbdDecoder(PlatformDecoder):
    """Decoder for NKE Provor / Arvor floats over Iridium SBD (decoder ids 201-232)."""

    platform_type = "provor_ir_sbd"

    def __init__(
        self,
        config: DecoderConfig,
        *,
        decoder_table: DecoderTable | None = None,
    ) -> None:
        super().__init__(config)
        self._table = decoder_table or get_decoder_table()

    def can_handle(self, info: FloatInfo, meta: FloatMeta | None) -> bool:
        del meta
        entry: Any = None
        # Prefer numeric decoder_id (authoritative) over FLOAT_TYPE string which
        # legacy *_info.json files sometimes label as the marketing family
        # (e.g. FLOAT_TYPE="PROVOR" for decoder_id 221 which is ARVOR_DEEP 5.67).
        if info.decoder_id is not None:
            try:
                entry = self._table.by_decoder_id(info.decoder_id)
            except KeyError:
                entry = None
        if entry is None:
            try:
                entry = self._table.by_platform_version(info.float_type, info.decoder_version)
            except KeyError:
                return False
        if entry.transmission != "IRIDIUM_SBD":
            return False
        # ``profile_class`` names the wire-protocol family of the entry.
        # This class implements the NKE demo SBD protocol, whose entries
        # carry ``profile_class: null``. ARVOR-I SBE41CP entries (e.g.
        # decoder ids 222/232, ``profile_class: arvor_i_sbe41cp``) speak a
        # different protocol and get a dedicated plugin; until it exists
        # routing must fall through to NullDecoder rather than let this
        # class NKE-decode ARVOR-I frames.
        if entry.profile_class is not None:
            return False
        return entry.platform_type in _PROVOR_PLATFORM_TYPES

    def decode_float(
        self,
        wmo: int,
        info: FloatInfo,
        meta: FloatMeta | None,
        cycles: list[CycleData],
    ) -> DecodeResult:
        result = DecodeResult(wmo=wmo)
        # Carry metadata onto the result so the NetCDF writer (and the
        # multi-profile builder it calls) can emit ADMT-compliant
        # bookkeeping strings (PLATFORM_TYPE, DATA_CENTRE, PI_NAME, ...).
        result.info = info
        result.meta = meta
        result.decoder_version = info.decoder_version
        result.institution = "CORIOLIS"
        mission = _seed_mission_from_meta(meta)

        by_cycle: dict[int, CycleDecodeState] = {}
        for cd in cycles:
            for rf in cd.frames:
                src = getattr(rf, "payload", b"")
                state = by_cycle.setdefault(cd.cycle, CycleDecodeState(cycle_number=cd.cycle))
                session, payload = parse_sbd_bytes(src)
                state.sbd_messages += 1
                if session.gps_lat is not None and session.gps_lon is not None:
                    fix = (session.gps_lat, session.gps_lon, session.session_time_utc)
                    state.email_session_fixes.append(fix)
                    state.gps_fixes.append((session.gps_lat, session.gps_lon))
                if not payload:
                    state.empty_sbd_messages += 1
                    continue
                try:
                    pkt = unpack_packet(payload)
                except (ValueError, IndexError) as exc:
                    _log.warning("sbd_unpack_failed", error=str(exc), cycle=cd.cycle)
                    continue
                if isinstance(pkt, Tech1Packet):
                    state.tech1_packets.append(pkt)
                    if pkt.gps_lat is not None and pkt.gps_lon is not None:
                        state.gps_fixes.append((pkt.gps_lat, pkt.gps_lon))
                elif isinstance(pkt, Tech2Packet):
                    state.tech2_packets.append(pkt)
                elif isinstance(pkt, Param1Packet):
                    state.param1_packets.append(pkt)
                    mission.apply_param1(
                        pkt.pt04_centisec,
                        pkt.pt31_min,
                        pkt.pt32_centisec,
                        pkt.pt33_cycles,
                        pkt.packet_time,
                    )
                elif isinstance(pkt, Param2Packet):
                    state.param2_packets.append(pkt)
                elif isinstance(pkt, CtdPacket):
                    state.ctd_packets.append(pkt)
                elif isinstance(pkt, CtdoPacket):
                    state.ctdo_packets.append(pkt)
                else:
                    state.other_packets.append(pkt)

        for cyc_num, state in sorted(by_cycle.items()):
            pmeta = assemble_profile_meta(
                cycle_number=cyc_num,
                launch_date=_to_utc_datetime(info.launch_date),
                reference_day=_to_utc_datetime(info.reference_day),
                tech1_packets=state.tech1_packets,
                email_session_fixes=state.email_session_fixes,
                mission=mission,
            )
            ds = _profile_dataset_from_state(
                state, wmo=wmo, info=info, meta=meta, pmeta=pmeta, mission=mission
            )
            ds.attrs["config_updates_applied"] = mission.updates
            result.mono_profile_datasets[cyc_num] = ds
            result.cycles.append(CycleData(wmo=wmo, cycle=cyc_num, frames=[]))

        return result


def _to_utc_datetime(d: object) -> datetime:
    """Convert a date/datetime to a tz-aware UTC datetime (midnight for plain dates)."""
    if isinstance(d, _dt):
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    if isinstance(d, _date):
        return _dt(d.year, d.month, d.day, tzinfo=UTC)
    return _dt(1950, 1, 1, tzinfo=UTC)


__all__ = ["ProvorIridiumSbdDecoder"]

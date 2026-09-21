"""Profile-level assembly for Provor/Arvor Iridium SBD cycles.

Combines decoded packet streams for one cycle (tech#1, tech#2, parameter,
CTD/CTDO, GPS/session metadata) into profile-level scalars:

* ``JULD``           - profile time (days since 1950-01-01 00:00 UTC, Argo
                       ref table 10; MATLAB ``g_decArgo_janFirst1950InMatlab``).
* ``LATITUDE``/``LONGITUDE`` - best GPS fix (tech#1) else Iridium session fix.
* ``DIRECTION``      - ``"A"`` (ascending; CTS4 fast-path only).
* ``PRES`` correction - surface pressure offset from tech#1 field 44.
* ``JULD_QC`` / ``POSITION_QC`` - Argo QC flags (b'1' = good GPS, b'0' = fallback).

Phase 2 Slice 4: JULD is computed as ``ascentEndDate`` (22 dbar crossing)
using CONFIG_PT04 / PT31 / PT32 / PT33 from :class:`MissionConfig`, matching
``compute_prv_dates_221_228_229.m``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from argo_decoder.platforms.provor_ir_sbd.frames import Tech1Packet
from argo_decoder.platforms.provor_ir_sbd.mission import (
    MissionConfig,
    compute_profile_datetime,
)

# MATLAB anchor: datenum('1950-01-01 00:00:00') = 712224.
_JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


def datetime_to_juld(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt - _JULD_EPOCH).total_seconds() / 86400.0


def juld_to_datetime(juld: float) -> datetime:
    return _JULD_EPOCH + timedelta(days=float(juld))


@dataclass
class ProfileMeta:
    direction: str = "A"
    juld: float | None = None
    juld_qc: bytes = b"0"
    juld_source: str = ""
    """Debug tag describing how JULD was derived (``GPS_ASCENT_END`` etc.)."""
    latitude: float | None = None
    longitude: float | None = None
    position_qc: bytes = b"0"
    position_system: str = "GPS"
    pres_offset_dbar: float = 0.0
    trans_start_date: datetime | None = None
    ascent_end_date: datetime | None = None
    gps_date: datetime | None = None
    vertical_sampling_scheme: str = ""
    config_mission_flag: int = 0
    cycle_number: int | None = None
    gps_fixes: int = 0
    data_mode: str = "A"
    extra: dict[str, Any] = field(default_factory=dict)

    def apply_pres_offset(self, pres_values: list[float]) -> list[float]:
        """Subtract the surface pressure offset from each PRES bin,
        preserving the PRES fill sentinel (9999.9)."""
        if self.pres_offset_dbar == 0.0:
            return list(pres_values)
        out: list[float] = []
        for p in pres_values:
            out.append(9999.9 if p == 9999.9 else p - self.pres_offset_dbar)
        return out


def _decode_pres_offset(tech1_packets: list[Tech1Packet]) -> float:
    """Decode surface pressure offset (dbar) from tech#1 field 44.

    Field 44 is an unsigned 8-bit value encoding a signed two's-complement
    offset in units of 0.1 dbar.
    """
    for pkt in tech1_packets:
        f = getattr(pkt, "fields", None)
        if f is None or len(f) <= 44:
            continue
        raw = int(f[44])
        signed = raw - 256 if raw >= 128 else raw
        return signed / 10.0
    return 0.0


def _best_gps_from_tech1(
    tech1_packets: list[Tech1Packet],
    reference_day: datetime,
    email_dt_hint: datetime | None = None,
) -> tuple[tuple[float, float] | None, datetime | None, int | None]:
    """Pick (lat, lon, gps_date, trans_start_hour) from tech#1 packets.

    Uses the **last** valid GPS fix from tech#1 packets (matches MATLAB
    ascending-end fix). ``gps_date`` is derived from the GPS fix HH/MM/SS
    carried in fields 38..40 plus the dd/mm/yy calendar day in fields
    41..43. If the calendar day is not decodable (all zeros), we fall back
    to ``reference_day + sub_day_offset`` (the MATLAB convention during a
    mission) and finally leave it ``None`` so JULD falls back to the
    Iridium session time.
    """
    ref = reference_day if reference_day.tzinfo else reference_day.replace(tzinfo=UTC)
    best_xy: tuple[float, float] | None = None
    best_dt: datetime | None = None
    best_trans_hour: int | None = None
    for pkt in tech1_packets:
        if pkt.gps_lat is None or pkt.gps_lon is None:
            continue
        best_xy = (pkt.gps_lat, pkt.gps_lon)
        best_trans_hour = pkt.trans_start_hour
        gps_dt: datetime | None = None
        if (
            pkt.float_time_elapsed_s is not None
            and pkt.gps_day is not None
            and pkt.gps_month is not None
            and pkt.gps_year_offset is not None
            and pkt.gps_day != 0
            and pkt.gps_month != 0
        ):
            yy = pkt.gps_year_offset
            year = 2000 + yy if yy < 80 else 1900 + yy
            try:
                gps_dt = datetime(
                    year,
                    pkt.gps_month,
                    pkt.gps_day,
                    tzinfo=UTC,
                ) + timedelta(seconds=float(pkt.float_time_elapsed_s))
            except ValueError:
                gps_dt = None
        if gps_dt is None and pkt.float_time_elapsed_s is not None:
            gps_dt = ref + timedelta(seconds=float(pkt.float_time_elapsed_s))
        best_dt = gps_dt
    return best_xy, best_dt, best_trans_hour


def assemble_profile_meta(
    *,
    cycle_number: int,
    launch_date: datetime,
    reference_day: datetime,
    tech1_packets: list[Tech1Packet],
    email_session_fixes: list[tuple[float, float, datetime | None]],
    mission: MissionConfig | None = None,
) -> ProfileMeta:
    """Build a :class:`ProfileMeta` from the packet stream of one cycle."""
    meta = ProfileMeta(cycle_number=cycle_number)
    if mission is None:
        mission = MissionConfig()

    meta.pres_offset_dbar = _decode_pres_offset(tech1_packets)

    # Use the earliest email session time as a hint for the absolute day
    # when the GPS fix's dd/mm/yy is zero (pre-deployment testing).
    email_hint: datetime | None = None
    for _lat, _lon, e_dt in email_session_fixes:
        if e_dt is not None:
            email_hint = e_dt
            break
    best_xy, best_gps_dt, trans_hour = _best_gps_from_tech1(
        tech1_packets, reference_day, email_hint
    )

    email_xy: tuple[float, float] | None = None
    email_dt: datetime | None = None
    for e_lat, e_lon, e_dt in email_session_fixes:
        if best_xy is None:
            email_xy = (e_lat, e_lon)
        if e_dt is not None and email_dt is None:
            email_dt = e_dt
        if email_xy is not None and email_dt is not None:
            break

    if best_xy is not None:
        meta.latitude, meta.longitude = best_xy
        meta.position_system = "GPS"
        meta.position_qc = b"1"
        meta.gps_date = best_gps_dt
    elif email_xy is not None:
        meta.latitude, meta.longitude = email_xy
        meta.position_system = "IRIDIUM"
        meta.position_qc = b"0"

    meta.gps_fixes = len(tech1_packets) + len(email_session_fixes)

    dt, source, qc = compute_profile_datetime(
        cycle_number=cycle_number,
        mission=mission,
        gps_date=best_gps_dt,
        trans_start_hour=trans_hour,
        email_session_dt=email_dt,
        launch_date=launch_date,
    )
    meta.juld = datetime_to_juld(dt)
    meta.juld_qc = qc
    meta.juld_source = source
    if source in ("GPS_ASCENT_END", "GPS_TRANS_START"):
        meta.ascent_end_date = dt if source == "GPS_ASCENT_END" else None
        if best_gps_dt is not None and trans_hour is not None:
            from argo_decoder.platforms.provor_ir_sbd.mission import compute_trans_start_date

            meta.trans_start_date = compute_trans_start_date(best_gps_dt, trans_hour)
    return meta


__all__ = [
    "ProfileMeta",
    "assemble_profile_meta",
    "datetime_to_juld",
    "juld_to_datetime",
]

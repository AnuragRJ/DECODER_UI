"""Decoding of PROVOR CTS4 technical packets 253/252/251/250 (Phase 2A).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md``
§1/§6 as extended by the Phase-2A scope (decode only; no calibration, no
emission, no CSV writes).

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7.2.4.6
(packet 253, vector technical data), §7.2.4.7 (packet 252, pressure packet),
§7.2.4.8 (packet 251, sensor parameters), §7.2.4.9 (packet 250, sensor
technical data). All integers big-endian unless noted (the 250 free zones are
explicitly **little-endian** per the manual).

Packet 253 (140 bytes, NKE §7.2.4.6): float time, serial, profile/cycle
identity, mission-relative day/hour stamps ("resolution: 1 minute", carried as
raw u16 counts — see :func:`hhmm_from_minutes`), hydraulic action counters,
1-Bar-resolution pressure extremes, grounding / emergency / remote-control
sections, GPS fix, show-mode flags, 33 spare zero bytes. Field order and
offsets are pinned by :class:`VectorTech` (offsets verified to sum to 140).

Packet 252 (140 bytes, NKE §7.2.4.7): cycle u16 + 27 hydraulic samples of
``(phase&profile, pump-or-eV, pressure Bar, relative time minutes)`` + 2 spare
zero bytes. Phase rides the high nibble, profile the low nibble. Buoyancy
reduction hydraulics are excluded by the manual.

Packet 251 (140 bytes, NKE §7.2.4.8): up to 12 change records of ``(sensor,
parameter type, parameter number, old float32, new float32)`` + 7 spare zero
bytes. Transmitted only when a parameter changed since the previous session;
absent from the 517-file corpus, so the float32 endianness (big-endian, NKE
convention) is documented but unvalidated against telemetry.

Packet 250 (140 bytes = two 70-byte halves, NKE §7.2.4.9): per-sensor
transmission/acquisition counters, status, and a 50-byte sensor-specific free
zone (little-endian): CTD surface-offset / subsurface (P, T, S) float32s, FLBB
serial + scale/dark coefficient slots, optode empty. A half with sensor id
``0xFF`` is filler. Any other unknown sensor id raises loudly (a new sensor is
a discovery, not noise).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from argo_decoder.platforms.provor_cts4_ir_sbd.packets import OpaquePacket, PacketType

#: Full 140-byte rows (the framer guarantees this; checked loudly anyway).
PACKET_LEN = 140
#: Spare tail of packet 253 (33 zero bytes, NKE §7.2.4.6).
VECTOR_SPARE_OFFSET = 107
VECTOR_SPARE_LEN = 33
#: Samples per 252 pressure packet (NKE §7.2.4.7).
PRESSURE_N_SAMPLES = 27
PRESSURE_STRIDE = 5
PRESSURE_SAMPLES_OFFSET = 3
PRESSURE_SPARE_LEN = 2
#: Change records per 251 packet (NKE §7.2.4.8).
PARAMS_N_CHANGES = 12
PARAMS_CHANGE_STRIDE = 11
PARAMS_CHANGES_OFFSET = 1
PARAMS_SPARE_LEN = 7
#: 250 half-packet geometry (NKE §7.2.4.9: each 70-byte half opens with the
#: 250 packet-type byte, then the sensor id X; corpus-verified).
HALF_LEN = 70
N_HALVES = 2
FREE_LEN = 50
FREE_OFFSET_IN_HALF = 20
X_OFFSET_IN_HALF = 1
#: Sensor id marking a 250 filler half (NKE §7.2.4.9).
FILLER_SENSOR_ID = 0xFF

#: 250 sensor ids (NKE §7.2.4.9 "Data Type").
SENSOR_NAMES: dict[int, str] = {0: "CTD", 1: "Optode", 4: "FLBB"}


class UnknownSensorTypeError(ValueError):
    """Raised for a 250 sensor id outside {0, 1, 4, 0xFF} (a discovery)."""


def _u16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def hhmm_from_minutes(value: int) -> tuple[int, int]:
    """Split a minute count into ``(HH, MM)`` (pure arithmetic).

    Applies to the 253 hour fields iff the wire stores minutes-since-midnight
    (NKE §7.2.4.6 wording: "resolution: 1 minute"); the corpus distribution
    adjudicates (values > 1439 or non-minute digit patterns would refute it).
    """
    return divmod(value, 60)


def vacuum_mbar_x5(raw: int) -> int:
    """Internal vacuum in mbar under the direct NKE reading.

    NKE §7.2.4.6: "modulo 5mbar, 5mbar resolution" for a 1-byte field, i.e.
    5 mbar per count. GDAC reference ``PRESSURE_InternalVacuumAtSurface_mbar``
    (e.g. 770 mbar on 2902091 cycle 1) implies raw values ~140-160.
    """
    return raw * 5


def battery_dropout_v(raw: int) -> float:
    """Battery voltage dropout in volts (NKE §7.2.4.6: from 15 V, 0.1 V)."""
    return raw / 10.0


def battery_voltage_v(raw: int) -> float:
    """Battery voltage in volts (15 V minus the :func:`battery_dropout_v`)."""
    return 15.0 - raw / 10.0


def gps_decimal(degrees: int, minutes: int, frac_minute: int, hemisphere: int) -> float:
    """Decimal degrees from a 253 GPS component (minutes fraction = 1/10000).

    ``hemisphere`` is 0 for N/E, 1 for S/W (NKE §7.2.4.6).
    """
    decimal = degrees + (minutes + frac_minute / 10000.0) / 60.0
    return -decimal if hemisphere else decimal


@dataclass(frozen=True)
class FloatTime:
    """253 float time: ``YY MM DD hh mm ss`` (NKE §7.2.4.6 order).

    Carried WITHOUT century interpretation, mirroring :class:`PacketDate`.
    """

    yy: int
    mm: int
    dd: int
    hh: int
    mi: int
    ss: int


@dataclass(frozen=True)
class VectorTech:
    """Decoded packet 253 vector technical data (NKE §7.2.4.6).

    Day fields count float days relative to mission start; hour fields are raw
    u16 counts (see :func:`hhmm_from_minutes`). Pressure extremes are 1-Bar
    resolution counts. Emergency relative day counts from the 1st cycle day
    (NKE wording), unlike the mission-start-relative day fields.
    """

    time: FloatTime
    serial: int
    total_profiles: int
    cycle: int
    profile: int
    cycle_start_day: int
    cycle_start_hour: int
    phase: int
    dialog_errors: int
    timeout_fp: int
    vacuum_raw: int
    battery_raw: int
    rtc: int
    buoy_start_day: int
    buoy_start_hour: int
    ev_timing_min: int
    n_valve_surface: int
    park_desc_start_day: int
    park_desc_start_hour: int
    stab_day: int
    stab_hour: int
    park_desc_end_day: int
    park_desc_end_hour: int
    n_valve_desc_park: int
    n_pump_desc_park: int
    stab_pres_bar: int
    max_pres_desc_park_bar: int
    n_entries_park: int
    n_repos_park: int
    min_pres_drift_park_bar: int
    max_pres_drift_park_bar: int
    n_valve_park: int
    n_pump_park: int
    prof_desc_start_day: int
    prof_desc_start_hour: int
    prof_desc_end_day: int
    prof_desc_end_hour: int
    n_valve_desc_prof: int
    n_pump_desc_prof: int
    max_pres_desc_prof_bar: int
    n_entries_prof: int
    n_repos_prof: int
    n_valve_drift_prof: int
    n_pump_drift_prof: int
    min_pres_drift_prof_bar: int
    max_pres_drift_prof_bar: int
    ascent_start_day: int
    ascent_start_hour: int
    ascent_end_day: int
    ascent_end_hour: int
    n_pump_ascent: int
    grounding_detected: int
    grounding_pres_bar: int
    grounding_day: int
    grounding_hour: int
    n_emergency: int
    emergency1_time_min: int
    emergency1_pres_bar: int
    n_pump_emergency1: int
    emergency1_rel_day: int
    remote_rx: int
    remote_rej: int
    gps_lat_deg: int
    gps_lat_min: int
    gps_lat_frac: int
    gps_lat_hem: int
    gps_lon_deg: int
    gps_lon_min: int
    gps_lon_frac: int
    gps_lon_hem: int
    gps_valid: int
    show_vector: int
    show_sensor: int
    spare: bytes

    @property
    def spare_ok(self) -> bool:
        """True when the 33-byte spare tail is all zeros (NKE: filled)."""
        return self.spare == bytes(VECTOR_SPARE_LEN)

    def gps_position(self) -> tuple[float, float] | None:
        """``(lat, lon)`` decimal degrees, or None unless the fix is valid."""
        if self.gps_valid != 1:
            return None
        lat = gps_decimal(self.gps_lat_deg, self.gps_lat_min, self.gps_lat_frac,
                          self.gps_lat_hem)
        lon = gps_decimal(self.gps_lon_deg, self.gps_lon_min, self.gps_lon_frac,
                          self.gps_lon_hem)
        return (lat, lon)


def decode_253(packet: OpaquePacket) -> VectorTech:
    """Decode a 253 vector-technical packet (NKE §7.2.4.6).

    Raises:
        ValueError: if the packet is not a 253 packet or not 140 bytes.
    """
    if packet.kind is not PacketType.VECTOR_TECH:
        raise ValueError(f"not a 253 packet (kind={packet.kind})")
    raw = packet.raw
    if len(raw) != PACKET_LEN:
        raise ValueError(f"253 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    u16 = lambda off: _u16be(raw, off)  # noqa: E731
    return VectorTech(
        # NKE §7.2.4.6 prints "Year, Month, Day" but the wire order is
        # DD MM YY HH MM SS — the same encoding PROVEN at Phase-0 on the
        # type-0 date header (11 02 0e -> 17/02/2014) and independently
        # confirmed by GDAC 2902086 tech.nc CLOCK_FloatTime_YYYYMMDDHHMMSS
        # = '20140221035709' for the 12170 cycle-98 packet whose bytes are
        # 21 02 0e 03 39 09. Field names below are the TRUE components.
        time=FloatTime(yy=raw[3], mm=raw[2], dd=raw[1], hh=raw[4], mi=raw[5],
                       ss=raw[6]),
        serial=u16(7),
        total_profiles=u16(9),
        cycle=u16(11),
        profile=raw[13],
        cycle_start_day=u16(14),
        cycle_start_hour=u16(16),
        phase=raw[18],
        dialog_errors=u16(19),
        timeout_fp=u16(21),
        vacuum_raw=raw[23],
        battery_raw=raw[24],
        rtc=raw[25],
        buoy_start_day=u16(26),
        buoy_start_hour=u16(28),
        ev_timing_min=raw[30],
        n_valve_surface=raw[31],
        park_desc_start_day=u16(32),
        park_desc_start_hour=u16(34),
        stab_day=u16(36),
        stab_hour=u16(38),
        park_desc_end_day=u16(40),
        park_desc_end_hour=u16(42),
        n_valve_desc_park=raw[44],
        n_pump_desc_park=raw[45],
        stab_pres_bar=raw[46],
        max_pres_desc_park_bar=raw[47],
        n_entries_park=raw[48],
        n_repos_park=raw[49],
        min_pres_drift_park_bar=raw[50],
        max_pres_drift_park_bar=raw[51],
        n_valve_park=raw[52],
        n_pump_park=raw[53],
        prof_desc_start_day=u16(54),
        prof_desc_start_hour=u16(56),
        prof_desc_end_day=u16(58),
        prof_desc_end_hour=u16(60),
        n_valve_desc_prof=raw[62],
        n_pump_desc_prof=raw[63],
        max_pres_desc_prof_bar=raw[64],
        n_entries_prof=raw[65],
        n_repos_prof=raw[66],
        n_valve_drift_prof=raw[67],
        n_pump_drift_prof=raw[68],
        min_pres_drift_prof_bar=raw[69],
        max_pres_drift_prof_bar=raw[70],
        ascent_start_day=u16(71),
        ascent_start_hour=u16(73),
        ascent_end_day=u16(75),
        ascent_end_hour=u16(77),
        n_pump_ascent=raw[79],
        grounding_detected=raw[80],
        grounding_pres_bar=raw[81],
        grounding_day=u16(82),
        grounding_hour=u16(84),
        n_emergency=raw[86],
        emergency1_time_min=u16(87),
        emergency1_pres_bar=raw[89],
        n_pump_emergency1=raw[90],
        emergency1_rel_day=raw[91],
        remote_rx=raw[92],
        remote_rej=raw[93],
        gps_lat_deg=raw[94],
        gps_lat_min=raw[95],
        gps_lat_frac=u16(96),
        gps_lat_hem=raw[98],
        gps_lon_deg=raw[99],
        gps_lon_min=raw[100],
        gps_lon_frac=u16(101),
        gps_lon_hem=raw[103],
        gps_valid=raw[104],
        show_vector=raw[105],
        show_sensor=raw[106],
        spare=bytes(raw[VECTOR_SPARE_OFFSET:]),
    )


@dataclass(frozen=True)
class PressureSample:
    """One 252 hydraulic sample (NKE §7.2.4.7).

    ``phase`` rides the high nibble of the first byte, ``profile`` the low
    nibble; ``is_pump`` distinguishes pump (1) from eV (0) actions.
    """

    phase: int
    profile: int
    is_pump: int
    pressure_bar: int
    reltime_min: int


@dataclass(frozen=True)
class PressurePacket:
    """Decoded packet 252 (NKE §7.2.4.7)."""

    cycle: int
    samples: tuple[PressureSample, ...]
    spare: bytes

    @property
    def spare_ok(self) -> bool:
        """True when the 2-byte spare tail is all zeros (NKE: filled)."""
        return self.spare == bytes(PRESSURE_SPARE_LEN)


def decode_252(packet: OpaquePacket) -> PressurePacket:
    """Decode a 252 pressure packet (NKE §7.2.4.7).

    Raises:
        ValueError: if the packet is not a 252 packet or not 140 bytes.
    """
    if packet.kind is not PacketType.PRESSURE:
        raise ValueError(f"not a 252 packet (kind={packet.kind})")
    raw = packet.raw
    if len(raw) != PACKET_LEN:
        raise ValueError(f"252 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    samples: list[PressureSample] = []
    for index in range(PRESSURE_N_SAMPLES):
        base = PRESSURE_SAMPLES_OFFSET + index * PRESSURE_STRIDE
        phase_profile = raw[base]
        samples.append(
            PressureSample(
                phase=(phase_profile >> 4) & 0x0F,
                profile=phase_profile & 0x0F,
                is_pump=raw[base + 1],
                pressure_bar=raw[base + 2],
                reltime_min=_u16be(raw, base + 3),
            )
        )
    return PressurePacket(
        cycle=_u16be(raw, 1),
        samples=tuple(samples),
        spare=bytes(raw[PACKET_LEN - PRESSURE_SPARE_LEN :]),
    )


@dataclass(frozen=True)
class SensorParamChange:
    """One 251 change record (NKE §7.2.4.8).

    ``param_type`` is 0 (standard) or 1 (specific). Float values are decoded
    big-endian per the NKE convention; no 251 packet exists in the corpus, so
    this endianness is documented but unvalidated against telemetry.
    """

    sensor: int
    param_type: int
    param_number: int
    old_value: float
    new_value: float


@dataclass(frozen=True)
class SensorParams:
    """Decoded packet 251 (NKE §7.2.4.8)."""

    changes: tuple[SensorParamChange, ...]
    spare: bytes

    @property
    def spare_ok(self) -> bool:
        """True when the 7-byte spare tail is all zeros (NKE: filled)."""
        return self.spare == bytes(PARAMS_SPARE_LEN)


def decode_251(raw: bytes) -> SensorParams:
    """Decode a raw 251 sensor-parameter row (NKE §7.2.4.8).

    Packet 251 never flows through :func:`dispatch_row` (Phase 1 routes byte0
    ``0xFB`` to :class:`UnknownPacketTypeError`: transmitted only when a
    parameter changed since the previous session, and absent from the
    517-file corpus), so this decoder takes the raw 140-byte row directly.

    Raises:
        ValueError: if byte0 is not ``0xFB`` or the row is not 140 bytes.
    """
    if len(raw) == 0 or raw[0] != 0xFB:
        byte0 = f"0x{raw[0]:02X}" if raw else "empty"
        raise ValueError(f"not a 251 row (byte0={byte0})")
    if len(raw) != PACKET_LEN:
        raise ValueError(f"251 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    changes: list[SensorParamChange] = []
    for index in range(PARAMS_N_CHANGES):
        base = PARAMS_CHANGES_OFFSET + index * PARAMS_CHANGE_STRIDE
        old_value = struct.unpack_from(">f", raw, base + 3)[0]
        new_value = struct.unpack_from(">f", raw, base + 7)[0]
        changes.append(
            SensorParamChange(
                sensor=raw[base],
                param_type=raw[base + 1],
                param_number=raw[base + 2],
                old_value=old_value,
                new_value=new_value,
            )
        )
    return SensorParams(
        changes=tuple(changes),
        spare=bytes(raw[PACKET_LEN - PARAMS_SPARE_LEN :]),
    )


@dataclass(frozen=True)
class CtdFree:
    """CTD 250 free zone: 4 little-endian float32s + 34 spare bytes.

    The manual names the fields surface pressure offset, subsurface pressure,
    subsurface temperature, subsurface salinity without stating T/S units; the
    corpus values adjudicate (plausible magnitudes decide °C vs m°C etc.).
    """

    offset_p: float
    p_sub: float
    t_sub: float
    s_sub: float
    spare: bytes


@dataclass(frozen=True)
class FlbbFree:
    """FLBB 250 free zone (little-endian; NKE §7.2.4.9 "FLBBNTU Data").

    The manual's turbidity scale/dark slots carry the backscatter (BB700)
    factory coefficients on the FLBB variant; the shared FLBB/FLBBNTU layout is
    the documented interpretation, confirmed by GDAC reference
    ``SCALE_BACKSCATTERING700`` / ``DARK_BACKSCATTERING700`` magnitudes. The
    second chlorophyll scale slot and the 32-byte spare tail are carried
    verbatim.
    """

    serial: int
    scale_chl: float
    dark_chl: int
    scale_bb: float
    dark_bb: int
    scale_chl_2: float
    spare: bytes


@dataclass(frozen=True)
class OptodeFree:
    """Optode 250 free zone: 50 bytes, empty per the manual (carried raw)."""

    raw: bytes


@dataclass(frozen=True)
class SensorHalf:
    """One 70-byte half of a 250 packet (NKE §7.2.4.9).

    ``present`` is False for filler halves (sensor id ``0xFF``), whose content
    is carried in ``raw`` only. ``free`` is None for filler halves.
    """

    present: bool
    sensor: int
    cycle: int
    profile: int
    tx_descent: int
    tx_drift: int
    tx_ascent: int
    acq_descent: tuple[int, ...]
    acq_drift: int
    acq_ascent: tuple[int, ...]
    status: int
    free: CtdFree | FlbbFree | OptodeFree | None
    raw: bytes


@dataclass(frozen=True)
class SensorTechPacket:
    """Decoded packet 250: the two 70-byte halves in wire order."""

    halves: tuple[SensorHalf, SensorHalf]


def _decode_half(raw: bytes) -> SensorHalf:
    if raw[0] != 0xFA:
        raise ValueError(f"250 half must open with 0xFA, got 0x{raw[0]:02X}")
    sensor = raw[X_OFFSET_IN_HALF]
    if sensor == FILLER_SENSOR_ID:
        return SensorHalf(
            present=False,
            sensor=sensor,
            cycle=_u16be(raw, 2),
            profile=raw[4],
            tx_descent=raw[5],
            tx_drift=raw[6],
            tx_ascent=raw[7],
            acq_descent=tuple(raw[8:13]),
            acq_drift=raw[13],
            acq_ascent=tuple(raw[14:19]),
            status=raw[19],
            free=None,
            raw=bytes(raw),
        )
    if sensor not in SENSOR_NAMES:
        raise UnknownSensorTypeError(f"unknown 250 sensor id {sensor}")
    free = raw[FREE_OFFSET_IN_HALF : FREE_OFFSET_IN_HALF + FREE_LEN]
    zone: CtdFree | FlbbFree | OptodeFree
    if sensor == 0:
        offset_p, p_sub, t_sub, s_sub = struct.unpack_from("<ffff", free, 0)
        zone = CtdFree(
            offset_p=offset_p, p_sub=p_sub, t_sub=t_sub, s_sub=s_sub,
            spare=bytes(free[16:]),
        )
    elif sensor == 4:
        serial = int.from_bytes(free[0:2], "little")
        (scale_chl,) = struct.unpack_from("<f", free, 2)
        dark_chl = int.from_bytes(free[6:8], "little")
        (scale_bb,) = struct.unpack_from("<f", free, 8)
        dark_bb = int.from_bytes(free[12:14], "little")
        (scale_chl_2,) = struct.unpack_from("<f", free, 14)
        zone = FlbbFree(
            serial=serial, scale_chl=scale_chl, dark_chl=dark_chl,
            scale_bb=scale_bb, dark_bb=dark_bb, scale_chl_2=scale_chl_2,
            spare=bytes(free[18:]),
        )
    else:
        zone = OptodeFree(raw=bytes(free))
    return SensorHalf(
        present=True,
        sensor=sensor,
        cycle=_u16be(raw, 2),
        profile=raw[4],
        tx_descent=raw[5],
        tx_drift=raw[6],
        tx_ascent=raw[7],
        acq_descent=tuple(raw[8:13]),
        acq_drift=raw[13],
        acq_ascent=tuple(raw[14:19]),
        status=raw[19],
        free=zone,
        raw=bytes(raw),
    )


def decode_250(packet: OpaquePacket) -> SensorTechPacket:
    """Decode a 250 sensor-technical packet (NKE §7.2.4.9).

    Raises:
        ValueError: if the packet is not a 250 packet or not 140 bytes.
        UnknownSensorTypeError: for a sensor id outside {0, 1, 4, 0xFF}.
    """
    if packet.kind is not PacketType.SENSOR_TECH:
        raise ValueError(f"not a 250 packet (kind={packet.kind})")
    raw = packet.raw
    if len(raw) != PACKET_LEN:
        raise ValueError(f"250 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    return SensorTechPacket(
        halves=(
            _decode_half(raw[0:HALF_LEN]),
            _decode_half(raw[HALF_LEN : 2 * HALF_LEN]),
        )
    )


__all__ = [
    "FILLER_SENSOR_ID",
    "FREE_LEN",
    "FREE_OFFSET_IN_HALF",
    "HALF_LEN",
    "N_HALVES",
    "PACKET_LEN",
    "PARAMS_CHANGES_OFFSET",
    "PARAMS_CHANGE_STRIDE",
    "PARAMS_N_CHANGES",
    "PARAMS_SPARE_LEN",
    "PRESSURE_N_SAMPLES",
    "PRESSURE_SAMPLES_OFFSET",
    "PRESSURE_SPARE_LEN",
    "PRESSURE_STRIDE",
    "SENSOR_NAMES",
    "VECTOR_SPARE_LEN",
    "VECTOR_SPARE_OFFSET",
    "X_OFFSET_IN_HALF",
    "CtdFree",
    "FlbbFree",
    "FloatTime",
    "OptodeFree",
    "PressurePacket",
    "PressureSample",
    "SensorHalf",
    "SensorParamChange",
    "SensorParams",
    "SensorTechPacket",
    "UnknownSensorTypeError",
    "VectorTech",
    "battery_dropout_v",
    "battery_voltage_v",
    "decode_250",
    "decode_251",
    "decode_252",
    "decode_253",
    "gps_decimal",
    "hhmm_from_minutes",
    "vacuum_mbar_x5",
]

"""Provor/Arvor Iridium SBD packet types and bit-unpacking.

An Iridium SBD payload is up to 340 bytes; for NKE Provor/Arvor floats
(decoder ids 201-232, CTS4 generation) it is 300 bytes long. The first
byte of the payload is the **packet type** and the remaining 299 bytes
contain bit-packed fields. Decoded values are extracted from the MSB of
the first message byte onward.

This module provides:

* :class:`BitReader` — MSB-first bit cursor compatible with MATLAB's
  ``get_bits()``.
* :class:`SbdPacketType` — enum of packet types present in the NKE
  Provor/Arvor CTS4 SBD stream.
* :func:`unpack_packet` — splits a raw payload into a typed packet
  dataclass using per-type bit-length tables.

Bit-width tables are transcribed verbatim from
``decode_prv_data_ir_sbd_221.m``. The fields array on each returned
packet is **1-indexed** to match the MATLAB convention (``fields[i]``
corresponds to ``tabTech(i)`` / ``tabParam(i)``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum

# ---------------------------------------------------------------------------
# Packet type enum
# ---------------------------------------------------------------------------


class SbdPacketType(IntEnum):
    """Packet type identifiers (first byte of payload)."""

    TECHNICAL_1 = 0
    CTD_P = 1
    CTD_PT = 2
    CTD_PTS = 3
    TECHNICAL_2 = 4
    PARAMETER_1 = 5
    PUMP_EV = 6
    PARAMETER_2 = 7
    CTDO_P = 8
    CTDO_PT = 9
    CTDO_PTS = 10
    CTDO_PTSO = 11
    CTDO_PTOT = 12
    CTD_13 = 13
    CTD_14 = 14


CTD_PACKET_TYPES = {
    SbdPacketType.CTD_P,
    SbdPacketType.CTD_PT,
    SbdPacketType.CTD_PTS,
    SbdPacketType.CTD_13,
    SbdPacketType.CTD_14,
}
CTDO_PACKET_TYPES = {
    SbdPacketType.CTDO_P,
    SbdPacketType.CTDO_PT,
    SbdPacketType.CTDO_PTS,
    SbdPacketType.CTDO_PTSO,
    SbdPacketType.CTDO_PTOT,
}


# ---------------------------------------------------------------------------
# MSB-first bit reader
# ---------------------------------------------------------------------------


class BitReader:
    """Read unsigned integer fields from a byte buffer MSB-first."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._len = len(data) * 8

    @property
    def remaining(self) -> int:
        return max(0, self._len - self._pos)

    def read(self, nbits: int) -> int:
        if nbits <= 0:
            raise ValueError(f"nbits must be positive, got {nbits}")
        if self._pos + nbits > self._len:
            raise BitReaderEofError(
                f"read past end of buffer: pos={self._pos} nbits={nbits} bufbits={self._len}"
            )
        val = 0
        for _ in range(nbits):
            byte_idx = self._pos >> 3
            bit_idx = 7 - (self._pos & 7)
            bit = (self._data[byte_idx] >> bit_idx) & 1
            val = (val << 1) | bit
            self._pos += 1
        return val

    def read_many(self, widths: list[int]) -> list[int]:
        return [self.read(w) for w in widths]

    def skip(self, nbits: int) -> None:
        self._pos += nbits


class BitReaderEofError(ValueError):
    """Raised when a read would extend past end of buffer."""


# ---------------------------------------------------------------------------
# Bit-width tables (verbatim from decode_prv_data_ir_sbd_221.m)
# ---------------------------------------------------------------------------
#
# Every table sums to 792 bits (99 bytes), leaving 200 bytes of payload
# unused for types 0/4/5/7 — those trailing bytes are ignored by MATLAB
# and we likewise ignore them.  Total SBD payload is 300 bytes: 1 byte
# pack_type + 299 bytes message body.


def _expand(group_sizes: list[tuple[int, int]]) -> list[int]:
    """Expand ``[(width, count), ...]`` into a flat widths list."""
    out: list[int] = []
    for w, n in group_sizes:
        out.extend([w] * n)
    return out


# Packet type 0: technical #1 (76 fields, 792 bits).
_TECH1_WIDTHS = _expand(
    [
        (16, 1),  # 1 cycleNum
        (8, 3),
        (16, 3),
        (8, 2),  # 2-9
        (16, 3),
        (8, 2),
        (16, 2),  # 10-16
        (8, 3),
        (16, 2),
        (8, 2),  # 17-23
        (16, 2),
        (8, 2),
        (16, 1),  # 24-28
        (8, 4),
        (16, 2),  # 29-34
        (16, 2),
        (8, 1),  # 35-37 (36 = ascentStartHour, 37 = transStartHour)
        (8, 3),  # 38-40 HH/MM/SS
        (8, 9),  # 41-49 (41-43=dd/mm/yy, 44=pres offset)
        (8, 2),
        (16, 1),
        (8, 3),
        (16, 1),
        (8, 2),
        (16, 1),
        (8, 1),  # 50-59 (GPS 50-53 lat, 54-57 lon, valid @ 58)
        (8, 2),  # 60-61
        (8, 7),  # 62-68 (eol @ 63)
        (16, 1),
        (8, 2),  # 69-71
        (16, 1),  # 72
        (8, 3),  # 73-75 (clock offset 73-74)
    ]
)

# Packet type 4: technical #2 (81 fields, 792 bits).
_TECH2_WIDTHS = _expand(
    [
        (16, 1),  # 1 cycleNum
        (8, 3),
        (16, 2),
        (8, 1),
        (16, 2),  # 2-9
        (16, 6),  # 10-15
        (8, 1),
        (16, 1),
        (8, 1),
        (16, 1),
        (8, 2),
        (16, 1),
        (8, 1),
        (16, 1),
        (8, 2),  # 16-26
        (8, 1),
        (16, 2),
        (8, 2),  # 27-31
        (8, 9),  # 32-40 (35-40 = HHMMSSddmmyy = last reset date)
        (8, 2),  # 41-42
        (8, 2),  # 43-44 (44 = expNbNearSurface)
        (8, 2),
        (16, 1),
        (8, 1),  # 45-48 (45 = expNbInAir)
        (8, 33),  # 49-81
    ]
)

# CTD / CTDO.
_CTD_WIDTHS: list[int] = _expand(
    [(16, 2), (8, 2), (16, 45), (8, 3)]  # 4 header  # 45 measurements  # 3 pad
)
_CTDO_WIDTHS: list[int] = _expand(
    [(16, 2), (8, 2), (16, 42), (8, 9)]  # 4 header  # 42 measurements  # 9 pad
)

# Parameter packet type 5: 83 fields, 792 bits.
_PARAM1_WIDTHS = _expand(
    [
        (8, 6),
        (16, 1),  # 1-7 (cycleNum = 7 - 1)
        (16, 1),
        (8, 6),
        (16, 4),
        (8, 3),
        (16, 2),
        (8, 2),  # 8-25
        (8, 6),
        (16, 1),
        (8, 5),
        (16, 1),
        (8, 4),
        (16, 1),
        (8, 12),
        (16, 2),
        (8, 2),
        (16, 1),
        (8, 1),
        (16, 2),  # 26-63
        (8, 20),  # 64-83
    ]
)

# Parameter packet type 7: 92 fields, 792 bits.
_PARAM2_WIDTHS = _expand(
    [
        (8, 6),
        (16, 1),  # 1-7
        (16, 2),
        (8, 3),
        (16, 2),
        (8, 2),
        (16, 1),
        (8, 5),
        (16, 1),  # 8-23
        (8, 69),  # 24-92
    ]
)

_PUMP_EV_WIDTHS: list[int] = _expand([(16, 3)] + [(8, 1), (16, 3)] * 13 + [(8, 2)])


def _widths_for(pack_type: SbdPacketType) -> list[int]:
    if pack_type == SbdPacketType.TECHNICAL_1:
        return _TECH1_WIDTHS
    if pack_type == SbdPacketType.TECHNICAL_2:
        return _TECH2_WIDTHS
    if pack_type in CTD_PACKET_TYPES:
        return _CTD_WIDTHS
    if pack_type in CTDO_PACKET_TYPES:
        return _CTDO_WIDTHS
    if pack_type == SbdPacketType.PARAMETER_1:
        return _PARAM1_WIDTHS
    if pack_type == SbdPacketType.PARAMETER_2:
        return _PARAM2_WIDTHS
    if pack_type == SbdPacketType.PUMP_EV:
        return _PUMP_EV_WIDTHS
    raise ValueError(f"No bit-width table for packet type {pack_type}")


# ---------------------------------------------------------------------------
# Decoded packet dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SbdPacket:
    pack_type: SbdPacketType
    raw: bytes
    cycle_number: int | None = None
    fields: list[int] = field(default_factory=list)
    truncated: bool = False

    def f(self, i: int) -> int:
        if i < 1 or i >= len(self.fields):
            raise IndexError(f"field index {i} out of range [1, {len(self.fields) - 1}]")
        return self.fields[i]


@dataclass
class Tech1Packet(SbdPacket):
    """Decoded technical #1 packet - GPS, pressure offset, timing markers."""

    float_time_elapsed_s: float | None = None
    """Seconds since midnight UTC on ``reference_day`` that this GPS fix was
    taken (HH/MM/SS at fields 38..40)."""
    gps_lat: float | None = None
    gps_lon: float | None = None
    trans_start_hour: int | None = None
    """Hour-of-day (0..23) at which Iridium transmission is scheduled to start
    (tabTech1(37)). MATLAB builds ``transStartDate = fix(gpsDate) + hour/1440``,
    then backs off buoyancy/in-air offsets to get ascentEndDate."""
    ascent_start_hour: int | None = None
    """Hour-of-day for ascent start (field 36)."""
    gps_day: int | None = None
    """Day-of-month of the GPS fix (field 41)."""
    gps_month: int | None = None
    """Month of the GPS fix (field 42)."""
    gps_year_offset: int | None = None
    """Year offset (0..99, field 43) - year is 2000+yy when yy<80."""
    eol_flag: int | None = None
    clock_offset_s: int | None = None

    @classmethod
    def from_fields(cls, raw: bytes, fields: list[int], truncated: bool) -> Tech1Packet:
        cycle = fields[1] if len(fields) > 1 else None
        float_time_s: float | None = None
        gps_day: int | None = None
        gps_month: int | None = None
        gps_year_off: int | None = None
        if len(fields) > 43:
            hh, mm, ss = fields[38], fields[39], fields[40]
            float_time_s = (hh / 24 + mm / 1440 + ss / 86400) * 86400
            gps_day = fields[41]
            gps_month = fields[42]
            gps_year_off = fields[43]
        trans_hour = fields[37] if len(fields) > 37 else None
        if trans_hour is not None and trans_hour > 23:
            trans_hour = None  # invalid; treat as unknown
        ascent_hour = fields[36] if len(fields) > 36 else None
        if ascent_hour is not None and ascent_hour > 23:
            ascent_hour = None
        gps_lat = _decode_gps(fields, 50, 51, 52, 53) if len(fields) >= 57 else None
        gps_lon = _decode_gps(fields, 54, 55, 56, 57) if len(fields) >= 57 else None
        eol = fields[63] if len(fields) > 63 else None
        clock_off: int | None = None
        # Clock offset is 16 bits spanning fields 73 & 74 (MSB first).
        if len(fields) > 74:
            clock_off = _twos_complement((fields[73] << 8) | fields[74], 16)
        return cls(
            pack_type=SbdPacketType.TECHNICAL_1,
            raw=raw,
            cycle_number=cycle,
            fields=fields,
            truncated=truncated,
            float_time_elapsed_s=float_time_s,
            gps_lat=gps_lat,
            gps_lon=gps_lon,
            trans_start_hour=trans_hour,
            ascent_start_hour=ascent_hour,
            gps_day=gps_day,
            gps_month=gps_month,
            gps_year_offset=gps_year_off,
            eol_flag=eol,
            clock_offset_s=clock_off,
        )


@dataclass
class Tech2Packet(SbdPacket):
    """Decoded technical #2 packet — reset date, experiment counters."""

    reset_date: datetime | None = None
    exp_nb_desc: int | None = None
    exp_nb_drift: int | None = None
    exp_nb_asc: int | None = None
    exp_nb_near_surface: int | None = None
    exp_nb_in_air: int | None = None

    @classmethod
    def from_fields(cls, raw: bytes, fields: list[int], truncated: bool) -> Tech2Packet:
        cycle = fields[1] if len(fields) > 1 else None
        reset_dt: datetime | None = None
        if len(fields) >= 40:
            try:
                hh, mm, ss, dd, mo, yy = (
                    fields[35],
                    fields[36],
                    fields[37],
                    fields[38],
                    fields[39],
                    fields[40],
                )
                if not (hh == 0 and mm == 0 and ss == 0 and dd == 0 and mo == 0):
                    year = 2000 + yy if yy < 80 else 1900 + yy
                    reset_dt = datetime(year, mo, dd, hh, mm, ss, tzinfo=UTC)
            except (ValueError, IndexError):
                reset_dt = None
        return cls(
            pack_type=SbdPacketType.TECHNICAL_2,
            raw=raw,
            cycle_number=cycle,
            fields=fields,
            truncated=truncated,
            reset_date=reset_dt,
            exp_nb_desc=fields[3] if len(fields) > 3 else None,
            exp_nb_drift=fields[4] if len(fields) > 4 else None,
            exp_nb_asc=fields[5] if len(fields) > 5 else None,
            exp_nb_near_surface=fields[44] if len(fields) > 44 else None,
            exp_nb_in_air=fields[45] if len(fields) > 45 else None,
        )


@dataclass
class Param1Packet(SbdPacket):
    """Decoded parameter #1 packet — PT04/PT31/PT32/PT33 and mission config.

    Field indexing follows ``update_float_config_ir_sbd_221_230.m``:

    * CONFIG_PM00..PM03    ->  fields[10]..fields[13]
    * CONFIG_PM05..PM18    ->  fields[14]..fields[27]
    * CONFIG_PT00..PT14    ->  fields[28]..fields[42]   (PT04 = field[32],
      PT04 is encoded in centiseconds and scaled *1000 on storage — i.e. the
      on-wire unit is centiseconds; MATLAB multiplies by 1000 to convert to
      millisec but in our pipeline we work in seconds so we divide by 100).
    * CONFIG_PT16..PT37    ->  fields[44]..fields[65]
    """

    packet_time: datetime | None = None
    pt04_centisec: int | None = None
    """Buoyancy acquisition duration in centiseconds (CONFIG_PT04)."""
    pt31_min: int | None = None
    """In-air acquisition phase duration in minutes (CONFIG_PT31)."""
    pt32_centisec: int | None = None
    """In-air pump/buoyancy duration in centiseconds (CONFIG_PT32)."""
    pt33_cycles: int | None = None
    """In-air measurement periodicity in cycles (CONFIG_PT33)."""

    @classmethod
    def from_fields(cls, raw: bytes, fields: list[int], truncated: bool) -> Param1Packet:
        cycle = (fields[7] - 1) if len(fields) > 7 else None
        pkt_dt = _decode_packet_datetime(fields)
        return cls(
            pack_type=SbdPacketType.PARAMETER_1,
            raw=raw,
            cycle_number=cycle,
            fields=fields,
            truncated=truncated,
            packet_time=pkt_dt,
            pt04_centisec=fields[32] if len(fields) > 32 else None,
            pt31_min=fields[59] if len(fields) > 59 else None,
            pt32_centisec=fields[60] if len(fields) > 60 else None,
            pt33_cycles=fields[61] if len(fields) > 61 else None,
        )


@dataclass
class Param2Packet(SbdPacket):
    """Decoded parameter #2 packet (PG00..PG15)."""

    packet_time: datetime | None = None
    pg05_ref_temp_c: float | None = None
    """Reference temperature in °C (CONFIG_PG05, signed 16-bit / 1000)."""

    @classmethod
    def from_fields(cls, raw: bytes, fields: list[int], truncated: bool) -> Param2Packet:
        cycle = (fields[7] - 1) if len(fields) > 7 else None
        pkt_dt = _decode_packet_datetime(fields)
        pg05: float | None = None
        if len(fields) > 13:
            raw13 = fields[13]
            signed = raw13 - 65536 if raw13 >= 32768 else raw13
            pg05 = signed / 1000.0
        return cls(
            pack_type=SbdPacketType.PARAMETER_2,
            raw=raw,
            cycle_number=cycle,
            fields=fields,
            truncated=truncated,
            packet_time=pkt_dt,
            pg05_ref_temp_c=pg05,
        )


@dataclass
class CtdPacket(SbdPacket):
    n_bins: int = 15
    pres_counts: list[int] = field(default_factory=list)
    temp_counts: list[int] = field(default_factory=list)
    sal_counts: list[int] = field(default_factory=list)


@dataclass
class CtdoPacket(SbdPacket):
    n_bins: int = 7
    pres_counts: list[int] = field(default_factory=list)
    temp_counts: list[int] = field(default_factory=list)
    sal_counts: list[int] = field(default_factory=list)
    c1phase_counts: list[int] = field(default_factory=list)
    c2phase_counts: list[int] = field(default_factory=list)
    tdoxy_counts: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_packet_datetime(fields: list[int]) -> datetime | None:
    """Decode HHMMSSddmmyy from fields[1..6] (common to param/trajectory pkts)."""
    if len(fields) < 7:
        return None
    try:
        hh, mm, ss, dd, mo, yy = fields[1], fields[2], fields[3], fields[4], fields[5], fields[6]
        if hh == 0 and mm == 0 and ss == 0 and dd == 0 and mo == 0 and yy == 0:
            return None
        year = 2000 + yy if yy < 80 else 1900 + yy
        return datetime(year, mo, dd, hh, mm, ss, tzinfo=UTC)
    except (ValueError, IndexError):
        return None


def _decode_gps(
    fields: list[int], deg_i: int, min_i: int, tenk_i: int, sign_i: int
) -> float | None:
    try:
        deg = fields[deg_i]
        minutes = fields[min_i]
        ten_thou = fields[tenk_i]
        sign = fields[sign_i]
    except IndexError:
        return None
    if deg == 0 and minutes == 0 and ten_thou == 0:
        return None
    sign_val = -1.0 if sign else 1.0
    return sign_val * (deg + (minutes + ten_thou / 10000.0) / 60.0)


def _twos_complement(value: int, nbits: int) -> int:
    if value >= (1 << (nbits - 1)):
        return value - (1 << nbits)
    return value


# ---------------------------------------------------------------------------
# Top-level unpack entry point
# ---------------------------------------------------------------------------


def unpack_packet(payload: bytes) -> SbdPacket:
    if not payload:
        raise ValueError("empty payload")
    pack_type = SbdPacketType(payload[0])
    msg = payload[1:]
    widths = _widths_for(pack_type)
    reader = BitReader(msg)
    fields: list[int] = [0]
    truncated = False
    for w in widths:
        try:
            fields.append(reader.read(w))
        except BitReaderEofError:
            truncated = True
            break

    if pack_type == SbdPacketType.TECHNICAL_1:
        return Tech1Packet.from_fields(payload, fields, truncated)
    if pack_type == SbdPacketType.TECHNICAL_2:
        return Tech2Packet.from_fields(payload, fields, truncated)
    if pack_type == SbdPacketType.PARAMETER_1:
        return Param1Packet.from_fields(payload, fields, truncated)
    if pack_type == SbdPacketType.PARAMETER_2:
        return Param2Packet.from_fields(payload, fields, truncated)
    if pack_type in CTD_PACKET_TYPES:
        pres, temp, sal = _unpack_cts_bins(fields, n_bins=15)
        return CtdPacket(
            pack_type=pack_type,
            raw=payload,
            cycle_number=fields[1] if len(fields) > 1 else None,
            fields=fields,
            truncated=truncated,
            n_bins=15,
            pres_counts=pres,
            temp_counts=temp,
            sal_counts=sal,
        )
    if pack_type in CTDO_PACKET_TYPES:
        pres, temp, sal, c1, c2, tdoxy = _unpack_ctso_bins(fields, n_bins=7)
        return CtdoPacket(
            pack_type=pack_type,
            raw=payload,
            cycle_number=fields[1] if len(fields) > 1 else None,
            fields=fields,
            truncated=truncated,
            n_bins=7,
            pres_counts=pres,
            temp_counts=temp,
            sal_counts=sal,
            c1phase_counts=c1,
            c2phase_counts=c2,
            tdoxy_counts=tdoxy,
        )
    return SbdPacket(
        pack_type=pack_type,
        raw=payload,
        cycle_number=_cycle_for(pack_type, fields),
        fields=fields,
        truncated=truncated,
    )


def _cycle_for(pack_type: SbdPacketType, fields: list[int]) -> int | None:
    if not fields or len(fields) < 2:
        return None
    if pack_type in (SbdPacketType.PARAMETER_1, SbdPacketType.PARAMETER_2):
        if len(fields) > 7:
            return fields[7] - 1
        return None
    return fields[1]


def _unpack_cts_bins(fields: list[int], *, n_bins: int) -> tuple[list[int], list[int], list[int]]:
    pres, temp, sal = [], [], []
    for k in range(n_bins):
        p_idx = 5 + 3 * k
        pres.append(fields[p_idx] if p_idx < len(fields) else 0)
        temp.append(fields[p_idx + 1] if p_idx + 1 < len(fields) else 0)
        sal.append(fields[p_idx + 2] if p_idx + 2 < len(fields) else 0)
    return pres, temp, sal


def _unpack_ctso_bins(
    fields: list[int], *, n_bins: int
) -> tuple[list[int], list[int], list[int], list[int], list[int], list[int]]:
    pres, temp, sal, c1, c2, tdoxy = [], [], [], [], [], []
    for k in range(n_bins):
        base = 5 + 6 * k
        pres.append(_safe_field(fields, base))
        temp.append(_safe_field(fields, base + 1))
        sal.append(_safe_field(fields, base + 2))
        c1.append(_safe_field(fields, base + 3))
        c2.append(_safe_field(fields, base + 4))
        tdoxy.append(_safe_field(fields, base + 5))
    return pres, temp, sal, c1, c2, tdoxy


def _safe_field(fields: list[int], idx: int) -> int:
    return fields[idx] if idx < len(fields) else 0


__all__ = [
    "BitReader",
    "BitReaderEofError",
    "CtdPacket",
    "CtdoPacket",
    "Param1Packet",
    "Param2Packet",
    "SbdPacket",
    "SbdPacketType",
    "Tech1Packet",
    "Tech2Packet",
    "unpack_packet",
]

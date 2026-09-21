"""ARVOR-I (NKE, Iridium SBD) raw packet decoding — layout family 222/223/225/232.

This module implements the *raw decoding foundation* for ARVOR-I floats
(decoder ids 222, 223, 225, 232 — firmware generations 5900A05 / 5900A05B,
float firmware versions 5.47 … 5.54).  It is intentionally limited to:

    .eml → MIME/attachment extraction → .sbd bytes → packet framing →
    100-byte packet rows → structured, identified packet objects

No cycle reconstruction, no grouping into profiles, no NetCDF output —
those belong to later phases.

Evidence basis (see ``docs/phase_reports/ARVOR_I_PHASE1_RAW_2026-08-24.md``
and the workspace investigation report
``ARVOR_I_INVESTIGATION_2026-08-24.md``):

* Bit-width tables are transcribed verbatim from the Coriolis MATLAB
  ``decode_prv_data_ir_sbd_222_223_225.m`` and ``decode_prv_data_ir_sbd_232.m``
  (verified bit-for-bit against both sources; the two engines' tables are
  semantically identical — their type-5 vectors differ only in how the
  trailing run of 8-bit items is grouped).
* SBD framing mirrors ``decode_sbd_file.m``: payload length must be a
  multiple of 100 bytes; the payload is reshaped into 100-byte rows;
  rows that are all ``0x00`` or all ``0x1A`` are padding and are dropped.
* Engine (decoder-id) identification mirrors ``check_decoder_id.m`` using
  the firmware checksum carried in Tech#1 item 3.
* Counts→physical conversions mirror ``sensor_2_value_for_pressure_2xx_*``,
  ``sensor_2_value_for_temp_2xx_*`` and ``sensor_2_value_for_salinity_2xx_*``
  (linear scalings; the float applies its factory calibration internally).

Deliberate divergence from MATLAB (documented, evidence-based):

* MATLAB drops a fully-empty CTD packet (all measurement items zero) with
  a warning; here the packet is returned with ``is_empty=True`` so nothing
  is silently discarded.  Callers decide.
* MATLAB's ``expNbDesc/expNbDrift/expNbAsc`` read Tech#2 items 4/5/6, which
  the manual (33-16-033 Rev14 §6.3) and the raw telemetry show to be
  drift/ascent/near-surface counts — an off-by-one.  This module exposes
  the *corrected* mapping (items 3/4/5 = descent/drift/ascent); the raw
  1-indexed ``fields`` list is preserved so the Coriolis reading remains
  reproducible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from argo_decoder.io.sbd_email import SbdSessionInfo, parse_sbd_bytes
from argo_decoder.platforms.provor_ir_sbd.frames import BitReader, BitReaderEofError

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Engine identification (PROVEN: check_decoder_id.m + raw telemetry)
# ---------------------------------------------------------------------------

# Firmware checksum (Tech#1 item 3) → candidate decoder ids.
FIRMWARE_CHECKSUM_TO_DECODER_IDS: dict[int, frozenset[int]] = {
    38844: frozenset({212}),  # 5900A03 / 5900A04
    47305: frozenset({212, 214, 217}),  # 5900A04
    11415: frozenset({222, 223, 225}),  # 5900A05
    43931: frozenset({224}),  # 5900A06
    43079: frozenset({226, 231}),  # 5900A07
    64629: frozenset({227}),  # 5900A08
    13872: frozenset({232}),  # 5900A05B
}

#: Decoder ids handled by this module (ARVOR-I SBE41CP generation).
ARVOR_I_DECODER_IDS = frozenset({222, 223, 225, 232})


class ArvorIEngine(StrEnum):
    """Layout variant within the ARVOR-I family.

    Kept for engine provenance (decoder-id resolution): the bit layouts of
    the 222/223/225 and 232 engines are semantically identical (verified
    against both MATLAB sources), so decoding is engine-independent today.
    """

    FAMILY_222_223_225 = "222_223_225"
    ENGINE_232 = "232"


class UnsupportedEngineError(ValueError):
    """Firmware checksum maps to a decoder family not implemented here."""


class SbdFramingError(ValueError):
    """SBD payload length is not a multiple of 100 bytes (MATLAB warns + skips)."""


def resolve_engine(firmware_checksum: int) -> tuple[ArvorIEngine, frozenset[int]]:
    """Map a Tech#1 firmware checksum to an engine + candidate decoder ids.

    Returns ``(engine, decoder_ids)``.  Raises :class:`UnsupportedEngineError`
    for checksums belonging to other NKE generations (212/214/217/224/226/
    227/231 …) — their layouts are outside this module's evidence base.

    Note: within the 222/223/225 family the checksum cannot distinguish the
    exact decoder id (Coriolis resolves it from float metadata); the shared
    layout is identical for decoding purposes.
    """

    ids = FIRMWARE_CHECKSUM_TO_DECODER_IDS.get(firmware_checksum)
    if ids is None:
        raise UnsupportedEngineError(
            f"Unknown firmware checksum {firmware_checksum} (not in check_decoder_id.m table)"
        )
    if not ids <= ARVOR_I_DECODER_IDS:
        raise UnsupportedEngineError(
            f"Firmware checksum {firmware_checksum} maps to decoder ids "
            f"{sorted(ids)} — not the ARVOR-I 222/223/225/232 family"
        )
    engine = ArvorIEngine.ENGINE_232 if ids == frozenset({232}) else ArvorIEngine.FAMILY_222_223_225
    return engine, ids


# ---------------------------------------------------------------------------
# Bit-width tables (verbatim from decode_prv_data_ir_sbd_222_223_225.m /
# decode_prv_data_ir_sbd_232.m; MSB-first, 1-indexed items like MATLAB)
# ---------------------------------------------------------------------------


def _expand(groups: list[tuple[int, int]]) -> list[int]:
    out: list[int] = []
    for width, count in groups:
        out.extend([width] * count)
    return out


def _matlab_expand(spec: str) -> list[int]:
    """Expand a compact MATLAB-like table spec string into bit widths.

    Example: ``"16 8 16 16 | 8 8 8 16 16 16 8 8 | 16x6 | 8x12"``.
    """

    widths: list[int] = []
    for chunk in spec.replace("|", " ").split():
        if "x" in chunk:
            w, n = chunk.split("x")
            widths.extend([int(w)] * int(n))
        else:
            widths.append(int(chunk))
    return widths


# Authoritative tables.  These mirror the tabNbBits vectors exactly as read
# from decode_prv_data_ir_sbd_222_223_225.m (types 0/4/CTD/6) and the single
# differing type-5 vector from decode_prv_data_ir_sbd_232.m.  A unit test
# (tests/unit/test_arvor_i_frames.py::test_width_tables_match_matlab_source)
# re-parses the .m sources and compares bit-for-bit.

_T0_TABLE = (
    "16 8 16 16 "
    "8 8 8 16 16 16 8 8 "
    "16 16 16 8 8 16 16 "
    "8 8 8 16 16 8 8 "
    "16 16 8 8 16 "
    "8 8 8 8 16 16 "
    "16 16 8 "
    "8x12 "
    "8 8 16 8 8 8 16 8 8 16 8 16 8 "
    "8x7 "
    "16 8"
)
TECH1_WIDTHS = _matlab_expand(_T0_TABLE)  # 74 items, 792 bits

_T4_TABLE = (
    "16 8 "
    "8 8 8 8 8 16 16 8 16 16 8 8 "
    "16x6 "
    "8 16 8 16 8 8 16 8 16 8 8 "
    "8 16 16 8 8 "
    "8x4 "
    "16 8 16 "
    "8x9 16 8x6 "
    "8x20"
)
TECH2_WIDTHS = _matlab_expand(_T4_TABLE)  # 59 items, 792 bits

_CTD_TABLE = "16 16 8 8 16x45 8x3"
CTD_WIDTHS = _matlab_expand(_CTD_TABLE)  # 52 items, 792 bits

_T5_222_TABLE = (
    "16 8x7 16 16x4 8x7 16x4 8 16 16 16 8 8 8 16 16 8x6 16 16 16 8x5 16 8x5 16 8 16 8x12 16 16 8x6"
)
PARAM1_WIDTHS_222_FAMILY = _matlab_expand(_T5_222_TABLE)  # 70 items, 792 bits

_T5_232_TABLE = (
    "16 8x7 16 "
    "16x4 8x7 16x4 8 16 16 16 8 8 8 16 16 8x6 16 16 "
    "16 8x5 16 8x5 16 8 16 8x12 16 16 8 "
    "8x5"
)
PARAM1_WIDTHS_232 = _matlab_expand(_T5_232_TABLE)  # 70 items, 792 bits

# Type 6 (hydraulic): 3 header items, then 13 action records, then 2 spare bytes.
PUMP_EV_WIDTHS = _expand([(16, 3)]) + _expand([(8, 1), (16, 3)] * 13) + _expand([(8, 2)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def twos_complement(value: int, nbits: int) -> int:
    """Two's-complement interpretation of an unsigned field."""
    if value >= 1 << (nbits - 1):
        return value - (1 << nbits)
    return value


def _field(fields: list[int], idx_1based: int) -> int | None:
    return fields[idx_1based] if idx_1based < len(fields) else None


def _two_digit_year(yy: int) -> int:
    """Map a 2-digit float year to 4 digits.

    Observed data uses yy = 25/26 (2025/2026).  MATLAB ``datenum`` maps
    2-digit years to the current century; we use a documented 1950/2050
    pivot.  PROVEN for yy ≤ 49 on all observed packets.
    """

    return 2000 + yy if yy <= 49 else 1900 + yy


def _parse_float_datetime(
    hh: int | None, mm: int | None, ss: int | None, dd: int | None, mon: int | None, yy: int | None
) -> datetime | None:
    """Parse an HHMMSSddmmyy float-clock timestamp (MATLAB datenum convention)."""

    vals = (hh, mm, ss, dd, mon, yy)
    if any(v is None for v in vals):
        return None
    try:
        return datetime(
            _two_digit_year(int(yy)),  # type: ignore[arg-type]
            int(mon),  # type: ignore[arg-type]
            int(dd),  # type: ignore[arg-type]
            int(hh),  # type: ignore[arg-type]
            int(mm),  # type: ignore[arg-type]
            int(ss),  # type: ignore[arg-type]
            tzinfo=UTC,
        )
    except ValueError:
        return None


# Counts → physical conversions (PROVEN: sensor_2_value_for_*_2xx_*.m + raw
# parity with operator CTD reference files).

FILL_COUNTS = (0, 0, 0)  # all-zero PTS triplet = fill/sentinel


def counts_to_pres(counts: int) -> float:
    """Pressure in dbar: ``(twos16(counts) + 10000) / 10``."""

    return (twos_complement(counts, 16) + 10000) / 10


def counts_to_temp(counts: int) -> float:
    """Temperature in °C: ``twos16(counts) / 1000``."""

    return twos_complement(counts, 16) / 1000


def counts_to_psal(counts: int) -> float:
    """Practical salinity: ``counts / 1000`` (unsigned)."""

    return counts / 1000


# ---------------------------------------------------------------------------
# Structured packet objects
# ---------------------------------------------------------------------------


@dataclass
class ArvorIPacket:
    """Base: one 100-byte packet row, raw bytes preserved."""

    pack_type: int
    raw: bytes
    fields: list[int] = field(default_factory=list)  # 1-indexed (fields[0] == 0)
    truncated: bool = False


@dataclass
class ArvorTech1Packet(ArvorIPacket):
    """Technical packet #1 (type 0) — PROVEN field map (manual §6.2 + MATLAB)."""

    @property
    def cycle(self) -> int | None:
        return _field(self.fields, 1)

    @property
    def iridium_session(self) -> int | None:
        return _field(self.fields, 2)

    @property
    def firmware_checksum(self) -> int | None:
        return _field(self.fields, 3)

    @property
    def serial_number(self) -> int | None:
        return _field(self.fields, 4)

    @property
    def float_time(self) -> datetime | None:
        """Float-clock timestamp (items 41-46, HHMMSSddmmyy)."""

        f = self.fields
        return _parse_float_datetime(
            _field(f, 41), _field(f, 42), _field(f, 43), _field(f, 44), _field(f, 45), _field(f, 46)
        )

    @property
    def pressure_offset_db(self) -> float | None:
        """Pressure-sensor offset in dbar (item 47, 8-bit twos / 10)."""

        v = _field(self.fields, 47)
        return None if v is None else twos_complement(v, 8) / 10

    @property
    def gps_lat(self) -> float | None:
        f = self.fields
        deg, minute, frac = _field(f, 53), _field(f, 54), _field(f, 55)
        sign = _field(f, 56)
        if deg is None or minute is None or frac is None or sign is None:
            return None
        lat = deg + (minute + frac / 10000) / 60
        return -lat if sign else lat

    @property
    def gps_lon(self) -> float | None:
        f = self.fields
        deg, minute, frac = _field(f, 57), _field(f, 58), _field(f, 59)
        sign = _field(f, 60)
        if deg is None or minute is None or frac is None or sign is None:
            return None
        lon = deg + (minute + frac / 10000) / 60
        return -lon if sign else lon

    @property
    def gps_valid(self) -> int | None:
        """Item 61: 1 = valid fix.  When 0 the float reused its last fix."""

        return _field(self.fields, 61)

    @property
    def eol_flag(self) -> int | None:
        """Item 66: end-of-life detection flag."""

        return _field(self.fields, 66)

    @property
    def clock_offset_s(self) -> int | None:
        """Item 73: 16-bit two's-complement clock retiming, seconds.

        Only meaningful on a valid GPS fix (MATLAB stores it gated on
        item 61); both the raw value and ``gps_valid`` are exposed.
        """

        v = _field(self.fields, 73)
        return None if v is None else twos_complement(v, 16)


@dataclass
class ArvorTech2Packet(ArvorIPacket):
    """Technical packet #2 (type 4) — CORRECTED expected-count mapping.

    Manual §6.3 and raw telemetry prove items 3/4/5 = number of descent /
    drift / ascent CTD(O) packets (items 6/7 = near-surface / in-air).
    Coriolis MATLAB reads items 4/5/6 as expNbDesc/Drift/Asc — an
    off-by-one documented in the investigation report.
    """

    @property
    def cycle(self) -> int | None:
        return _field(self.fields, 1)

    @property
    def iridium_session(self) -> int | None:
        return _field(self.fields, 2)

    @property
    def n_descent_packets(self) -> int | None:
        return _field(self.fields, 3)

    @property
    def n_drift_packets(self) -> int | None:
        return _field(self.fields, 4)

    @property
    def n_ascent_packets(self) -> int | None:
        return _field(self.fields, 5)

    @property
    def n_near_surface_packets(self) -> int | None:
        return _field(self.fields, 6)

    @property
    def n_in_air_packets(self) -> int | None:
        return _field(self.fields, 7)

    @property
    def last_reset(self) -> datetime | None:
        """Items 46-51 = HHMMSSddmmyy of the last float reset."""

        f = self.fields
        return _parse_float_datetime(
            _field(f, 46), _field(f, 47), _field(f, 48), _field(f, 49), _field(f, 50), _field(f, 51)
        )

    @property
    def hydraulic_type(self) -> int | None:
        """Item 58: 0 = ARVOR, 1 = PROVOR hydraulics."""

        return _field(self.fields, 58)

    @property
    def ice_flag(self) -> int | None:
        """Item 59: ice-detection flag (bit flags, fw ≥ 5900A03)."""

        return _field(self.fields, 59)

    # Coriolis-as-coded reading (items 4/5/6) kept for parity comparison.
    @property
    def coriolis_exp_nb_desc_drift_asc(self) -> tuple[int | None, int | None, int | None]:
        return _field(self.fields, 4), _field(self.fields, 5), _field(self.fields, 6)


@dataclass
class ArvorCtdPacket(ArvorIPacket):
    """CTD packet (types 1/2/3/13/14): 15 PTS triplets, 16-bit counts.

    Measurement #1 carries the first-measurement time (items 2-4 =
    hours/minutes/seconds of day, fraction used by MATLAB); triplets occupy
    items 5-49 (pres, temp, sal per bin).
    """

    @property
    def cycle(self) -> int | None:
        return _field(self.fields, 1)

    @property
    def first_meas_time_day_fraction(self) -> float | None:
        """``H/24 + M/1440 + S/86400`` for the first measurement (MATLAB)."""

        h, m, s = _field(self.fields, 2), _field(self.fields, 3), _field(self.fields, 4)
        if h is None or m is None or s is None:
            return None
        return h / 24 + m / 1440 + s / 86400

    @staticmethod
    def _triplet(fields: list[int], bin_index_1based: int) -> tuple[int, int, int]:
        base = 3 * (bin_index_1based - 1) + 5
        return (
            fields[base] if base < len(fields) else 0,
            fields[base + 1] if base + 1 < len(fields) else 0,
            fields[base + 2] if base + 2 < len(fields) else 0,
        )

    @property
    def is_empty(self) -> bool:
        """All items after the cycle number are zero (MATLAB warns + drops)."""

        return not any(self.fields[2:])

    def triplets(self) -> list[tuple[int, int, int]]:
        return [self._triplet(self.fields, i) for i in range(1, 16)]

    def valid_mask(self) -> list[bool]:
        """False where the triplet is the all-zero fill sentinel."""

        return [t != FILL_COUNTS for t in self.triplets()]

    def pres(self) -> list[float | None]:
        return [
            counts_to_pres(t[0]) if valid else None
            for t, valid in zip(self.triplets(), self.valid_mask(), strict=True)
        ]

    def temp(self) -> list[float | None]:
        return [
            counts_to_temp(t[1]) if valid else None
            for t, valid in zip(self.triplets(), self.valid_mask(), strict=True)
        ]

    def psal(self) -> list[float | None]:
        return [
            counts_to_psal(t[2]) if valid else None
            for t, valid in zip(self.triplets(), self.valid_mask(), strict=True)
        ]


@dataclass
class ArvorParam1Packet(ArvorIPacket):
    """Parameter packet #1 (type 5).  Only cycle + float-clock time are
    interpreted (PROVEN, identical prefix across engines); the remaining raw
    items are preserved.  Full mission-parameter interpretation is deferred."""

    @property
    def cycle(self) -> int | None:
        return _field(self.fields, 1)

    @property
    def float_time(self) -> datetime | None:
        f = self.fields
        return _parse_float_datetime(
            _field(f, 3), _field(f, 4), _field(f, 5), _field(f, 6), _field(f, 7), _field(f, 8)
        )


@dataclass
class HydraulicAction:
    """One valve/pump action from a type-6 packet (MATLAB: type 0 = EV)."""

    action_type: int
    ref_time_min: int
    pressure_db: float  # 16-bit two's complement
    duration_s: int

    @property
    def is_pump(self) -> bool:
        return self.action_type != 0


@dataclass
class ArvorHydraulicPacket(ArvorIPacket):
    """Hydraulic packet (type 6): reference day/minute + up to 13 actions."""

    @property
    def cycle(self) -> int | None:
        return _field(self.fields, 1)

    @property
    def ref_day(self) -> int | None:
        return _field(self.fields, 2)

    @property
    def ref_min(self) -> int | None:
        return _field(self.fields, 3)

    def actions(self) -> list[HydraulicAction]:
        out: list[HydraulicAction] = []
        for i in range(13):
            base = 4 * i + 4
            a_type = _field(self.fields, base)
            ref_min = _field(self.fields, base + 1)
            pres = _field(self.fields, base + 2)
            dur = _field(self.fields, base + 3)
            if a_type is None or ref_min is None or pres is None or dur is None:
                break
            if ref_min == 0 and pres == 0 and dur == 0:
                continue  # empty slot (MATLAB skips)
            out.append(
                HydraulicAction(
                    action_type=a_type,
                    ref_time_min=ref_min,
                    pressure_db=twos_complement(pres, 16),
                    duration_s=dur,
                )
            )
        return out


@dataclass
class ArvorUnsupportedPacket(ArvorIPacket):
    """Packet type with no layout implemented in this module.

    Deliberate: types 7-14 were never observed in the evidence datasets;
    their MATLAB tables exist but are NOT transcribed (scope rule: no
    support for unobserved packet types until evidence requires it).
    """


# ---------------------------------------------------------------------------
# Framing + dispatch
# ---------------------------------------------------------------------------

PAD_BYTE_0x1A = 0x1A


def _is_padding_row(row: bytes) -> bool:
    """MATLAB: a row that is all 0x00 or all 0x1A (26) is padding."""

    return all(b == 0 for b in row) or all(b == PAD_BYTE_0x1A for b in row)


def frame_sbd_payload(payload: bytes) -> tuple[list[bytes], list[int]]:
    """Split an SBD payload into packet rows (decode_sbd_file.m framing).

    Returns ``(packet_rows, padding_row_indices)`` where indices refer to
    the 100-byte row position inside the payload (0-based).  Raises
    :class:`SbdFramingError` when ``len(payload) % 100 != 0`` (MATLAB
    warns and skips the whole file; here the error is explicit).
    """

    if len(payload) == 0:
        return [], []
    if len(payload) % 100 != 0:
        raise SbdFramingError(f"SBD payload length {len(payload)} is not a multiple of 100 bytes")
    rows = [payload[i * 100 : (i + 1) * 100] for i in range(len(payload) // 100)]
    packets = [r for r in rows if not _is_padding_row(r)]
    padding = [i for i, r in enumerate(rows) if _is_padding_row(r)]
    return packets, padding


def decode_packet(row: bytes, engine: ArvorIEngine | None = None) -> ArvorIPacket:
    """Decode one 100-byte packet row into a structured packet.

    ``engine`` selects the type-5 layout variant; it defaults to the
    222/223/225 family table (the two variants only differ in trailing
    8-bit items).
    """

    if len(row) != 100:
        raise ValueError(f"packet row must be 100 bytes, got {len(row)}")
    pack_type = row[0]
    reader = BitReader(row[1:])

    def read(widths: list[int]) -> tuple[list[int], bool]:
        fields: list[int] = [0]  # 1-indexed like MATLAB
        truncated = False
        for w in widths:
            try:
                fields.append(reader.read(w))
            except BitReaderEofError:
                truncated = True
                break
        return fields, truncated

    if pack_type == 0:
        fields, truncated = read(TECH1_WIDTHS)
        return ArvorTech1Packet(pack_type=0, raw=row, fields=fields, truncated=truncated)
    if pack_type == 4:
        fields, truncated = read(TECH2_WIDTHS)
        return ArvorTech2Packet(pack_type=4, raw=row, fields=fields, truncated=truncated)
    if pack_type in (1, 2, 3, 13, 14):
        fields, truncated = read(CTD_WIDTHS)
        return ArvorCtdPacket(pack_type=pack_type, raw=row, fields=fields, truncated=truncated)
    if pack_type == 5:
        widths = (
            PARAM1_WIDTHS_232 if engine is ArvorIEngine.ENGINE_232 else PARAM1_WIDTHS_222_FAMILY
        )
        fields, truncated = read(widths)
        return ArvorParam1Packet(pack_type=5, raw=row, fields=fields, truncated=truncated)
    if pack_type == 6:
        fields, truncated = read(PUMP_EV_WIDTHS)
        return ArvorHydraulicPacket(pack_type=6, raw=row, fields=fields, truncated=truncated)
    return ArvorUnsupportedPacket(pack_type=pack_type, raw=row)


@dataclass
class ArvorSbdDecode:
    """Result of decoding one SBD payload: packets + framing metadata."""

    payload: bytes  # original payload preserved verbatim
    packets: list[ArvorIPacket]
    padding_rows: list[int]  # 0-based row indices that were padding
    engine: ArvorIEngine | None = None


def decode_arvor_i_sbd(payload: bytes, engine: ArvorIEngine | None = None) -> ArvorSbdDecode:
    """Frame + decode one SBD payload (3 x 100 B -> up to 3 packets)."""

    rows, padding = frame_sbd_payload(payload)
    packets = [decode_packet(r, engine) for r in rows]
    return ArvorSbdDecode(payload=payload, packets=packets, padding_rows=padding, engine=engine)


# ---------------------------------------------------------------------------
# .eml handling (transport metadata strictly separated from float data)
# ---------------------------------------------------------------------------


@dataclass
class ArvorIridiumMessage:
    """One .eml delivery: session/transport metadata + raw SBD payload.

    ``session`` fields (MOMSN, session time, unit location, CEP) are
    *transport* metadata generated by the Iridium ground station — they are
    NOT float-clock timestamps and must never be mixed with float-generated
    times (investigation §2).

    Two on-disk forms are supported:

    * a true MIME e-mail (Coriolis ``co_*`` style) whose base64 ``*.sbd``
      attachment carries the payload — handled by ``parse_sbd_bytes``;
    * the ARVOR-I raw export form: a header-only ``.eml`` (200 bytes of
      Iridium session text, no MIME part) with the payload stored in a
      sidecar ``.sbd`` file of the same stem (investigation report §2
      correction of 2026-08-24: the supplied dataset splits mail text and
      binary payload into separate files).
    """

    source_path: Path
    session: SbdSessionInfo
    payload: bytes


def _looks_like_mime(raw: bytes) -> bool:
    head = raw[:2048]
    return b"MIME-Version" in head or b"Content-Type: multipart" in head


def _parse_header_text(raw: bytes) -> SbdSessionInfo:
    """Parse a bare Iridium header-text file using the shared regexes."""

    from argo_decoder.io.sbd_email import _parse_session_text

    return _parse_session_text(raw.decode("ascii", errors="replace"))


def read_arvor_i_eml(path: str | Path) -> ArvorIridiumMessage:
    """Parse one ARVOR-I delivery (.eml [+ sidecar .sbd], or MIME e-mail)."""

    p = Path(path)
    raw = p.read_bytes()
    if _looks_like_mime(raw):
        session, payload = parse_sbd_bytes(raw)
    else:
        session = _parse_header_text(raw)
        sidecar = p.with_suffix(".sbd")
        payload = sidecar.read_bytes() if sidecar.exists() else b""
    if session.momsn is None:
        raise ValueError(f"no MOMSN header in {p}")
    if payload and session.message_size_bytes and len(payload) != session.message_size_bytes:
        raise ValueError(
            f"{p}: payload length {len(payload)} != Message Size header "
            f"{session.message_size_bytes}"
        )
    return ArvorIridiumMessage(source_path=p, session=session, payload=payload)


def momsn_from_filename(name: str) -> int | None:
    """MOMSN from a ``redacted_imei_XXX_<MOMSN>.(eml|sbd)`` filename."""

    stem = name.rsplit(".", 1)[0]
    try:
        return int(stem.rsplit("_", 1)[1])
    except (IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Duplicate / retransmission detection (flag only — never discard)
# ---------------------------------------------------------------------------


def find_identical_payloads(messages: list[ArvorIridiumMessage]) -> list[list[Path]]:
    """Group messages whose SBD payloads are byte-identical.

    Coriolis removes duplicated *mail files* (same delivery stored twice),
    keeping the copy with non-zero message size and smallest CEP radius
    (``ignore_duplicated_mail_files.m``).  Content-level retransmissions —
    e.g. the float re-sending an ascent profile in a later, distinct MOMSN —
    are genuine separate transmissions and MUST be preserved.  This function
    therefore only *flags* identical payloads; the caller decides.
    """

    groups: dict[bytes, list[Path]] = {}
    for msg in messages:
        if msg.payload:
            groups.setdefault(msg.payload, []).append(msg.source_path)
    return [sorted(g) for g in groups.values() if len(g) > 1]


__all__ = [
    "ARVOR_I_DECODER_IDS",
    "CTD_WIDTHS",
    "FILL_COUNTS",
    "FIRMWARE_CHECKSUM_TO_DECODER_IDS",
    "PARAM1_WIDTHS_222_FAMILY",
    "PARAM1_WIDTHS_232",
    "PUMP_EV_WIDTHS",
    "TECH1_WIDTHS",
    "TECH2_WIDTHS",
    "ArvorCtdPacket",
    "ArvorHydraulicPacket",
    "ArvorIEngine",
    "ArvorIPacket",
    "ArvorIridiumMessage",
    "ArvorParam1Packet",
    "ArvorSbdDecode",
    "ArvorTech1Packet",
    "ArvorTech2Packet",
    "ArvorUnsupportedPacket",
    "SbdFramingError",
    "UnsupportedEngineError",
    "counts_to_pres",
    "counts_to_psal",
    "counts_to_temp",
    "decode_arvor_i_sbd",
    "decode_packet",
    "find_identical_payloads",
    "frame_sbd_payload",
    "momsn_from_filename",
    "read_arvor_i_eml",
    "resolve_engine",
    "twos_complement",
]

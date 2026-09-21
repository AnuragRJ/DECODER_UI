"""Phase-1 unit tests: PROVOR CTS4 front-end on synthetic fixtures (no IO).

Contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md`` §6.
Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7.
Covers framer geometry, dispatch routing/errors, attribution decisions, CTD record
geometry/scaling, and the regression pins for the (aq) NKE correction
(record start 10, P/T/S order, T-2000, S/1000, header cycle, no MOMSN, no +33).
The full 517-file telemetry contract lives in
``tests/test_provor_cts4_phase1_telemetry.py``.
"""

from __future__ import annotations

import struct
from dataclasses import fields
from pathlib import Path

import pytest

import argo_decoder.platforms.provor_cts4_ir_sbd.ctd as ctd_module
from argo_decoder.platforms.provor_cts4_ir_sbd import (
    CtdRecord,
    CycleBasis,
    FramingError,
    MeasPacket,
    MeasSubtype,
    PacketType,
    ParamPacket,
    UnknownMeasSubtypeError,
    UnknownPacketTypeError,
    attribute_file,
    dispatch_framed,
    dispatch_row,
    extract_ctd,
    frame_bytes,
)

pytestmark = pytest.mark.unit


def _row(
    byte0: int,
    *,
    byte1: int = 0,
    byte2: int = 0,
    byte3: int = 0,
    byte4: int = 0,
    byte5: int = 0,
    fill: int = 0x2E,
) -> bytes:
    row = bytearray([fill]) * 140
    row[0] = byte0
    row[1] = byte1
    row[2] = byte2
    row[3] = byte3
    row[4] = byte4
    row[5] = byte5
    return bytes(row)


def _meas_row(subtype: int, *, cycle: int, profile: int = 0, phase: int = 9) -> bytes:
    row = bytearray(_row(0x00, byte1=subtype))
    row[2:4] = cycle.to_bytes(2, "big")
    row[4] = profile
    row[5] = phase
    return bytes(row)


def _param_row(kind: int, *, cycle: int, profile: int = 0) -> bytes:
    row = bytearray(_row(kind, byte1=17, byte2=2, byte3=14, byte4=10, byte5=55))
    row[6] = 9
    row[7:9] = cycle.to_bytes(2, "big")
    row[9] = profile
    if kind == 0xFF:
        row[10] = 1  # PV0: number of different cycle durations
    else:
        row[10:12] = (2700).to_bytes(2, "big")  # PT0: max eV activation on surface
    return bytes(row)


def _ctd_row(records: list[tuple[int, int, int]], *, cycle: int = 0) -> bytes:
    row = bytearray(_meas_row(0, cycle=cycle))
    for i, (p, t, s) in enumerate(records):
        struct.pack_into(">hHH", row, 10 + i * 6, p, t, s)
    row[136:140] = bytes([0xAA, 0xBB, 0xCC, 0xDD])
    return bytes(row)


def _dispatch(*rows: bytes, path: Path = Path("synthetic.sbd")):
    framed = frame_bytes(b"".join(rows), path=path)
    return dispatch_framed(framed)


# --- framer -----------------------------------------------------------------


def test_frame_exact_multiple() -> None:
    framed = frame_bytes(_row(0x00) * 3)
    assert len(framed.rows) == 3
    assert framed.kept_indices == (0, 1, 2)
    assert framed.dropped_blank == 0
    assert framed.truncated_1024 is False


def test_frame_1024_truncation_coriolis_rule() -> None:
    data = _row(0xFF) * 7 + bytes(44)
    assert len(data) == 1024
    framed = frame_bytes(data)
    assert framed.truncated_1024 is True
    assert len(framed.rows) == 7


def test_frame_rejects_non_multiple() -> None:
    with pytest.raises(FramingError):
        frame_bytes(bytes(100))
    with pytest.raises(FramingError):
        frame_bytes(bytes(150))


def test_frame_drops_blank_rows_coriolis_rule() -> None:
    data = _row(0x00) + bytes(140) + bytes([0x1A]) * 140 + _row(0xFF)
    framed = frame_bytes(data)
    assert len(framed.rows) == 2
    assert framed.kept_indices == (0, 3)
    assert framed.dropped_blank == 2


def test_frame_all_blank_ok() -> None:
    framed = frame_bytes(bytes(280))
    assert framed.rows == ()
    assert framed.dropped_blank == 2


# --- dispatch ---------------------------------------------------------------


def test_dispatch_all_six_types() -> None:
    dispatched = _dispatch(_row(0x00), _row(0xFA), _row(0xFC), _row(0xFD), _row(0xFE), _row(0xFF))
    assert dispatched.kinds == frozenset(PacketType)


def test_dispatch_packet_type_values_follow_nke() -> None:
    assert PacketType.MEASUREMENT == 0x00
    assert PacketType.SENSOR_TECH == 0xFA
    assert PacketType.PRESSURE == 0xFC
    assert PacketType.VECTOR_TECH == 0xFD
    assert PacketType.TECH_PARAMS == 0xFE
    assert PacketType.MISSION_PARAMS == 0xFF


def test_dispatch_unknown_type_raises() -> None:
    with pytest.raises(UnknownPacketTypeError):
        dispatch_row(_row(0x01), index=0)
    with pytest.raises(UnknownPacketTypeError):
        # NKE packet 251 (sensor params): defined, sent only-on-modification,
        # absent from the corpus — a discovery if ever seen, never skipped.
        dispatch_row(_row(0xFB), index=0)


def test_dispatch_meas_subtypes() -> None:
    assert dispatch_row(_row(0x00, byte1=0)).subtype is MeasSubtype.CTD  # type: ignore[union-attr]
    assert dispatch_row(_row(0x00, byte1=3)).subtype is MeasSubtype.DOXY_CLASS  # type: ignore[union-attr]
    assert dispatch_row(_row(0x00, byte1=6)).subtype is MeasSubtype.OPTICS_FLBB  # type: ignore[union-attr]


def test_dispatch_meas_header_cycle_profile_phase() -> None:
    """Regression: cycle is the u16be header field (bytes2-3), not byte3."""
    packet = dispatch_row(_meas_row(0, cycle=0x0102, profile=2, phase=6))
    assert isinstance(packet, MeasPacket)
    assert packet.cycle == 0x0102
    assert packet.profile == 2
    assert packet.phase == 6


def test_dispatch_meas_header_split_at_byte_10() -> None:
    """Regression: type-0 records start at byte 10 (NKE §7.2.4.1)."""
    row = _meas_row(0, cycle=7)
    packet = dispatch_row(row)
    assert isinstance(packet, MeasPacket)
    assert packet.header == row[:10]
    assert packet.payload == row[10:]
    assert len(packet.payload) == 130


def test_dispatch_unknown_subtype_raises() -> None:
    with pytest.raises(UnknownMeasSubtypeError):
        dispatch_row(_row(0x00, byte1=1), index=0)


def test_dispatch_param_fields() -> None:
    ff = dispatch_row(_param_row(0xFF, cycle=0x1234))
    assert isinstance(ff, ParamPacket)
    assert ff.kind is PacketType.MISSION_PARAMS
    assert ff.cycle == 0x1234
    assert ff.profile == 0
    assert (ff.date.dd, ff.date.mm, ff.date.yy) == (17, 2, 14)
    fe = dispatch_row(_param_row(0xFE, cycle=9))
    assert isinstance(fe, ParamPacket)
    assert fe.kind is PacketType.TECH_PARAMS
    assert fe.cycle == 9
    assert fe.profile == 0


def test_dispatch_param_field_set() -> None:
    """The old cross-boundary ``tag`` slice is gone; byte9 is ``profile``."""
    names = {f.name for f in fields(ParamPacket)}
    assert names == {"kind", "cycle", "profile", "date", "raw"}


# --- attribution ------------------------------------------------------------


def test_attribute_unanimous_with_params() -> None:
    dispatched = _dispatch(
        _param_row(0xFF, cycle=5),
        _param_row(0xFE, cycle=5),
        _meas_row(0, cycle=5),
        _meas_row(3, cycle=5),
    )
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.UNANIMOUS
    assert attrib.cycle == 5
    assert attrib.meas_cycles == (5,)
    assert attrib.mission_cycle == 5
    assert attrib.tech_cycle == 5
    assert attrib.conflicts == ()


def test_attribute_unanimous_cycle_zero_is_genuine() -> None:
    """Regression: cycle 0 is a genuine header cycle, fully attributable."""
    dispatched = _dispatch(
        _param_row(0xFF, cycle=0),
        _meas_row(0, cycle=0),
        _meas_row(6, cycle=0),
    )
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.UNANIMOUS
    assert attrib.cycle == 0
    assert attrib.meas_cycles == (0,)
    assert attrib.conflicts == ()


def test_attribute_unanimous_data_only() -> None:
    dispatched = _dispatch(_meas_row(0, cycle=4), _meas_row(6, cycle=4))
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.UNANIMOUS
    assert attrib.cycle == 4
    assert attrib.conflicts == ()


def test_attribute_multi_cycle_recorded_not_conflict() -> None:
    """Backlog pattern (NKE §7.4): several header cycles, no conflict."""
    dispatched = _dispatch(
        _param_row(0xFF, cycle=5),
        _meas_row(0, cycle=0),
        _meas_row(0, cycle=5),
    )
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.MULTI_CYCLE
    assert attrib.cycle is None
    assert attrib.meas_cycles == (0, 5)
    assert attrib.mission_cycle == 5
    assert attrib.conflicts == ()


def test_attribute_param_disagreement_is_conflict() -> None:
    dispatched = _dispatch(
        _param_row(0xFF, cycle=5),
        _param_row(0xFF, cycle=6),
        _meas_row(0, cycle=5),
    )
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.CONFLICT
    assert attrib.cycle is None
    assert len(attrib.conflicts) == 1


def test_attribute_mission_tech_mismatch_is_conflict() -> None:
    dispatched = _dispatch(_param_row(0xFF, cycle=5), _param_row(0xFE, cycle=6))
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.CONFLICT
    assert attrib.cycle is None
    assert len(attrib.conflicts) == 1


def test_attribute_no_cycle_info() -> None:
    dispatched = _dispatch(_row(0xFD))
    attrib = attribute_file(dispatched, group="synthetic")
    assert attrib.basis is CycleBasis.NO_CYCLE_INFO
    assert attrib.cycle is None


def test_cycle_ignores_filename_momsn() -> None:
    """Regression: identical bytes under different MOMSNs attribute identically."""
    rows = (_param_row(0xFF, cycle=5), _meas_row(0, cycle=5))
    first = attribute_file(_dispatch(*rows, path=Path("x_000030.sbd")), group="g")
    second = attribute_file(_dispatch(*rows, path=Path("x_999999.sbd")), group="g")
    assert (
        (first.cycle, first.basis, first.meas_cycles, first.conflicts)
        == (
            second.cycle,
            second.basis,
            second.meas_cycles,
            second.conflicts,
        )
        == (5, CycleBasis.UNANIMOUS, (5,), ())
    )


# --- CTD --------------------------------------------------------------------


def test_extract_ctd_records() -> None:
    packet = dispatch_row(_ctd_row([(19628, 21062, 35381)], cycle=7))
    assert isinstance(packet, MeasPacket)
    data = extract_ctd(packet, packet_index=3)
    assert data.packet_index == 3
    assert data.cycle == 7
    assert len(data.records) == 21
    first = data.records[0]
    assert (first.p_raw, first.t_raw, first.s_raw) == (19628, 21062, 35381)
    assert first.pres_dbar == pytest.approx(1962.8)
    assert first.temp_c == pytest.approx(19.062)
    assert first.psal == pytest.approx(35.381)
    assert data.tail == bytes([0xAA, 0xBB, 0xCC, 0xDD])


def test_extract_ctd_record_start_and_order() -> None:
    """Regression: record 0 is bytes[10:16] parsed as (P, T, S).

    The marker triplet is chosen so the old offset-12 T/S/P framing would read
    different values in every column.
    """
    row = _ctd_row([(1000, 2250, 34000), (1010, 2260, 34010)], cycle=1)
    packet = dispatch_row(row)
    assert isinstance(packet, MeasPacket)
    data = extract_ctd(packet)
    assert struct.unpack_from(">hHH", row, 10) == (1000, 2250, 34000)
    assert (data.records[0].p_raw, data.records[0].t_raw, data.records[0].s_raw) == (
        1000,
        2250,
        34000,
    )
    assert (data.records[1].p_raw, data.records[1].t_raw, data.records[1].s_raw) == (
        1010,
        2260,
        34010,
    )


def test_extract_ctd_rejects_non_ctd() -> None:
    packet = dispatch_row(_row(0x00, byte1=3))
    assert isinstance(packet, MeasPacket)
    with pytest.raises(ValueError):
        extract_ctd(packet)


def test_ctd_temperature_offset() -> None:
    """Regression: T = (raw - 2000) / 1000 (NKE §7.2.4.1)."""
    packet = dispatch_row(_ctd_row([(0, 2000, 0), (0, 3121, 0), (0, 0, 0)]))
    assert isinstance(packet, MeasPacket)
    records = extract_ctd(packet).records
    assert records[0].temp_c == pytest.approx(0.0)
    assert records[1].temp_c == pytest.approx(1.121)
    # Padding honesty: an all-zero record yields the formula value, not a clamp.
    assert records[2].temp_c == pytest.approx(-2.0)


def test_ctd_pressure_signed() -> None:
    """Regression: P is signed s16 cBar (NKE INT), so 0xFFFF is -0.1 dbar."""
    packet = dispatch_row(_ctd_row([(-1, 2000, 35000)]))
    assert isinstance(packet, MeasPacket)
    first = extract_ctd(packet).records[0]
    assert first.p_raw == -1
    assert first.pres_dbar == pytest.approx(-0.1)


def test_ctd_psal_single_encoding_no_plus33() -> None:
    """Regression: psal == s_raw / 1000 for every value; no phantom +33."""
    raws = [0, 1120, 1150, 1170, 31076, 34120, 35381, 36698, 65535]
    packet = dispatch_row(_ctd_row([(0, 2000, s) for s in raws]))
    assert isinstance(packet, MeasPacket)
    records = extract_ctd(packet).records
    for index, raw in enumerate(raws):
        assert records[index].psal == raw / 1000.0
    # The old artifact trigger range yields ~1.1 PSU, never ~34.1.
    assert records[1].psal == pytest.approx(1.120)
    assert records[1].psal != pytest.approx(1.120 + 33.0)


def test_ctd_field_set_pinned() -> None:
    """Record shape pin: wire-order raws + NKE-scaled physical values."""
    names = {f.name for f in fields(CtdRecord)}
    assert names == {"p_raw", "t_raw", "s_raw", "pres_dbar", "temp_c", "psal"}
    assert not any("provisional" in name for name in names)


def test_ctd_module_has_no_provisional_or_plus33() -> None:
    """The old T/S/P provisional factors and +33 numerology are fully gone."""
    assert not any("PROVISIONAL" in name or "33" in name for name in dir(ctd_module))
    assert "TEMP_PROVISIONAL_DIVISOR" not in dir(ctd_module)
    assert "PRES_PROVISIONAL_DIVISOR" not in dir(ctd_module)

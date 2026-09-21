"""Phase-2A unit tests: synthetic NKE fixtures for 255/254/253/252/251/250, BGC raw
extraction, equation smoke checks, association primitives, and label-map shape.

No workspace IO: every packet is built byte-exact in-fixture from the NKE
``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7 layouts. Corpus-scale pins
live in ``tests/test_provor_cts4_phase2a_telemetry.py``; GDAC recomputation
pins (inline vectors) live further below in this file.
"""

from __future__ import annotations

import csv
import dataclasses
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_cts4_ir_sbd import (
    CtdRecord,
    DispatchedFile,
    FlbbRecord,
    MeasPacket,
    MeasSubtype,
    O2Record,
    OpaquePacket,
    PacketType,
    ProfileKey,
    SensorHalf,
    VectorTech,
    battery_dropout_v,
    battery_voltage_v,
    bbp700_m1,
    beta_sw,
    calphase,
    chla_ug_l,
    coverage,
    decode_250,
    decode_251,
    decode_252,
    decode_253,
    decode_254,
    decode_255,
    dispatch_row,
    doxy_chain,
    doxy_umol_kg,
    extract_flbb,
    extract_o2,
    foil_delta_p,
    gps_decimal,
    group_meas,
    hhmm_from_minutes,
    is_padding_ctd,
    is_padding_flbb,
    is_padding_o2,
    molar_doxy,
    nearest_ctd,
    phase_pcorr,
    pressure_correction,
    salinity_correction,
    sample_datetime,
    tphase,
    ts_ratio,
    vacuum_mbar_x5,
    FoilCoefs,
    PhaseCoefs,
    SolubilityConsts,
    UnknownSensorTypeError,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.labels_301 import (
    PM_CONFIG_LABEL,
    PT_CONFIG_LABEL,
    PV_CONFIG_LABEL,
    TECH250_CTD_FREE_LABEL,
    TECH250_FLBB_FREE_LABEL,
    TECH250_LABEL,
    TECH253_LABEL,
)
from argo_decoder.platforms.provor_cts4_ir_sbd.tech import CtdFree, FlbbFree


# --- fixture builders ---------------------------------------------------------


def _param_header(byte0: int) -> bytearray:
    row = bytearray(140)
    row[0] = byte0
    row[1:7] = bytes((5, 3, 13, 14, 30, 0))  # DD MM YY HH MM SS
    row[7:9] = (7).to_bytes(2, "big")  # cycle
    row[9] = 1  # profile
    return row


def _row_255() -> bytes:
    row = _param_header(0xFF)
    row[10] = 2  # PV0: two durations
    row[11:13] = (60).to_bytes(2, "big")  # PV1: EOL period
    row[13] = 10  # PV2: 2nd session wait
    durations = [(24, 31, 12, 99), (120, 31, 12, 99)] + [(0, 0, 0, 0)] * 3
    for block, (period, dd, mm, yy) in enumerate(durations):
        base = 14 + 5 * block
        row[base : base + 2] = period.to_bytes(2, "big")
        row[base + 2] = dd
        row[base + 3] = mm
        row[base + 4] = yy
    row[39] = 1  # PM0: one profile
    row[40:42] = (0).to_bytes(2, "big")  # PM1: no delay
    row[42] = 1  # PM2: reference day
    profiles = [(1, 4, 100, 200, 1)] + [(0, 0, 0, 0, 0)] * 9
    for block, (day, hour, park, prof, tx) in enumerate(profiles):
        base = 43 + 7 * block
        row[base] = day
        row[base + 1] = hour
        row[base + 2 : base + 4] = park.to_bytes(2, "big")
        row[base + 4 : base + 6] = prof.to_bytes(2, "big")
        row[base + 6] = tx
    return bytes(row)


def _row_254() -> bytes:
    row = _param_header(0xFE)
    # GDAC-2902091-like words (launch config, INCOIS meta.nc); PT26/PT27 carry
    # the raw values implied by coef1=1.524 / coef2=-442 (corpus adjudicates).
    words = [
        2700, 15, 60, 2, 30, 400, 2000, 40000, 30, 2100, 4, 8, 2, 0,
        100, 200, 50, 50, 30, 0, 0, 83, 90, 0, 0, 0, 1524, 65094,
    ]
    for index, word in enumerate(words):
        row[10 + 2 * index : 12 + 2 * index] = word.to_bytes(2, "big")
    return bytes(row)


def _row_253() -> bytes:
    row = bytearray(140)
    row[0] = 0xFD
    # Wire order is DD MM YY HH MM SS (Phase-0 proven on the type-0 date
    # header; corroborated by GDAC 2902086 CLOCK_FloatTime_YYYYMMDDHHMMSS).
    row[1:7] = bytes((23, 2, 13, 4, 14, 43))  # DD MM YY hh mm ss
    row[7:9] = (836).to_bytes(2, "big")  # serial
    row[9:11] = (1).to_bytes(2, "big")  # total profiles
    row[11:13] = (1).to_bytes(2, "big")  # cycle
    row[13] = 0  # profile
    row[14:16] = (0).to_bytes(2, "big")  # cycle start day
    row[16:18] = (1035).to_bytes(2, "big")  # 17:15 as minutes (NKE wording)
    row[18] = 2  # phase
    row[19:21] = (0).to_bytes(2, "big")  # dialog errors
    row[21:23] = (1).to_bytes(2, "big")  # timeout FP
    row[23] = 154  # vacuum: 154 x 5 = 770 mbar (GDAC 2902091 cyc1)
    row[24] = 10  # battery: dropout 1.0 V -> 14.0 V (GDAC stores raw 10)
    row[25] = 1  # RTC ok
    row[26:28] = (0).to_bytes(2, "big")
    row[28:30] = (1051).to_bytes(2, "big")
    row[30] = 0  # EV timing
    row[31] = 71  # valves at surface
    row[32:34] = (0).to_bytes(2, "big")
    row[34:36] = (1156).to_bytes(2, "big")
    row[36:38] = (0).to_bytes(2, "big")
    row[38:40] = (1201).to_bytes(2, "big")
    row[40:42] = (0).to_bytes(2, "big")
    row[42:44] = (1156).to_bytes(2, "big")
    row[44] = 0
    row[45] = 0
    row[46] = 99  # stab pressure Bar
    row[47] = 101  # max descent Bar
    row[48] = 0
    row[49] = 0
    row[50] = 98
    row[51] = 102
    row[52] = 0
    row[53] = 0
    row[54:56] = (0).to_bytes(2, "big")
    row[56:58] = (1156).to_bytes(2, "big")
    row[58:60] = (0).to_bytes(2, "big")
    row[60:62] = (1312).to_bytes(2, "big")
    row[62] = 3
    row[63] = 0
    row[64] = 201  # max descent to Pprofile Bar
    row[65] = 0
    row[66] = 1
    row[67] = 2
    row[68] = 0
    row[69] = 198
    row[70] = 202
    row[71:73] = (1).to_bytes(2, "big")
    row[73:75] = (83).to_bytes(2, "big")
    row[75:77] = (1).to_bytes(2, "big")
    row[77:79] = (241).to_bytes(2, "big")
    row[79] = 6
    row[80] = 0  # no grounding
    row[81] = 0
    row[82:84] = (0).to_bytes(2, "big")
    row[84:86] = (0).to_bytes(2, "big")
    row[86] = 0  # no emergency
    row[87:89] = (0).to_bytes(2, "big")
    row[89] = 0
    row[90] = 0
    row[91] = 0
    row[92] = 0
    row[93] = 0
    row[94] = 12  # lat 12 deg
    row[95] = 34  # lat 34 min
    row[96:98] = (5678).to_bytes(2, "big")  # lat frac
    row[98] = 0  # N
    row[99] = 45  # lon 45 deg
    row[100] = 6  # lon 6 min
    row[101:103] = (7890).to_bytes(2, "big")  # lon frac
    row[103] = 0  # E
    row[104] = 1  # valid fix
    row[105] = 0
    row[106] = 0
    return bytes(row)


def _row_252() -> bytes:
    row = bytearray(140)
    row[0] = 0xFC
    row[1:3] = (5).to_bytes(2, "big")
    row[3] = 0x20  # phase 2, profile 0
    row[4] = 1  # pump
    row[5] = 100  # Bar
    row[6:8] = (30).to_bytes(2, "big")  # reltime min
    row[8] = 0x31  # phase 3, profile 1
    row[9] = 0  # eV
    row[10] = 55
    row[11:13] = (90).to_bytes(2, "big")
    return bytes(row)


def _row_251() -> bytes:
    row = bytearray(140)
    row[0] = 0xFB
    row[1] = 0  # sensor CTD
    row[2] = 0  # standard
    row[3] = 5  # param number
    row[4:8] = struct.pack(">f", 1.5)
    row[8:12] = struct.pack(">f", 2.5)
    return bytes(row)


def _row_250_corpus_style() -> bytes:
    """Corpus truth: halves at [0:70]/[70:140], each opening with 0xFA then X."""
    row = bytearray(140)
    row[0] = 0xFA
    row[1] = 0  # half-1 sensor: CTD
    row[1 + 1 : 1 + 3] = (3).to_bytes(2, "big")  # cycle
    row[1 + 3] = 0  # profile
    row[1 + 4], row[1 + 5], row[1 + 6] = 0, 1, 5
    row[1 + 7 : 1 + 12] = bytes((0, 0, 0, 0, 0))
    row[1 + 12] = 1
    row[1 + 13 : 1 + 18] = bytes((9, 38, 30, 18, 0))
    row[1 + 18] = 1
    row[1 + 19 : 1 + 23] = struct.pack("<f", 0.04)
    row[1 + 23 : 1 + 27] = struct.pack("<f", 5.6506)
    row[1 + 27 : 1 + 31] = struct.pack("<f", 25.0)
    row[1 + 31 : 1 + 35] = struct.pack("<f", 36.0)
    row[70] = 0xFA  # half-2 opens with the packet-type byte, like half 1
    row[71] = 4  # half-2 sensor: FLBB
    row[71 + 1 : 71 + 3] = (3).to_bytes(2, "big")
    row[71 + 3] = 0
    row[71 + 4], row[71 + 5], row[71 + 6] = 0, 1, 5
    row[71 + 7 : 71 + 12] = bytes((0, 0, 0, 0, 0))
    row[71 + 12] = 1
    row[71 + 13 : 71 + 18] = bytes((9, 38, 30, 18, 0))
    row[71 + 18] = 1
    row[71 + 19 : 71 + 21] = (2662).to_bytes(2, "little")
    row[71 + 21 : 71 + 25] = struct.pack("<f", 0.0073)
    row[71 + 25 : 71 + 27] = (48).to_bytes(2, "little")
    row[71 + 27 : 71 + 31] = struct.pack("<f", 1.773e-06)
    row[71 + 31 : 71 + 33] = (49).to_bytes(2, "little")
    row[71 + 33 : 71 + 37] = struct.pack("<f", 0.0)
    return bytes(row)


def _meas_packet(subtype: MeasSubtype, payload_words: bytes) -> MeasPacket:
    header = bytes((0x00, subtype, 0, 7, 1, 2, 0x4C, 0x9B, 0xDA, 0x00))
    assert len(payload_words) == 130
    return MeasPacket(
        subtype=subtype, cycle=7, profile=1, phase=2,
        header=header, payload=payload_words,
    )


def _o2_payload() -> bytes:
    buf = bytearray()
    records = [
        (20100, 32954, 3515, 27203),  # GDAC-L00-like: 2010 dbar, 32.954°
        (15000, 40000, 3400, 26000),
    ] + [(0, 0, 0, 0)] * 8  # short-profile padding
    for rec in records:
        buf += struct.pack(">hiiH", *rec)
    buf += bytes(10)
    return bytes(buf)


def _flbb_payload() -> bytes:
    buf = bytearray()
    records = [(4, 1230, 1110)] + [(100, 500, 600)] * 4 + [(0, 0, 0)] * 16
    for rec in records:
        buf += struct.pack(">hHH", *rec)
    buf += bytes(4)
    return bytes(buf)


# --- 255 / 254 ---------------------------------------------------------------


def test_decode_255_layout() -> None:
    packet = dispatch_row(_row_255(), index=0)
    mission = decode_255(packet)  # type: ignore[arg-type]
    assert mission.cycle == 7
    assert mission.profile == 1
    assert (mission.date.dd, mission.date.mm, mission.date.yy) == (5, 3, 13)
    assert mission.n_durations == 2
    assert mission.eol_period_min == 60
    assert mission.second_session_wait_min == 10
    assert mission.durations[0].period_hours == 24
    assert (mission.durations[0].end_dd, mission.durations[0].end_mm,
            mission.durations[0].end_yy) == (31, 12, 99)
    assert mission.durations[1].period_hours == 120
    assert len(mission.durations) == 5
    assert mission.n_profiles == 1
    assert mission.delay_before_mission_min == 0
    assert mission.reference_day == 1
    first = mission.profiles[0]
    assert (first.surfacing_day, first.surfacing_hour, first.parking_dbar,
            first.profile_dbar, first.transmission) == (1, 4, 100, 200, 1)
    assert len(mission.profiles) == 10
    assert mission.spare_ok


def test_decode_254_layout() -> None:
    packet = dispatch_row(_row_254(), index=0)
    tech = decode_254(packet)  # type: ignore[arg-type]
    assert tech.cycle == 7
    assert tech.pt[0] == 2700
    assert tech.pt[9] == 2100
    assert tech.pt[12] == 2  # PT12 raw word (semantic conflict documented)
    assert tech.pt[18] == 30
    assert tech.pt[21] == 83
    assert tech.pt[22] == 90
    assert tech.pt[26] == 1524
    assert tech.pt[27] == 65094
    assert len(tech.pt) == 28
    assert tech.named()["max_pres_before_emergency_dbar"] == 2100
    assert tech.spare_ok


def test_decode_255_254_wrong_kind_and_length() -> None:
    p255 = dispatch_row(_row_255(), index=0)
    p254 = dispatch_row(_row_254(), index=0)
    with pytest.raises(ValueError):
        decode_255(p254)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        decode_254(p255)  # type: ignore[arg-type]
    short = dispatch_row(_row_255(), index=0)
    object.__setattr__  # frozen dataclass: rebuild instead
    bad = type(short)(kind=short.kind, cycle=short.cycle, profile=short.profile,
                      date=short.date, raw=bytes(10))
    with pytest.raises(ValueError):
        decode_255(bad)  # type: ignore[arg-type]


# --- 253 / 252 / 251 ----------------------------------------------------------


def test_decode_253_layout() -> None:
    packet = dispatch_row(_row_253(), index=0)
    assert isinstance(packet, OpaquePacket)
    vec = decode_253(packet)
    assert (vec.time.yy, vec.time.mm, vec.time.dd, vec.time.hh, vec.time.mi,
            vec.time.ss) == (13, 2, 23, 4, 14, 43)
    assert vec.serial == 836
    assert vec.total_profiles == 1
    assert vec.cycle == 1
    assert vec.profile == 0
    assert vec.cycle_start_day == 0
    assert vec.cycle_start_hour == 1035
    assert hhmm_from_minutes(vec.cycle_start_hour) == (17, 15)
    assert vec.phase == 2
    assert vec.dialog_errors == 0
    assert vec.timeout_fp == 1
    assert vacuum_mbar_x5(vec.vacuum_raw) == 770
    assert battery_dropout_v(vec.battery_raw) == pytest.approx(1.0)
    assert battery_voltage_v(vec.battery_raw) == pytest.approx(14.0)
    assert vec.rtc == 1
    assert vec.n_valve_surface == 71
    assert vec.max_pres_desc_park_bar == 101
    assert vec.n_pump_ascent == 6
    assert vec.grounding_detected == 0
    assert vec.n_emergency == 0
    assert vec.gps_valid == 1
    lat, lon = vec.gps_position()  # type: ignore[misc]
    assert lat == pytest.approx(12 + (34 + 0.5678) / 60)
    assert lon == pytest.approx(45 + (6 + 0.7890) / 60)
    assert vec.show_vector == 0
    assert vec.show_sensor == 0
    assert vec.spare_ok


def test_gps_helpers() -> None:
    assert gps_decimal(12, 34, 5678, 0) == pytest.approx(12.57613, rel=1e-6)
    assert gps_decimal(12, 34, 5678, 1) == pytest.approx(-12.57613, rel=1e-6)
    assert hhmm_from_minutes(0) == (0, 0)
    assert hhmm_from_minutes(1439) == (23, 59)


def test_decode_252_layout() -> None:
    packet = dispatch_row(_row_252(), index=0)
    assert isinstance(packet, OpaquePacket)
    press = decode_252(packet)
    assert press.cycle == 5
    assert len(press.samples) == 27
    first, second = press.samples[0], press.samples[1]
    assert (first.phase, first.profile, first.is_pump, first.pressure_bar,
            first.reltime_min) == (2, 0, 1, 100, 30)
    assert (second.phase, second.profile, second.is_pump, second.pressure_bar,
            second.reltime_min) == (3, 1, 0, 55, 90)
    assert all(s.pressure_bar == 0 for s in press.samples[2:])
    assert press.spare_ok


def test_decode_251_layout() -> None:
    params = decode_251(_row_251())
    assert len(params.changes) == 12
    first = params.changes[0]
    assert (first.sensor, first.param_type, first.param_number) == (0, 0, 5)
    assert first.old_value == pytest.approx(1.5)
    assert first.new_value == pytest.approx(2.5)
    assert params.spare_ok
    with pytest.raises(ValueError):
        decode_251(bytes(140))  # byte0 != 0xFB
    with pytest.raises(ValueError):
        decode_251(b"\xfb" + bytes(10))  # short row


def test_decode_wrong_kind_253_252() -> None:
    p253 = dispatch_row(_row_253(), index=0)
    p252 = dispatch_row(_row_252(), index=0)
    with pytest.raises(ValueError):
        decode_253(p252)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        decode_252(p253)  # type: ignore[arg-type]


# --- 250 ----------------------------------------------------------------------


def test_decode_250_layout() -> None:
    packet = dispatch_row(_row_250_corpus_style(), index=0)
    assert isinstance(packet, OpaquePacket)
    tech = decode_250(packet)
    ctd_half, flbb_half = tech.halves
    assert ctd_half.present and ctd_half.sensor == 0
    assert (ctd_half.cycle, ctd_half.profile) == (3, 0)
    assert (ctd_half.tx_descent, ctd_half.tx_drift, ctd_half.tx_ascent) == (0, 1, 5)
    assert ctd_half.acq_ascent == (9, 38, 30, 18, 0)
    assert ctd_half.acq_drift == 1
    assert ctd_half.status == 1
    assert isinstance(ctd_half.free, CtdFree)
    assert ctd_half.free.offset_p == pytest.approx(0.04, rel=1e-6)
    assert ctd_half.free.p_sub == pytest.approx(5.6506, rel=1e-6)
    assert flbb_half.present and flbb_half.sensor == 4
    assert isinstance(flbb_half.free, FlbbFree)
    assert flbb_half.free.serial == 2662
    assert flbb_half.free.scale_chl == pytest.approx(0.0073, rel=1e-6)
    assert flbb_half.free.dark_chl == 48
    assert flbb_half.free.scale_bb == pytest.approx(1.773e-06, rel=1e-6)
    assert flbb_half.free.dark_bb == 49


def test_decode_250_filler_and_unknown() -> None:
    row = bytearray(_row_250_corpus_style())
    row[71] = 0xFF  # second half becomes filler
    packet = dispatch_row(bytes(row), index=0)
    assert isinstance(packet, OpaquePacket)
    tech = decode_250(packet)
    assert tech.halves[0].present
    assert not tech.halves[1].present
    assert tech.halves[1].free is None
    row[1] = 9  # unknown sensor id is a discovery, not noise
    with pytest.raises(UnknownSensorTypeError):
        decode_250(dispatch_row(bytes(row), index=0))  # type: ignore[arg-type]


# --- BGC extraction -----------------------------------------------------------


def test_extract_o2_layout() -> None:
    packet = _meas_packet(MeasSubtype.DOXY_CLASS, _o2_payload())
    data = extract_o2(packet, packet_index=3)
    assert data.packet_index == 3
    assert (data.cycle, data.profile, data.phase) == (7, 1, 2)
    assert len(data.records) == 10
    first = data.records[0]
    assert (first.p_raw, first.c1_raw, first.c2_raw, first.t_raw) == (
        20100, 32954, 3515, 27203)
    assert first.pres_dbar == pytest.approx(2010.0)
    assert first.c1_phase_deg == pytest.approx(32.954)
    assert first.c2_phase_deg == pytest.approx(3.515)
    assert first.temp_c == pytest.approx(25.203)
    assert data.tail == bytes(10)
    assert all(r.p_raw == 0 for r in data.records[2:])
    with pytest.raises(ValueError):
        extract_o2(_meas_packet(MeasSubtype.CTD, _o2_payload()))


def test_extract_flbb_layout() -> None:
    packet = _meas_packet(MeasSubtype.OPTICS_FLBB, _flbb_payload())
    data = extract_flbb(packet, packet_index=5)
    assert data.packet_index == 5
    assert (data.cycle, data.profile, data.phase) == (7, 1, 2)
    assert len(data.records) == 21
    first = data.records[0]
    assert (first.p_raw, first.chl_raw, first.bb_raw) == (4, 1230, 1110)
    assert first.pres_dbar == pytest.approx(0.4)
    assert first.fluorescence_counts == pytest.approx(123.0)
    assert first.backscatter_counts == pytest.approx(111.0)
    assert data.tail == bytes(4)
    with pytest.raises(ValueError):
        extract_flbb(_meas_packet(MeasSubtype.CTD, _flbb_payload()))


def test_sample_datetime() -> None:
    assert sample_datetime(0) == datetime(2000, 1, 1, tzinfo=timezone.utc)
    moment = sample_datetime(410_000_000)
    assert (moment - datetime(2000, 1, 1, tzinfo=timezone.utc)).total_seconds() == 410_000_000


# --- association --------------------------------------------------------------


def _ctd(p_raw: int, t_raw: int = 25000, s_raw: int = 36000) -> CtdRecord:
    return CtdRecord(p_raw=p_raw, t_raw=t_raw, s_raw=s_raw,
                     pres_dbar=p_raw / 10.0, temp_c=(t_raw - 2000) / 1000.0,
                     psal=s_raw / 1000.0)


def test_group_meas_and_padding() -> None:
    packets = [
        _meas_packet(MeasSubtype.CTD, bytes(130)),
        _meas_packet(MeasSubtype.DOXY_CLASS, bytes(130)),
    ]
    dispatched = DispatchedFile(path=Path("x.sbd"), packets=tuple(packets))
    groups = group_meas(dispatched)
    assert list(groups) == [ProfileKey(cycle=7, profile=1, phase=2)]
    assert len(groups[ProfileKey(cycle=7, profile=1, phase=2)]) == 2
    assert is_padding_ctd(_ctd(0, 0, 0))
    assert not is_padding_ctd(_ctd(57))
    assert is_padding_o2(O2Record(0, 0, 0, 0, 0.0, 0.0, 0.0, -2.0))
    assert is_padding_flbb(FlbbRecord(0, 0, 0, 0.0, 0.0, 0.0))


def test_nearest_ctd() -> None:
    records = (_ctd(0, 0, 0), _ctd(57), _ctd(200))
    assert nearest_ctd((), 5.0) is None
    assert nearest_ctd(records, 5.0) is not None
    assert nearest_ctd(records, 5.0).p_raw == 57  # padding never matches
    assert nearest_ctd(records, 19.9).p_raw == 200
    assert nearest_ctd((_ctd(0, 0, 0),), 0.0) is None
    assert nearest_ctd((_ctd(0, 0, 0),), 0.0, exclude_padding=False) is not None


# --- equation smoke (no hidden state; GDAC pins follow below) -----------------


def test_equation_primitives() -> None:
    assert tphase(32.954, 3.515) == pytest.approx(29.439)
    assert phase_pcorr(29.439, 2010.0, 0.1) == pytest.approx(29.439 + 0.201)
    phase = PhaseCoefs(c0=-1.60243, c1=1.01254, c2=0.0, c3=0.0)
    assert calphase(29.64, phase) == pytest.approx(-1.60243 + 1.01254 * 29.64)
    assert ts_ratio(25.0) == pytest.approx(-0.0875756, rel=1e-6)
    assert molar_doxy(200.0, 100.0) == pytest.approx(200.0 * 44.614)
    assert doxy_umol_kg(200.0, 1.025) == pytest.approx(200.0 / 1.025)
    assert chla_ug_l(123.0, 48.0, 0.0073) == pytest.approx(0.5475)
    assert pressure_correction(25.0, 0.0, 0.00022, 0.0419) == pytest.approx(1.0)
    assert salinity_correction(25.0, 0.0, (0.0, 0.0, 0.0, 0.0), 0.0,
                               (24.4543, -67.4509, -4.8489, -0.000544),
                               0.0) == pytest.approx(1.0)


def test_coef_container_validation() -> None:
    with pytest.raises(ValueError):
        FoilCoefs(c=(0.0,) * 27, m=(0,) * 28, n=(0,) * 28)
    with pytest.raises(ValueError):
        SolubilityConsts(a=(0.0,) * 5, b=(0.0,) * 4, c0=0.0, d=(0.0,) * 4,
                         spreset=0.0, pcoef1=0.1, pcoef2=0.0, pcoef3=0.0,
                         nom_air_press=1013.25, nom_air_mix=0.20946)


def test_beta_sw_smoke() -> None:
    sea = beta_sw(25.0, 36.0, 700.0, 142.0, 0.039)
    fresh = beta_sw(25.0, 0.0, 700.0, 142.0, 0.039)
    assert sea > 0 and fresh > 0
    assert sea > fresh  # concentration fluctuation adds scattering
    assert beta_sw(25.0, 36.0, 700.0, 142.0, 0.039) < beta_sw(
        25.0, 36.0, 532.0, 142.0, 0.039)  # longer wavelength scatters less


def test_foil_single_term() -> None:
    foil = FoilCoefs(c=(2.0,) + (0.0,) * 27, m=(0,) * 28, n=(0,) * 28)
    assert foil_delta_p(29.0, 25.0, foil) == pytest.approx(2.0)


# --- label-map shape ----------------------------------------------------------


def test_label_map_key_completeness() -> None:
    assert sorted(PT_CONFIG_LABEL) == list(range(28))
    assert sorted(PM_CONFIG_LABEL) == list(range(53))
    assert sorted(PV_CONFIG_LABEL) == list(range(23))
    vec_fields = {f.name for f in dataclasses.fields(VectorTech)}
    assert set(TECH253_LABEL) == vec_fields
    half_fields = {f.name for f in dataclasses.fields(SensorHalf)}
    assert set(TECH250_LABEL) == half_fields
    assert set(TECH250_CTD_FREE_LABEL) == {f.name for f in dataclasses.fields(CtdFree)}
    assert set(TECH250_FLBB_FREE_LABEL) == {f.name for f in dataclasses.fields(FlbbFree)}
    assert sum(1 for label in PT_CONFIG_LABEL.values() if label) == 23
    assert sum(1 for label in PM_CONFIG_LABEL.values() if label) == 8


def test_coverage_needs_tables() -> None:
    report = coverage([], [])
    assert report.n_config_labels == 0
    assert report.mapped_pt == 23
    assert report.unmapped_pt == (19, 20, 23, 24, 25)
    assert report.mapped_tech253_fields == sum(
        1 for label in TECH253_LABEL.values() if label)


# --- GDAC recomputation pins (inline vectors, no IO) ---------------------------
# Provenance: INCOIS 2902091 cycle 1, files preserved at
# ``provor_bio_irsbd/ref/gdac_incois_301/`` (``incois_2902091_meta.nc`` for the
# coefficients, ``incois_BD2902091_001.nc`` profiles 2/3 for raw inputs and
# published values, ``incois_D2902091_001.nc`` for S/T matchup via linear
# interpolation and gsw potential density). Constants below were generated by
# ``scripts/probe_cts4_phase2a_gdac.py``; that script re-derives them on demand.
#
# CHLA/BBP700/beta_sw match publication to float precision (equation EXACT).
# DOXY matches to ~0.2 µmol/kg with a fitted 2-point-style residual signature
# (gain≈1.0017, offset≈+0.208 µmol/L): INCOIS applies an adjustment that no
# published authority documents, so the chain stays meta.nc-literal and the
# gap is classified PUBLICATION-RTQC (explicitly unresolved, never fitted
# into the implementation).

_WMO_2902091_PHASE = PhaseCoefs(c0=-1.60243, c1=1.01254, c2=0.0, c3=0.0)
_WMO_2902091_FOIL = FoilCoefs(
    c=(-3.60479e-06, -6.84366e-06, 0.0018392, -0.198444, 0.000812123,
       -1.22073e-06, 10.8689, -0.0709398, 0.000281047, -1.32885e-06,
       -309.375, 2.92369, -0.0222201, 0.000214634, -7.93483e-07,
       3792.41, -49.3514, 0.633521, -0.0108549, 0.000121895,
       -7.34497e-07, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    m=(1, 0, 0, 0, 1, 2, 0, 1, 2, 3, 0, 1, 2, 3, 4,
       0, 1, 2, 3, 4, 5, 0, 0, 0, 0, 0, 0, 0),
    n=(4, 5, 4, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 1, 1,
       0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
)
_WMO_2902091_SOL = SolubilityConsts(
    a=(2.00856, 3.224, 3.99063, 4.80299, 0.978188, 1.71069),
    b=(-0.00624523, -0.00737614, -0.010341, -0.00817083),
    c0=-4.88682e-07,
    d=(24.4543, -67.4509, -4.8489, -0.000544),
    spreset=0.0,
    pcoef1=0.1, pcoef2=0.00022, pcoef3=0.0419,
    nom_air_press=1013.25, nom_air_mix=0.20946,
)

_DOXY_VECTORS = [
    # (P, C1, C2, T, S, rho, o2_literal, doxy_literal, DOXY_published)
    (107.4000015258789, 42.483001708984375, 3.503999948501587, 23.65399932861328,
     36.32099914550781, 1.024752963542535, 86.78832753403533, 84.69195076441754,
     84.9195327758789),
    (197.1999969482422, 65.99600219726562, 3.313999891281128, 18.70199966430664,
     35.95600128173828, 1.0258333487353182, 0.1166625565583906, 0.1137246675614671,
     0.2737521827220917),
    (465.5, 66.0780029296875, 3.0480000972747803, 13.776000022888184,
     35.927724181692106, 1.0269701018503516, 0.10472989065612522, 0.10197949333425316,
     0.2831404209136963),
]

_OPT_VECTORS = [
    # (FLUO, BETA, T, S, CHLA_published, BBP_published, bsw_literal)
    (142.8000030517578, 146.3000030517578, 24.41900062561035, 36.444000244140625,
     0.6920400261878967, 0.0007746551418676972, 6.0124385599388766e-05),
    (56.900001525878906, 118.30000305175781, 16.613000869750977, 36.154998779296875,
     0.064970001578331, 0.0004294424725230783, 6.0564573138831525e-05),
    (57.70000076293945, 114.5999984741211, 12.289999961853027, 35.722999572753906,
     0.0708099976181984, 0.0003811852657236159, 6.100566317382489e-05),
]


def test_doxy_chain_gdac_vectors() -> None:
    for pres, c1, c2, temp, psal, rho, o2_lit, doxy_lit, doxy_pub in _DOXY_VECTORS:
        res = doxy_chain(c1, c2, temp, pres, psal, _WMO_2902091_PHASE,
                         _WMO_2902091_FOIL, _WMO_2902091_SOL, rho_kg_l=rho)
        # regression on the meta.nc-literal implementation (deterministic math)
        assert res.o2_umol_l == pytest.approx(o2_lit, rel=1e-12)
        assert res.doxy_umol_kg == pytest.approx(doxy_lit, rel=1e-12)
        # known publication gap (PUBLICATION-RTQC, unresolved): the literal
        # chain lands within 0.6 µmol/kg of the published value; the fitted
        # +0.21 µmol/L-style residual is documented, never implemented.
        assert abs(res.doxy_umol_kg - doxy_pub) < 0.6


def test_doxy_chain_intermediates_gdac_l27() -> None:
    pres, c1, c2, temp, psal, rho = _DOXY_VECTORS[0][:6]
    res = doxy_chain(c1, c2, temp, pres, psal, _WMO_2902091_PHASE,
                     _WMO_2902091_FOIL, _WMO_2902091_SOL, rho_kg_l=rho)
    assert res.tphase_deg == pytest.approx(38.97900176048279, rel=1e-12)
    assert res.delta_p == pytest.approx(83.03418757671777, rel=1e-12)
    assert res.airsat_percent == pytest.approx(40.28863814634954, rel=1e-12)
    assert res.cstar_ml_l == pytest.approx(5.922480887408314, rel=1e-12)
    assert res.molar_umol_l == pytest.approx(106.45288068956944, rel=1e-12)
    assert res.scorr == pytest.approx(0.8111709009176896, rel=1e-12)
    assert res.pcorr == pytest.approx(1.0050589567680113, rel=1e-12)


def test_chla_bbp_beta_gdac_vectors() -> None:
    for fluo, beta, temp, psal, chla_pub, bbp_pub, bsw_lit in _OPT_VECTORS:
        assert chla_ug_l(fluo, 48.0, 0.0073) == pytest.approx(chla_pub, abs=1e-6)
        assert beta_sw(temp, psal, 700.0, 142.0, 0.039) == pytest.approx(
            bsw_lit, rel=1e-12)
        assert bbp700_m1(beta, temp, psal, 49.0, 1.773e-06, 1.097,
                         700.0, 142.0, 0.039) == pytest.approx(bbp_pub, abs=1e-8)


# ---------------------------------------------------------------------------
# Phase-2A reference CSV integrity (config/metadata/provor_cts4_301_reference.csv)
# ---------------------------------------------------------------------------

_REFERENCE_CSV = (Path(__file__).resolve().parents[2] / "config" / "metadata"
                  / "provor_cts4_301_reference.csv")
#: The INCOIS 301 floats with a dedicated calibration block. 2902130 and
#: 2902131 were added at the freeze gate: they are the published WMOs for FLBB
#: serials 3043 and 3044, which the original 13-file snapshot predated.
_REFERENCE_WMOS = (2902086, 2902087, 2902088, 2902089, 2902090, 2902091,
                   2902092, 2902093, 2902113, 2902114, 2902115, 2902118,
                   2902120, 2902130, 2902131)
_REFERENCE_COLUMNS = ("scope", "wmo", "sensor_model", "sensor_serial",
                      "parameter", "coefficient", "value", "source_file",
                      "source_variable", "interpretation")


def _reference_rows() -> list[dict[str, str]]:
    with open(_REFERENCE_CSV, newline="") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames or ()) == _REFERENCE_COLUMNS
        return list(reader)


def test_reference_csv_schema_and_provenance() -> None:
    rows = _reference_rows()
    # 118 rows per float (30 float-specific + 88 family-generic), one block per
    # INCOIS 301 float in the reference. 15 floats as of the freeze gate: the
    # original 13 plus 2902130 and 2902131, found published on the live GDAC.
    n_floats = len({r["wmo"] for r in rows})
    assert n_floats == 15
    assert len(rows) == 118 * n_floats
    assert sorted({int(r["wmo"]) for r in rows}) == list(_REFERENCE_WMOS)
    by_wmo: dict[int, set[tuple[str, str]]] = {}
    for r in rows:
        assert r["scope"] in ("family_generic", "float_specific")
        # every row carries WMO + source file + variable + interpretation
        assert r["wmo"] and r["source_file"] and r["source_variable"]
        assert r["interpretation"]
        assert r["source_file"] == f"incois_{r['wmo']}_meta.nc"
        assert r["source_variable"] == "PREDEPLOYMENT_CALIB_COEFFICIENT"
        assert r["parameter"] in ("TEMP_DOXY", "DOXY", "CHLA", "BBP700")
        if r["parameter"] in ("TEMP_DOXY", "DOXY"):
            assert r["sensor_model"] == "AANDERAA_OPTODE_4330"
        else:
            assert r["sensor_model"] == "ECO_FLBB"
        assert r["sensor_serial"]
        float(r["value"])  # must parse as a number
        by_wmo.setdefault(int(r["wmo"]), set()).add(
            (r["parameter"], r["coefficient"]))
    assert all(len(v) == 118 for v in by_wmo.values())


def test_reference_csv_scope_labels() -> None:
    """Generic ⟺ numerically identical across all 13 meta.nc (audit rule)."""
    rows = _reference_rows()
    by_coef: dict[tuple[str, str], set[float]] = {}
    scopes: dict[tuple[str, str], set[str]] = {}
    for r in rows:
        key = (r["parameter"], r["coefficient"])
        by_coef.setdefault(key, set()).add(float(r["value"]))
        scopes.setdefault(key, set()).add(r["scope"])
    n_generic = n_specific = 0
    for key, values in by_coef.items():
        assert len(scopes[key]) == 1
        (scope,) = scopes[key]
        if len(values) == 1:
            assert scope == "family_generic", key
            n_generic += 1
        else:
            assert scope == "float_specific", key
            n_specific += 1
    assert (n_generic, n_specific) == (88, 30)


def test_reference_csv_agrees_with_validated_2902091_constants() -> None:
    """The CSV's 2902091 column matches the equation-validated constants."""
    vals = {(r["parameter"], r["coefficient"]): float(r["value"])
            for r in _reference_rows() if r["wmo"] == "2902091"}
    assert vals[("DOXY", "PhaseCoef0")] == _WMO_2902091_PHASE.c0
    assert vals[("DOXY", "PhaseCoef1")] == _WMO_2902091_PHASE.c1
    for i, c in enumerate(_WMO_2902091_FOIL.c):
        assert vals[("DOXY", f"c{i}")] == c
    for i, m in enumerate(_WMO_2902091_FOIL.m):
        assert vals[("DOXY", f"m{i}")] == m
    for i, n in enumerate(_WMO_2902091_FOIL.n):
        assert vals[("DOXY", f"n{i}")] == n
    for i, a in enumerate(_WMO_2902091_SOL.a):
        assert vals[("DOXY", f"A{i}")] == a
    for i, b in enumerate(_WMO_2902091_SOL.b):
        assert vals[("DOXY", f"B{i}")] == b
    assert vals[("DOXY", "C0")] == _WMO_2902091_SOL.c0
    for i, d in enumerate(_WMO_2902091_SOL.d):
        assert vals[("DOXY", f"D{i}")] == d
    assert vals[("DOXY", "Spreset")] == _WMO_2902091_SOL.spreset
    assert vals[("DOXY", "Pcoef1")] == _WMO_2902091_SOL.pcoef1
    # literals shared with test_chla_bbp_beta_gdac_vectors (same meta.nc)
    assert vals[("CHLA", "SCALE_CHLA")] == 0.0073
    assert vals[("CHLA", "DARK_CHLA")] == 48.0
    assert vals[("BBP700", "DARK_BACKSCATTERING700")] == 49.0
    assert vals[("BBP700", "SCALE_BACKSCATTERING700")] == 1.773e-06
    assert vals[("BBP700", "khi")] == 1.097
    # TEMP_DOXY thermistor coefs (reference-only; firmware-internal)
    assert vals[("TEMP_DOXY", "T0")] == 27.4829
    assert vals[("TEMP_DOXY", "T3")] == -4.46488e-09

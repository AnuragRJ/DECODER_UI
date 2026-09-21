"""Phase 6A.3: APEX APF9 engineering / technical message decoder tests.

Byte layouts are pinned against the Teledyne/Webb APF9A format
specification shipped with the Coriolis container, as re-validated
against the archived raw messages (see
``docs/phase_reports/phase6a3_engineering_map.md``).
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from argo_decoder.platforms.apex_argos.engineering import (
    APF9_ENG_1005,
    APF9_ENG_1010,
    SBE41_STATUS_BITS,
    STATUS_BITS,
    STATUS_BITS_061810,
    STATUS_BITS_071807,
    ApexEngineeringData,
    decode_auxiliary_engineering,
    decode_engineering,
    decode_engineering_message_1,
    decode_engineering_message_2,
    decode_engineering_message_3,
    decode_status_flags,
    engineering_layout_for_decoder,
    status_bits_for_decoder,
)
from argo_decoder.platforms.apex_argos.frames import (
    _MAJORITY_BYTE_OFFSETS,
    ArgosMessage,
    SelectedArgosMessage,
    build_frame,
    parse_argos_frame,
    select_redundant_messages,
)


def _msg(number: int, payload: bytes) -> SelectedArgosMessage:
    return SelectedArgosMessage(message_number=number, payload=payload, redundancy=1)


def _message1(
    *,
    sp_shift: int = 1,
    profile_id: int = 71,
    status: int = 0x8001,
    surface_pressure_cbar: int = -4,
    pump_seconds: int = 145,
) -> bytes:
    """Build a synthetic message-1 payload for the given block shift."""
    payload = bytearray(b"\xff" * 31)
    payload[0] = 3  # BLK
    payload[1:3] = (0x031B).to_bytes(2, "big")  # FLT
    payload[3] = profile_id
    payload[4] = 58  # LEN
    payload[5:7] = status.to_bytes(2, "big")
    payload[9] = 250  # VAC
    payload[10] = 163  # ABP
    payload[11] = 83  # SPP
    payload[12] = 30  # PPP2
    payload[13] = 5  # PPP
    payload[14:16] = (0x0000).to_bytes(2, "big")
    payload[16:18] = pump_seconds.to_bytes(2, "big")
    payload[18] = 145  # VQ
    payload[19] = 5  # IQ
    payload[26] = 14  # PAP
    # SP last: on 091x15 it occupies bytes 8-9, overlapping the VAC slot
    # written above, and the later write must win.
    payload[7 + sp_shift : 9 + sp_shift] = struct.pack(">h", surface_pressure_cbar)
    return bytes(payload)


def _message2(epoch: int = 1766626360, tinit: int = 352, nadj: int = 1) -> bytes:
    payload = bytearray(b"\x00" * 29)
    payload[0:4] = struct.pack("<i", epoch)
    payload[4:6] = struct.pack(">h", tinit)
    payload[6] = nadj
    return bytes(payload)


# ---------------------------------------------------------------------------
# Layout selection
# ---------------------------------------------------------------------------


def test_layouts_registered_for_known_decoders() -> None:
    assert engineering_layout_for_decoder(1005) is APF9_ENG_1005
    assert engineering_layout_for_decoder(1001) is APF9_ENG_1005
    assert engineering_layout_for_decoder(1010) is APF9_ENG_1010


def test_unknown_firmware_has_no_layout() -> None:
    """APF11 (1021/1022) uses a different format; not guessed."""
    assert engineering_layout_for_decoder(1021) is None
    assert decode_engineering([_msg(1, _message1())], decoder_id=1021) is None


def test_firmware_block_shifts_differ() -> None:
    """Confirmed against the GDAC ``_tech.nc`` reference in Phase 6A.4.

    Both firmwares use the documented block offsets; only ``SP`` moves,
    sitting one byte later on 091x15.
    """
    assert APF9_ENG_1005.sp_shift == 0
    assert APF9_ENG_1005.block_shift == 0
    assert APF9_ENG_1010.sp_shift == 1
    assert APF9_ENG_1010.block_shift == 0


# ---------------------------------------------------------------------------
# Status bitfields
# ---------------------------------------------------------------------------


def test_status_bit_table_matches_specification() -> None:
    assert STATUS_BITS["deep_profile"] == 0x0001
    assert STATUS_BITS["ascent_timeout"] == 0x0010
    assert STATUS_BITS["prelude_message"] == 0x0040
    assert STATUS_BITS["profile_id_overflow"] == 0x8000
    assert len(STATUS_BITS) == 16


def test_sbe41_status_bit_table() -> None:
    assert SBE41_STATUS_BITS["p_no_response"] == 0x0020
    assert SBE41_STATUS_BITS["pts_no_response"] == 0x2000


def test_decode_status_flags_expands_named_bits() -> None:
    flags = decode_status_flags(0x8001, STATUS_BITS)
    assert flags["deep_profile"] is True
    assert flags["profile_id_overflow"] is True
    assert flags["ascent_timeout"] is False


def test_profile_id_overflow_explains_cycle_offset() -> None:
    """STATUS bit 0x8000 is why 2902222 PRF=71 becomes cycle 327."""
    data = decode_engineering([_msg(1, _message1(profile_id=71, status=0x8001))], decoder_id=1010)
    assert data is not None
    assert data.profile_id == 71
    assert data.profile_id_overflow is True
    assert data.profile_id + 256 == 327


def test_no_overflow_leaves_profile_id_unshifted() -> None:
    data = decode_engineering([_msg(1, _message1(profile_id=2, status=0x0001))], decoder_id=1010)
    assert data is not None
    assert data.profile_id_overflow is False


# ---------------------------------------------------------------------------
# Message 1 engineering block
# ---------------------------------------------------------------------------


def test_message1_fields_decode_for_1010() -> None:
    data = decode_engineering([_msg(1, _message1(sp_shift=1))], decoder_id=1010)
    assert data is not None
    assert data.surface_pressure_dbar == pytest.approx(-0.4)
    assert data.air_bladder_pressure_counts == 163
    assert data.piston_position_surface_counts == 83
    assert data.piston_position_park_end_counts == 30
    assert data.air_pump_pulses == 14
    # SBE41 is a 32-bit long-word on this firmware (D5 p.21), so it spans
    # the two bytes this synthetic fixture had reserved for a 16-bit word
    # plus the following pair. On real 110613/090413 telemetry all four
    # bytes are zero and PMT reads 0, matching the GDAC reference.
    assert data.sbe41_status_word == 0x00000091


def test_real_1010_telemetry_has_zero_sbe41_long_word() -> None:
    """Guard the M3 change against the fixture above being unrealistic.

    Every archived 110613/090413 cycle carries four zero SBE41 bytes, so
    widening the read cannot corrupt a real value.
    """
    payload = bytearray(_message1(sp_shift=1))
    payload[14:18] = bytes(4)
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.sbe41_status_word == 0


def test_message1_fields_decode_for_1005() -> None:
    """1005 uses the documented offsets throughout."""
    payload = bytearray(b"\xff" * 31)
    payload[3] = 2
    payload[5:7] = (0x0001).to_bytes(2, "big")
    payload[7:9] = struct.pack(">h", -4)
    payload[9] = 252
    payload[16:18] = (1751).to_bytes(2, "big")
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1005)
    assert data is not None
    assert data.surface_pressure_dbar == pytest.approx(-0.4)
    assert data.vacuum_counts == 252
    assert data.pump_motor_time_s == 1751


def test_surface_pressure_is_signed_not_unsigned() -> None:
    """0xFFFC is -0.4 dbar; read unsigned it would be 6553.2 dbar."""
    data = decode_engineering([_msg(1, _message1(surface_pressure_cbar=-4))], decoder_id=1010)
    assert data is not None
    assert data.surface_pressure_dbar == pytest.approx(-0.4)


@pytest.mark.parametrize("sentinel", [0x8000, 0x8001, 0x7FFF])
def test_documented_pressure_sentinels_yield_none(sentinel: int) -> None:
    """Sentinels mean 'no value', not a real pressure.

    Only the saturation words at the ends of the signed range qualify:
    they would decode to +/-3276 dbar, which no surface offset can be.
    """
    payload = bytearray(_message1(sp_shift=1))
    payload[8:10] = sentinel.to_bytes(2, "big")
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.surface_pressure_dbar is None


@pytest.mark.parametrize(("word", "expected"), [(0xFFFE, -0.2), (0xFFFF, -0.1)])
def test_small_negative_offsets_are_measurements_not_sentinels(word: int, expected: float) -> None:
    """``0xFFFE``/``0xFFFF`` are -2 and -1 centibars, not "no value".

    They were previously treated as sentinels, which silently dropped
    five of WMO 2901304's twenty-three cycles. The GDAC reference
    publishes every cycle whose raw word is ``0xFFFE`` (1, 2, 3, 6, 9) as
    ``PRES_SurfaceOffsetNotTruncated_dbar = -0.2``.
    """
    payload = bytearray(_message1(sp_shift=1))
    payload[8:10] = word.to_bytes(2, "big")
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.surface_pressure_dbar == pytest.approx(expected)


def test_deep_profile_and_timeout_helpers() -> None:
    data = decode_engineering([_msg(1, _message1(status=0x0011))], decoder_id=1010)
    assert data is not None
    assert data.is_deep_profile is True
    assert data.hit_ascent_timeout is True


# ---------------------------------------------------------------------------
# Message 2 cycle timing
# ---------------------------------------------------------------------------


def test_epoch_is_little_endian() -> None:
    """Big-endian decoding yields a date decades away; LE is correct."""
    data = decode_engineering([_msg(2, _message2())], decoder_id=1010)
    assert data is not None
    assert data.down_time_expiry == datetime(2025, 12, 25, 1, 32, 40, tzinfo=UTC)


def test_epoch_offset_is_the_same_on_both_firmwares() -> None:
    """Message 2 is not affected by the message-1 block shift."""
    for decoder_id in (1005, 1010):
        data = decode_engineering([_msg(2, _message2())], decoder_id=decoder_id)
        assert data is not None
        assert data.down_time_expiry == datetime(2025, 12, 25, 1, 32, 40, tzinfo=UTC)


def test_implausible_epoch_is_rejected() -> None:
    """A corrupt timestamp must not become a confident date."""
    data = decode_engineering([_msg(2, _message2(epoch=12345))], decoder_id=1010)
    assert data is not None
    assert data.down_time_expiry is None


def test_telemetry_init_combines_epoch_and_offset() -> None:
    data = decode_engineering([_msg(2, _message2(tinit=352))], decoder_id=1010)
    assert data is not None
    assert data.telemetry_init_minutes == 352
    assert data.telemetry_init == datetime(2025, 12, 25, 7, 24, 40, tzinfo=UTC)


def test_telemetry_init_is_none_without_epoch() -> None:
    data = ApexEngineeringData(telemetry_init_minutes=352)
    assert data.telemetry_init is None


def test_ballast_adjustment_count() -> None:
    data = decode_engineering([_msg(2, _message2(nadj=4))], decoder_id=1010)
    assert data is not None
    assert data.n_park_ballast_adjustments == 4


# ---------------------------------------------------------------------------
# Robustness / honesty
# ---------------------------------------------------------------------------


def test_no_messages_yields_none() -> None:
    assert decode_engineering([], decoder_id=1010) is None


def test_missing_message_two_still_decodes_message_one() -> None:
    data = decode_engineering([_msg(1, _message1())], decoder_id=1010)
    assert data is not None
    assert data.messages_decoded == (1,)
    assert data.down_time_expiry is None
    assert data.vacuum_counts is not None


def test_truncated_payload_does_not_raise() -> None:
    data = decode_engineering([_msg(1, b"\x03\x01\x02")], decoder_id=1010)
    assert data is not None
    assert data.pump_motor_time_s is None


def test_as_dict_omits_unknown_fields() -> None:
    """Absent values must not appear as zeros or placeholders."""
    data = decode_engineering([_msg(1, b"\x03\x01\x02")], decoder_id=1010)
    assert data is not None
    flat = data.as_dict()
    assert "pump_motor_time_s" not in flat
    assert "down_time_expiry" not in flat


def test_messages_decoded_records_provenance() -> None:
    data = decode_engineering([_msg(1, _message1()), _msg(2, _message2())], decoder_id=1010)
    assert data is not None
    assert data.messages_decoded == (1, 2)


def test_direct_message_decoders_are_reusable() -> None:
    out = ApexEngineeringData()
    decode_engineering_message_1(_message1(), APF9_ENG_1010, out)
    decode_engineering_message_2(_message2(), APF9_ENG_1010, out)
    assert out.air_bladder_pressure_counts == 163
    assert out.n_park_ballast_adjustments == 1


# ---------------------------------------------------------------------------
# M1: firmware-aware STATUS bit tables (D4 p.21, D5 p.22)
# ---------------------------------------------------------------------------


def test_status_bits_for_decoder_selects_documented_table() -> None:
    """Decoders 1001/1005/1010 use the 061810/110613 semantics."""
    for decoder_id in (1001, 1005, 1010):
        assert status_bits_for_decoder(decoder_id) is STATUS_BITS_061810


def test_status_bits_falls_back_to_formatnotes_for_unknown_firmware() -> None:
    assert status_bits_for_decoder(None) is STATUS_BITS_071807
    assert status_bits_for_decoder(9999) is STATUS_BITS_071807


def test_documented_table_renames_sbe41_bits() -> None:
    """D4 p.21 / D5 p.22 redefine 0x0200 and 0x0400."""
    assert STATUS_BITS_061810["sbe41_exception"] == 0x0200
    assert STATUS_BITS_061810["sbe41_p_unreliable"] == 0x0400
    # The 071807 FormatNotes meanings must not leak into the new table.
    assert "sbe41_p_fail" not in STATUS_BITS_061810
    assert "sbe41_pt_fail" not in STATUS_BITS_061810


def test_reserved_bits_are_not_named_on_documented_firmware() -> None:
    """0x0800 and 0x1000 are "not used yet" -- naming them would invent meaning."""
    assert 0x0800 not in STATUS_BITS_061810.values()
    assert 0x1000 not in STATUS_BITS_061810.values()
    # They remain named under the older FormatNotes table.
    assert STATUS_BITS_071807["sbe41_pts_fail"] == 0x0800


def test_stable_bits_are_identical_across_firmware_tables() -> None:
    """The twelve unchanged bits must agree, or cycle numbering breaks."""
    stable = {
        "deep_profile",
        "shallow_water_trap",
        "sample_timeout_25min",
        "piston_full_extension",
        "ascent_timeout",
        "test_message",
        "prelude_message",
        "pressure_activation_message",
        "bad_sequence_point",
        "air_system_bypass",
        "watchdog_alarm",
        "profile_id_overflow",
    }
    for name in stable:
        assert STATUS_BITS_061810[name] == STATUS_BITS_071807[name]


def test_decoded_flags_use_firmware_table() -> None:
    """A real 1010 cycle reports the documented name, not the 071807 one."""
    data = decode_engineering([_msg(1, _message1(profile_id=71, status=0x8201))], decoder_id=1010)
    assert data is not None
    assert data.status_flags["sbe41_exception"] is True
    assert "sbe41_p_fail" not in data.status_flags
    # Cycle numbering is unaffected by the table swap.
    assert data.profile_id_overflow is True


# ---------------------------------------------------------------------------
# M3: firmware-specific SBE41 width and TELONICS byte (D5 p.21, D3 p.5)
# ---------------------------------------------------------------------------


def test_sbe41_width_is_firmware_specific() -> None:
    """061810 sends 16 bits; 110613/090413 send a 32-bit long-word."""
    assert APF9_ENG_1005.sbe41_width == 2
    assert APF9_ENG_1010.sbe41_width == 4


def test_telonics_present_only_on_decoder_1010() -> None:
    assert APF9_ENG_1005.telonics_offset is None
    assert APF9_ENG_1010.telonics_offset == 7


def test_sbe41_long_word_read_as_32_bits_on_1010() -> None:
    payload = bytearray(_message1(profile_id=5, status=0x0001))
    payload[14:18] = bytes([0x12, 0x34, 0x56, 0x78])
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.sbe41_status_word == 0x12345678


def test_sbe41_read_as_16_bits_on_1005() -> None:
    """The extra bytes belong to PMT on 061810 and must not be absorbed."""
    payload = bytearray(_message1(profile_id=5, status=0x0001))
    payload[14:18] = bytes([0x12, 0x34, 0x56, 0x78])
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1005)
    assert data is not None
    assert data.sbe41_status_word == 0x1234


def test_only_documented_sbe41_bits_are_expanded() -> None:
    """Upper 16 bits of the long-word have no documented meaning."""
    payload = bytearray(_message1(profile_id=5, status=0x0001))
    payload[14:18] = bytes([0xFF, 0xFF, 0x00, 0x20])
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.sbe41_status_flags["p_no_response"] is True
    assert len(data.sbe41_status_flags) == len(SBE41_STATUS_BITS)


def test_telonics_byte_is_preserved_not_interpreted() -> None:
    payload = bytearray(_message1(profile_id=5, status=0x0001))
    payload[7] = 0xA5
    data = decode_engineering([_msg(1, bytes(payload))], decoder_id=1010)
    assert data is not None
    assert data.telonics_status_byte == 0xA5
    # No flag expansion exists for it -- inventing one would be a guess.
    assert not hasattr(data, "telonics_status_flags")


# ---------------------------------------------------------------------------
# M4: park statistics and park-end sample (D4 pp.22-23; D3 p.6)
# ---------------------------------------------------------------------------


def _real_engineering(ptt: str, decoder_id: int) -> list[ApexEngineeringData]:
    """Decode every archived cycle for one PTT."""
    from argo_decoder.platforms.apex_argos.frames import (
        iter_argos_messages_from_payload,
        select_redundant_messages,
    )

    root = Path(__file__).resolve().parents[2] / "phase4_reference/raw/raw-files" / ptt
    out = []
    for raw in sorted(root.glob("*.txt")):
        selected = select_redundant_messages(
            iter_argos_messages_from_payload(raw.read_bytes(), frame_length=31)
        )
        data = decode_engineering(selected, decoder_id=decoder_id)
        if data is not None:
            out.append(data)
    return out


@pytest.mark.parametrize(
    ("cycle", "t_mean", "p_mean"),
    [(327, 2.750, 1000.9), (328, 2.797, 1005.4), (329, 2.796, 1006.5)],
)
def test_park_statistics_match_gdac_mc296(cycle: int, t_mean: float, p_mean: float) -> None:
    """TMEAN/PMEAN reproduce the reference MC 296 triplet exactly."""
    for data in _real_engineering("152389", 1010):
        number = (data.profile_id or 0) + (256 if data.profile_id_overflow else 0)
        if number != cycle:
            continue
        assert data.park_temperature_mean == pytest.approx(t_mean, abs=1e-3)
        assert data.park_pressure_mean == pytest.approx(p_mean, abs=1e-3)
        return
    pytest.fail(f"cycle {cycle} not decoded")


@pytest.mark.parametrize(
    ("cycle", "temp", "psal", "pres"),
    [(327, 2.731, 34.548, 1004.2), (328, 2.780, 34.532, 1004.2), (329, 2.786, 34.531, 1005.4)],
)
def test_park_end_sample_matches_gdac_mc290(
    cycle: int, temp: float, psal: float, pres: float
) -> None:
    """PRKT/PRKS/PRKP reproduce the reference MC 290 triplet exactly."""
    for data in _real_engineering("152389", 1010):
        number = (data.profile_id or 0) + (256 if data.profile_id_overflow else 0)
        if number != cycle:
            continue
        assert data.park_end_temperature == pytest.approx(temp, abs=1e-3)
        assert data.park_end_salinity == pytest.approx(psal, abs=1e-3)
        assert data.park_end_pressure == pytest.approx(pres, abs=1e-3)
        return
    pytest.fail(f"cycle {cycle} not decoded")


def test_park_sample_offset_is_firmware_specific() -> None:
    """110613/090413 prepend fields before the park sample (D3 p.6).

    Firmware 061810 puts the park-end T/S/P triplet at the very start of
    the message-3 payload. Measured against the GDAC ``MC=290`` block for
    WMO 2901304: offset 0 reproduces 20 of 23 cycles exactly (the other
    three transmit all-filler), while the previously assumed offset 1
    reproduces none and yields non-physical values such as -818 dbar and
    salinity 44.
    """
    assert APF9_ENG_1005.park_sample_offset == 0
    assert APF9_ENG_1010.park_sample_offset == 4


def test_park_statistics_are_physically_plausible_on_1005() -> None:
    """Firmware 061810 must decode park pressure near the 1000 dbar park."""
    seen = 0
    for data in _real_engineering("102510", 1005):
        if data.park_pressure_mean is None:
            continue
        seen += 1
        assert -10.0 < data.park_pressure_mean < 2100.0
    assert seen > 10


def test_salinity_uses_the_profile_sentinel_band() -> None:
    """0x86F4 is a valid salinity (34.548), not a negative 2's-complement."""
    payload = bytearray(b"\xff" * 30)
    payload[4:6] = (0x0AAB).to_bytes(2, "big")
    payload[6:8] = (0x86F4).to_bytes(2, "big")
    payload[8:10] = (0x273A).to_bytes(2, "big")
    data = ApexEngineeringData()
    decode_engineering_message_3(bytes(payload), APF9_ENG_1010, data)
    assert data.park_end_temperature == pytest.approx(2.731, abs=1e-3)
    assert data.park_end_salinity == pytest.approx(34.548, abs=1e-3)
    assert data.park_end_pressure == pytest.approx(1004.2, abs=1e-3)


# ---------------------------------------------------------------------------
# M5: auxiliary engineering block (D3 p.7; D2 rows 228-237)
# ---------------------------------------------------------------------------


def test_auxiliary_block_layout_is_firmware_specific() -> None:
    """D2 row 232 lists VAC for 061810; 110613/090413 omit it."""
    assert APF9_ENG_1005.aux_has_vacuum is True
    assert APF9_ENG_1010.aux_has_vacuum is False


def test_auxiliary_block_decodes_1010_layout() -> None:
    tail = bytes([0x00, 0x06, 0xFF, 0x98, 0x06, 0x04, 0x2C, 0x51, 0x61, 0x63, 0x64, 0xFF])
    data = ApexEngineeringData()
    decode_auxiliary_engineering(tail, APF9_ENG_1010, data)
    assert data.pressure_divergence_dbar == pytest.approx(0.6)
    assert data.profile_init_offset_minutes == -104
    assert data.park_end_vacuum_counts is None
    assert data.n_descent_pressure_marks == 6
    assert data.descent_pressure_marks_bar == (4, 44, 81, 97, 99, 100)


def test_auxiliary_block_decodes_1005_layout_with_vacuum() -> None:
    tail = bytes([0x00, 0x06, 0xFF, 0x98, 0x53, 0x06, 0x04, 0x29, 0x48, 0x59, 0x5C, 0x5D])
    data = ApexEngineeringData()
    decode_auxiliary_engineering(tail, APF9_ENG_1005, data)
    assert data.pressure_divergence_dbar == pytest.approx(0.6)
    assert data.profile_init_offset_minutes == -104
    assert data.park_end_vacuum_counts == 83
    assert data.n_descent_pressure_marks == 6
    assert data.descent_pressure_marks_bar == (4, 41, 72, 89, 92, 93)


def test_auxiliary_filler_is_not_mistaken_for_data() -> None:
    """0xFF is the documented filler byte, not a measurement."""
    data = ApexEngineeringData()
    decode_auxiliary_engineering(bytes([0x00, 0x06, 0x00, 0x00, 0xFF]), APF9_ENG_1010, data)
    assert data.n_descent_pressure_marks is None
    assert data.descent_pressure_marks_bar == ()


def test_truncated_auxiliary_block_degrades_gracefully() -> None:
    data = ApexEngineeringData()
    decode_auxiliary_engineering(b"\x00\x06", APF9_ENG_1010, data)
    assert data.pressure_divergence_dbar == pytest.approx(0.6)
    assert data.profile_init_offset_minutes is None
    assert data.n_descent_pressure_marks is None


def test_descent_marks_increase_monotonically_on_real_data() -> None:
    """A physical check: the float descends, so marks must not decrease."""
    from argo_decoder.platforms.apex_argos.frames import (
        iter_argos_messages_from_payload,
        select_redundant_messages,
    )
    from argo_decoder.platforms.apex_argos.profile import decode_profile, layout_for_decoder

    root = Path(__file__).resolve().parents[2] / "phase4_reference/raw/raw-files/152389"
    seen = 0
    for raw in sorted(root.glob("*.txt")):
        selected = select_redundant_messages(
            iter_argos_messages_from_payload(raw.read_bytes(), frame_length=31)
        )
        decoded = decode_profile(selected, layout=layout_for_decoder(1010))
        data = decode_engineering(selected, decoder_id=1010)
        assert data is not None
        decode_auxiliary_engineering(decoded.auxiliary_bytes, APF9_ENG_1010, data)
        marks = data.descent_pressure_marks_bar
        if not marks:
            continue
        seen += 1
        assert list(marks) == sorted(marks)
    assert seen >= 2


def test_self_test_engineering_is_not_mistaken_for_a_cycle() -> None:
    """A saturated engineering block must not be numbered as a real cycle.

    The APF9 raises the profile-id sentinel both on its first real cycle
    and on the deployment self test. Only the self test reports saturated
    counters and a nonsensical surface offset -- WMO 2901304's 2011-02-13
    transmission carries a 256.0 dbar offset with piston and air-bladder
    counts of 254/255 -- so the two are told apart on the physics. The
    real cycle 1 GDAC publishes for that float (park piston 15, pump
    11972 s) is absent from the raw archive entirely, and numbering the
    self test "cycle 1" would publish saturated counters as science.
    """
    from argo_decoder.platforms.apex_argos.decoder import _engineering_is_measured

    def _block(*, cbar: int, abp: int, piston_surface: int) -> bytes:
        payload = bytearray(_message1(sp_shift=0, surface_pressure_cbar=cbar))
        payload[10] = abp
        payload[11] = piston_surface
        return bytes(payload)

    self_test = decode_engineering(
        [_msg(1, _block(cbar=2560, abp=255, piston_surface=254))], decoder_id=1005
    )
    assert not _engineering_is_measured(self_test)

    real_cycle = decode_engineering(
        [_msg(1, _block(cbar=-2, abp=138, piston_surface=66))], decoder_id=1005
    )
    assert _engineering_is_measured(real_cycle)
    assert real_cycle is not None
    assert real_cycle.surface_pressure_dbar == pytest.approx(-0.2)


def test_transmission_split_keeps_the_pass_header_with_its_messages() -> None:
    """A satellite pass header belongs to the burst it introduces.

    Format-1 dumps interleave pass headers ("02602 102525 129 31 L 2
    <date> <lat> <lon> ...") with the messages received during that pass.
    Splitting a multi-transmission file on the message timestamps alone
    leaves a header stranded at the end of the previous burst, taking its
    Argos fix with it. On WMO 2901304 that lost cycle 1's 02:12:23 fix,
    which is the position the reference publishes as the profile JULD.
    """
    from argo_decoder.platforms.apex_argos.frames import (
        parse_argos_fixes,
        split_transmission_text,
    )

    header = "02602 102525   9 31 M"

    def pass_line(stamp: str, lat: str) -> str:
        return f"02602 102525 129 31 L 2 {stamp} {lat}   57.577  0.000 401645288"

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    text = "\n".join(
        [
            header,
            pass_line("2011-02-13 03:53:14", "-55.500"),
            message("2011-02-13 03:53:14"),
            # The second burst's pass header precedes its first message.
            pass_line("2011-02-14 02:12:23", "-55.556"),
            message("2011-02-14 02:05:29"),
            message("2011-02-14 02:46:30"),
        ]
    )
    parts = split_transmission_text(text.encode("ascii"))
    assert len(parts) == 2
    second = [f.at.strftime("%H:%M:%S") for f in parse_argos_fixes(parts[1])]
    assert "02:12:23" in second
    assert "02:12:23" not in [f.at.strftime("%H:%M:%S") for f in parse_argos_fixes(parts[0])]


def test_volatile_engineering_bytes_use_per_byte_majority() -> None:
    """Analogue channels are re-sampled per transmission, so copies differ.

    Whole-frame selection picks one arbitrary copy, which reproduced the
    GDAC reference on only 13 of 23 cycles for the profile-depth current.
    Taking the majority per byte lifts that to 22/23 and leaves the
    stable fields untouched.

    Built here as three copies that agree everywhere except offset 23,
    where the minority value is the one whole-frame selection would keep.
    """
    frames = [_frame_with_byte(23, value) for value in (0xC0, 0xBD, 0xBD)]
    selected = select_redundant_messages(frames)
    assert len(selected) == 1
    assert selected[0].payload[23] == 0xBD


def test_majority_leaves_unanimous_bytes_unchanged() -> None:
    """A byte identical in every copy is its own majority."""
    frames = [_frame_with_byte(23, 0xBD) for _ in range(3)]
    selected = select_redundant_messages(frames)
    assert selected[0].payload[23] == 0xBD


def test_majority_is_scoped_to_the_analogue_engineering_bytes() -> None:
    """Stable fields keep whole-frame selection semantics.

    Offset 16-17 is the pump-motor timer, a counter rather than an
    analogue reading, so it is deliberately outside the majority set.
    """
    assert 23 in _MAJORITY_BYTE_OFFSETS
    assert 9 in _MAJORITY_BYTE_OFFSETS
    assert 16 not in _MAJORITY_BYTE_OFFSETS
    assert 17 not in _MAJORITY_BYTE_OFFSETS


def _frame_with_byte(offset: int, value: int) -> ArgosMessage:
    """A CRC-valid message-1 frame whose payload[offset] is ``value``."""
    payload = bytearray(29)
    payload[0] = 1
    payload[offset] = value
    return parse_argos_frame(build_frame(1, bytes(payload), frame_length=31), frame_length=31)


def test_out_of_order_passes_are_grouped_by_time_not_by_file_order() -> None:
    """Bursts are decided on sorted reception times, never on file order.

    A ground-station dump is a time window whose passes are written in
    arbitrary order. Two rules fail on real archives:

    * differencing consecutive lines fires on every backward step, so one
      burst is reported many times over;
    * differencing against a running maximum is defeated when the newest
      pass comes first -- the high-water mark is saturated on line 1 and
      nothing can exceed it again. WMO 2902206's ``..._360.txt`` opens
      with its newest pass and steps backwards on 262 of 293 boundaries,
      so that rule found *zero* cuts and merged three surfacings.

    Coriolis differences ``sort(unique(dates))``
    (``read_argos_file_fmt1_rough.m:99`` feeding
    ``split_argos_file.m:47-51``). Sorting first is what makes the answer
    independent of the order the ground station happened to write.

    Here the file opens with its newest pass, then reports two older
    surfacings. Three distinct surfacings must come back, each contiguous
    in time.
    """
    from argo_decoder.platforms.apex_argos.frames import (
        split_transmission_text,
        transmission_time_span,
    )

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    text = "\n".join(
        [
            "02602 152389   9 31 M",
            # Newest pass first -- this is what defeats a running maximum.
            message("2026-01-14 07:17:42"),
            message("2026-01-14 08:02:11"),
            # An older surfacing, reported afterwards.
            message("2026-01-11 17:32:16"),
            message("2026-01-11 17:35:18"),
            # A third, between the other two in time.
            message("2026-01-13 17:41:24"),
            message("2026-01-13 17:55:20"),
        ]
    )
    parts = split_transmission_text(text.encode("ascii"))
    assert len(parts) == 3
    spans = [transmission_time_span(part) for part in parts]
    assert all(span is not None for span in spans)
    # Returned oldest-first, and no burst overlaps the next.
    days = [span[0].strftime("%m-%d") for span in spans if span is not None]
    assert days == ["01-11", "01-13", "01-14"]
    for earlier, later in pairwise(spans):
        assert earlier is not None and later is not None
        assert earlier[1] < later[0]


def test_receptions_within_one_surfacing_stay_together() -> None:
    """Reordering *inside* a burst must not manufacture a split.

    A float surfaces for a few hours, so a real burst spans well under
    the 6 h gap: the three bursts of WMO 2902222's 2026-01-14 file span
    0.1 h, 0.2 h and 7.4 h. Passes reported out of order within that
    window are one transmission.
    """
    from argo_decoder.platforms.apex_argos.frames import split_transmission_text

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    text = "\n".join(
        [
            "02602 152389   9 31 M",
            message("2026-01-14 09:30:00"),
            message("2026-01-14 07:17:42"),  # earlier, reported later
            message("2026-01-14 08:02:11"),
            message("2026-01-14 10:15:00"),
        ]
    )
    assert len(split_transmission_text(text.encode("ascii"))) == 1


def test_named_cycle_files_are_still_split_when_they_hold_two_bursts() -> None:
    """The file name says which cycle it was filed under, not what it holds.

    WMO 2902222's ``..._328.txt`` spans 2026-01-03 to 01-11 and carries a
    second surfacing. Trusting the name and merging them put
    ``JULD_LAST_MESSAGE`` seven days late.
    """
    from argo_decoder.domain.frames import CycleData, RawFrame
    from argo_decoder.platforms.apex_argos.decoder import _split_multi_transmission_cycles

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    text = "\n".join(
        [
            "02602 152389   9 31 M",
            message("2026-01-04 06:10:53"),
            message("2026-01-04 06:11:37"),
            message("2026-01-11 17:32:00"),
            message("2026-01-11 17:35:00"),
        ]
    ).encode("ascii")

    # ``received_at`` is the date discovery read off the file name.
    cycle = CycleData(wmo=2902222, cycle=328)
    cycle.frames.append(
        RawFrame(
            payload=text,
            cycle=328,
            profile=328,
            received_at=datetime(2026, 1, 11, tzinfo=UTC),
        )
    )
    out = _split_multi_transmission_cycles([cycle], frame_length=31)

    assert len(out) == 2
    # The name stays with the burst the file is named for; the extra one
    # falls through to telemetry-based recovery under a provisional key.
    keys = sorted(c.cycle for c in out)
    assert 328 in keys
    assert any(k < 0 for k in keys)
    # The named burst is chosen by *time*: the file is named for 01-11, so
    # the 01-11 surfacing keeps the number. Handing it to the first burst
    # instead is what dated WMO 2902206 cycle 360 five days early.
    named = next(c for c in out if c.cycle == 328)
    assert b"2026-01-11" in named.frames[0].payload
    assert b"2026-01-04" not in named.frames[0].payload


def test_named_cycle_goes_to_the_dominant_burst_on_the_named_date() -> None:
    """A stray reception on the named date must not steal the number.

    WMO 2902201's ``..._2026-01-04_..._359.txt`` opens with a single
    reception at 05:41 and carries the real surfacing from 12:33 to
    22:43 -- both on the named date. Giving the cycle to the fragment
    left the actual profile unresolved and dropped it from the output.
    """
    from argo_decoder.domain.frames import CycleData, RawFrame
    from argo_decoder.platforms.apex_argos.decoder import _split_multi_transmission_cycles

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    # Mirrors the real file: the 05:41 fragment is ~6.9 h before the
    # surfacing, so it is a separate burst on the *same* named date, and
    # a later pass follows days afterwards.
    text = "\n".join(
        [
            "02602 152399   9 31 M",
            message("2026-01-04 05:41:33"),  # lone fragment
            message("2026-01-04 12:33:21"),  # the real surfacing
            message("2026-01-04 13:10:02"),
            message("2026-01-04 17:50:11"),
            message("2026-01-08 07:39:40"),
        ]
    ).encode("ascii")

    cycle = CycleData(wmo=2902201, cycle=359)
    cycle.frames.append(
        RawFrame(
            payload=text,
            cycle=359,
            profile=359,
            received_at=datetime(2026, 1, 4, tzinfo=UTC),
        )
    )
    out = _split_multi_transmission_cycles([cycle], frame_length=31)

    assert len(out) == 3
    named = next(c for c in out if c.cycle == 359)
    assert b"12:33:21" in named.frames[0].payload
    assert b"05:41:33" not in named.frames[0].payload


def test_named_burst_falls_back_to_the_newest_without_a_file_date() -> None:
    """No date in the name means no date comparison; take the newest."""
    from argo_decoder.domain.frames import CycleData, RawFrame
    from argo_decoder.platforms.apex_argos.decoder import _split_multi_transmission_cycles

    def message(stamp: str) -> str:
        return f"      {stamp}  1         C0           01           02           1C"

    text = "\n".join(
        [
            "02602 152389   9 31 M",
            message("2026-01-04 06:10:53"),
            message("2026-01-11 17:32:00"),
        ]
    ).encode("ascii")

    cycle = CycleData(wmo=2902222, cycle=328)
    cycle.frames.append(RawFrame(payload=text, cycle=328, profile=328, received_at=None))
    out = _split_multi_transmission_cycles([cycle], frame_length=31)

    named = next(c for c in out if c.cycle == 328)
    assert b"2026-01-11" in named.frames[0].payload


# ---------------------------------------------------------------------------
# VAC / ABP live in message 3 on firmware 110613/091x15
# ---------------------------------------------------------------------------


def test_message_3_carries_vacuum_and_air_bladder_on_1010() -> None:
    """``VAC``/``ABP`` head message 3 on the 091x15 family.

    APF9A 110613 manual p.25 ("Data Message 3 - N") lists ``2 VAC`` and
    ``3 ABP`` in a table whose bytes 0/1 are ``CRC``/``MSG``, so they are
    payload bytes 0 and 1. Coriolis reads the same pair as fields 1-2 of
    ``tabNbBits = [1 1 2 2 2 2]`` at ``firstBit = 17``
    (``decode_data_apx_10.m:784``).
    """
    from argo_decoder.platforms.apex_argos.engineering import (
        APF9_ENG_1010,
        ApexEngineeringData,
        decode_engineering_message_3,
    )

    payload = bytes([80, 123]) + bytes(28)
    out = ApexEngineeringData(decoder_id=1010)
    decode_engineering_message_3(payload, APF9_ENG_1010, out)

    assert out.msg3_vacuum_counts == 80
    assert out.msg3_air_bladder_counts == 123


def test_message_3_head_is_not_read_on_1005() -> None:
    """061810 has no ``VAC``/``ABP`` prefix in message 3.

    Its message-3 table opens directly with the park sample, so reading a
    prefix there would consume hydrographic bytes.
    """
    from argo_decoder.platforms.apex_argos.engineering import (
        APF9_ENG_1005,
        ApexEngineeringData,
        decode_engineering_message_3,
    )

    out = ApexEngineeringData(decoder_id=1005)
    decode_engineering_message_3(bytes([80, 123]) + bytes(28), APF9_ENG_1005, out)

    assert out.msg3_vacuum_counts is None
    assert out.msg3_air_bladder_counts is None


def test_message_3_prefix_does_not_disturb_the_park_sample() -> None:
    """The park sample keeps its own offset on both families.

    ``park_sample_offset`` already reserves the four prefix bytes on
    1010, so adding the VAC/ABP read must leave the T/S/P triplet where
    it was.
    """
    from argo_decoder.platforms.apex_argos.engineering import (
        APF9_ENG_1010,
        ApexEngineeringData,
        decode_engineering_message_3,
    )

    # bytes 0..3 = VAC, ABP, PMT(2); park sample T/S/P starts at byte 4.
    payload = bytes([80, 123, 0, 0]) + bytes([0x0A, 0xAB, 0x08, 0x6F, 0x27, 0x2C])
    payload += bytes(31 - len(payload))
    out = ApexEngineeringData(decoder_id=1010)
    decode_engineering_message_3(payload, APF9_ENG_1010, out)

    assert out.msg3_vacuum_counts == 80
    assert out.park_end_temperature is not None
    assert out.park_end_pressure is not None

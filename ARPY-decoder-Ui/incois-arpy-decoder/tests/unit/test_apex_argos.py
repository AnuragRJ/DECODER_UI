"""Unit tests for the APEX ARGOS Phase 4 parser."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from argo_decoder.config import DecoderConfig, get_decoder_table
from argo_decoder.domain.frames import CycleData, RawFrame
from argo_decoder.metadata.models import FloatInfo, FloatMeta
from argo_decoder.platforms import get_decoder
from argo_decoder.platforms.apex_argos.frames import (
    build_frame,
    check_crc,
    combine_bits,
    compute_crc,
    iter_argos_messages_from_payload,
    select_redundant_messages,
)
from argo_decoder.platforms.apex_argos.profile import (
    APF9_CTD_19,
    APF9_CTD_23,
    APF11_CTD_24,
    decode_profile,
)


def _put_u16(buf: bytearray, offset: int, value: int) -> None:
    buf[offset : offset + 2] = int(value).to_bytes(2, "big")


def _apf9_1010_messages(profile_length: int = 2) -> list[bytes]:
    msg1_payload = bytearray(29)
    msg1_payload[3] = 72
    msg1_payload[4] = profile_length
    msg3_payload = bytearray(29)
    profile_offset = 10
    _put_u16(msg3_payload, profile_offset + 0, 12_345)
    _put_u16(msg3_payload, profile_offset + 2, 34_567)
    _put_u16(msg3_payload, profile_offset + 4, 10_000)
    _put_u16(msg3_payload, profile_offset + 6, 12_346)
    _put_u16(msg3_payload, profile_offset + 8, 34_568)
    _put_u16(msg3_payload, profile_offset + 10, 10_010)
    return [build_frame(1, msg1_payload), build_frame(3, msg3_payload)]


def _apf11_1021_messages(profile_length: int = 2) -> list[bytes]:
    msg10_payload = bytearray(29)
    msg10_payload[5] = profile_length
    msg12_payload = bytearray(29)
    profile_offset = 5
    _put_u16(msg12_payload, profile_offset + 0, 12_345)
    _put_u16(msg12_payload, profile_offset + 2, 10_000)
    _put_u16(msg12_payload, profile_offset + 4, 34_567)
    _put_u16(msg12_payload, profile_offset + 6, 12_346)
    _put_u16(msg12_payload, profile_offset + 8, 10_010)
    _put_u16(msg12_payload, profile_offset + 10, 34_568)
    return [build_frame(10, msg10_payload), build_frame(12, msg12_payload)]


def test_apex_crc_matches_matlab_reference() -> None:
    frame = bytes.fromhex(
        "8F 00 08 1C 8E 47 23 91 48 A4 D2 E9 74 3A 1D 0E "
        "07 03 81 C0 60 30 98 4C 26 93 49 24 92 C9 64 B2"
    )
    assert compute_crc(frame[1:]) == 0x8F
    assert check_crc(frame)


def test_iter_argos_messages_accepts_binary_and_hex_text() -> None:
    frame = _apf9_1010_messages()[0]
    assert iter_argos_messages_from_payload(frame)[0].message_number == 1
    parsed = iter_argos_messages_from_payload(("prefix " + frame.hex().upper()).encode("ascii"))
    assert parsed[0].raw == frame


def test_parse_cls_format1_multiline_message_expands_occurrence() -> None:
    frame = _apf9_1010_messages()[0]
    hex_tokens = [f"{value:02X}" for value in frame]
    first = "      2026-01-04 12:33:21  2         " + "           ".join(hex_tokens[:4])
    continuations = [
        "                                     " + "           ".join(hex_tokens[start : start + 4])
        for start in range(4, len(hex_tokens), 4)
    ]
    parsed = iter_argos_messages_from_payload((first + "\n" + "\n".join(continuations)).encode())
    assert len(parsed) == 2
    assert parsed[0].raw == frame
    assert parsed[0].received_at == datetime(2026, 1, 4, 12, 33, 21, tzinfo=UTC)


def test_select_redundant_messages_keeps_most_common_crc_clean_payload() -> None:
    frame1, frame3 = _apf9_1010_messages()
    duplicate = iter_argos_messages_from_payload(frame3)[0]
    messages = iter_argos_messages_from_payload(frame1)
    messages.extend([duplicate, duplicate])
    selected = select_redundant_messages(messages)
    by_num = {msg.message_number: msg for msg in selected}
    assert by_num[1].redundancy == 1
    assert by_num[3].redundancy == 2


def test_combine_bits_majority_vote() -> None:
    assert combine_bits([b"\xf0", b"\xf0", b"\x00"]) == b"\xf0"


def test_decode_apf9_1010_profile_from_selected_messages() -> None:
    messages = []
    for frame in _apf9_1010_messages():
        messages.extend(iter_argos_messages_from_payload(frame))
    decoded = decode_profile(select_redundant_messages(messages), layout=APF9_CTD_19)
    assert decoded.expected_profile_length == 2
    assert decoded.profile_number == 72
    # The 8-bit counter is unwrapped by the caller, which knows how long
    # this float has been deployed; the layout no longer adds a blanket
    # +256 that would mislabel a float still in its first 256 cycles.
    assert decoded.output_cycle_number == 72
    assert decoded.pressure_dbar == [1000.0, 1001.0]
    assert decoded.temperature_deg_c == [12.345, 12.346]
    assert decoded.salinity_psu == [34.567, 34.568]

    # A float past its first counter period supplies the roll-over.
    wrapped = decode_profile(
        select_redundant_messages(messages), layout=APF9_CTD_19, cycle_number_wrap=256
    )
    assert wrapped.output_cycle_number == 328


def test_decode_apf11_1021_profile_from_selected_messages() -> None:
    messages = []
    for frame in _apf11_1021_messages():
        messages.extend(iter_argos_messages_from_payload(frame))
    decoded = decode_profile(select_redundant_messages(messages), layout=APF11_CTD_24)
    assert decoded.expected_profile_length == 2
    assert decoded.pressure_dbar == [1000.0, 1001.0]
    assert decoded.temperature_deg_c == [12.345, 12.346]
    assert decoded.salinity_psu == [34.567, 34.568]


def test_older_apf9_1005_layout_remains_decodable() -> None:
    msg1_payload = bytearray(29)
    msg1_payload[3] = 2
    msg1_payload[4] = 1
    msg3_payload = bytearray(29)
    profile_offset = 6
    _put_u16(msg3_payload, profile_offset + 0, 12_345)
    _put_u16(msg3_payload, profile_offset + 2, 34_567)
    _put_u16(msg3_payload, profile_offset + 4, 10_000)
    messages = []
    for frame in (build_frame(1, msg1_payload), build_frame(3, msg3_payload)):
        messages.extend(iter_argos_messages_from_payload(frame))
    decoded = decode_profile(select_redundant_messages(messages), layout=APF9_CTD_23)
    # Firmware 061810 has no counter roll-over, so the layout applies no
    # correction and the transmitted id passes through unchanged. The -1
    # this test used to expect was WMO 2901339's *deployment* offset,
    # which now lives in the registry as ``np0`` and is applied by the
    # decoder, not by the profile layout.
    assert APF9_CTD_23.cycle_number_wrap == 0
    assert decoded.profile_number == 2
    assert decoded.output_cycle_number == 2
    assert decoded.pressure_dbar == [1000.0]
    assert decoded.temperature_deg_c == [12.345]
    assert decoded.salinity_psu == [34.567]


def test_apex_argos_decoder_registered_and_builds_dataset() -> None:
    info = FloatInfo.model_validate(
        {
            "WMO": 2902222,
            "PTT": "152389",
            "FLOAT_TYPE": "APEX",
            "DECODER_VERSION": "091615",
            "DECODER_ID": 1010,
            "FRAME_LENGTH": 31,
            "CYCLE_LENGTH": 240,
            "DRIFT_SAMPLING_PERIOD": 240.0,
            "LAUNCH_DATE": datetime(2017, 1, 20, 8, 44, tzinfo=UTC),
            "LAUNCH_LON": 68.1,
            "LAUNCH_LAT": -53.0,
            "REFERENCE_DAY": datetime(2017, 1, 20, tzinfo=UTC).date(),
        }
    )
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "PLATFORM_TYPE": "APEX",
            "PLATFORM_MAKER": "WRC",
            "DATA_CENTRE": "IN",
        }
    )
    decoder = get_decoder(info, meta, DecoderConfig())
    assert type(decoder).__name__ == "ApexArgosDecoder"
    received_at = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    cycle = CycleData(
        wmo=2902222,
        cycle=327,
        frames=[
            RawFrame(payload=frame, cycle=327, profile=327, received_at=received_at)
            for frame in _apf9_1010_messages()
        ],
    )
    result = decoder.decode_float(2902222, info, meta, [cycle])
    assert not result.errors
    assert 328 in result.mono_profile_datasets
    ds = result.mono_profile_datasets[328]
    assert ds.attrs["decoder"] == "apex_argos"
    np.testing.assert_allclose(ds["PRES"].values, np.array([1000.0, 1001.0]))


def test_decoder_table_contains_phase4_apex_argos_rows() -> None:
    table = get_decoder_table()
    assert table.by_platform_version("APEX", "61810").decoder_id == 1005
    assert table.by_platform_version("APEX", "61810").profile_class == "apf9_ctd_23"
    assert table.by_platform_version("APEX", "091615").decoder_id == 1010
    assert table.by_platform_version("APEX", "091615").profile_class == "apf9_ctd_19"
    assert table.by_platform_version("APEX", "2.8.0.A").decoder_id == 1021


def test_duplicate_output_cycle_keeps_richer_argos_profile() -> None:
    info = FloatInfo.model_validate(
        {
            "WMO": 2902222,
            "PTT": "152389",
            "FLOAT_TYPE": "APEX",
            "DECODER_VERSION": "091615",
            "DECODER_ID": 1010,
            "FRAME_LENGTH": 31,
            "CYCLE_LENGTH": 240,
            "DRIFT_SAMPLING_PERIOD": 240.0,
            "LAUNCH_DATE": datetime(2017, 1, 20, 8, 44, tzinfo=UTC),
            "LAUNCH_LON": 68.1,
            "LAUNCH_LAT": -53.0,
            "REFERENCE_DAY": datetime(2017, 1, 20, tzinfo=UTC).date(),
        }
    )
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "PLATFORM_TYPE": "APEX",
            "PLATFORM_MAKER": "WRC",
            "DATA_CENTRE": "IN",
        }
    )
    decoder = get_decoder(info, meta, DecoderConfig())
    # Received ~9 years after launch at a 240 h cycle, i.e. well past the
    # 256-cycle counter roll-over, so the transmitted id 72 unwraps to
    # 328. Without a realistic reception time the roll-over derives to
    # zero and this fixture would not exercise unwrapping at all.
    received = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
    cycles = [
        CycleData(
            wmo=2902222,
            cycle=10,
            frames=[
                RawFrame(payload=frame, cycle=10, profile=10, received_at=received)
                for frame in _apf9_1010_messages(1)
            ],
        ),
        CycleData(
            wmo=2902222,
            cycle=11,
            frames=[
                RawFrame(payload=frame, cycle=11, profile=11, received_at=received)
                for frame in _apf9_1010_messages(2)
            ],
        ),
    ]

    result = decoder.decode_float(2902222, info, meta, cycles)

    ds = result.mono_profile_datasets[328]
    assert ds.sizes["N_LEVELS"] == 2
    assert ds.attrs["raw_cycle_number"] == 11
    assert ds.attrs["superseded_raw_cycle_number"] == 10


def test_counter_wrap_is_derived_from_deployment_not_hardcoded() -> None:
    """An 1010 float inside its first 256 cycles must not gain +256.

    Regression for WMO 2901328, which decoded as cycles 257-355 against
    GDAC's 1-98 because the roll-over was a layout constant rather than a
    property of the float's own history.
    """
    from argo_decoder.platforms.apex_argos.profile import cycle_number_wrap_for

    # Two months after launch at a 240 h cycle: ~6 cycles, no roll-over.
    assert cycle_number_wrap_for(APF9_CTD_19, elapsed_hours=60 * 24, cycle_length_hours=240.0) == 0
    # Nine years in: 328 cycles, one roll-over.
    assert (
        cycle_number_wrap_for(APF9_CTD_19, elapsed_hours=3280 * 24, cycle_length_hours=240.0) == 256
    )
    # Two roll-overs.
    assert (
        cycle_number_wrap_for(APF9_CTD_19, elapsed_hours=5200 * 24, cycle_length_hours=240.0) == 512
    )
    # Unknown deployment must not silently shift every cycle.
    assert cycle_number_wrap_for(APF9_CTD_19, elapsed_hours=None, cycle_length_hours=240.0) == 0
    assert cycle_number_wrap_for(APF9_CTD_19, elapsed_hours=3280 * 24, cycle_length_hours=None) == 0
    # A layout without a rolling counter keeps its static offset.
    assert (
        cycle_number_wrap_for(APF9_CTD_23, elapsed_hours=5200 * 24, cycle_length_hours=240.0) == 0
    )

"""Unit tests: ARVOR-I technical product model (Phase 4A).

Covers the Coriolis emitter ports in ``arvor_i_tech.py``: label lookup
(including the +10000 TECH_AUX_SURFACE duplication), the two time
formatters (statement-level ports of format_time_hhmm/mmss_dec_argo.m),
num2str semantics, the store_tech1/store_tech2/store_misc gates, the NKE
grounding-day fix, finalize (statistical zero-fill + name sort) and the
tech/aux row split.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i import ArvorTech1Packet, ArvorTech2Packet
from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import (
    TECH_PARAM_NAMES_222_232,
    ArvorTechDataset,
    TechParamRow,
    apply_grounding_day_fix,
    finalize_technical_data,
    format_hhmm_dec_argo,
    format_mmss_dec_argo,
    num2str_dec_argo,
    store_misc_rows,
    store_packet_type_info_rows,
    store_tech1_rows,
    store_tech2_rows,
    tech_param_name,
)

CORIOLIS_SRC = Path(__file__).resolve().parents[1] / "data" / "arvor_i" / "coriolis_src"


# ---------------------------------------------------------------------------
# Label table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dec_id", [222, 232])
def test_label_table_matches_vendored_coriolis_json(dec_id: int) -> None:
    """The embedded table must equal BOTH vendored JSONs byte for byte."""

    path = CORIOLIS_SRC / "_techParamNames" / f"_tech_param_name_{dec_id}.json"
    data = json.loads(path.read_text())
    expected = {
        int(entry["TECH_PARAM_DEC_ID"]): entry["TECH_PARAM_NAME"].rstrip()
        for entry in data.values()
    }
    assert expected == TECH_PARAM_NAMES_222_232


def test_label_table_id_range() -> None:
    ids = set(TECH_PARAM_NAMES_222_232)
    assert {100, 136, 200, 243, 400, 409, 1000, 1010, 1012, 1015} <= ids
    # 1011 and 1016+ do not exist for this family (other decoders only).
    assert 1011 not in ids and 1016 not in ids and 1017 not in ids


def test_tech_param_name_plus_10000_duplication() -> None:
    # get_nc_tech_parameters_json: plain prefix for base names ...
    assert tech_param_name(10127) == (
        "TECH_AUX_SURFACE_PRES_SurfaceOffsetCorrectedNotResetNegative_1cBarResolution_dbar"
    )
    # ... and TECH_AUX_ is REPLACED for already-aux-prefixed base names.
    assert tech_param_name(10243) == "TECH_AUX_SURFACE_FLAG_FloatIceDetected_NUMBER"
    assert tech_param_name(11000) == "TECH_AUX_SURFACE_FLAG_GPSValidFix_LOGICAL"


def test_tech_param_name_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        tech_param_name(99999)


# ---------------------------------------------------------------------------
# format_time_hhmm_dec_argo / format_time_mmss_dec_argo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (0, "0000"),
        (310, "0510"),  # 310/60: fix(9.99..)=9 then round(59.99..)=60 -> carry
        (59, "0059"),
        (60, "0100"),
        (1439, "2359"),
        (-1, "2359"),  # negative wraps by +24
        (1234, "2034"),
    ],
)
def test_format_hhmm(minutes: int, expected: str) -> None:
    assert format_hhmm_dec_argo(minutes) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00"),
        (-5, "- 00:05"),  # sign, space, MM:SS -- the MATLAB %c quirk
        (69, "01:09"),
        (3599, "59:59"),
        (-3600, "- 60:00"),  # h*60+m totals 60 minutes, as coded
        (5, "00:05"),
        (-69, "- 01:09"),
    ],
)
def test_format_mmss(seconds: int, expected: str) -> None:
    assert format_mmss_dec_argo(seconds) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (15, "15"),
        (0, "0"),
        (14.9, "14.9"),
        (6558.8, "6558.8"),
        (9999.9, "9999.9"),
        (45 * 5, "225"),
    ],
)
def test_num2str(value: float | int, expected: str) -> None:
    assert num2str_dec_argo(value) == expected


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------


def make_t1(overrides: dict[int, int] | None = None) -> ArvorTech1Packet:
    """A Tech#1 packet with distinctive, easy-to-trace item values."""

    fields = [0] * 74  # fields[k] == item k; fields[0] placeholder
    defaults = {
        1: 1,  # cycle
        5: 2,
        6: 3,
        7: 25,  # dd/mm/yy -> 20250302
        8: 416,  # float day
        9: 310,  # minutes -> 0510
        10: 10,
        11: 11,
        12: 12,
        13: 313,
        14: 314,
        15: 315,
        16: 16,
        17: 17,
        20: 2,
        21: 21,
        22: 22,
        25: 25,
        26: 26,
        27: 327,
        28: 328,
        29: 29,
        30: 30,
        32: 32,
        33: 33,
        34: 34,
        35: 35,
        38: 338,
        39: 339,
        40: 40,
        47: 155,  # -> -10.1 dbar after twos8/10 (155 - 256)
        48: 7,  # -> 35 mbar
        49: 1,  # -> 14.9 volts
        50: 0,  # RTC -> inverted 1
        51: 51,
        61: 1,  # GPS valid
        62: 62,
        64: 64,
        65: 65,
        66: 0,  # no EOL
        67: 11,
        68: 12,
        69: 13,
        70: 4,
        71: 3,
        72: 25,
        73: 65531,  # twos16 -> -5 s
    }
    defaults.update(overrides or {})
    for k, v in defaults.items():
        fields[k] = v
    return ArvorTech1Packet(pack_type=0, raw=b"\x00" * 100, fields=fields)


def make_t2(overrides: dict[int, int] | None = None) -> ArvorTech2Packet:
    fields = [0] * 60
    defaults = {
        1: 1,
        **{item: 100 + item for item in range(3, 15)},
        15: 55588,  # -> 6558.8 dbar
        16: 654,
        17: 33652,
        21: 0,  # no grounding
        23: 23,
        24: 324,
        25: 25,
        26: 26,
        28: 28,
        29: 329,
        30: 30,
        31: 31,
        32: 0,  # no emergency ascent
        33: 333,
        34: 334,
        35: 35,
        36: 36,
        **{item: 200 + item for item in range(37, 58)},
        46: 58,
        47: 4,
        48: 59,
        49: 3,
        50: 3,
        51: 25,  # last reset 20250302580459
        59: 0,
    }
    defaults.update(overrides or {})
    for k, v in defaults.items():
        fields[k] = v
    return ArvorTech2Packet(pack_type=4, raw=b"\x04" * 100, fields=fields)


# ---------------------------------------------------------------------------
# store_tech1_rows
# ---------------------------------------------------------------------------


def rows_by_id(rows: list[TechParamRow]) -> dict[int, TechParamRow]:
    return {r.param_id: r for r in rows}


def test_tech1_deep_emits_100_to_134_plus_1000() -> None:
    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1(), deep=True)
    ids = [r.param_id for r in rows]
    # emission order: 100..131, 1000, 132..134, then 136 (GPS valid by
    # default; 135 stays gated off because item 66 == 0)
    assert ids == [*range(100, 132), 1000, 132, 133, 134, 136]


def test_tech1_deep_values() -> None:
    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1(), deep=True)
    by_id = rows_by_id(rows)
    assert by_id[100].value == "20250302"
    assert by_id[101].value == "416"
    assert by_id[102].value == "0510"
    assert by_id[111].value == "02"
    assert by_id[127].value == "-10.1"  # twos8(155) = -119 -> -11.9? no: (155-256)/10
    assert by_id[128].value == "35"
    assert by_id[129].value == "14.9"
    assert by_id[130].value == "1"  # item50 == 0 -> inverted 1
    assert by_id[1000].value == "1"
    assert by_id[1000].name.startswith("TECH_AUX")


def test_tech1_deep_135_gate_is_exactly_one() -> None:
    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1({66: 2}), deep=True)  # type: ignore[misc]
    assert 135 not in rows_by_id(rows)
    rows = []
    store_tech1_rows(rows, 1, make_t1({66: 1}), deep=True)  # type: ignore[misc]
    assert rows_by_id(rows)[135].value == "20250304111213"


def test_tech1_136_gate_on_gps_valid() -> None:
    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1(), deep=True)
    assert rows_by_id(rows)[136].value == "- 00:05"
    rows = []
    store_tech1_rows(rows, 1, make_t1({61: 0}), deep=True)  # type: ignore[misc]
    assert 136 not in rows_by_id(rows)


def test_tech1_non_deep_emits_plus_10000_set() -> None:
    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1(), deep=False)
    ids = [r.param_id for r in rows]
    assert ids == [
        *range(100, 106),  # always emitted, before the deep fork
        10127,
        10128,
        10129,
        10130,
        10131,
        11000,
        # 10135 absent: the surface gate is "item 66 nonzero" and it is 0
        10132,
        10133,
        10134,
        10136,
    ]
    assert all(r.name.startswith("TECH_AUX_SURFACE_") for r in rows if r.param_id > 10000)


def test_tech1_non_deep_135_gate_is_nonzero() -> None:
    """As-coded divergence: the surface branch gates on 'nonzero' item 66."""

    rows: list[TechParamRow] = []
    store_tech1_rows(rows, 1, make_t1({66: 2}), deep=False)  # type: ignore[misc]
    assert 10135 in rows_by_id(rows)


# ---------------------------------------------------------------------------
# store_tech2_rows
# ---------------------------------------------------------------------------


def test_tech2_items_are_the_corrected_off_by_one_mapping() -> None:
    """200..211 read items 3..14 (dated correction of the migration doc)."""

    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=True, ice_detection_enabled=False)
    by_id = rows_by_id(rows)
    for param_id, item in zip(range(200, 212), range(3, 15), strict=True):
        assert by_id[param_id].value == str(100 + item)
    # 204 is the IN-AIR packet count == item 7 (manual + label table agree)
    assert by_id[204].value == str(100 + 7)


def test_tech2_deep_row_order_and_unconditional_ids() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=True, ice_detection_enabled=False)
    ids = [r.param_id for r in rows]
    assert ids == [
        *range(200, 213),
        213,
        222,
        *range(227, 235),
        235,
        236,
        *range(237, 243),
    ]


def test_tech2_subsurface_pressure_gate_and_value() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=True, ice_detection_enabled=False)
    by_id = rows_by_id(rows)
    assert by_id[212].value == "5.2"  # twos16(55588) = -9948 -> (-9948+10000)/10
    # the gate compares CONVERTED values: raw zero counts give pres
    # 1000.0 dbar, so the row is still emitted (MATLAB semantics)
    t2 = make_t2({15: 0, 16: 0, 17: 0})
    rows = []
    store_tech2_rows(rows, 1, t2.fields, deep=True, ice_detection_enabled=False)
    assert rows_by_id(rows)[212].value == "1000"
    # suppressed only when all three CONVERTED values are exactly zero
    t2 = make_t2({15: 55536, 16: 0, 17: 0})
    rows = []
    store_tech2_rows(rows, 1, t2.fields, deep=True, ice_detection_enabled=False)
    assert 212 not in rows_by_id(rows)


def test_tech2_grounding_rows_gate_on_item21() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=True, ice_detection_enabled=False)
    assert all(p not in rows_by_id(rows) for p in range(214, 222))

    t2 = make_t2({21: 1})
    rows = []
    store_tech2_rows(rows, 1, t2.fields, deep=True, ice_detection_enabled=False)
    by_id = rows_by_id(rows)
    assert [p for p in range(214, 222) if p in by_id] == [214, 215, 216, 217]

    t2 = make_t2({21: 2})
    rows = []
    store_tech2_rows(rows, 1, t2.fields, deep=True, ice_detection_enabled=False)
    assert [p for p in range(214, 222) if p in rows_by_id(rows)] == list(range(214, 222))


def test_tech2_emergency_rows_gate_on_item32() -> None:
    t2 = make_t2({32: 1, 33: 333, 34: 55536})
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, t2.fields, deep=True, ice_detection_enabled=False)
    by_id = rows_by_id(rows)
    assert {223, 224, 225, 226} <= set(by_id)
    assert by_id[224].value == "0"  # twos16(55536) = -10000 -> 0.0 dbar


def test_tech2_last_reset_date_items_46_to_51() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=True, ice_detection_enabled=False)
    by_id = rows_by_id(rows)
    # yy=25 mm=03 dd=03 from items 51/50/49; hh=58 mi=04 ss=59 from 46/47/48
    assert by_id[236].value == "20250303580459"


def test_tech2_243_only_when_ice_detection_enabled() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2({59: 1}).fields, deep=True, ice_detection_enabled=False)
    assert 243 not in rows_by_id(rows)
    rows = []
    store_tech2_rows(rows, 1, make_t2({59: 1}).fields, deep=True, ice_detection_enabled=True)
    assert rows_by_id(rows)[243].value == "1"


def test_tech2_non_deep_emits_reduced_plus_10000_set() -> None:
    rows: list[TechParamRow] = []
    store_tech2_rows(rows, 1, make_t2().fields, deep=False, ice_detection_enabled=False)
    ids = [r.param_id for r in rows]
    assert ids == [204, 211, *range(10227, 10234), 10236, *range(10237, 10243)]
    assert all(r.name.startswith("TECH_AUX_SURFACE_") for r in rows if r.param_id > 10000)


# ---------------------------------------------------------------------------
# Grounding-day fix, packet counts, misc
# ---------------------------------------------------------------------------


def test_grounding_day_fix_phase2_becomes_relative() -> None:
    t2 = make_t2({21: 2, 23: 500, 25: 2, 28: 600, 31: 2})
    fixed = apply_grounding_day_fix(t2.fields, t1_first_item8=416)
    assert fixed[23] == 500 - 416
    assert fixed[28] == 600 - 416
    # phase != 2 -> unchanged
    t2 = make_t2({21: 1, 23: 500, 25: 1})
    fixed = apply_grounding_day_fix(t2.fields, 416)
    assert fixed[23] == 500
    # no Tech#1 in buffer -> MATLAB skips the fix entirely
    t2 = make_t2({21: 1, 23: 500, 25: 2})
    assert apply_grounding_day_fix(t2.fields, None)[23] == 500


def test_packet_type_counts_and_gates() -> None:
    class P:  # minimal stand-in for StreamPacket
        def __init__(self, t: int) -> None:
            self.pack_type = t

    packets = [P(0), P(4), P(1), P(1), P(2), P(3), P(3), P(3), P(6), P(5)]
    rows: list[TechParamRow] = []
    store_packet_type_info_rows(rows, 7, packets, deep=True, type_7_seen=False)
    by_id = rows_by_id(rows)
    assert by_id[1001].value == "2"
    assert by_id[1002].value == "1"
    assert by_id[1003].value == "3"
    assert by_id[1004].value == "0"  # type 13 never present
    assert by_id[1005].value == "0"  # type 14
    assert by_id[1006].value == "1"  # hydraulic
    assert by_id[1007].value == "1"  # tech1
    assert by_id[1008].value == "1"  # tech2
    assert by_id[1009].value == "1"  # param1
    assert 1010 not in by_id  # type-7 never received

    rows = []
    store_packet_type_info_rows(rows, 7, packets, deep=False, type_7_seen=True)
    ids = {r.param_id for r in rows}
    assert 1001 not in ids and 1004 not in ids  # deep-gated
    assert {1005, 1006, 1007, 1008, 1009, 1010} <= ids


def test_misc_rows_values_and_216_exception() -> None:
    rows: list[TechParamRow] = []
    store_misc_rows(
        rows,
        3,
        deep=True,
        delayed=1,
        completed=False,
        dec_id=222,
        ice_activated=True,
    )
    by_id = rows_by_id(rows)
    assert by_id[1012].value == "1"
    assert by_id[1013].value == "1"
    assert by_id[1014].value == "1"
    assert by_id[1015].value == "0"
    assert all(r.name.startswith("TECH_AUX") for r in rows)

    rows = []
    store_misc_rows(
        rows,
        3,
        deep=True,
        delayed=0,
        completed=True,
        dec_id=216,
        ice_activated=False,
    )
    assert 1012 not in rows_by_id(rows)  # Arvor Deep IFREMER


# ---------------------------------------------------------------------------
# finalize + aux split
# ---------------------------------------------------------------------------


def test_finalize_zero_fills_missing_statistical_params_on_last_cycle() -> None:
    rows = [
        TechParamRow(1, 200, tech_param_name(200), "1", "x"),
        TechParamRow(2, 201, tech_param_name(201), "2", "x"),
    ]
    out = finalize_technical_data(rows)
    filled = [r for r in out if r.source == "statistical zero-fill"]
    assert {r.param_id for r in filled} == set(range(1001, 1011))
    assert all(r.cycle_number == 2 for r in filled)  # last row's cycle
    assert all(r.value == "0" for r in filled)


def test_finalize_sorts_by_parameter_name() -> None:
    rows = [
        TechParamRow(1, 105, tech_param_name(105), "0", "x"),
        TechParamRow(2, 200, tech_param_name(200), "0", "x"),
        TechParamRow(1, 100, tech_param_name(100), "0", "x"),
    ]
    out = finalize_technical_data(rows)
    assert [r.param_id for r in out if r.param_id < 300] == [100, 105, 200]


def test_finalize_empty_is_identity() -> None:
    assert finalize_technical_data([]) == []


def test_dataset_tech_aux_split() -> None:
    ds = ArvorTechDataset(dec_id=222)
    ds.rows = [
        TechParamRow(1, 100, tech_param_name(100), "20250302", "x"),
        TechParamRow(1, 1000, tech_param_name(1000), "1", "x"),
        TechParamRow(1, 1013, tech_param_name(1013), "1", "x"),
        TechParamRow(1, 10243, tech_param_name(10243), "0", "x"),
    ]
    assert [r.param_id for r in ds.tech_rows] == [100]
    assert [r.param_id for r in ds.aux_rows] == [1000, 1013, 10243]

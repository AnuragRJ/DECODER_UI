"""Phase 6A.4: ADMT technical (``<wmo>_tech.nc``) regression tests.

Structure and the parameter vocabulary are pinned against the six
supplied GDAC ``<wmo>_tech.nc`` references, which share an identical
10-variable layout and a 14-name parameter set.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.technical import (
    DERIVED_NOT_PUBLISHED_TECH_PARAMETERS,
    GDAC_VERIFIED_TECH_PARAMETERS,
    PUBLISHED_TECH_PARAMETERS,
    TECH_PARAMETER_ORDER,
    UNSUPPORTED_TECH_PARAMETERS,
    TechRecord,
    build_technical_dataset,
    build_technical_records,
    format_termination_flag,
    technical_records_for_cycle,
    technical_values_for_cycle,
    write_technical_file,
)
from argo_decoder.platforms.apex_argos.engineering import (
    STATUS_BITS,
    ApexEngineeringData,
    decode_status_flags,
)

EXPECTED_VARIABLES = [
    "DATE_CREATION",
    "DATE_UPDATE",
    "PLATFORM_NUMBER",
    "DATA_CENTRE",
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "TECHNICAL_PARAMETER_NAME",
    "TECHNICAL_PARAMETER_VALUE",
    "CYCLE_NUMBER",
]

EXPECTED_DIMS = {
    "STRING2",
    "STRING4",
    "STRING8",
    "STRING32",
    "STRING128",
    "DATE_TIME",
    "N_TECH_PARAM",
}


def _engineering(decoder_id: int = 1005, status: int = 0x8001) -> ApexEngineeringData:
    return ApexEngineeringData(
        decoder_id=decoder_id,
        status_word=status,
        status_flags=decode_status_flags(status, STATUS_BITS),
        surface_pressure_dbar=-0.4,
        piston_position_surface_counts=163,
        piston_position_park_end_counts=83,
        piston_position_deep_descent_counts=30,
        air_bladder_pressure_counts=159,
        pump_motor_time_s=1751,
    )


def _meta() -> FloatMeta:
    return FloatMeta.model_validate({"PLATFORM_NUMBER": "2902222", "DATA_CENTRE": "IN"})


def _build():
    records = build_technical_records({327: _engineering()})
    return build_technical_dataset(records, wmo=2902222, meta=_meta(), institution="IN")


def _written():
    ds = _build()
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "2902222_tech.nc"
    write_technical_file(ds, path)
    return tmp, netCDF4.Dataset(path)


def _table(nc: netCDF4.Dataset) -> dict[str, str]:
    names = [
        str(x).strip()
        for x in np.asarray(
            netCDF4.chartostring(nc.variables["TECHNICAL_PARAMETER_NAME"][:])
        ).reshape(-1)
    ]
    values = [
        str(x).strip()
        for x in np.asarray(
            netCDF4.chartostring(nc.variables["TECHNICAL_PARAMETER_VALUE"][:])
        ).reshape(-1)
    ]
    return dict(zip(names, values, strict=True))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_all_technical_dimensions_exist() -> None:
    tmp, nc = _written()
    with tmp:
        assert set(nc.dimensions) == EXPECTED_DIMS


def test_variable_set_and_order_match_reference() -> None:
    tmp, nc = _written()
    with tmp:
        assert list(nc.variables) == EXPECTED_VARIABLES


def test_n_tech_param_is_unlimited() -> None:
    tmp, nc = _written()
    with tmp:
        assert nc.dimensions["N_TECH_PARAM"].isunlimited()


def test_no_history_group_in_technical_files() -> None:
    ds = _build()
    assert not [n for n in ds.data_vars if str(n).startswith("HISTORY")]


def test_dtypes_and_fill_values() -> None:
    ds = _build()
    assert ds["CYCLE_NUMBER"].dtype == np.int32
    assert ds["CYCLE_NUMBER"].attrs["_FillValue"] == np.int32(99999)
    assert ds["TECHNICAL_PARAMETER_NAME"].attrs["_FillValue"] == b" "


def test_file_identity_scalars() -> None:
    tmp, nc = _written()
    with tmp:
        chars = lambda n: str(netCDF4.chartostring(nc.variables[n][:]).ravel()[0])  # noqa: E731
        assert chars("DATA_TYPE").strip() == "Argo technical data"
        assert chars("FORMAT_VERSION") == "3.1 "
        # Technical references carry ' 1.2', right-aligned.
        assert chars("HANDBOOK_VERSION") == " 1.2"
        assert chars("PLATFORM_NUMBER") == "2902222 "


def test_global_attributes_match_reference_set() -> None:
    ds = _build()
    assert set(ds.attrs) == {
        "title",
        "institution",
        "source",
        "history",
        "references",
        "user_manual_version",
        "Conventions",
    }
    assert ds.attrs["title"] == "Argo float technical data file"
    assert ds.attrs["institution"] == "INCOIS"


def test_technical_file_has_no_feature_type() -> None:
    assert "featureType" not in _build().attrs


# ---------------------------------------------------------------------------
# Record generation
# ---------------------------------------------------------------------------


def test_records_use_reference_parameter_names() -> None:
    tmp, nc = _written()
    with tmp:
        table = _table(nc)
        assert set(table) <= set(TECH_PARAMETER_ORDER)
        assert "POSITION_PistonSurface_COUNT" in table


def test_values_come_from_the_engineering_decoder() -> None:
    tmp, nc = _written()
    with tmp:
        table = _table(nc)
        assert table["PRES_SurfaceOffsetNotTruncated_dbar"] == "-0.4"
        assert table["POSITION_PistonSurface_COUNT"] == "163"
        assert table["POSITION_PistonPark_COUNT"] == "83"
        assert table["POSITION_PistonProfile_COUNT"] == "30"
        assert table["TIME_PumpMotor_seconds"] == "1751"


def test_cycle_number_is_recorded_per_row() -> None:
    records = build_technical_records({12: _engineering(), 13: _engineering()})
    ds = build_technical_dataset(records, wmo=1, meta=_meta())
    cycles = set(np.asarray(ds["CYCLE_NUMBER"].values).tolist())
    assert cycles == {12, 13}


def test_records_emitted_in_reference_order() -> None:
    records = technical_records_for_cycle(1, _engineering())
    emitted = [r.name for r in records]
    assert emitted == [n for n in TECH_PARAMETER_ORDER if n in set(emitted)]


def test_cycles_are_ordered_ascending() -> None:
    records = build_technical_records({9: _engineering(), 3: _engineering()})
    assert next(r.cycle_number for r in records) == 3


def test_prelude_messages_are_excluded() -> None:
    """A prelude PRF collides with a real cycle and describes self-test."""
    prelude = _engineering(status=0x8041)
    assert prelude.status_flags["prelude_message"] is True
    assert build_technical_records({15: prelude}) == []


# ---------------------------------------------------------------------------
# Termination flag encoding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_word", "expected"),
    [
        (0x0001, "01"),
        (0x0005, "05"),
        (0x000D, "0D"),
        (0x004D, "4D"),
        (0x8001, "801"),
        (0x8005, "805"),
        (0x804D, "84D"),
        (0x8901, "901"),
    ],
)
def test_termination_flag_reproduces_reference_values(status_word: int, expected: str) -> None:
    """The DAC re-packs PrfIdOverflow from bit 15 into bit 11."""
    assert format_termination_flag(status_word) == expected


def test_termination_flag_is_written_to_the_table() -> None:
    tmp, nc = _written()
    with tmp:
        assert _table(nc)["FLAG_ProfileTermination_hex"] == "801"


# ---------------------------------------------------------------------------
# Honest handling of unavailable values
# ---------------------------------------------------------------------------


def test_uncalibrated_parameters_are_not_emitted() -> None:
    """Voltages, currents and vacuum need calibration we do not have."""
    tmp, nc = _written()
    with tmp:
        table = _table(nc)
        for name in UNSUPPORTED_TECH_PARAMETERS:
            assert name not in table


def test_air_bladder_emitted_only_for_verified_firmware() -> None:
    """Raw ABP matches the reference on 1005 but not on 1010."""
    verified = build_technical_records({1: _engineering(decoder_id=1005)})
    assert any(r.name == "PRESSURE_AirBladder_COUNT" for r in verified)
    unverified = build_technical_records({1: _engineering(decoder_id=1010)})
    assert not any(r.name == "PRESSURE_AirBladder_COUNT" for r in unverified)


def test_absent_measurements_produce_no_row() -> None:
    sparse = ApexEngineeringData(decoder_id=1005, surface_pressure_dbar=-0.4)
    records = technical_records_for_cycle(1, sparse)
    assert [r.name for r in records] == ["PRES_SurfaceOffsetNotTruncated_dbar"]


def test_sentinel_pressure_produces_no_row() -> None:
    sparse = ApexEngineeringData(decoder_id=1005, piston_position_surface_counts=64)
    names = [r.name for r in technical_records_for_cycle(1, sparse)]
    assert "PRES_SurfaceOffsetNotTruncated_dbar" not in names


def test_integer_values_render_without_decimal_point() -> None:
    data = ApexEngineeringData(decoder_id=1005, surface_pressure_dbar=-1.0)
    record = technical_records_for_cycle(1, data)[0]
    assert record.value == "-1"


def test_empty_engineering_yields_empty_table() -> None:
    assert build_technical_records({}) == []


def test_tech_record_is_hashable_value_object() -> None:
    record = TechRecord(cycle_number=1, name="X", value="1")
    assert record == TechRecord(cycle_number=1, name="X", value="1")


# ---------------------------------------------------------------------------
# M2: ARGOS statistics are deliberately withheld
# ---------------------------------------------------------------------------


def test_argos_statistics_are_published() -> None:
    """M2 revisited: these labels are Argo-approved for 1005/1010.

    They were previously withheld because the INCOIS reference files do
    not publish them. That confused DAC publication policy with decoder
    capability -- ``_tech_param_name_{1005,1010}.json`` lists every one
    of them as an allowed Argo label.
    """
    for name in (
        "NUMBER_ArgosPositions_COUNT",
        "NUMBER_ArgosPositioningClass1_COUNT",
        "NUMBER_ArgosPositioningClassZ_COUNT",
        "NUMBER_TransmissionFloatFramesComplete_COUNT",
        "NUMBER_TransmissionFloatFramesCrcOk_COUNT",
    ):
        assert name in TECH_PARAMETER_ORDER


def test_gdac_verified_subset_is_unchanged() -> None:
    """Extending the vocabulary must not disturb the verified core.

    Grew from 7 to 11 when the four calibrated battery channels were
    verified against WMO 2901304 (22/22 comparable cycles, firmware
    061810). The original seven must still be present.
    """
    assert set(TECH_PARAMETER_ORDER) >= GDAC_VERIFIED_TECH_PARAMETERS
    assert len(GDAC_VERIFIED_TECH_PARAMETERS) == 11
    assert {
        "FLAG_ProfileTermination_hex",
        "PRES_SurfaceOffsetNotTruncated_dbar",
        "POSITION_PistonSurface_COUNT",
        "TIME_PumpMotor_seconds",
        "POSITION_PistonProfile_COUNT",
        "POSITION_PistonPark_COUNT",
        "PRESSURE_AirBladder_COUNT",
    } <= GDAC_VERIFIED_TECH_PARAMETERS


def test_emission_order_contains_no_duplicates() -> None:
    assert len(TECH_PARAMETER_ORDER) == len(set(TECH_PARAMETER_ORDER))


# ---------------------------------------------------------------------------
# M2 revisited: ARGOS reception statistics and float engineering
# ---------------------------------------------------------------------------


def test_argos_class_labels_cover_all_cls_classes() -> None:
    """CLS defines 0/1/2/3/A/B/Z; every one needs an approved label."""
    from argo_decoder.nc.technical import _ARGOS_CLASS_LABELS

    assert set(_ARGOS_CLASS_LABELS) == {"0", "1", "2", "3", "A", "B", "Z"}
    for label in _ARGOS_CLASS_LABELS.values():
        assert label in TECH_PARAMETER_ORDER


def test_argos_statistics_are_emitted_with_zero_classes_present() -> None:
    """Absent classes report 0, not a missing row: 0 is a real count."""
    engineering = _engineering(status=0x0001)
    engineering.n_argos_positions = 7
    engineering.argos_position_classes = {"3": 4, "2": 2, "1": 1}
    engineering.n_transmission_frames = 175
    engineering.n_transmission_frames_crc_ok = 146

    # Derived but deliberately not published, so read the full mapping.
    values = technical_values_for_cycle(engineering)
    assert values["NUMBER_ArgosPositions_COUNT"] == "7"
    assert values["NUMBER_ArgosPositioningClass3_COUNT"] == "4"
    assert values["NUMBER_ArgosPositioningClass0_COUNT"] == "0"
    assert values["NUMBER_ArgosPositioningClassZ_COUNT"] == "0"
    assert values["NUMBER_TransmissionFloatFramesComplete_COUNT"] == "175"
    assert values["NUMBER_TransmissionFloatFramesCrcOk_COUNT"] == "146"


def test_argos_class_counts_sum_to_position_total() -> None:
    engineering = _engineering(status=0x0001)
    engineering.n_argos_positions = 7
    engineering.argos_position_classes = {"3": 4, "2": 2, "1": 1}
    values = technical_values_for_cycle(engineering)
    total = sum(
        int(values[label])
        for label in TECH_PARAMETER_ORDER
        if label.startswith("NUMBER_ArgosPositioningClass")
    )
    assert total == int(values["NUMBER_ArgosPositions_COUNT"])


def test_statistics_absent_when_not_derived() -> None:
    """No invented zeros when the decoder never counted anything."""
    values = technical_values_for_cycle(_engineering(status=0x0001))
    assert "NUMBER_ArgosPositions_COUNT" not in values
    assert "NUMBER_TransmissionFloatFramesCrcOk_COUNT" not in values


def test_telonics_flag_emitted_as_hex_without_interpretation() -> None:
    engineering = _engineering(status=0x0001)
    engineering.telonics_status_byte = 0xA5
    values = technical_values_for_cycle(engineering)
    assert values["FLAG_TelonicsPTTStatus_hex"] == "A5"


# ---------------------------------------------------------------------------
# GDAC emission scope and the recovered calibration channels
# ---------------------------------------------------------------------------


def test_only_reference_vocabulary_is_written_to_the_file() -> None:
    """Derived-but-unpublished parameters must not reach the file.

    The decoder computes 32 labels; the INCOIS references publish 14.
    Emitting the surplus doubled the row count (641 against 322 on WMO
    2901304) and made a row-wise comparison impossible.
    """
    engineering = _engineering(status=0x0001)
    engineering.n_argos_positions = 7
    engineering.argos_position_classes = {"3": 4, "2": 2, "1": 1}
    engineering.telonics_status_byte = 0xA5

    computed = technical_values_for_cycle(engineering)
    emitted = {r.name for r in technical_records_for_cycle(327, engineering)}

    assert "NUMBER_ArgosPositions_COUNT" in computed
    assert "NUMBER_ArgosPositions_COUNT" not in emitted
    assert emitted <= PUBLISHED_TECH_PARAMETERS
    assert DERIVED_NOT_PUBLISHED_TECH_PARAMETERS.isdisjoint(emitted)


def test_profile_depth_voltage_uses_its_own_calibration() -> None:
    """0.078*n+0.5, not the 0.077*n+0.486 of the other channels.

    Recovered by inverting the published WMO 2901304 values; the
    documented form matches 0 of 23 cycles, this one all 23. Raw count
    186 is cycle 1, published as 15.008 V.
    """
    engineering = _engineering(status=0x0001)
    engineering.battery_voltage_pump_counts = 186
    values = technical_values_for_cycle(engineering)
    assert values["VOLTAGE_BatteryInitialAtProfileDepth_volts"] == "15.008"


def test_internal_vacuum_is_decoded_from_the_message_one_byte() -> None:
    """0.293*n-29.767, exact on all 23 cycles of WMO 2901304.

    n=254 is cycle 1 (44.655 inHg); n=0 gives the negative reading the
    reference publishes on cycle 8.
    """
    engineering = _engineering(status=0x0001)
    engineering.vacuum_counts = 254
    assert technical_values_for_cycle(engineering)["PRESSURE_InternalVacuum_inHg"] == "44.655"
    engineering.vacuum_counts = 0
    assert technical_values_for_cycle(engineering)["PRESSURE_InternalVacuum_inHg"] == "-29.767"


def test_no_technical_parameter_is_left_unsupported() -> None:
    """All three former gaps were resolved to an exact source byte."""
    assert UNSUPPORTED_TECH_PARAMETERS == {}


def test_profile_depth_voltage_calibration_is_firmware_specific() -> None:
    """061810 uses 0.078*n+0.5; 091x15 uses the shared 0.077*n+0.486.

    Both recovered by inverting the published values to integer counts:
    raw 186 is WMO 2901304 cycle 1 (15.008 V on decoder 1005), raw 120 is
    WMO 2902222 cycle 327 (9.726 V on decoder 1010). Applying either
    float's constants to the other reproduces neither.
    """
    apf9a = _engineering(status=0x0001)
    apf9a.decoder_id = 1005
    apf9a.battery_voltage_pump_counts = 186
    assert (
        technical_values_for_cycle(apf9a)["VOLTAGE_BatteryInitialAtProfileDepth_volts"] == "15.008"
    )

    apf9g = _engineering(status=0x0001)
    apf9g.decoder_id = 1010
    apf9g.battery_voltage_pump_counts = 120
    assert (
        technical_values_for_cycle(apf9g)["VOLTAGE_BatteryInitialAtProfileDepth_volts"] == "9.726"
    )


def test_internal_vacuum_is_only_emitted_on_firmware_061810() -> None:
    """On 091x15 the reference's value inverts to a count found nowhere.

    WMO 2902222 publishes -28.009 inHg, which is raw 6 under the verified
    conversion; no offset of any message carries 6 on all three cycles,
    so the field is not in the message-1 block on that firmware and is
    withheld rather than read from a guessed byte.
    """
    apf9g = _engineering(status=0x0001)
    apf9g.decoder_id = 1010
    apf9g.vacuum_counts = 254
    assert "PRESSURE_InternalVacuum_inHg" not in technical_values_for_cycle(apf9g)


# ---------------------------------------------------------------------------
# ABP / vacuum source byte is firmware-dependent
# ---------------------------------------------------------------------------


def test_air_bladder_comes_from_message_3_on_1010() -> None:
    """On 091x15 ``ABP`` must be taken from message 3, not message 1.

    The 110613 message-1 table has no ``ABP`` entry at all; the byte we
    read there on 061810 holds something else. Withholding the parameter
    (the previous behaviour) left a real parameter-count gap against the
    reference, which publishes it on every cycle.
    """
    from argo_decoder.nc.technical import technical_records_for_cycle
    from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData

    eng = ApexEngineeringData(decoder_id=1010)
    eng.air_bladder_pressure_counts = 99  # message-1 byte: must be ignored
    eng.msg3_air_bladder_counts = 123
    values = {r.name: r.value for r in technical_records_for_cycle(1, eng)}

    assert values["PRESSURE_AirBladder_COUNT"] == "123"


def test_air_bladder_stays_on_message_1_for_1005() -> None:
    """061810 keeps the message-1 byte, which matches the reference."""
    from argo_decoder.nc.technical import technical_records_for_cycle
    from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData

    eng = ApexEngineeringData(decoder_id=1005)
    eng.air_bladder_pressure_counts = 148
    eng.msg3_air_bladder_counts = 123  # not present on this firmware
    values = {r.name: r.value for r in technical_records_for_cycle(1, eng)}

    assert values["PRESSURE_AirBladder_COUNT"] == "148"


def test_vacuum_source_byte_differs_by_firmware() -> None:
    """Vacuum uses the message-3 byte on 1010 and message 1 on 1005.

    Both use the same conversion (APF9A p.28,
    ``V = counts * 0.293 - 29.767``); only the source byte moves.
    """
    from argo_decoder.nc.technical import technical_records_for_cycle
    from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData

    ten = ApexEngineeringData(decoder_id=1010)
    ten.vacuum_counts = 254
    ten.msg3_vacuum_counts = 80
    ten_v = {r.name: r.value for r in technical_records_for_cycle(1, ten)}
    assert ten_v["PRESSURE_InternalVacuum_inHg"] == "-6.327"

    five = ApexEngineeringData(decoder_id=1005)
    five.vacuum_counts = 254
    five.msg3_vacuum_counts = 80
    five_v = {r.name: r.value for r in technical_records_for_cycle(1, five)}
    assert five_v["PRESSURE_InternalVacuum_inHg"] == "44.655"

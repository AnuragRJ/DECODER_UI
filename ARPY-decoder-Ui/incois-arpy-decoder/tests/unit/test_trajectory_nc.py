"""Phase 6A: ADMT trajectory (``<wmo>_Rtraj.nc``) regression tests.

Structure, ordering, dtypes, attributes and fill conventions are pinned
against the six supplied GDAC ``<wmo>_Rtraj.nc`` references, which are
structurally identical to one another.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.trajectory import (
    CYCLE_JULD_STATUS,
    CYCLE_JULD_STATUS_WHEN_ABSENT,
    CYCLE_MEASUREMENT_TEMPLATE,
    JULD_QC_BY_MEASUREMENT_CODE,
    JULD_STATUS_BY_MEASUREMENT_CODE,
    TrajCycle,
    TrajectoryRecords,
    TrajMeasurement,
    TrajMeasurementCode,
    build_trajectory_dataset,
    write_trajectory,
)
from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData
from argo_decoder.platforms.apex_argos.frames import ArgosFix
from argo_decoder.platforms.apex_argos.profile import datetime_to_juld
from argo_decoder.platforms.apex_argos.trajectory import (
    ArgosCycleTelemetry,
    build_argos_trajectory_records,
)

# Variable order transcribed from the references; the on-disk order must
# match because ADMT readers and the GDAC checker rely on it.
EXPECTED_ORDER = [
    "DATE_CREATION",
    "DATE_UPDATE",
    "PLATFORM_NUMBER",
    "DATA_CENTRE",
    "WMO_INST_TYPE",
    "PROJECT_NAME",
    "PI_NAME",
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "REFERENCE_DATE_TIME",
    "POSITIONING_SYSTEM",
    "TRAJECTORY_PARAMETERS",
    "DATA_STATE_INDICATOR",
    "PLATFORM_TYPE",
    "FLOAT_SERIAL_NO",
    "FIRMWARE_VERSION",
    "JULD",
    "JULD_STATUS",
    "JULD_QC",
    "JULD_ADJUSTED",
    "JULD_ADJUSTED_STATUS",
    "JULD_ADJUSTED_QC",
    "LATITUDE",
    "LONGITUDE",
    "POSITION_ACCURACY",
    "POSITION_QC",
    "CYCLE_NUMBER",
    "CYCLE_NUMBER_ADJUSTED",
    "MEASUREMENT_CODE",
]

EXPECTED_DIMS = {
    "N_CYCLE",
    "STRING2",
    "STRING4",
    "STRING8",
    "STRING16",
    "STRING32",
    "STRING64",
    "DATE_TIME",
    "N_PARAM",
    "N_HISTORY",
    "N_MEASUREMENT",
}


def _meta() -> FloatMeta:
    return FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "PLATFORM_TYPE": "APEX",
            "DATA_CENTRE": "IN",
            "PROJECT_NAME": "Argo INDIA",
            "PI_NAME": "M Ravichandran",
            "FLOAT_SERIAL_NO": "7532",
            "FIRMWARE_VERSION": "091615",
            "WMO_INST_TYPE": "846",
            "LAUNCH_DATE": "20170120084400",
            "LAUNCH_LATITUDE": -53.0,
            "LAUNCH_LONGITUDE": 68.1,
        }
    )


def _fix(hour: int, lat: float, lon: float, cls: str = "3") -> ArgosFix:
    return ArgosFix(
        at=datetime(2025, 12, 25, hour, 0, 0, tzinfo=UTC),
        latitude=lat,
        longitude=lon,
        location_class=cls,
    )


def _telemetry(cycle: int = 327, n_fixes: int = 3) -> ArgosCycleTelemetry:
    return ArgosCycleTelemetry(
        cycle_number=cycle,
        fixes=[_fix(7 + i, -54.0 - i * 0.01, -160.0 + i * 0.01) for i in range(n_fixes)],
        message_times=[datetime(2025, 12, 25, 6 + i, 30, 0, tzinfo=UTC) for i in range(4)],
    )


def _records(n_fixes: int = 3) -> TrajectoryRecords:
    return build_argos_trajectory_records([_telemetry(n_fixes=n_fixes)], meta=_meta())


def _build(n_fixes: int = 3):
    return build_trajectory_dataset(_records(n_fixes), wmo=2902222, meta=_meta(), institution="IN")


def _written(n_fixes: int = 3):
    ds = _build(n_fixes)
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "2902222_Rtraj.nc"
    write_trajectory(ds, path)
    return tmp, netCDF4.Dataset(path)


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------


def test_all_admt_trajectory_dimensions_exist() -> None:
    tmp, nc = _written()
    with tmp:
        assert set(nc.dimensions) == EXPECTED_DIMS


def test_n_measurement_is_unlimited() -> None:
    tmp, nc = _written()
    with tmp:
        assert nc.dimensions["N_MEASUREMENT"].isunlimited()


def test_fixed_string_dimension_sizes() -> None:
    tmp, nc = _written()
    with tmp:
        for name, size in (
            ("STRING2", 2),
            ("STRING4", 4),
            ("STRING8", 8),
            ("STRING16", 16),
            ("STRING32", 32),
            ("STRING64", 64),
            ("DATE_TIME", 14),
            ("N_PARAM", 3),
        ):
            assert len(nc.dimensions[name]) == size


def test_n_cycle_matches_number_of_cycles() -> None:
    ds = _build()
    assert ds.sizes["N_CYCLE"] == 1


# ---------------------------------------------------------------------------
# Variable set and ordering
# ---------------------------------------------------------------------------


def test_variable_order_matches_reference_prefix() -> None:
    tmp, nc = _written()
    with tmp:
        assert list(nc.variables)[: len(EXPECTED_ORDER)] == EXPECTED_ORDER


def test_full_variable_count_matches_reference() -> None:
    tmp, nc = _written()
    with tmp:
        assert len(nc.variables) == 102


def test_history_variables_present() -> None:
    ds = _build()
    for name in (
        "HISTORY_INSTITUTION",
        "HISTORY_STEP",
        "HISTORY_SOFTWARE",
        "HISTORY_SOFTWARE_RELEASE",
        "HISTORY_REFERENCE",
        "HISTORY_DATE",
        "HISTORY_ACTION",
        "HISTORY_PARAMETER",
        "HISTORY_PREVIOUS_VALUE",
        "HISTORY_INDEX_DIMENSION",
        "HISTORY_START_INDEX",
        "HISTORY_STOP_INDEX",
        "HISTORY_QCTEST",
    ):
        assert name in ds.data_vars


# ---------------------------------------------------------------------------
# Coordinate variables and dtypes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "dtype"),
    [
        ("JULD", np.float64),
        ("LATITUDE", np.float64),
        ("LONGITUDE", np.float64),
        ("CYCLE_NUMBER", np.int32),
        ("MEASUREMENT_CODE", np.int32),
        ("PRES", np.float32),
        ("TEMP", np.float32),
        ("PSAL", np.float32),
    ],
)
def test_measurement_variable_dtypes(name: str, dtype: type) -> None:
    ds = _build()
    assert ds[name].dtype == dtype
    assert ds[name].dims == ("N_MEASUREMENT",)


def test_cycle_variables_sit_on_n_cycle() -> None:
    ds = _build()
    for name in (
        "JULD_FIRST_MESSAGE",
        "JULD_LAST_MESSAGE",
        "CYCLE_NUMBER_INDEX",
        "CONFIG_MISSION_NUMBER",
        "DATA_MODE",
        "GROUNDED",
    ):
        assert ds[name].dims == ("N_CYCLE",)


def test_coordinate_axis_attributes() -> None:
    ds = _build()
    assert ds["JULD"].attrs["axis"] == "T"
    assert ds["LATITUDE"].attrs["axis"] == "Y"
    assert ds["LONGITUDE"].attrs["axis"] == "X"
    assert ds["PRES"].attrs["axis"] == "Z"


# ---------------------------------------------------------------------------
# Fill values
# ---------------------------------------------------------------------------


def test_fill_values_match_admt() -> None:
    ds = _build()
    assert ds["JULD"].attrs["_FillValue"] == np.float64(999999.0)
    assert ds["LATITUDE"].attrs["_FillValue"] == np.float64(99999.0)
    assert ds["PRES"].attrs["_FillValue"] == np.float32(99999.0)
    assert ds["CYCLE_NUMBER"].attrs["_FillValue"] == np.int32(99999)
    assert ds["JULD_STATUS"].attrs["_FillValue"] == b" "


def test_engineering_only_events_are_fill_not_invented() -> None:
    """Events needing the APEX engineering message must stay unset.

    ``JULD`` stays fill for all of them. ``JULD_STATUS`` is checked
    separately: it is a per-measurement-code constant applied by the
    platform builder, not a function of whether this bare dataset
    happens to carry a time.
    """
    ds = _build()
    mc = np.asarray(ds["MEASUREMENT_CODE"].values)
    juld = np.asarray(ds["JULD"].values)
    for code in (100, 250, 290, 296, 300, 400, 500, 600, 700, 800, 903):
        idx = np.where(mc == code)[0]
        assert idx.size == 1
        assert juld[idx[0]] == np.float64(999999.0)


def test_unavailable_cycle_timings_are_fill() -> None:
    ds = _build()
    for name in (
        "JULD_ASCENT_START",
        "JULD_ASCENT_END",
        "JULD_DESCENT_START",
        "JULD_PARK_START",
        "JULD_PARK_END",
        "JULD_TRANSMISSION_START",
        "JULD_TRANSMISSION_END",
        "CLOCK_OFFSET",
    ):
        assert np.all(np.asarray(ds[name].values) == np.float64(999999.0))


def test_traj_cycle_defaults_grounded_to_table_20_unknown() -> None:
    """The digit 0 is not a table-20 code; unknown is U."""
    assert TrajCycle(cycle_number=1).grounded == "U"


def test_grounded_is_unknown_when_undetermined() -> None:
    """Cycles built without a grounding determination stay table-20 'U'.

    A space fill or the digit ``0`` is not a valid reference-table-20
    code. The Y/N derivation lives in the APEX/ARGOS platform layer
    (see ``test_grounded_apex_argos.py``); records assembled without it
    must still serialise a valid unknown.
    """
    ds = _build()
    assert np.all(np.asarray(ds["GROUNDED"].values) == b"U")


# ---------------------------------------------------------------------------
# Trajectory event generation
# ---------------------------------------------------------------------------


def test_per_cycle_template_is_emitted_in_order() -> None:
    records = _records(n_fixes=3)
    codes = [m.measurement_code for m in records.measurements if m.cycle_number == 327]
    expected = []
    for code in CYCLE_MEASUREMENT_TEMPLATE:
        expected.append(code)
        if code == TrajMeasurementCode.FIRST_MESSAGE:
            expected.extend([TrajMeasurementCode.SURFACE_FIX] * 3)
    assert codes == expected


def test_one_surface_fix_row_per_argos_fix() -> None:
    for n in (0, 1, 5):
        records = _records(n_fixes=n)
        rows = [
            m for m in records.measurements if m.measurement_code == TrajMeasurementCode.SURFACE_FIX
        ]
        assert len(rows) == n


def test_surface_fix_rows_carry_position_and_accuracy() -> None:
    records = _records(n_fixes=2)
    rows = [
        m for m in records.measurements if m.measurement_code == TrajMeasurementCode.SURFACE_FIX
    ]
    assert rows[0].latitude == pytest.approx(-54.0)
    assert rows[0].longitude == pytest.approx(-160.0)
    assert rows[0].position_accuracy == "3"
    # A located ARGOS fix is flagged good; 95.5% of the 22 040 fixes
    # in the four reference files carry POSITION_QC='1'.
    assert rows[0].position_qc == "1"
    assert rows[0].juld_status == "4"


def test_launch_row_uses_metadata_position() -> None:
    records = _records()
    launch = [m for m in records.measurements if m.measurement_code == TrajMeasurementCode.LAUNCH]
    assert len(launch) == 1
    assert launch[0].cycle_number == -1
    assert launch[0].latitude == pytest.approx(-53.0)
    assert launch[0].longitude == pytest.approx(68.1)


def test_no_launch_row_without_metadata() -> None:
    records = build_argos_trajectory_records([_telemetry()], meta=None)
    assert not [m for m in records.measurements if m.measurement_code == TrajMeasurementCode.LAUNCH]


def test_first_and_last_message_rows_use_transmission_times() -> None:
    telemetry = _telemetry()
    records = build_argos_trajectory_records([telemetry], meta=_meta())
    by_code = {m.measurement_code: m for m in records.measurements if m.cycle_number == 327}
    assert by_code[TrajMeasurementCode.FIRST_MESSAGE].juld == pytest.approx(
        telemetry.first_message_juld
    )
    assert by_code[TrajMeasurementCode.LAST_MESSAGE].juld == pytest.approx(
        telemetry.last_message_juld
    )


def test_cycles_are_ordered_ascending() -> None:
    telemetry = [_telemetry(cycle=c) for c in (329, 327, 328)]
    records = build_argos_trajectory_records(telemetry, meta=_meta())
    assert [c.cycle_number for c in records.cycles] == [327, 328, 329]


def test_cycle_summary_derives_location_window_from_fixes() -> None:
    telemetry = _telemetry(n_fixes=3)
    records = build_argos_trajectory_records([telemetry], meta=_meta())
    cycle = records.cycles[0]
    ordered = telemetry.ordered_fixes
    assert cycle.juld_first_location == pytest.approx(datetime_to_juld(ordered[0].at))
    assert cycle.juld_last_location == pytest.approx(datetime_to_juld(ordered[-1].at))


def test_cycle_without_fixes_has_no_location_window() -> None:
    records = build_argos_trajectory_records([_telemetry(n_fixes=0)], meta=_meta())
    cycle = records.cycles[0]
    assert cycle.juld_first_location is None
    assert cycle.juld_last_location is None


# ---------------------------------------------------------------------------
# QC variables
# ---------------------------------------------------------------------------


def test_measured_parameters_flag_good_and_absent_blank() -> None:
    records = TrajectoryRecords(
        measurements=[
            TrajMeasurement(cycle_number=1, measurement_code=290, pres=12.5),
            TrajMeasurement(cycle_number=1, measurement_code=703),
        ],
        cycles=[TrajCycle(cycle_number=1)],
    )
    ds = build_trajectory_dataset(records, wmo=1, meta=_meta())
    assert np.asarray(ds["PRES_QC"].values).tolist() == [b"1", b" "]


def test_adjusted_families_are_declared_but_unset() -> None:
    ds = _build()
    for name in ("PRES", "TEMP", "PSAL"):
        assert np.all(np.asarray(ds[f"{name}_ADJUSTED"].values) == np.float32(99999.0))
        assert np.all(np.asarray(ds[f"{name}_ADJUSTED_QC"].values) == b" ")
        assert np.all(np.asarray(ds[f"{name}_ADJUSTED_ERROR"].values) == np.float32(99999.0))


def test_juld_adjusted_is_unset_in_real_time() -> None:
    ds = _build()
    assert np.all(np.asarray(ds["JULD_ADJUSTED"].values) == np.float64(999999.0))
    assert np.all(np.asarray(ds["JULD_ADJUSTED_STATUS"].values) == b" ")


def test_error_ellipse_is_unset_for_argos() -> None:
    """Error-ellipse geometry is a GPS/Iridium product."""
    ds = _build()
    for name in (
        "AXES_ERROR_ELLIPSE_MAJOR",
        "AXES_ERROR_ELLIPSE_MINOR",
        "AXES_ERROR_ELLIPSE_ANGLE",
    ):
        assert np.all(np.asarray(ds[name].values) == np.float32(99999.0))


# ---------------------------------------------------------------------------
# Metadata and global attributes
# ---------------------------------------------------------------------------


def test_file_level_scalars_match_reference_values() -> None:
    tmp, nc = _written()
    with tmp:
        chars = lambda n: str(netCDF4.chartostring(nc.variables[n][:]).ravel()[0])  # noqa: E731
        assert chars("DATA_TYPE") == "Argo trajectory "
        assert chars("FORMAT_VERSION") == "3.1 "
        # Trajectory files carry ' 3.1'; the profile files carry ' 1.2'.
        assert chars("HANDBOOK_VERSION") == " 3.1"
        assert chars("REFERENCE_DATE_TIME") == "19500101000000"
        assert chars("DATA_STATE_INDICATOR") == "2B  "
        assert chars("PLATFORM_NUMBER") == "2902222 "
        assert chars("DATA_CENTRE") == "IN"
        assert chars("POSITIONING_SYSTEM") == "ARGOS   "


def test_trajectory_parameters_lists_core_params() -> None:
    tmp, nc = _written()
    with tmp:
        values = [str(v) for v in netCDF4.chartostring(nc.variables["TRAJECTORY_PARAMETERS"][:])]
        assert values == ["PRES".ljust(16), "TEMP".ljust(16), "PSAL".ljust(16)]


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
        "featureType",
        "comment_on_resolution",
    }
    assert ds.attrs["title"] == "Argo float trajectory file"
    assert ds.attrs["featureType"] == "trajectory"
    assert ds.attrs["institution"] == "INCOIS"


def test_decoder_internal_attributes_never_reach_the_file() -> None:
    ds = _build()
    for leaked in ("wmo", "decoder", "n_argos_messages", "raw_cycle_number"):
        assert leaked not in ds.attrs


def test_launch_juld_uses_days_since_1950_epoch() -> None:
    """Launch JULD must honour the file's own ``units`` attribute.

    The GDAC references encode the ``MC=0`` launch row as an
    *astronomical* Julian Date (~2.45e6) in all six files, which
    contradicts their own ``days since 1950-01-01`` units. We emit the
    CF-correct value; both describe the same instant.
    """
    records = _records()
    launch = next(
        m for m in records.measurements if m.measurement_code == TrajMeasurementCode.LAUNCH
    )
    assert launch.juld is not None
    expected = datetime_to_juld(datetime(2017, 1, 20, 8, 44, 0, tzinfo=UTC))
    assert launch.juld == pytest.approx(expected, abs=1e-6)


def test_registry_style_launch_dates_are_parsed() -> None:
    """The CSV registry stores launch dates as DD/MM/YYYY HH:MM:SS."""
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "LAUNCH_DATE": "20/01/2017 08:44:00",
            "LAUNCH_LATITUDE": -53.0,
            "LAUNCH_LONGITUDE": 68.1,
        }
    )
    records = build_argos_trajectory_records([_telemetry()], meta=meta)
    launch = [m for m in records.measurements if m.measurement_code == TrajMeasurementCode.LAUNCH]
    assert len(launch) == 1
    assert launch[0].juld == pytest.approx(
        datetime_to_juld(datetime(2017, 1, 20, 8, 44, 0, tzinfo=UTC)), abs=1e-6
    )


def test_launch_row_skipped_for_null_island_coordinates() -> None:
    """(0, 0) is the registry's 'unset' marker, not a real deployment."""
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "LAUNCH_DATE": "20/01/2017 08:44:00",
            "LAUNCH_LATITUDE": 0.0,
            "LAUNCH_LONGITUDE": 0.0,
        }
    )
    records = build_argos_trajectory_records([_telemetry()], meta=meta)
    assert not [m for m in records.measurements if m.measurement_code == TrajMeasurementCode.LAUNCH]


# ---------------------------------------------------------------------------
# M6: documented cycle-timing model (ApexTimings.xlsx rows 27/29/31)
# ---------------------------------------------------------------------------


def _telemetry_with_engineering(cycle: int, epoch_minutes: int) -> ArgosCycleTelemetry:
    from datetime import UTC, datetime

    from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData

    eng = ApexEngineeringData(
        profile_id=cycle,
        down_time_expiry=datetime(2025, 12, 25, 1, 32, 40, tzinfo=UTC),
        telemetry_init_minutes=epoch_minutes,
        decoder_id=1010,
    )
    return ArgosCycleTelemetry(cycle_number=cycle, fixes=[], message_times=[], engineering=eng)


def test_ascent_end_is_ten_minutes_before_transmission_start() -> None:
    """ApexTimings row 31: AET_float = TST_float - 10 minutes."""
    records = build_argos_trajectory_records([_telemetry_with_engineering(327, 352)])
    cycle = records.cycles[0]
    assert cycle.juld_transmission_start is not None
    assert cycle.juld_ascent_end is not None
    delta_minutes = (cycle.juld_transmission_start - cycle.juld_ascent_end) * 24 * 60
    assert delta_minutes == pytest.approx(10.0, abs=1e-6)


def test_transmission_start_is_epoch_plus_tinit() -> None:
    """ApexTimings row 27: TST_float = EPOCH + TINIT."""
    from datetime import UTC, datetime

    from argo_decoder.platforms.apex_argos.profile import datetime_to_juld

    records = build_argos_trajectory_records([_telemetry_with_engineering(327, 352)])
    expected = datetime_to_juld(datetime(2025, 12, 25, 7, 24, 40, tzinfo=UTC))
    assert records.cycles[0].juld_transmission_start == pytest.approx(expected, abs=1e-9)


def test_timing_fields_stay_absent_without_engineering() -> None:
    """No engineering message means no invented timing."""
    records = build_argos_trajectory_records(
        [ArgosCycleTelemetry(cycle_number=5, fixes=[], message_times=[])]
    )
    assert records.cycles[0].juld_ascent_end is None
    assert records.cycles[0].juld_transmission_start is None


# ---------------------------------------------------------------------------
# Reference flag tables and the mission schedule (GDAC parity)
# ---------------------------------------------------------------------------


def test_juld_status_is_a_constant_of_the_measurement_code() -> None:
    """Verified identical on WMO 2901304, 2902222, 2902223 and 2902224.

    The mission-schedule events are float-clock ('1'), the two derived
    from the timing model are '3', the reception times are '4', and the
    events this decoder never times are '9' or blank.
    """
    assert JULD_STATUS_BY_MEASUREMENT_CODE[290] == "1"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[296] == "1"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[600] == "3"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[700] == "3"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[702] == "4"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[703] == "4"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[100] == "9"
    assert JULD_STATUS_BY_MEASUREMENT_CODE[903] == " "


def test_juld_qc_does_not_track_whether_a_time_is_present() -> None:
    """MC 400 is always '0' though its JULD is always empty; MC 100 blank.

    This is the discriminating case: a rule of "0 when timed, blank when
    not" would get both of these wrong.
    """
    assert JULD_QC_BY_MEASUREMENT_CODE[400] == "0"
    assert JULD_QC_BY_MEASUREMENT_CODE[100] == " "
    assert JULD_QC_BY_MEASUREMENT_CODE[703] == "0"
    assert JULD_QC_BY_MEASUREMENT_CODE[290] == "1"


def test_cycle_juld_status_separates_absent_from_undetermined() -> None:
    """'9' means "expected, not determined"; blank means "not applicable"."""
    assert CYCLE_JULD_STATUS["JULD_DESCENT_START"] == "1"
    assert CYCLE_JULD_STATUS["JULD_ASCENT_END"] == "3"
    assert CYCLE_JULD_STATUS["JULD_FIRST_MESSAGE"] == "4"
    assert CYCLE_JULD_STATUS_WHEN_ABSENT["JULD_ASCENT_START"] == "9"
    assert "JULD_DESCENT_END" not in CYCLE_JULD_STATUS_WHEN_ABSENT


def test_park_pressure_is_adjusted_by_the_surface_offset() -> None:
    """``PRES_ADJUSTED = PRES - surface offset``, exact on 2 020 rows."""
    measurements = [
        TrajMeasurement(
            cycle_number=1,
            measurement_code=TrajMeasurementCode.PARK_END,
            pres=1000.0,
            pres_adjusted=1000.2,
            temp=2.0,
            psal=34.7,
            science_qc="0",
        )
    ]
    ds = build_trajectory_dataset(
        TrajectoryRecords(measurements=measurements, cycles=[TrajCycle(cycle_number=1)]),
        wmo=2901304,
    )
    assert float(ds["PRES"].values[0]) == pytest.approx(1000.0)
    assert float(ds["PRES_ADJUSTED"].values[0]) == pytest.approx(1000.2)
    # The park samples are unscreened engineering values: QC '0'.
    assert ds["PRES_QC"].values[0] == b"0"
    assert ds["PRES_ADJUSTED_QC"].values[0] == b"0"
    # TEMP and PSAL are published unchanged in the adjusted family.
    assert float(ds["TEMP_ADJUSTED"].values[0]) == pytest.approx(2.0)
    assert float(ds["PSAL_ADJUSTED"].values[0]) == pytest.approx(34.7)


def test_adjusted_qc_is_blank_where_no_adjusted_value_exists() -> None:
    """A row with no ``_ADJUSTED`` must not carry an adjusted flag."""
    measurements = [
        TrajMeasurement(
            cycle_number=1,
            measurement_code=TrajMeasurementCode.GROUNDING,
            pres=-0.2,
        )
    ]
    ds = build_trajectory_dataset(
        TrajectoryRecords(measurements=measurements, cycles=[TrajCycle(cycle_number=1)]),
        wmo=2901304,
    )
    assert float(ds["PRES_ADJUSTED"].values[0]) == pytest.approx(99999.0)
    assert ds["PRES_ADJUSTED_QC"].values[0] == b" "


def _telemetry_with_park_sample(cycle: int = 327) -> ArgosCycleTelemetry:
    """Telemetry whose engineering carries a park sample and an offset."""
    engineering = ApexEngineeringData(decoder_id=1005)
    engineering.surface_pressure_dbar = -0.2
    engineering.park_end_temperature = 2.108
    engineering.park_end_salinity = 34.711
    engineering.park_end_pressure = 933.8
    engineering.park_temperature_mean = 2.119
    engineering.park_pressure_mean = 929.2
    telemetry = _telemetry(cycle=cycle)
    telemetry.engineering = engineering
    return telemetry


def test_park_rows_are_offset_corrected_and_flagged_zero() -> None:
    """The platform builder must wire the offset and the QC through.

    Reproduces the reference relation ``PRES_ADJUSTED = PRES - offset``
    on both park rows, and the ``'0'`` ("no QC performed") flag the
    references give these unscreened engineering samples.
    """
    records = build_argos_trajectory_records([_telemetry_with_park_sample()], meta=_meta())
    rows = {
        m.measurement_code: m
        for m in records.measurements
        if m.measurement_code
        in (TrajMeasurementCode.PARK_END, TrajMeasurementCode.DEEP_PARK_DESCENT)
    }
    park_end = rows[TrajMeasurementCode.PARK_END]
    assert park_end.pres == pytest.approx(933.8)
    assert park_end.pres_adjusted == pytest.approx(934.0)
    assert park_end.science_qc == "0"

    park_mean = rows[TrajMeasurementCode.DEEP_PARK_DESCENT]
    assert park_mean.pres_adjusted == pytest.approx(929.4)
    assert park_mean.science_qc == "0"


def test_grounding_row_publishes_the_surface_offset() -> None:
    """MC 903 PRES equals the tech file's surface offset, 23/23 on 2901304."""
    records = build_argos_trajectory_records([_telemetry_with_park_sample()], meta=_meta())
    grounding = next(
        m for m in records.measurements if m.measurement_code == TrajMeasurementCode.GROUNDING
    )
    assert grounding.pres == pytest.approx(-0.2)
    # It is a raw offset, not a corrected depth, so it is not adjusted.
    assert grounding.pres_adjusted is None


def test_mission_schedule_uses_cycle_time_not_double() -> None:
    """The schedule advances one CycleTime per cycle.

    Anchored on LAUNCH_DATE, with PARK_END at DownTime+2 h and
    TRANSMISSION_END at CycleTime, chained so the next descent starts
    where the last transmission ended.
    """
    meta = FloatMeta.model_validate(
        {
            **_meta().model_dump(exclude_none=True),
            "LAUNCH_CONFIG_PARAMETER_NAME": [
                {
                    "LAUNCH_CONFIG_PARAMETER_NAME_1": "CONFIG_DownTime_hours",
                    "LAUNCH_CONFIG_PARAMETER_NAME_2": "CONFIG_CycleTime_hours",
                }
            ],
            "LAUNCH_CONFIG_PARAMETER_VALUE": [
                {
                    "LAUNCH_CONFIG_PARAMETER_VALUE_1": "222",
                    "LAUNCH_CONFIG_PARAMETER_VALUE_2": "240",
                }
            ],
        }
    )
    records = build_argos_trajectory_records([_telemetry(cycle=1), _telemetry(cycle=2)], meta=meta)
    first, second = records.cycles
    assert first.juld_descent_start is not None
    # TRANSMISSION_END is exactly one CycleTime (240 h = 10 d) later.
    assert second.juld_descent_start == pytest.approx(first.juld_descent_start + 10.0)
    assert first.juld_transmission_end == pytest.approx(first.juld_descent_start + 10.0)
    # PARK_END is DownTime + 2 h after descent start.
    assert first.juld_park_end == pytest.approx(first.juld_descent_start + 224.0 / 24.0)


def test_satellite_name_is_left_blank_on_surface_fixes() -> None:
    """All four references publish SATELLITE_NAME empty for ARGOS.

    The raw pass header does name the spacecraft, so this is a
    deliberate suppression: writing it would be a difference from the
    reference on every one of the 22 040 fixes.
    """
    telemetry = _telemetry(n_fixes=2)
    telemetry.fixes = [
        ArgosFix(
            at=datetime(2025, 12, 25, 7, 0, 0, tzinfo=UTC),
            latitude=-54.0,
            longitude=-160.0,
            location_class="2",
            satellite="M",
        )
    ]
    records = build_argos_trajectory_records([telemetry], meta=_meta())
    fixes = [
        m for m in records.measurements if m.measurement_code == TrajMeasurementCode.SURFACE_FIX
    ]
    assert fixes and all(m.satellite_name == "" for m in fixes)

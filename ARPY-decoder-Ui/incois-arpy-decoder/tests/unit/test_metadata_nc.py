"""Phase 6A.2: ADMT metadata (``<wmo>_meta.nc``) regression tests.

Structure, ordering, dtypes, attributes and fill conventions are pinned
against the six supplied GDAC ``<wmo>_meta.nc`` references, which share
an identical 65-variable layout.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import netCDF4
import numpy as np
import pytest

from argo_decoder.metadata.builder import _parameter_vectors
from argo_decoder.metadata.models import FloatMeta, SensorEntry
from argo_decoder.nc.admt import DOUBLE_FILL
from argo_decoder.nc.metadata_file import (
    build_metadata_dataset,
    numbered_block,
    write_metadata_file,
)

EXPECTED_DIMS = {
    "STRING2",
    "STRING4",
    "STRING8",
    "STRING16",
    "STRING32",
    "STRING64",
    "STRING128",
    "STRING256",
    "STRING1024",
    "DATE_TIME",
    "N_MISSIONS",
    "N_POSITIONING_SYSTEM",
    "N_TRANS_SYSTEM",
    "N_CONFIG_PARAM",
    "N_LAUNCH_CONFIG_PARAM",
    "N_PARAM",
    "N_SENSOR",
}

# First and last slices of the reference variable order.
ORDER_HEAD = [
    "DATA_TYPE",
    "FORMAT_VERSION",
    "HANDBOOK_VERSION",
    "DATE_CREATION",
    "DATE_UPDATE",
    "PLATFORM_NUMBER",
    "PTT",
    "TRANS_SYSTEM",
    "TRANS_SYSTEM_ID",
    "TRANS_FREQUENCY",
    "POSITIONING_SYSTEM",
    "PLATFORM_FAMILY",
    "PLATFORM_TYPE",
    "PLATFORM_MAKER",
    "FIRMWARE_VERSION",
]
ORDER_TAIL = [
    "SENSOR",
    "SENSOR_MAKER",
    "SENSOR_MODEL",
    "SENSOR_SERIAL_NO",
    "PARAMETER",
    "PARAMETER_SENSOR",
    "PARAMETER_UNITS",
    "PARAMETER_ACCURACY",
    "PARAMETER_RESOLUTION",
    "PREDEPLOYMENT_CALIB_EQUATION",
    "PREDEPLOYMENT_CALIB_COEFFICIENT",
    "PREDEPLOYMENT_CALIB_COMMENT",
]


def _meta() -> FloatMeta:
    return FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2902222",
            "PTT": "152389",
            "TRANS_SYSTEM": [{"TRANS_SYSTEM_1": "ARGOS"}],
            "TRANS_SYSTEM_ID": [{"TRANS_SYSTEM_ID_1": "n/a"}],
            "POSITIONING_SYSTEM": [{"POSITIONING_SYSTEM_1": "ARGOS"}],
            "PLATFORM_FAMILY": "FLOAT",
            "PLATFORM_TYPE": "APEX",
            "PLATFORM_MAKER": "WRC",
            "FIRMWARE_VERSION": "091615",
            "FLOAT_SERIAL_NO": "7532",
            "WMO_INST_TYPE": "846",
            "PROJECT_NAME": "Argo INDIA",
            "DATA_CENTRE": "IN",
            "PI_NAME": "M Ravichandran",
            "FLOAT_OWNER": "INCOIS",
            "OPERATING_INSTITUTION": "INCOIS",
            "LAUNCH_DATE": "20/01/2017 08:44:00",
            "LAUNCH_LATITUDE": -53.0,
            "LAUNCH_LONGITUDE": 68.1,
            "LAUNCH_QC": "1",
            "DEPLOYMENT_PLATFORM": "S.A. Agulhas",
            "CONFIG_MISSION_NUMBER": [{"CONFIG_MISSION_NUMBER_1": "0"}],
            "SENSOR": [{"SENSOR_1": "CTD_PRES", "SENSOR_2": "CTD_TEMP", "SENSOR_3": "CTD_CNDC"}],
            "SENSOR_MAKER": [
                {"SENSOR_MAKER_1": "n/a", "SENSOR_MAKER_2": "n/a", "SENSOR_MAKER_3": "n/a"}
            ],
            "PARAMETER": [{"PARAMETER_1": "PRES", "PARAMETER_2": "TEMP", "PARAMETER_3": "CNDC"}],
            "PARAMETER_SENSOR": [
                {
                    "PARAMETER_SENSOR_1": "CTD_PRES",
                    "PARAMETER_SENSOR_2": "CTD_TEMP",
                    "PARAMETER_SENSOR_3": "CTD_CNDC",
                }
            ],
            "PARAMETER_UNITS": [
                {
                    "PARAMETER_UNITS_1": "decibar",
                    "PARAMETER_UNITS_2": "degree_Celsius",
                    "PARAMETER_UNITS_3": "S/m",
                }
            ],
            "PARAMETER_ACCURACY": [
                {
                    "PARAMETER_ACCURACY_1": "2.4",
                    "PARAMETER_ACCURACY_2": "0.002",
                    "PARAMETER_ACCURACY_3": "0.005",
                }
            ],
        }
    )


def _build():
    return build_metadata_dataset(wmo=2902222, meta=_meta(), institution="IN")


def _written():
    ds = _build()
    tmp = tempfile.TemporaryDirectory()
    path = Path(tmp.name) / "2902222_meta.nc"
    write_metadata_file(ds, path)
    return tmp, netCDF4.Dataset(path)


def _chars(nc: netCDF4.Dataset, name: str) -> list[str]:
    arr = nc.variables[name][:]
    if arr.ndim == 0:
        item = arr.item()
        return [item.decode() if isinstance(item, bytes) else str(item)]
    return [str(v).strip() for v in np.asarray(netCDF4.chartostring(arr)).reshape(-1)]


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_all_metadata_dimensions_exist() -> None:
    tmp, nc = _written()
    with tmp:
        assert set(nc.dimensions) == EXPECTED_DIMS


def test_no_history_group_in_metadata_files() -> None:
    """Unlike profile/trajectory products, _meta.nc has no HISTORY."""
    ds = _build()
    assert not [n for n in ds.data_vars if str(n).startswith("HISTORY")]
    tmp, nc = _written()
    with tmp:
        assert "N_HISTORY" not in nc.dimensions


def test_variable_count_matches_reference() -> None:
    tmp, nc = _written()
    with tmp:
        assert len(nc.variables) == 65


def test_variable_order_matches_reference() -> None:
    tmp, nc = _written()
    with tmp:
        names = list(nc.variables)
        assert names[: len(ORDER_HEAD)] == ORDER_HEAD
        assert names[-len(ORDER_TAIL) :] == ORDER_TAIL


def test_n_missions_is_unlimited() -> None:
    tmp, nc = _written()
    with tmp:
        assert nc.dimensions["N_MISSIONS"].isunlimited()


def test_fixed_string_dimension_sizes() -> None:
    tmp, nc = _written()
    with tmp:
        for name, size in (
            ("STRING2", 2),
            ("STRING16", 16),
            ("STRING128", 128),
            ("STRING1024", 1024),
            ("DATE_TIME", 14),
        ):
            assert len(nc.dimensions[name]) == size


# ---------------------------------------------------------------------------
# Datatypes and fill values
# ---------------------------------------------------------------------------


def test_numeric_variable_dtypes_and_fills() -> None:
    ds = _build()
    assert ds["LAUNCH_LATITUDE"].dtype == np.float64
    assert ds["LAUNCH_LATITUDE"].attrs["_FillValue"] == np.float64(99999.0)
    assert ds["CONFIG_MISSION_NUMBER"].dtype == np.int32
    assert ds["CONFIG_MISSION_NUMBER"].attrs["_FillValue"] == np.int32(99999)
    assert ds["CONFIG_PARAMETER_VALUE"].dtype == np.float64


def test_scalar_qc_flags_are_zero_dimensional() -> None:
    tmp, nc = _written()
    with tmp:
        for name in ("LAUNCH_QC", "START_DATE_QC", "STARTUP_DATE_QC", "END_MISSION_STATUS"):
            assert nc.variables[name].dimensions == ()


def test_char_fill_value_is_blank() -> None:
    ds = _build()
    for name in ("DATA_TYPE", "PTT", "SENSOR", "PARAMETER"):
        assert ds[name].attrs["_FillValue"] == b" "


# ---------------------------------------------------------------------------
# Values traceable to metadata
# ---------------------------------------------------------------------------


def test_file_identity_scalars() -> None:
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "DATA_TYPE")[0] == "Argo meta-data"
        assert _chars(nc, "FORMAT_VERSION")[0] == "3.1"
        assert _chars(nc, "HANDBOOK_VERSION")[0] == "1.2"
        assert _chars(nc, "PLATFORM_NUMBER")[0] == "2902222"


def test_platform_fields_come_from_metadata() -> None:
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "PLATFORM_TYPE")[0] == "APEX"
        assert _chars(nc, "PLATFORM_MAKER")[0] == "WRC"
        assert _chars(nc, "FLOAT_SERIAL_NO")[0] == "7532"
        assert _chars(nc, "PI_NAME")[0] == "M Ravichandran"
        assert _chars(nc, "DATA_CENTRE")[0] == "IN"


def test_launch_position_and_normalised_date() -> None:
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "LAUNCH_DATE")[0] == "20170120084400"
        assert float(nc.variables["LAUNCH_LATITUDE"][:]) == pytest.approx(-53.0)
        assert float(nc.variables["LAUNCH_LONGITUDE"][:]) == pytest.approx(68.1)
        assert _chars(nc, "LAUNCH_QC")[0] == "1"


@pytest.mark.parametrize(
    "raw",
    ["20/01/2017 08:44:00", "2017-01-20T08:44:00", "2017-01-20 08:44:00", "20170120084400"],
)
def test_launch_date_formats_are_normalised(raw: str) -> None:
    meta = FloatMeta.model_validate({"PLATFORM_NUMBER": "1", "LAUNCH_DATE": raw})
    ds = build_metadata_dataset(wmo=1, meta=meta)
    decoded = netCDF4.chartostring(np.asarray(ds["LAUNCH_DATE"].values))
    assert str(decoded) == "20170120084400"


def test_end_mission_date_is_written_when_supplied() -> None:
    """The writer already supported the field; the date must not stay blank
    just because the builder used to hard-code an empty string."""
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "2901304",
            "END_MISSION_DATE": "20110922051440",
            "END_MISSION_STATUS": "T",
        }
    )
    ds = build_metadata_dataset(wmo=2901304, meta=meta)
    decoded = str(netCDF4.chartostring(np.asarray(ds["END_MISSION_DATE"].values)))
    assert decoded == "20110922051440"


def test_end_mission_date_stays_blank_when_not_supplied() -> None:
    """A live float with no declared end-of-mission must stay empty."""
    meta = FloatMeta.model_validate({"PLATFORM_NUMBER": "2902222", "END_MISSION_STATUS": ""})
    ds = build_metadata_dataset(wmo=2902222, meta=meta)
    decoded = str(netCDF4.chartostring(np.asarray(ds["END_MISSION_DATE"].values)))
    assert decoded.strip() == ""


def test_unparseable_date_is_blank_not_guessed() -> None:
    meta = FloatMeta.model_validate({"PLATFORM_NUMBER": "1", "LAUNCH_DATE": "sometime 2017"})
    ds = build_metadata_dataset(wmo=1, meta=meta)
    decoded = str(netCDF4.chartostring(np.asarray(ds["LAUNCH_DATE"].values)))
    assert decoded.strip() == ""


# ---------------------------------------------------------------------------
# Sensor / parameter ordering
# ---------------------------------------------------------------------------


def test_sensors_reordered_to_admt_convention() -> None:
    """All six references list CTD sensors as TEMP, CNDC, PRES."""
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "SENSOR") == ["CTD_TEMP", "CTD_CNDC", "CTD_PRES"]
        assert _chars(nc, "PARAMETER_SENSOR") == ["CTD_TEMP", "CTD_CNDC", "CTD_PRES"]


def test_parameter_block_follows_the_same_permutation() -> None:
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "PARAMETER") == ["TEMP", "CNDC", "PRES"]
        assert _chars(nc, "PARAMETER_UNITS") == ["degree_Celsius", "S/m", "decibar"]
        assert _chars(nc, "PARAMETER_ACCURACY") == ["0.002", "0.005", "2.4"]


def test_cndc_sensor_reports_psal_as_the_parameter() -> None:
    """``PARAMETER`` carries the reported parameter, not the sensor quantity.

    A CTD conductivity cell measures CNDC, but every DAC publishes the
    derived PSAL: 10/10 GDAC ``_meta.nc`` references across incois,
    coriolis, bodc and aoml read ``PARAMETER_SENSOR='CTD_CNDC'`` paired
    with ``PARAMETER='PSAL'``, and none lists ``CNDC``.
    """
    sensors = [SensorEntry(sensor="CTD_TEMP"), SensorEntry(sensor="CTD_CNDC")]
    blocks = _parameter_vectors(sensors)
    assert blocks["PARAMETER"] == [{"PARAMETER_1": "TEMP", "PARAMETER_2": "PSAL"}]
    assert blocks["PARAMETER_SENSOR"] == [
        {"PARAMETER_SENSOR_1": "CTD_TEMP", "PARAMETER_SENSOR_2": "CTD_CNDC"}
    ]
    assert "CNDC" not in blocks["PARAMETER"][0].values()


def test_parameter_units_use_the_incois_gdac_strings() -> None:
    """Unit strings match the publishing DAC, verified against GDAC.

    INCOIS writes ``deg C`` / ``Siemens/meter`` / ``decibars`` in 5/5
    sampled APEX and ARVOR floats. These are a DAC house convention
    rather than the NVS R03 vocabulary (which says ``degree_Celsius`` /
    ``psu`` / ``decibar``); we follow our publishing DAC.
    """
    sensors = [
        SensorEntry(sensor="CTD_TEMP"),
        SensorEntry(sensor="CTD_CNDC"),
        SensorEntry(sensor="CTD_PRES"),
    ]
    blocks = _parameter_vectors(sensors)
    assert blocks["PARAMETER_UNITS"] == [
        {
            "PARAMETER_UNITS_1": "deg C",
            "PARAMETER_UNITS_2": "Siemens/meter",
            "PARAMETER_UNITS_3": "decibars",
        }
    ]


def test_unknown_sensors_are_kept_not_dropped() -> None:
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "1",
            "SENSOR": [{"SENSOR_1": "CTD_PRES", "SENSOR_2": "OPTODE_DOXY", "SENSOR_3": "CTD_TEMP"}],
        }
    )
    ds = build_metadata_dataset(wmo=1, meta=meta)
    values = [
        str(v).strip()
        for v in np.asarray(netCDF4.chartostring(np.asarray(ds["SENSOR"].values))).reshape(-1)
    ]
    assert set(values) == {"CTD_TEMP", "CTD_PRES", "OPTODE_DOXY"}
    assert values[:2] == ["CTD_TEMP", "CTD_PRES"]


# ---------------------------------------------------------------------------
# Honest handling of unavailable metadata
# ---------------------------------------------------------------------------


def test_not_available_tokens_become_blank() -> None:
    """'n/a' is a registry placeholder, not a real value.

    ...except in the fields where the Argo User's Manual asks for an
    explicit not-applicable marker (see
    :data:`_NOT_AVAILABLE_SIGNIFICANT_KEYS`), which are covered by
    :func:`test_not_available_kept_where_manual_requires_it`.
    """
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "SENSOR_MAKER") == ["", "", ""]


def test_not_available_kept_where_manual_requires_it() -> None:
    """Argo User's Manual 3.44.0 §2.4.4 sanctions 'n/a' for these.

    TRANS_SYSTEM_ID / TRANS_FREQUENCY describe an ARGOS subscription;
    on a non-ARGOS platform the manual states DACs "can use N/A ... when
    not applicable (e.g. : Iridium or Orbcomm)". Blanking the token would
    conflate "not applicable" with "not recorded".
    """
    tmp, nc = _written()
    with tmp:
        assert _chars(nc, "TRANS_SYSTEM_ID") == ["n/a"]


def test_absent_metadata_is_blank_not_invented() -> None:
    ds = build_metadata_dataset(wmo=1, meta=None)
    for name in ("BATTERY_TYPE", "MANUAL_VERSION", "CONTROLLER_BOARD_TYPE_PRIMARY"):
        decoded = str(netCDF4.chartostring(np.asarray(ds[name].values)))
        assert decoded.strip() == ""


def test_empty_config_block_yields_single_fill_valued_entry() -> None:
    """The registry carries no mission programming for these floats.

    The block is clamped to one entry rather than left at length zero:
    ``netCDF4.createDimension(name, 0)`` defines a *record* dimension, and
    NETCDF3_CLASSIC allows only one of those per file. The Coriolis chain
    clamps identically
    (``create_nc_meta_file_3_1_from_json_float_meta.m:248-256``). The single
    entry must stay empty -- absent configuration is never invented.
    """
    ds = _build()
    assert ds.sizes["N_CONFIG_PARAM"] == 1
    assert ds.sizes["N_LAUNCH_CONFIG_PARAM"] == 1
    for name in ("CONFIG_PARAMETER_NAME", "LAUNCH_CONFIG_PARAMETER_NAME"):
        decoded = netCDF4.chartostring(np.asarray(ds[name].values))
        assert str(decoded[0]).strip() == ""
    assert np.asarray(ds["CONFIG_PARAMETER_VALUE"].values)[0, 0] == DOUBLE_FILL
    assert np.asarray(ds["LAUNCH_CONFIG_PARAMETER_VALUE"].values)[0] == DOUBLE_FILL


def test_no_dimension_is_zero_length() -> None:
    """A zero-length dimension would become a spurious record dimension."""
    ds = _build()
    zero = [name for name, size in ds.sizes.items() if int(size) == 0]
    assert zero == []


def test_config_mission_number_is_one_based() -> None:
    """ADMT states '1 : first complete mission'; registry stores 0."""
    ds = _build()
    assert int(np.asarray(ds["CONFIG_MISSION_NUMBER"].values)[0]) == 1


def test_config_mission_number_defaults_when_absent() -> None:
    meta = FloatMeta.model_validate({"PLATFORM_NUMBER": "1"})
    ds = build_metadata_dataset(wmo=1, meta=meta)
    assert int(np.asarray(ds["CONFIG_MISSION_NUMBER"].values)[0]) == 1


# ---------------------------------------------------------------------------
# Global attributes and helpers
# ---------------------------------------------------------------------------


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
    assert ds.attrs["title"] == "Argo float metadata file"
    assert ds.attrs["institution"] == "INCOIS"


def test_metadata_has_no_feature_type() -> None:
    """There is no geophysical feature in a metadata file."""
    assert "featureType" not in _build().attrs


def test_numbered_block_reads_in_index_order() -> None:
    meta = FloatMeta.model_validate(
        {"PLATFORM_NUMBER": "1", "SENSOR": [{"SENSOR_2": "B", "SENSOR_1": "A"}]}
    )
    assert numbered_block(meta, "SENSOR") == ["A", "B"]


def test_numbered_block_handles_absent_metadata() -> None:
    assert numbered_block(None, "SENSOR") == []


def test_numbered_block_keeps_leading_space_only_for_calib_equation() -> None:
    """The published SBE41 conductivity equation starts with a space.

    Verified byte-identical on the 2901304, 2901305, 2901339, 2902201,
    2902222, 2902223 and 2902224 GDAC references, so the writer copies
    ``PREDEPLOYMENT_CALIB_EQUATION`` verbatim. Every other block keeps the
    ordinary strip, since leading whitespace there is spreadsheet noise.
    """
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "1",
            "PREDEPLOYMENT_CALIB_EQUATION": [{"PREDEPLOYMENT_CALIB_EQUATION_1": " f = inst freq"}],
            "SENSOR": [{"SENSOR_1": " CTD_PRES "}],
        }
    )
    assert numbered_block(meta, "PREDEPLOYMENT_CALIB_EQUATION") == [" f = inst freq"]
    assert numbered_block(meta, "SENSOR") == ["CTD_PRES"]


def test_numbered_block_still_blanks_not_available_tokens_when_padded() -> None:
    """A whitespace-significant block must not publish a padded 'n/a'."""
    meta = FloatMeta.model_validate(
        {
            "PLATFORM_NUMBER": "1",
            "PREDEPLOYMENT_CALIB_EQUATION": [{"PREDEPLOYMENT_CALIB_EQUATION_1": " n/a "}],
        }
    )
    assert numbered_block(meta, "PREDEPLOYMENT_CALIB_EQUATION") == [""]


# ---------------------------------------------------------------------------
# Transmission vs positioning, and controller-board typing
# ---------------------------------------------------------------------------


class TestPositioningSystemIsNotTheCommsSystem:
    """Argo reference table 9 (positioning) != reference table 10 (transmission).

    A store-and-forward satellite link carries no location of its own:
    the float fixes itself with GNSS and transmits that fix. ARGOS is the
    exception, being a Doppler positioning system in its own right.
    """

    def test_argos_positions_itself(self):
        from argo_decoder.metadata.multi_csv_loader import _positioning_system

        assert _positioning_system("ARGOS") == "ARGOS"

    def test_satellite_links_use_gnss(self):
        from argo_decoder.metadata.multi_csv_loader import _positioning_system

        for comms in ("IRIDIUM", "iridium", "ORBCOMM", "BEIDOU"):
            assert _positioning_system(comms) == "GPS"


class TestControllerBoardType:
    """Argo reference table 28 has no ``APF0``; don't invent codes."""

    def test_apex_serials_keep_apf9(self):
        from argo_decoder.metadata.multi_csv_loader import _controller_board_type

        for serial in ("9A-7319", "9G-10795", "9I-9308"):
            assert _controller_board_type(serial) == "APF9"

    def test_placeholder_serial_is_not_applicable(self):
        """``0i-0`` carries no generation -- must not become ``APF0``."""
        from argo_decoder.metadata.multi_csv_loader import _controller_board_type

        assert _controller_board_type("0i-0") == "n/a"

    def test_empty_serial_stays_blank(self):
        from argo_decoder.metadata.multi_csv_loader import _controller_board_type

        assert _controller_board_type("") == ""


class TestStartDateQcPairing:
    """START_DATE_QC always carries an Argo reference table 2 code.

    Blank is not a member of table 2, and the GDAC FileChecker rejects it
    (CK_0122: "START_DATE_QC: ' ' Status: Invalid"). When START_DATE is
    absent the honest code is '9' -- "Missing Value" -- rather than '1'
    ("Good data"), which would assert quality for a value we never
    published.
    """

    def test_blank_start_date_gets_missing_value_qc(self):
        from argo_decoder.metadata.builder import build_meta
        from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

        loader = MultiCsvLoader(Path("config/metadata"))
        row = loader.get_float(1902844)
        meta = build_meta(row)
        assert meta.start_date == ""
        assert meta.start_date_qc == "9"  # ref table 2: Missing Value

    def test_present_start_date_gets_good_qc(self):
        """A populated START_DATE takes '1'; the rule is value-driven.

        Guards against the flag becoming a constant: it must track the
        presence of the date, so a future four-CSV deployment-date column
        yields '1' with no further code change.
        """
        from argo_decoder.metadata.builder import build_meta
        from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

        loader = MultiCsvLoader(Path("config/metadata"))
        row = loader.get_float(1902844)
        row.start_date_utc = datetime(2026, 1, 19, 19, 21, 47, tzinfo=UTC)
        meta = build_meta(row)
        assert meta.start_date != ""
        assert meta.start_date_qc == "1"


class TestArvorIStartDateDerivation:
    """START_DATE from the decoded first descent (UM 3.44.0 §2.4.5).

    The manual defines START_DATE as the "Date (UTC) of the first descent
    of the float". Trajectory Cookbook 6.1 §2.2 (p.19) defines DST
    (MC 100) as the "Time when float leaves the surface, beginning
    descent" -- the same instant -- and its Arvor annex (p.99) records DST
    as transmitted by the float, so the value is derivable rather than
    fill.
    """

    def test_uses_dst_not_cycle_start(self):
        """MC 89 is buoyancy-reduction start, still at the surface."""
        import sys

        sys.path.insert(0, "scripts")
        from validate_arvor_i_rtraj import science

        from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
            _first_descent_utc,
        )

        result = science(7902408)
        first = _first_descent_utc(result)
        assert first is not None
        starts = [
            c.timing.descent_to_park_start
            for c in result.cycles
            if c.timing is not None and c.timing.descent_to_park_start is not None
        ]
        cycle_starts = [
            c.timing.cycle_start
            for c in result.cycles
            if c.timing is not None and c.timing.cycle_start is not None
        ]
        # DST is the earliest descent; cycle start precedes it.
        assert min(starts) == pytest.approx(
            (first - datetime(1950, 1, 1, tzinfo=UTC)).total_seconds() / 86400.0,
            abs=1e-9,
        )
        assert min(cycle_starts) < min(starts), "MC 89 must precede MC 100"

    def test_no_dated_descent_leaves_field_fill(self):
        """Absent telemetry the field stays fill -- never invented."""
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
            _first_descent_utc,
        )

        assert _first_descent_utc(None) is None

    def test_qc_tracks_the_derived_value(self):
        """'1' once a date is published, '9' while it is not."""
        from datetime import datetime as _dt

        from argo_decoder.platforms.provor_ir_sbd.arvor_i_meta import (
            build_arvor_float_meta,
        )

        meta = build_arvor_float_meta(
            wmo=7902408, launch_date=_dt(2026, 3, 25, tzinfo=UTC), result=None
        )
        assert meta.start_date == ""
        assert meta.start_date_qc == "9"

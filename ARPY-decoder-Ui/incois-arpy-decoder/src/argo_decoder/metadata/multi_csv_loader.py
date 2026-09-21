"""Four-CSV metadata backend.

Replaces the single ``registry.csv`` with the four operational
spreadsheets INCOIS maintains per deployment:

``meta.csv``
    One row per float: identity, launch, hardware serials, deployment.
``sensor-info.csv``
    One row per float: CTD/pressure/oxygen makers, models, serials,
    firmware revision, comms and battery configuration.
``calib.csv``
    One row per float: the Sea-Bird pre-deployment calibration
    coefficients (PA0..PTHA2, TA0..TA3, G..WBOTC) plus accuracies.
``config_params.csv``
    One row per float: the ``CONFIG_*`` mission programming, using the
    Argo-approved parameter names as column headers.

The four sheets are joined on ``WMO id`` and projected onto the existing
:class:`~argo_decoder.metadata.models.FloatRegistryRow`, so the rest of
the pipeline -- and the decoder itself -- is unchanged. The JSON contract
(``<wmo>_<ptt>_info.json`` / ``<wmo>_meta.json``) is produced by the same
:mod:`argo_decoder.metadata.builder` used by the single-CSV backend.

Source-of-truth policy
----------------------
Several quantities appear in more than one sheet, and the copies do not
agree (verified against the GDAC references, see
``docs/phase_reports/METADATA_MIGRATION_REPORT.md``). Rather than
inventing a precedence rule, each field is read from exactly one
authoritative sheet:

===========================  ==================  ============================
Field                        Authoritative       Why
===========================  ==================  ============================
``CONFIG_*``                 config_params.csv   14/14 match GDAC
                                                 ``LAUNCH_CONFIG_PARAMETER``
                                                 for 2902222; the meta.csv
                                                 copies are stale or in days
``firmware_version``         sensor-info.csv     matches GDAC
                                                 ``FIRMWARE_VERSION``; the
                                                 config_params
                                                 "firmware date" column
                                                 disagrees (20811 vs 61810)
``manual_version``           config_params.csv   "manual date" matches GDAC
                                                 ``MANUAL_VERSION``
``sensor serials/makers``    sensor-info.csv     the dedicated sheet
``calibration``              calib.csv           the dedicated sheet
``identity / launch``        meta.csv            the dedicated sheet
===========================  ==================  ============================

``Float subtype`` is **not** the Coriolis decoder id: it is the Argo
``DAC_FORMAT_ID`` (confirmed across 11 INCOIS floats -- e.g. 2902222
carries 1021 there but decodes with id 1010). Decoder identity is
therefore derived from the firmware revision, exactly as before.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from argo_decoder.metadata import builder as _builder
from argo_decoder.metadata.models import (
    FloatInfo,
    FloatMeta,
    FloatRegistryRow,
    SensorCalibration,
    SensorEntry,
)
from argo_decoder.util.logging import get_logger

#: Canonical file names inside the metadata directory.
META_CSV = "meta.csv"
SENSOR_CSV = "sensor-info.csv"
CALIB_CSV = "calib.csv"
CONFIG_CSV = "config_params.csv"

#: Firmware revision -> Coriolis MATLAB decoder id.
#:
#: The spreadsheets carry no decoder id (``Float subtype`` is the Argo
#: ``DAC_FORMAT_ID``, not the decoder). Firmware is the reliable key, and
#: this is the same mapping ``scripts/registry_row_from_meta_nc.py``
#: already used to onboard floats from GDAC metadata.
FIRMWARE_TO_DECODER: dict[str, int] = {
    "061810": 1005,
    "110613": 1010,
    "090413": 1010,
    "102015": 1010,
    "091515": 1010,
    "091615": 1010,
    "100410": 1010,
    "020811": 1010,
}

#: DAC-wide constants. Verified invariant across an 11-float INCOIS GDAC
#: sample (2900103, 2901288, 2901304, 2901305, 2901339, 2902155, 2902201,
#: 2902222, 2902223, 2902224, 2902269, 2902276): every one carries these
#: identical values, so they belong in configuration rather than in a
#: per-float spreadsheet column.
INCOIS_DEFAULTS: dict[str, str] = {
    "data_centre": "IN",
    "pi_name": "M Ravichandran",
    "project_name": "Argo INDIA",
    "float_owner": "INCOIS",
    "operating_institution": "INCOIS",
}

#: ``BATTERY_TYPE`` is ``Alkaline`` on 11/11 sampled INCOIS floats even
#: where the pack string mentions lithium, so the sheet's "battery
#: config" column populates ``BATTERY_PACKS`` and the type comes from
#: this DAC-wide default.
DEFAULT_BATTERY_TYPE = "Alkaline"

#: ``(accuracy, resolution)`` published for every CTD parameter. All six
#: sampled INCOIS APEX floats carry ``0`` for both, including the two
#: with no calibration sheet.
INCOIS_DEFAULT_ACCURACY = ("0", "0")

#: ARGOS transmission identity as published by INCOIS. ``TRANS_SYSTEM_ID``
#: is the Argos *programme* number (02602 on 9/9 ARGOS floats sampled),
#: not the platform PTT, and the frequency is the standard Argos uplink.
#: The sheet's "argos frequency" column carries the word STANDARD, which
#: is the programme's own shorthand for this value.
ARGOS_TRANS_SYSTEM_ID = "02602"
ARGOS_TRANS_FREQUENCY = "401.65 x 10^6"

#: Argo User's Manual 3.44.0 §2.4.4 sanctions an explicit
#: not-applicable marker for transmission fields that only describe an
#: ARGOS subscription ("DACs can use N/A or alternative of their choice
#: when not applicable (e.g. : Iridium or Orbcomm)").  ``n/a`` is the
#: spelling used by the Coriolis reference float-info JSON and by the
#: INCOIS GDAC references for these Iridium hulls.
NOT_APPLICABLE = "n/a"

#: Sheet spelling -> Argo reference table 26 (``SENSOR_MAKER``) code.
#:
#: ``SENSOR_MAKER`` names the firm that *built the transducer*, not the
#: firm that integrated it. Reference table 27 encodes this as a SKOS
#: ``broader`` link from each ``SENSOR_MODEL`` to its one legal maker, and
#: the GDAC file checker enforces it (``CK_0164``,
#: ``ArgoMetadataFileValidator.java:1032``): model ``DRUCK`` -> maker
#: ``DRUCK``, model ``KISTLER`` -> maker ``KISTLER``, model ``SBE41`` ->
#: maker ``SBE``. Only the CTD module itself is Sea-Bird; the pressure
#: transducer inside it keeps its own manufacturer, exactly as AOML,
#: Coriolis, CSIRO and BODC publish it.
#:
#: The DRUCK -> SBE entry that used to live here made every INCOIS APEX
#: ``_meta.nc`` fail the checker with
#: ``SENSOR_MODEL/SENSOR_MAKER[3]: Inconsistent: 'DRUCK'/'SBE'``.
SENSOR_MAKER_CANONICAL = {
    "SEABIRD": "SBE",
    "SBE": "SBE",
    "DRUCK": "DRUCK",
    "KISTLER": "KISTLER",
}

#: Webb Research Corporation is published as ``WRC`` (10/10 APEX floats);
#: the sheets spell it "webb".
PLATFORM_MAKER_CANONICAL = {"WEBB": "WRC", "WRC": "WRC", "ARVOR": "NKE", "NKE": "NKE"}

#: Sea-Bird SBE41 pre-deployment calibration equations.
#:
#: Verified constant per sensor model, not per float: across the 11-float
#: INCOIS sample every ``CTD_PRES`` / ``CTD_TEMP`` / ``CTD_CNDC`` entry is
#: byte-identical (md5 f29a4f8a / a02716ed / 7b62fc10), spanning APEX and
#: PROVOR hulls and firmware 061810 through 091615. They are therefore a
#: shared default keyed by measured quantity, while the *coefficients*
#: stay per-float from ``calib.csv``.
#:
#: Stored in GDAC emission order (pressure, temperature, conductivity),
#: which is the order the references use for the
#: ``PREDEPLOYMENT_CALIB_*`` blocks.
SBE41_CALIB_EQUATIONS: dict[str, str] = {
    "PRES": (
        "y=thermistor output; t=PTHA0+PTHA1*y+PTHA2*y^2; "
        "x=pressure output-PTCA0+PTCA1*t+PTCA2*t^2; "
        "n=x*PTCB0/(PTCB0+PTCB1*t+PTCB2*t^2); "
        "pressure (psia)=PA0+PA1*n+PA2*n^2"
    ),
    "TEMP": (
        "Temperature ITS-90 = 1/ { a0 + a1[lambda nu (n)] + "
        "a2 [lambda nu^2 (n)] + a3 [lambda nu^3 (n)]} - 273.15 (deg C)"
    ),
    # The conductivity string carries a leading space in every published
    # reference (verified byte-identical, md5 7b62fc10, on 2901304,
    # 2901305, 2901339, 2902201, 2902222, 2902223 and 2902224). It is
    # preserved rather than trimmed so the emitted block matches.
    "PSAL": (
        " f = inst freq * sqrt(1.0 + WBOTC * t) / 1000.0; t = temperature [deg C]; "
        "p = pressure [decibars]; delta = CTcor; epsilon = CPcor; "
        "Conductivity = (g + hf^2 + if^3 + jf^4)/(1+ delta t + epsilon p) Siemens/meter"
    ),
}

#: Coefficient groups, in the order the GDAC references emit them.
_PRES_COEFFS = (
    "PA0",
    "PA1",
    "PA2",
    "PTCA0",
    "PTCA1",
    "PTCA2",
    "PTCB0",
    "PTCB1",
    "PTCB2",
    "PTHA0",
    "PTHA1",
    "PTHA2",
)
_TEMP_COEFFS = ("TA0", "TA1", "TA2", "TA3")
_CNDC_COEFFS = ("G", "H", "I", "J", "CPCOR", "CTCOR", "WBOTC")


def _clean(value: Any) -> str:
    """Normalise a spreadsheet cell to a stripped string."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none"} else text


def _read_csv(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV into a list of cleaned dicts."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [{k: _clean(v) for k, v in row.items() if k} for row in csv.DictReader(handle)]


def _index_by_wmo(rows: list[dict[str, str]], column: str = "WMO id") -> dict[int, dict[str, str]]:
    """Key rows by integer WMO, ignoring rows without a usable WMO."""
    out: dict[int, dict[str, str]] = {}
    for row in rows:
        raw = row.get(column, "")
        try:
            wmo = int(float(raw))
        except (TypeError, ValueError):
            continue
        out[wmo] = row
    return out


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_str(value: str) -> str:
    """Render a spreadsheet number as an integer string when exact.

    Excel round-trips integers as ``7532.0``; the JSON contract and the
    GDAC references carry ``7532``.
    """
    number = _num(value)
    if number is None:
        return value
    return str(int(number)) if number == int(number) else value


def _zero_padded_firmware(value: str) -> str:
    """Normalise a firmware revision to the 6-digit MMDDYY form.

    The sheets store it numerically, so ``061810`` arrives as ``61810``.
    """
    digits = _int_str(value)
    return digits.zfill(6) if digits.isdigit() and len(digits) in (5, 6) else digits


#: Sea-Bird labels the temperature coefficients ``A0..A3`` in the
#: published string even though the calibration sheet column is
#: ``TA0..TA3`` (verified against every GDAC INCOIS reference).
_COEFF_LABELS = {"TA0": "A0", "TA1": "A1", "TA2": "A2", "TA3": "A3"}


def _pressure_number(value: float) -> str:
    """Format a pressure coefficient the way the GDAC references do.

    Reverse-engineered from the published strings and verified to
    reproduce all 12 coefficients byte-for-byte on WMO 2902222, 2902223
    and 2902224: magnitudes >= 1 are rounded to four decimals with
    trailing zeros trimmed (25.1785, -19.3599, -73.2551), everything
    smaller falls back to five significant digits (-0.043144,
    -3.3056e-08).

    Note the two branches coincide for every coefficient in the current
    archive -- the ``>= 1`` values all fit inside six significant digits,
    so a plain ``%g`` produces the same text there. The explicit
    four-decimal rounding is kept because it is what the reference
    actually documents, and it stays correct for a future sensor whose
    coefficients need more digits.
    """
    if value == 0:
        return "0"
    if abs(value) >= 1:
        return format(round(value, 4), ".4f").rstrip("0").rstrip(".")
    return format(value, ".5g")


def _format_coefficients(names: Iterable[str], row: dict[str, str], fmt: str) -> str:
    """Render ``NAME = value`` pairs using the GDAC label and spacing."""
    parts = []
    for name in names:
        number = _num(row.get(name, ""))
        if number is None:
            continue
        label = _COEFF_LABELS.get(name, name)
        rendered = _pressure_number(number) if fmt == "pressure" else format(number, fmt)
        parts.append(f"{label} = {rendered}")
    return " ".join(parts)


def build_calibrations(calib_row: dict[str, str]) -> list[SensorCalibration]:
    """Build the three SBE41 calibration records from a ``calib.csv`` row.

    Emitted in GDAC order (pressure, temperature, conductivity) with the
    reference's own number formatting: pressure coefficients use ``%g``
    (significant digits), temperature and conductivity use ``%8.4f``.

    With no calibration row the *equations* are still emitted: they are a
    property of the SBE41 sensor model, byte-identical across all eleven
    sampled INCOIS floats, so publishing them asserts nothing about the
    individual instrument. The coefficients stay empty -- they are
    genuinely per-float and are never guessed.
    """
    if not calib_row:
        return [
            SensorCalibration(parameter=parameter, equation=equation, coefficients={}, comment="")
            for parameter, equation in SBE41_CALIB_EQUATIONS.items()
        ]
    serial = _int_str(calib_row.get("SBE serial number", ""))
    prefix = f"ser# = {serial} " if serial else ""
    groups = (
        ("PRES", "pressure coeffs", _PRES_COEFFS, "pressure"),
        ("TEMP", "temperature coeffs", _TEMP_COEFFS, "8.4f"),
        ("PSAL", "conductivity coeffs", _CNDC_COEFFS, "8.4f"),
    )
    out: list[SensorCalibration] = []
    for parameter, label, names, fmt in groups:
        body = _format_coefficients(names, calib_row, fmt)
        if not body:
            continue
        coefficients = {n: v for n in names if (v := _num(calib_row.get(n, ""))) is not None}
        out.append(
            SensorCalibration(
                parameter=parameter,
                equation=SBE41_CALIB_EQUATIONS[parameter],
                coefficients=coefficients,
                comment=f"{prefix}{label}: {body}",
            )
        )
    return out


def build_config_parameters(config_row: dict[str, str]) -> list[tuple[str, str]]:
    """Extract ``(CONFIG_name, value)`` pairs in spreadsheet column order.

    Only populated cells become entries, which is what reproduces the
    GDAC reference exactly: for 2902222 the 14 non-empty ``CONFIG_*``
    columns are precisely the 14 ``LAUNCH_CONFIG_PARAMETER_NAME`` entries,
    in the same order.
    """
    out: list[tuple[str, str]] = []
    for key, value in config_row.items():
        if not key.startswith("CONFIG_") or not value:
            continue
        out.append((key, _int_str(value)))
    return out


#: calib.csv accuracy/resolution column per measured parameter.
_ACCURACY_COLUMNS = {
    "PRES": ("Press acc", "Press res"),
    "TEMP": ("Temp acc", "Temp res"),
    "PSAL": ("Cond acc", "Cond res"),
}


def build_accuracy(calib_row: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Return ``{parameter: (accuracy, resolution)}`` from ``calib.csv``.

    The sheet is the authoritative source. Where a float has no
    calibration row the DAC-wide default applies instead of the
    manufacturer specification: all six sampled INCOIS APEX floats
    publish ``PARAMETER_ACCURACY`` and ``PARAMETER_RESOLUTION`` as
    ``0, 0, 0``, including the two with no calibration sheet, so a zero
    here reports the DAC's own convention rather than asserting a
    measurement we do not have.
    """
    if not calib_row:
        return dict.fromkeys(_ACCURACY_COLUMNS, INCOIS_DEFAULT_ACCURACY)
    out: dict[str, tuple[str, str]] = {}
    for parameter, (acc_col, res_col) in _ACCURACY_COLUMNS.items():
        acc, res = calib_row.get(acc_col, ""), calib_row.get(res_col, "")
        if acc == "" and res == "":
            out[parameter] = INCOIS_DEFAULT_ACCURACY
            continue
        out[parameter] = (_int_str(acc), _int_str(res))
    return out


def _sensors_from_rows(
    sensor_row: dict[str, str],
    calibrations: list[SensorCalibration],
    accuracy: dict[str, tuple[str, str]] | None = None,
) -> list[SensorEntry]:
    """Build the CTD sensor triple from ``sensor-info.csv``.

    Ordered PRES, TEMP, CNDC -- the registry convention; the metadata
    writer permutes to the ADMT publication order.
    """
    ctd_maker = SENSOR_MAKER_CANONICAL.get(sensor_row.get("CTD mfg", "").upper(), "SBE")
    ctd_model = sensor_row.get("CTD Sensor Type", "")
    ctd_serial = _int_str(sensor_row.get("CTD serial number", ""))
    pres_maker_raw = sensor_row.get("Pressure sensor mfg", "")
    # The sheet's "Pressure sensor mfg" column names the transducer
    # brand, which is simultaneously the reference-table-27 code for that
    # transducer at unknown pressure rating (``DRUCK`` = "Druck pressure
    # sensor with unknown pressure rating"). Model and maker are therefore
    # the same token for these instruments; uppercasing means a sheet that
    # spells it "Druck" still emits the valid code.
    pres_model = pres_maker_raw.upper() if pres_maker_raw else ""
    pres_maker = SENSOR_MAKER_CANONICAL.get(pres_model, pres_model)
    pres_serial = _int_str(sensor_row.get("Pressure sensor serial #", ""))
    by_parameter = {c.parameter: [c] for c in calibrations}
    acc = accuracy or {}

    def extras(parameter: str) -> dict[str, str]:
        if parameter not in acc:
            return {}
        a, r = acc[parameter]
        return {"accuracy": a, "resolution": r}

    return [
        SensorEntry(
            sensor="CTD_PRES",
            make=pres_maker,
            model=pres_model,
            serial=pres_serial,
            calibration=by_parameter.get("PRES", []),
            **extras("PRES"),
        ),
        SensorEntry(
            sensor="CTD_TEMP",
            make=ctd_maker,
            model=ctd_model,
            serial=ctd_serial,
            calibration=by_parameter.get("TEMP", []),
            **extras("TEMP"),
        ),
        SensorEntry(
            sensor="CTD_CNDC",
            make=ctd_maker,
            model=ctd_model,
            serial=ctd_serial,
            calibration=by_parameter.get("PSAL", []),
            **extras("PSAL"),
        ),
    ]


def _launch_datetime(value: str) -> str:
    """Convert the sheet's ``YYYYMMDDHHMMSS`` stamp to ISO-8601 Z."""
    digits = _int_str(value)
    if len(digits) != 14 or not digits.isdigit():
        return digits
    return (
        f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}T{digits[8:10]}:{digits[10:12]}:{digits[12:14]}Z"
    )


#: Sheet columns that would carry a genuine operator-declared
#: ``START_DATE``. None of the four CSVs supplies one today, but Coriolis
#: sources this field from the operator database
#: (``generate_json_float_meta_apx_argos_.m:1015``), so the hook is kept
#: for when the column is added. ``start marker`` is deliberately absent:
#: it is a row delimiter, not a date.
_START_DATE_COLUMNS: tuple[str, ...] = ("start date", "start_date", "first descent date")


def _start_datetime(meta: Mapping[str, str]) -> str:
    """Operator-declared ``START_DATE`` as ISO-8601 Z, or empty.

    Empty is the correct answer when the sheets do not state one: the
    launch time is a *different* instant (Argo User Manual v3.3 §2.4
    defines LAUNCH_DATE, STARTUP_DATE and START_DATE separately), so
    substituting it would publish a value the operator never gave.
    """
    for column in _START_DATE_COLUMNS:
        raw = meta.get(column, "")
        if raw and raw.strip():
            return _launch_datetime(raw)
    return ""


class MultiCsvLoader:
    """Join the four metadata CSVs into :class:`FloatRegistryRow` records.

    Presents the same ``MetadataLoader`` protocol as ``CsvLoader``, so
    ``metadata_stage`` can swap backends without touching the decoder.
    """

    def __init__(
        self,
        metadata_dir: Path | str,
        *,
        materialized_dir: Path | str | None = None,
        strict: bool = False,
        defaults: dict[str, str] | None = None,
    ) -> None:
        self.metadata_dir = Path(metadata_dir)
        self.materialized_dir = Path(materialized_dir) if materialized_dir else None
        self.strict = strict
        self.defaults = dict(INCOIS_DEFAULTS if defaults is None else defaults)
        self._rows: dict[int, FloatRegistryRow] | None = None
        self._log = get_logger().bind(component="MultiCsvLoader")

    # ----- MetadataLoader protocol ---------------------------------------
    def name(self) -> str:
        return f"multi-csv:{self.metadata_dir}"

    def get_float(self, wmo: int) -> FloatRegistryRow | None:
        self._ensure_loaded()
        assert self._rows is not None
        return self._rows.get(int(wmo))

    def iter_floats(self, wmos: Iterable[int] | None = None) -> Iterator[FloatRegistryRow]:
        self._ensure_loaded()
        assert self._rows is not None
        wanted = {int(w) for w in wmos} if wmos is not None else None
        for wmo, row in self._rows.items():
            if wanted is None or wmo in wanted:
                yield row

    def load_info(self, wmo: int) -> FloatInfo:
        row = self._require(wmo)
        info = _builder.build_info(row)
        if self.materialized_dir is not None:
            _builder.write_info_json(info, self.materialized_dir)
        return info

    def load_meta(self, wmo: int) -> FloatMeta:
        row = self._require(wmo)
        meta = _builder.build_meta(row)
        if self.materialized_dir is not None:
            _builder.write_meta_json(meta, self.materialized_dir)
        return meta

    # ----- internals ------------------------------------------------------
    def _require(self, wmo: int) -> FloatRegistryRow:
        row = self.get_float(wmo)
        if row is None:
            raise FileNotFoundError(
                f"WMO {wmo} not present in metadata CSVs at {self.metadata_dir}"
            )
        return row

    def _ensure_loaded(self) -> None:
        if self._rows is not None:
            return
        meta_rows = _index_by_wmo(_read_csv(self.metadata_dir / META_CSV))
        sensor_rows = _index_by_wmo(_read_csv(self.metadata_dir / SENSOR_CSV))
        calib_rows = _index_by_wmo(_read_csv(self.metadata_dir / CALIB_CSV))
        config_rows = _index_by_wmo(_read_csv(self.metadata_dir / CONFIG_CSV))

        rows: dict[int, FloatRegistryRow] = {}
        for wmo in sorted(meta_rows):
            try:
                rows[wmo] = self._build_row(
                    wmo,
                    meta_rows[wmo],
                    sensor_rows.get(wmo, {}),
                    calib_rows.get(wmo, {}),
                    config_rows.get(wmo, {}),
                )
            except Exception as exc:  # pragma: no cover - defensive
                if self.strict:
                    raise
                self._log.error("multi_csv_row_invalid", wmo=wmo, error=str(exc))
        self._rows = rows
        self._log.info(
            "multi_csv_loaded",
            n_floats=len(rows),
            n_meta=len(meta_rows),
            n_sensor=len(sensor_rows),
            n_calib=len(calib_rows),
            n_config=len(config_rows),
            path=str(self.metadata_dir),
        )
        for wmo in sorted(meta_rows):
            missing = [
                label
                for label, table in (
                    ("sensor-info", sensor_rows),
                    ("calib", calib_rows),
                    ("config_params", config_rows),
                )
                if wmo not in table
            ]
            if missing:
                self._log.warning("multi_csv_incomplete", wmo=wmo, missing=",".join(missing))

    def _build_row(
        self,
        wmo: int,
        meta: dict[str, str],
        sensor: dict[str, str],
        calib: dict[str, str],
        config: dict[str, str],
    ) -> FloatRegistryRow:
        """Project the four joined sheets onto the canonical registry row."""
        calibrations = build_calibrations(calib)
        sensors = _sensors_from_rows(sensor, calibrations, build_accuracy(calib))

        # Firmware is authoritative in sensor-info.csv; it decides the
        # decoder. config_params' "firmware date/software date" column
        # disagrees for 2901304 (20811 vs 61810) and is not used.
        # Two distinct quantities that the sheets keep in different places:
        #
        # * the *format* revision that selects the decoder, from
        #   sensor-info.csv. This is what the Coriolis decoder id keys on.
        # * the *published* FIRMWARE_VERSION, from config_params.csv's
        #   "firmware date" column. Verified against GDAC on all five
        #   floats in the sheets (2901304/2901305 -> 020811,
        #   2902222/3/4 -> 091615).
        #
        # They differ on the 1005 floats -- 061810 selects the decoder but
        # 020811 is published -- so routing must never be taken from the
        # published label: firmware 020811 maps to decoder 1010, which
        # decodes this hull's pressure as -3079 dbar instead of 2000.2.
        #
        # ARVOR-I hulls (Manufacturer "arvor" -> NKE) are a separate
        # family: sensor-info's "firmware revision number" is the SBE41CP
        # *sensor* firmware ("7.2.5"), which is NOT the float-engine id --
        # across this fleet it spans engines 5900A05 (checksum 11415 ->
        # {222, 223, 225}) and 5900A05B (checksum 13872 -> 232), verified
        # 2026-09-04 from Tech#1 checksums. The APF9 firmware map is
        # therefore never consulted for these hulls: decoder routing comes
        # from the registry (checksum-proven decoder_id) and the engine
        # version from the telemetry itself.
        manufacturer = (meta.get("Manufacturer", "") or "WRC").upper()
        is_arvor = PLATFORM_MAKER_CANONICAL.get(manufacturer, "WRC") == "NKE"
        comms = sensor.get("Comms system", "") or "ARGOS"
        ctd_model = (sensor.get("CTD Sensor Type", "") or "").upper()
        # ARVOR-I SBE41CP family signature: NKE/Arvor hull + SBE41CP CTD +
        # Iridium SBD. This is the *protocol* the float speaks, derivable
        # from the sheets alone; the engine inside the family (5900A05 vs
        # 5900A05B) comes from the telemetry checksum at decode time.
        # Must stay in sync with ``decoder_table.yaml`` profile_class.
        is_arvor_i_sbe41cp = is_arvor and ctd_model == "SBE41CP" and comms.upper() != "ARGOS"
        if is_arvor:
            decoder_revision = ""
            decoder_id = 0
        else:
            decoder_revision = _zero_padded_firmware(sensor.get("firmware revision number", ""))
            decoder_id = FIRMWARE_TO_DECODER.get(decoder_revision, 0)
        firmware = _zero_padded_firmware(config.get("firmware date/software date", ""))

        ptt = _int_str(meta.get("Argos number", "")) or _int_str(sensor.get("Comms ID", ""))
        ctrl_serial = meta.get("controller board serial number", "")
        launch = _launch_datetime(meta.get("launch date", ""))

        config_pairs = build_config_parameters(config)

        # The sensor-info "firmware revision number" is the CTD sensor
        # firmware (e.g. SBE41CP "7.2.5" on the ARVOR-I fleet) -- the
        # label GDAC publishes in FIRMWARE_VERSION for these hulls. It
        # is deliberately NOT ``firmware_version`` (the float-engine
        # date-code used for routing); exposing it as an extra field
        # lets the ARVOR-I mono builder publish the reference label.
        sensor_firmware_version = str(sensor.get("firmware revision number", "") or "").strip()

        payload: dict[str, Any] = {
            # identity
            "wmo": wmo,
            "ptt": ptt,
            "imei": "",
            "platform_maker": PLATFORM_MAKER_CANONICAL.get(manufacturer, "WRC"),
            "platform_type": "ARVOR" if is_arvor else "APEX",
            "platform_family": "FLOAT",
            "transmission_type": 1 if comms.upper() == "ARGOS" else 3,
            # decoder routing
            "decoder_id": decoder_id,
            "decoder_version": decoder_revision,
            "profile_class": "arvor_i_sbe41cp" if is_arvor_i_sbe41cp else "",
            "firmware_version": firmware or decoder_revision,
            "sensor_firmware_version": sensor_firmware_version,
            "manual_version": _zero_padded_firmware(config.get("manual date", "")),
            # mission
            # APF9 Argos frames are 31 bytes; ARVOR-I SBD payloads are the
            # 100-byte rows of decode_sbd_file.m (300-byte mails = 3 rows).
            "frame_length": 100 if is_arvor else 31,
            "cycle_length_hours": int(
                _num(config.get("CONFIG_CycleTime_hours", "")) or 240,
            ),
            "drift_sampling_period_hours": float(
                _num(config.get("CONFIG_ParkSamplingPeriod_hours", "")) or 240.0,
            ),
            "delay_before_mission_minutes": -1,
            # launch / reference
            "launch_date_utc": launch,
            "launch_lon": _num(meta.get("long", "")) or 0.0,
            "launch_lat": _num(meta.get("lat", "")) or 0.0,
            "launch_qc": 1,
            # START_DATE is "date of the first descent" (Argo User Manual
            # v3.3 §2.4), which is a *different* instant from the launch:
            # the manual defines LAUNCH_DATE, STARTUP_DATE and START_DATE
            # separately. Echoing the launch time here published a value
            # the sheets never stated, so it is left empty unless the
            # operator supplies a genuine ``start date`` column. The
            # platform layer then falls back to cycle 1 (see
            # ``apex_argos.decoder._cycle_one_start_date``), and to the
            # _FillValue when even that is unavailable -- which the
            # manual permits (§2.4.9 does not list START_DATE as
            # mandatory) and Coriolis itself does.
            "start_date_utc": _start_datetime(meta),
            "reference_day": launch[:10] if len(launch) >= 10 else launch,
            "dm_flag": False,
            # Argo bookkeeping
            "argo_user_manual_version": "3.1",
            "wmo_inst_type": _int_str(meta.get("WMO Instrument Type", "")),
            # hardware
            "battery_type": DEFAULT_BATTERY_TYPE,
            "battery_packs": sensor.get("battery config", ""),
            # GDAC stores the serial lower-cased (9a-7319, 9g-10795).
            "controller_board_primary_serial": ctrl_serial.lower(),
            "controller_board_primary_type": _controller_board_type(ctrl_serial),
            "float_serial_no": _int_str(meta.get("Manufacturer Serial Number", "")),
            # GDAC publishes the vessel name lower-cased.
            "deployment_platform": meta.get("Launch platform", "").lower(),
            # sensors / systems
            "sensors": sensors,
            "transmission_system": [comms.upper()],
            "positioning_system": [_positioning_system(comms)],
            "notes": f"multi-CSV metadata backend ({self.metadata_dir.name})",
        }
        payload.update(self.defaults)

        # Extras consumed by the metadata writer but not part of the
        # canonical v1 schema. FloatRegistryRow allows extras.
        payload["dac_format_id"] = _int_str(meta.get("Float subtype", ""))
        standard_format = _int_str(config.get("format standard number", ""))
        payload["standard_format_id"] = standard_format.zfill(6) if standard_format else ""
        is_argos = comms.upper() == "ARGOS"
        # TRANS_SYSTEM_ID is the ARGOS *programme* number of the
        # telecommunication subscription (Argo User's Manual 3.44.0
        # §2.4.4: "Program identifier of the telecommunication
        # subscription. DACs can use N/A or alternative of their choice
        # when not applicable (e.g. : Iridium or Orbcomm)"). A float's
        # PTT is a beacon identifier, not a programme identifier, so
        # publishing it here mislabels the field on non-ARGOS platforms.
        payload["trans_system_id"] = ARGOS_TRANS_SYSTEM_ID if is_argos else NOT_APPLICABLE
        # TRANS_FREQUENCY likewise has no meaning for a store-and-forward
        # satellite link: Iridium SBD has no fixed carrier the DAC can
        # publish. Same manual sanction for "not applicable".
        payload["trans_frequency"] = ARGOS_TRANS_FREQUENCY if is_argos else NOT_APPLICABLE
        payload["end_mission_status"] = _end_mission_status(meta.get("Status", ""))
        # Operational fact from the DAC database, not telemetry. Copied
        # only when the sheet carries it; never derived from last message.
        payload["end_mission_date"] = _end_mission_date(meta.get("end mission date", ""))
        payload["profile_count_offset"] = _int_str(meta.get("np0 Profile count offset", ""))
        payload["config_parameters"] = config_pairs
        return FloatRegistryRow.model_validate(payload)


def _positioning_system(comms: str) -> str:
    """Positioning system (reference table 9) for a transmission system.

    The positioning system and the transmission system are *different*
    concepts with different vocabularies -- Argo reference table 9
    (https://vocab.nerc.ac.uk/collection/R09/) versus reference table 10
    -- and the communications column of the sheets describes only the
    latter.  Copying it into ``POSITIONING_SYSTEM`` asserted that these
    hulls are located by the Iridium network, which is not what happens.

    ARGOS floats genuinely are positioned by the ARGOS Doppler solution,
    so for them the two coincide.  A satellite store-and-forward link
    (Iridium/Orbcomm/Beidou) carries no location of its own: the float
    fixes itself with GNSS and transmits that fix.  For the ARVOR-I
    family this is proven from telemetry -- Tech#1 carries real GPS
    fixes, decoded as ``GpsRecord(accuracy='G')`` -- and it matches the
    Coriolis reference float info, which pairs
    ``POSITIONING_SYSTEM = 'GPS'`` with ``TRANS_SYSTEM = 'IRIDIUM'``.

    Family-generic: keyed on the transmission system alone, never on a
    WMO or hull, so any future float inherits the correct pairing.
    """

    if comms.strip().upper() == "ARGOS":
        return "ARGOS"
    return "GPS"


def _controller_board_type(serial: str) -> str:
    """Derive the controller board type from its serial prefix.

    Teledyne Webb (APEX) serials are ``<generation><variant>-<number>``
    -- ``9A-7319``, ``9G-10795``, ``9I-9308``. Across the APEX GDAC
    sample every serial beginning ``9`` carries
    ``CONTROLLER_BOARD_TYPE_PRIMARY = APF9`` (7/7 references checked), so
    for that family the leading digit is the board generation.

    The generation digit is *only* meaningful for the APEX serial
    convention.  Applying it blindly produced ``APF0`` on the ARVOR-I
    sheets, whose ``controller board serial number`` is ``0i-0`` -- and
    ``APF0`` is not a controller board at all: Argo reference table 28
    (https://vocab.nerc.ac.uk/collection/R28/) has no ``APF*`` entry
    below ``APF9``-era hardware, and the NKE boards it does list are the
    ``I5xx`` family.  Rather than invent an R28 code we cannot derive --
    the sheets carry no board *type* column, only a serial, and ``0i-0``
    is a placeholder with no generation information -- the value is
    reported as explicitly not applicable, matching the INCOIS GDAC
    references for these hulls and the Coriolis convention.

    Family-generic: the APEX rule fires only on serials that follow the
    APEX convention (leading digit 1-9 plus a letter variant); anything
    else yields ``n/a`` rather than a fabricated code.
    """
    text = serial.strip()
    if not text:
        return ""
    head = text.split("-", 1)[0]
    # APEX convention: <non-zero generation digit><letter variant>.
    if len(head) >= 2 and head[0].isdigit() and head[0] != "0" and head[1:].isalpha():
        return f"APF{head[0]}"
    return NOT_APPLICABLE


def _end_mission_status(status: str) -> str:
    """Map the sheet's live/Dead marker to Argo reference table 19."""
    text = status.strip().lower()
    if text.startswith("dead"):
        return "T"
    return ""


def _end_mission_date(raw: str) -> str:
    """Return a compact ``YYYYMMDDHHMMSS`` stamp, or blank.

    The date is an operator-declared end of mission (Coriolis BDD
    ``END_MISSION_DATE``). It cannot be computed from telemetry -- on
    the three dead INCOIS floats it matches last message once and
    misses by 159 and 650 days on the other two -- so an empty cell
    stays empty rather than being filled from the last reception.
    """
    digits = "".join(ch for ch in raw.strip() if ch.isdigit())
    return digits if len(digits) == 14 else ""


__all__ = [
    "CALIB_CSV",
    "CONFIG_CSV",
    "DEFAULT_BATTERY_TYPE",
    "FIRMWARE_TO_DECODER",
    "INCOIS_DEFAULTS",
    "INCOIS_DEFAULT_ACCURACY",
    "META_CSV",
    "SBE41_CALIB_EQUATIONS",
    "SENSOR_CSV",
    "MultiCsvLoader",
    "build_accuracy",
    "build_calibrations",
    "build_config_parameters",
]

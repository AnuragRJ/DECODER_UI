"""Metadata validation helpers.

Three families of checks:

* :func:`validate_float_info` / :func:`validate_float_meta` — quick
  sanity checks on the JSON-contract objects used by the decoder.
* :func:`validate_registry_row` — per-row checks on a
  :class:`FloatRegistryRow` (range checks, enum membership, WMO format).
* :func:`validate_registry`  — cross-row checks over a whole registry
  (duplicate WMOs, duplicate IMEIs/serials, referential integrity).

The CLI ``argo-decoder metadata validate`` calls :func:`validate_registry`
and prints/returns the :class:`ValidationReport`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from argo_decoder.metadata.models import (
    _DATA_CENTRES,
    _PLATFORM_FAMILIES,
    _PLATFORM_MAKERS,
    _PLATFORM_TYPES,
    _TRANSMISSION_TYPES,
    END_DECODING_SENTINEL,
    FloatInfo,
    FloatMeta,
    FloatRegistryRow,
)

if TYPE_CHECKING:
    from argo_decoder.config.decoder_table import DecoderTable


@dataclass
class ValidationIssue:
    level: str  # "error" | "warning"
    code: str
    message: str
    wmo: int | None = None


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    @property
    def n_errors(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    @property
    def n_warnings(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    def add(
        self,
        level: str,
        code: str,
        message: str,
        wmo: int | None = None,
    ) -> None:
        self.issues.append(ValidationIssue(level, code, message, wmo))

    def summary(self) -> str:
        return (
            f"{self.n_errors} error(s), {self.n_warnings} warning(s); "
            f"{'PASS' if self.ok else 'FAIL'}"
        )


# ---------------------------------------------------------------------------
# JSON-contract validation
# ---------------------------------------------------------------------------


def validate_float_info(info: FloatInfo) -> ValidationReport:
    """Sanity-check a decoded ``*_info.json`` record."""
    report = ValidationReport()
    if info.wmo <= 0 or info.wmo > 9_999_999:
        report.add("error", "WMO_RANGE", f"WMO out of range: {info.wmo}", info.wmo)
    if info.frame_length <= 0:
        report.add("error", "FRAME_LEN", "FRAME_LENGTH must be positive", info.wmo)
    if info.cycle_length_hours <= 0:
        report.add("error", "CYCLE_LEN", "CYCLE_LENGTH must be positive", info.wmo)
    if not -180.0 <= info.launch_lon <= 180.0:
        report.add(
            "error",
            "LAUNCH_LON",
            f"LAUNCH_LON out of [-180,180]: {info.launch_lon}",
            info.wmo,
        )
    if not -90.0 <= info.launch_lat <= 90.0:
        report.add(
            "error",
            "LAUNCH_LAT",
            f"LAUNCH_LAT out of [-90,90]: {info.launch_lat}",
            info.wmo,
        )
    if info.decoder_id <= 0:
        report.add("warning", "DECODER_ID", "DECODER_ID missing/zero", info.wmo)
    return report


def validate_float_meta(meta: FloatMeta) -> ValidationReport:
    report = ValidationReport()
    if not meta.platform_number:
        report.add("error", "PLATFORM_NUMBER", "PLATFORM_NUMBER is required")
    if not meta.platform_type:
        report.add("error", "PLATFORM_TYPE", "PLATFORM_TYPE is required")
    return report


# ---------------------------------------------------------------------------
# Registry validation
# ---------------------------------------------------------------------------


def validate_registry_row(row: FloatRegistryRow) -> ValidationReport:
    """Validate one central-registry row."""
    report = ValidationReport()
    wmo = row.wmo

    # identity
    if wmo <= 0 or wmo > 9_999_999:
        report.add("error", "WMO_RANGE", f"WMO out of 7-digit range: {wmo}", wmo)
    if not row.ptt:
        report.add("error", "PTT_MISSING", "PTT is required", wmo)
    if row.platform_maker not in _PLATFORM_MAKERS:
        report.add(
            "warning",
            "PLATFORM_MAKER_UNKNOWN",
            f"Unknown platform_maker: {row.platform_maker!r}",
            wmo,
        )
    if row.platform_type not in _PLATFORM_TYPES:
        report.add(
            "warning",
            "PLATFORM_TYPE_UNKNOWN",
            f"Unknown platform_type: {row.platform_type!r}",
            wmo,
        )
    if row.platform_family not in _PLATFORM_FAMILIES:
        report.add(
            "error",
            "PLATFORM_FAMILY_UNKNOWN",
            f"Unknown platform_family: {row.platform_family!r}",
            wmo,
        )
    if row.transmission_type not in _TRANSMISSION_TYPES:
        report.add(
            "error",
            "TRANSMISSION_TYPE",
            f"transmission_type must be one of {sorted(_TRANSMISSION_TYPES)}",
            wmo,
        )
    if row.data_centre not in _DATA_CENTRES:
        report.add(
            "warning",
            "DATA_CENTRE_UNKNOWN",
            f"Unknown data_centre: {row.data_centre!r}",
            wmo,
        )

    # routing
    if row.decoder_id <= 0:
        report.add("error", "DECODER_ID", "decoder_id is required (> 0)", wmo)
    if not row.decoder_version:
        report.add("error", "DECODER_VERSION", "decoder_version is required", wmo)
    if not row.firmware_version:
        report.add("warning", "FIRMWARE_VERSION", "firmware_version is empty", wmo)

    # mission parameters
    if row.frame_length <= 0:
        report.add("error", "FRAME_LENGTH", "frame_length must be positive", wmo)
    if row.cycle_length_hours <= 0 or row.cycle_length_hours > 24 * 60:
        report.add(
            "error",
            "CYCLE_LENGTH",
            f"cycle_length_hours out of range: {row.cycle_length_hours}",
            wmo,
        )
    if row.drift_sampling_period_hours <= 0:
        report.add(
            "error",
            "DRIFT_SAMPLING",
            "drift_sampling_period_hours must be positive",
            wmo,
        )

    # times / positions
    if not -180.0 <= row.launch_lon <= 180.0:
        report.add("error", "LAUNCH_LON", "launch_lon out of [-180,180]", wmo)
    if not -90.0 <= row.launch_lat <= 90.0:
        report.add("error", "LAUNCH_LAT", "launch_lat out of [-90,90]", wmo)
    if row.launch_date_utc.year < 1990 or row.launch_date_utc > datetime(9999, 12, 31):
        report.add("error", "LAUNCH_DATE", "launch_date_utc out of range", wmo)
    if (
        row.end_decoding_date != END_DECODING_SENTINEL
        and row.end_decoding_date < row.launch_date_utc
    ):
        report.add(
            "error",
            "END_DECODING",
            "end_decoding_date before launch_date_utc",
            wmo,
        )
    if row.reference_day is None:
        report.add("error", "REFERENCE_DAY", "reference_day is required", wmo)

    # sensors
    if not row.sensors:
        report.add("warning", "NO_SENSORS", "sensors list is empty", wmo)

    return report


def validate_registry(
    rows: list[FloatRegistryRow],
    *,
    decoder_table: DecoderTable | None = None,
) -> ValidationReport:
    """Cross-row validation: duplicates, referential integrity.

    Parameters
    ----------
    rows:
        Registry rows to validate.
    decoder_table:
        Optional :class:`argo_decoder.config.DecoderTable` instance used
        for referential-integrity checks between registry rows and the
        routing table.  When ``None``, decoder-table cross-checks are
        skipped (useful for unit tests that don't care about routing).

        Typed as a string forward reference to avoid a hard import-time
        dependency from :mod:`argo_decoder.metadata` onto
        :mod:`argo_decoder.config`; the attribute is resolved lazily.
    """
    report = ValidationReport()

    wmo_counts = Counter(r.wmo for r in rows)
    for wmo, n in wmo_counts.items():
        if n > 1:
            report.add("error", "DUP_WMO", f"Duplicate WMO {wmo} appears {n} times", wmo)

    imei_counts = Counter(r.imei for r in rows if r.imei)
    for imei, n in imei_counts.items():
        if n > 1:
            report.add(
                "error",
                "DUP_IMEI",
                f"Duplicate IMEI {imei!r} appears {n} times",
            )

    ptt_counts = Counter(r.ptt for r in rows if r.ptt)
    for ptt, n in ptt_counts.items():
        if n > 1:
            report.add(
                "warning",
                "DUP_PTT",
                f"PTT {ptt!r} appears {n} times (legitimate for reflashes, review)",
            )

    # --- Decoder-table referential integrity -------------------------------
    _known_ids: set[int] | None = None
    _known_keys: set[tuple[str, str]] | None = None
    if decoder_table is not None:
        _known_ids = set(decoder_table.all_decoder_ids())
        _known_keys = set(decoder_table.all_platform_version_keys())

    for row in rows:
        sub = validate_registry_row(row)
        report.issues.extend(sub.issues)

        if _known_keys is None or decoder_table is None:
            continue

        key = (row.platform_type, row.decoder_version)
        if key not in _known_keys:
            report.add(
                "error",
                "DECODER_VERSION_UNKNOWN",
                (
                    f"(platform_type={row.platform_type!r}, "
                    f"decoder_version={row.decoder_version!r}) "
                    "not present in decoder_table.yaml"
                ),
                row.wmo,
            )
            # Also flag a totally unknown decoder_id independently (i.e. the
            # numeric id doesn't appear anywhere in the table at all).
            if _known_ids is not None and row.decoder_id not in _known_ids:
                report.add(
                    "error",
                    "DECODER_ID_UNKNOWN",
                    f"decoder_id={row.decoder_id} not present in decoder_table.yaml",
                    row.wmo,
                )
            continue

        # Key found -> cross-check that decoder_id matches (catches
        # copy-paste errors in registry rows).
        entry = decoder_table.by_platform_version(row.platform_type, row.decoder_version)
        if entry.decoder_id != row.decoder_id:
            report.add(
                "error",
                "DECODER_ID_MISMATCH",
                (
                    f"decoder_id={row.decoder_id} disagrees with decoder_table "
                    f"entry decoder_id={entry.decoder_id} for "
                    f"(platform_type={row.platform_type!r}, "
                    f"decoder_version={row.decoder_version!r})"
                ),
                row.wmo,
            )

    return report

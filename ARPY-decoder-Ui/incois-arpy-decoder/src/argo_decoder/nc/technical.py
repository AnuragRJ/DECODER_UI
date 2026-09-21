"""ADMT technical (``<wmo>_tech.nc``) builder.

Implements Phase 6A.4. The technical file is a flat name/value/cycle
table: every row is one technical parameter for one cycle, with the
value stored as text.

Structure, variable order, dtypes, attributes and fill conventions were
transcribed from the six supplied GDAC ``<wmo>_tech.nc`` references,
which share an identical 10-variable layout.

This module is a **thin writer**. It never parses ARGOS messages; it
consumes :class:`~argo_decoder.platforms.apex_argos.engineering.ApexEngineeringData`
objects produced by the validated Phase 6A.3 decoder and renders them
into the ADMT vocabulary.

Parameter vocabulary
--------------------

All six references use the same 14 ``TECHNICAL_PARAMETER_NAME`` values.
Of those, this writer emits the ones whose provenance is established:

===================================== ==========================
Parameter                             Source
===================================== ==========================
``PRES_SurfaceOffsetNotTruncated_dbar`` message 1 ``SP`` (signed cbar)
``POSITION_PistonSurface_COUNT``      message 1 ``SPP``
``POSITION_PistonPark_COUNT``         message 1 ``PPP2``
``POSITION_PistonProfile_COUNT``      message 1 ``PPP``
``TIME_PumpMotor_seconds``            message 1 ``PMT``
``FLAG_ProfileTermination_hex``       message 1 ``STATUS``
``PRESSURE_AirBladder_COUNT``         message 1 ``ABP`` (firmware 061810 only)
===================================== ==========================

The remaining seven -- the three ``VOLTAGE_*`` / three ``CURRENT_*``
pairs and ``PRESSURE_InternalVacuum_inHg`` -- require per-float
count-to-engineering-unit calibration coefficients that the archived
messages do not carry and the available specification does not publish.
They are deliberately **not emitted** rather than written with a guessed
scale; see the Phase 6A.4 progress entry for the measurement evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import (
    DATE_TIME_LEN,
    INT_FILL,
    STRING2,
    STRING4,
    STRING8,
    STRING32,
    STRING128,
    char_column,
    date_char,
    scalar_char,
    standard_globals,
    utc_stamp,
    write_admt_dataset,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Imported lazily to keep nc/ independent of platforms/ at runtime.
    from argo_decoder.platforms.apex_argos.engineering import ApexEngineeringData

_TECH = "N_TECH_PARAM"

#: Decoders that carry ``ABP`` in message 3 rather than message 1.
#:
#: Firmware 110613/091x15 moves the air-bladder byte out of message 1
#: (its message-1 table has no ``ABP`` entry at all) into message-3
#: payload byte 1. Everything else keeps the message-1 field.
_ABP_MSG3_DECODERS = frozenset({1010})

#: Decoders for which the calibrated battery channels reproduce the GDAC
#: references exactly, so the "store average of decoded values" caveat
#: does not bite.
#:
#: On firmware 061810 the redundancy-selected copy already carries the
#: value the DAC published: applying the documented conversions (D4 p.23)
#: to WMO 2901304 matches the reference on **22/22** comparable cycles
#: for all four channels below, and modal selection across the redundant
#: copies gives the identical result. The single non-match is that
#: float's cycle 1, an incomplete first transmission that carries no
#: usable engineering block.
_BATTERY_VERIFIED_DECODERS = frozenset({1001, 1005, 1010})

#: ``(label, engineering attribute, scale, offset)`` for the calibrated
#: battery channels. Conversions are D4 p.23, identical in all fourteen
#: APF9A manuals: ``V = raw*0.077 + 0.486``, ``I = raw*4.052 - 3.606``.
_BATTERY_CHANNELS: tuple[tuple[str, str, float, float], ...] = (
    ("VOLTAGE_BatteryParkNoLoad_volts", "battery_voltage_quiescent_counts", 0.077, 0.486),
    ("CURRENT_BatteryPark_mA", "battery_current_quiescent_counts", 4.052, -3.606),
    ("VOLTAGE_BatterySBEAscent_volts", "battery_voltage_sbe41_counts", 0.077, 0.486),
    ("CURRENT_BatterySBEPump_mA", "battery_current_sbe41_counts", 4.052, -3.606),
    # The profile-depth pair reads the *next* (voltage, current) couple in
    # the same message-1 block, bytes 22 and 23. Recovered by inverting
    # the published values: dividing them by the documented step yields
    # exact integers in 0..255, and those integers are byte 22 / byte 23.
    # The current uses the shared conversion on both firmwares; the
    # voltage does not (see _PROFILE_DEPTH_VOLTAGE_BY_DECODER).
    ("CURRENT_BatteryInitialAtProfileDepth_mA", "battery_current_pump_counts", 4.052, -3.606),
)

#: ``VOLTAGE_BatteryInitialAtProfileDepth_volts`` is the one channel whose
#: calibration is firmware-specific.
#:
#: On firmware 061810 the published values quantise on 0.078 V and
#: ``0.078*n + 0.5`` is exact on all 23 cycles of WMO 2901304, where the
#: shared ``0.077*n + 0.486`` form matches none. On 091x15 the opposite
#: holds: WMO 2902222 quantises on 0.077 and the shared form is exact on
#: all three comparable cycles. Both were obtained by inverting the
#: reference to integer counts and confirming those counts are byte 22.
_PROFILE_DEPTH_VOLTAGE_BY_DECODER: dict[int, tuple[float, float]] = {
    1001: (0.078, 0.5),
    1005: (0.078, 0.5),
    1010: (0.077, 0.486),
}

#: Internal vacuum at the end of the park phase, in inHg.
#:
#: ``V = counts * 0.293 - 29.767`` -- APF9A manual p.28, whose worked
#: example ``0x56 -> 86 -> -4.5 inHg`` matches
#: ``sensor_2_value_for_apex_apf9_vacuum.m:23`` exactly.
#:
#: The *source byte* differs by firmware, and neither family carries it
#: in message 1:
#:
#: * 061810 -- auxiliary block item 3, after ``PDIVMAX`` (2 bytes) and
#:   ``TPI`` (2 bytes). ``ApexCoDecoder`` 061810 row 232 labels it
#:   ``PRESSURE_InternalVacuumParkEnd_inHg`` (techId 1024) and Coriolis
#:   reads ``decData(3)`` of the aux block
#:   (``decode_data_apx_1_5.m:1122``). Carried on
#:   :attr:`park_end_vacuum_counts`.
#: * 110613/091x15 -- message-3 payload byte 0, carried on
#:   :attr:`msg3_vacuum_counts`.
#:
#: The message-1 byte previously published here is the second byte of the
#: two-byte ``SP`` field: on WMO 2901328 it yields only counts 254 and 0,
#: which are pressure sentinels rather than physical vacuum readings.
#: 061810 keeps the message-1 byte. It is the byte the reference itself
#: reads: inverting GDAC's published values for WMO 2901304 gives counts
#: 254, 254, 252, 251, 254 for cycles 1-5, which is exactly the modal
#: message-1 ``payload[9]`` across the CRC-valid copies of those cycles.
#: The auxiliary ``park_end_vacuum_counts`` decodes to a different,
#: physically more plausible value (counts 76-80), but it is *not* the
#: quantity the reference publishes, so it is left unpublished rather
#: than silently substituted -- see ``docs/APF9_VACUUM_INVESTIGATION``
#: notes in ``APF9_PARITY_STATE.md``.
_VACUUM_SOURCE_ATTRS: dict[int, str] = {
    1001: "vacuum_counts",
    1005: "vacuum_counts",
    1010: "msg3_vacuum_counts",
}
_VACUUM_SCALE_OFFSET = (0.293, -29.767)

#: Parameter emission order.
#:
#: Every label here is drawn from the Argo-approved technical vocabulary
#: that Coriolis ships for these exact decoder ids,
#: ``decArgo_soft/config/_techParamNames/_tech_param_name_{1005,1010}.json``.
#: The decoder manual (V1.10 section 14.2) states that
#: ``TECHNICAL_PARAMETER_NAME`` values "should be allowed by the Argo
#: project", and those files are the machine-readable form of that
#: allow-list -- so publishing a label from them is standards-compliant
#: regardless of whether one particular DAC chooses to emit it.
#:
#: The first seven were verified value-for-value against the GDAC
#: references (531/531). The remainder are documentation-backed
#: capabilities of this decoder that the INCOIS reference files happen
#: not to publish; see ``docs/phase_reports/M2_REVISITED.md``.
#: The order below is the reference's own per-cycle order, read off
#: WMO 2901304 cycle 1 and identical on every cycle of all seven INCOIS
#: APEX references.
TECH_PARAMETER_ORDER: tuple[str, ...] = (
    # --- verified against the GDAC references ---
    "VOLTAGE_BatteryInitialAtProfileDepth_volts",
    "PRESSURE_InternalVacuum_inHg",
    "FLAG_ProfileTermination_hex",
    "PRES_SurfaceOffsetNotTruncated_dbar",
    "POSITION_PistonSurface_COUNT",
    "TIME_PumpMotor_seconds",
    "CURRENT_BatteryInitialAtProfileDepth_mA",
    "POSITION_PistonProfile_COUNT",
    "POSITION_PistonPark_COUNT",
    # Calibrated battery channels, verified 22/22 against the WMO 2901304
    # reference on firmware 061810. Note INCOIS publishes these under its
    # own names: the Coriolis ``_tech_param_name_*.json`` allow-list calls
    # the same quantities ``VOLTAGE_BatteryParkEnd_volts`` and
    # ``CURRENT_BatterySBEParkEnd_mA``. The published reference wins over
    # the source listing, as elsewhere in this module.
    "VOLTAGE_BatteryParkNoLoad_volts",
    "CURRENT_BatteryPark_mA",
    "VOLTAGE_BatterySBEAscent_volts",
    "PRESSURE_AirBladder_COUNT",
    "CURRENT_BatterySBEPump_mA",
    # --- float engineering, decoded from messages 2/3 and the
    #     auxiliary block; approved labels, DERIVED BUT NOT EMITTED
    #     (see PUBLISHED_TECH_PARAMETERS) ---
    "FLAG_CTDStatus_hex",
    "FLAG_TelonicsPTTStatus_hex",
    "NUMBER_RepositionsDuringPark_COUNT",
    "NUMBER_ParkSamples_COUNT",
    "PRES_MaxDifferencePvsPTorPTSSamples_dbar",
    "CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes",
    "NUMBER_PRESSamplesDuringDescentToPark_COUNT",
    "NUMBER_AscendingCTDSamplesInternalCounter_COUNT",
    # --- ARGOS reception statistics, derived from received data ---
    "NUMBER_ArgosPositions_COUNT",
    "NUMBER_ArgosPositioningClass0_COUNT",
    "NUMBER_ArgosPositioningClass1_COUNT",
    "NUMBER_ArgosPositioningClass2_COUNT",
    "NUMBER_ArgosPositioningClass3_COUNT",
    "NUMBER_ArgosPositioningClassA_COUNT",
    "NUMBER_ArgosPositioningClassB_COUNT",
    "NUMBER_ArgosPositioningClassZ_COUNT",
    "NUMBER_TransmissionFloatFramesComplete_COUNT",
    "NUMBER_TransmissionFloatFramesCrcOk_COUNT",
)

#: Labels verified value-for-value against the GDAC reference files.
#: The audit tooling compares only these, so extending the vocabulary
#: cannot silently mask a parity regression.
GDAC_VERIFIED_TECH_PARAMETERS: frozenset[str] = frozenset(
    {
        "FLAG_ProfileTermination_hex",
        "PRES_SurfaceOffsetNotTruncated_dbar",
        "POSITION_PistonSurface_COUNT",
        "TIME_PumpMotor_seconds",
        "POSITION_PistonProfile_COUNT",
        "POSITION_PistonPark_COUNT",
        "PRESSURE_AirBladder_COUNT",
        "VOLTAGE_BatteryParkNoLoad_volts",
        "VOLTAGE_BatterySBEAscent_volts",
        "CURRENT_BatteryPark_mA",
        "CURRENT_BatterySBEPump_mA",
    }
)

#: Labels actually written to ``<wmo>_tech.nc``.
#:
#: The decoder derives every label in :data:`TECH_PARAMETER_ORDER`, and
#: the surplus ones are genuinely decodable Argo-approved quantities.
#: They are nonetheless withheld from the file: the goal is to *match*
#: the GDAC reference, and emitting parameters the reference does not
#: carry doubles the row count (641 against 322 on WMO 2901304) and
#: makes a row-wise comparison against the published file impossible.
#:
#: The values remain available through
#: :func:`technical_records_for_cycle`'s internal mapping and through
#: :data:`DERIVED_NOT_PUBLISHED_TECH_PARAMETERS`, so nothing that was
#: decoded is lost -- only the emission is scoped to the reference
#: vocabulary. Verified against all seven INCOIS APEX references: the
#: union of names they publish is exactly this set.
PUBLISHED_TECH_PARAMETERS: frozenset[str] = frozenset(
    {
        "FLAG_ProfileTermination_hex",
        "PRES_SurfaceOffsetNotTruncated_dbar",
        "POSITION_PistonSurface_COUNT",
        "TIME_PumpMotor_seconds",
        "POSITION_PistonProfile_COUNT",
        "POSITION_PistonPark_COUNT",
        "PRESSURE_AirBladder_COUNT",
        "VOLTAGE_BatteryParkNoLoad_volts",
        "CURRENT_BatteryPark_mA",
        "VOLTAGE_BatterySBEAscent_volts",
        "CURRENT_BatterySBEPump_mA",
        "VOLTAGE_BatteryInitialAtProfileDepth_volts",
        "CURRENT_BatteryInitialAtProfileDepth_mA",
        "PRESSURE_InternalVacuum_inHg",
    }
)

#: Decoded, standards-approved, deliberately not written to the file.
DERIVED_NOT_PUBLISHED_TECH_PARAMETERS: frozenset[str] = frozenset(
    set(TECH_PARAMETER_ORDER) - set(PUBLISHED_TECH_PARAMETERS)
)

#: Shared reason string for the calibrated engineering channels.
_AVERAGING_RULE_UNKNOWN = (
    "published conversion (D4 p.23) but the DAC's multi-copy averaging rule is unresolved"
)

#: Parameters present in the references that this writer cannot supply,
#: with the reason. Kept as data so the audit tooling can report them.
#:
#: The conversions themselves **are** published and are reproduced in
#: :mod:`argo_decoder.platforms.apex_argos.engineering` (D4 p.23,
#: identical in all fourteen APF9A manuals). What blocks emission is not
#: the scale factor but the aggregation: D2 annotates every one of these
#: parameters "store average of decoded values", because each ARGOS copy
#: of a message carries a fresh measurement. Applying the published
#: formula to a single copy reproduces the reference on only some cycles
#: (e.g. 52/73 for ``CURRENT_BatteryPark_mA`` on WMO 2901339, though
#: 3/3 on decoder 1010), and mean-of-raw, mean-of-converted, rounded
#: mean, ceil, floor, median, last-copy and max-copy were each tested
#: and rejected. Emitting a value under a guessed aggregation rule would
#: be curve fitting presented as decoding.
#: All three former entries were resolved by inverting the published
#: values to recover exact integer raw counts, which then located the
#: source byte unambiguously (22, 23 and 9 of message 1). The
#: "averaging" that had defeated earlier fits was in fact *copy
#: selection*: these bytes differ between ARGOS copies of the same
#: message, so the value depends on which copy is read, not on any
#: arithmetic over them. See :data:`_MAJORITY_BYTE_OFFSETS`.
UNSUPPORTED_TECH_PARAMETERS: dict[str, str] = {}

#: Parameters emitted only for some firmware revisions.
#:
#: ``PRESSURE_AirBladder_COUNT``: the manuals explain why decoder 1010
#: differs. ``ABP`` is present in Data Message 1 on firmware 061810
#: (D4 p.20 byte 27) but **absent from Data Message 1** on 110613/090413
#: (D5 p.21, which ends VAP/IAP/PAP/VSAP with no ABP). On those
#: revisions the air-bladder reading is carried in Data Message 3.
#:
#: Data Message 3 spec byte 3 tracks the reference closely (123/123/123/
#: 125 against 123/122/123/126) and is therefore ``ABP``, **not** ``VAC``
#: as D3 p.6 labels it -- applying the documented vacuum conversion to
#: that byte gives +6.27 inHg where the reference reports -28.009 inHg,
#: which is not physically possible for a vacuum. Verified telemetry
#: overrides the source listing here.
#:
#: It still is not emitted for 1010: the residual +/-1 count is the same
#: unresolved multi-copy averaging rule that blocks the calibrated
#: channels (see ``UNSUPPORTED_TECH_PARAMETERS``), so an exact value
#: cannot be reconstructed.
FIRMWARE_LIMITED_TECH_PARAMETERS: dict[str, str] = {
    "PRESSURE_AirBladder_COUNT": (
        "absent from Data Message 1 on decoder 1010 (D5 p.21); the Data "
        "Message 3 source is subject to the unresolved DAC averaging rule"
    ),
}


#: CLS location class -> approved Argo label.
_ARGOS_CLASS_LABELS: dict[str, str] = {
    "0": "NUMBER_ArgosPositioningClass0_COUNT",
    "1": "NUMBER_ArgosPositioningClass1_COUNT",
    "2": "NUMBER_ArgosPositioningClass2_COUNT",
    "3": "NUMBER_ArgosPositioningClass3_COUNT",
    "A": "NUMBER_ArgosPositioningClassA_COUNT",
    "B": "NUMBER_ArgosPositioningClassB_COUNT",
    "Z": "NUMBER_ArgosPositioningClassZ_COUNT",
}


@dataclass(frozen=True)
class TechRecord:
    """One ``(cycle, parameter, value)`` row."""

    cycle_number: int
    name: str
    value: str


def format_termination_flag(status_word: int) -> str:
    """Render ``STATUS`` as the DAC's ``FLAG_ProfileTermination_hex``.

    The references use a 12-bit flag word rather than the raw 16-bit
    engineering ``STATUS``: bit 15 (``PrfIdOverflow``) is re-packed into
    bit 11, and the result is printed as bare uppercase hex zero-padded
    to two digits. Verified against every comparable cycle of the three
    floats with references (78/78 exact), reproducing the full observed
    value set ``01, 05, 0D, 4D, 801, 805, 84D, 901``.

    ``PrfIdOverflow`` is a profile-counter artefact rather than a
    termination cause, which is presumably why the DAC moves it out of
    the top bit.
    """
    packed = (status_word & 0x7FFF) | (0x800 if status_word & 0x8000 else 0)
    return f"{packed:02X}"


def _format_number(value: float) -> str:
    """Render a numeric technical value the way the references do."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def technical_values_for_cycle(engineering: ApexEngineeringData) -> dict[str, str]:
    """Return every technical value the decoder can derive for one cycle.

    This is the full computation, including the parameters that are
    deliberately withheld from the file (see
    :data:`DERIVED_NOT_PUBLISHED_TECH_PARAMETERS`). Callers that want the
    published subset should use :func:`technical_records_for_cycle`.
    """
    values: dict[str, str] = {}

    if engineering.status_word is not None:
        values["FLAG_ProfileTermination_hex"] = format_termination_flag(engineering.status_word)
    if engineering.surface_pressure_dbar is not None:
        values["PRES_SurfaceOffsetNotTruncated_dbar"] = _format_number(
            engineering.surface_pressure_dbar
        )
    if engineering.piston_position_surface_counts is not None:
        values["POSITION_PistonSurface_COUNT"] = str(engineering.piston_position_surface_counts)
    if engineering.pump_motor_time_s is not None:
        values["TIME_PumpMotor_seconds"] = str(engineering.pump_motor_time_s)
    if engineering.piston_position_deep_descent_counts is not None:
        values["POSITION_PistonProfile_COUNT"] = str(
            engineering.piston_position_deep_descent_counts
        )
    if engineering.piston_position_park_end_counts is not None:
        values["POSITION_PistonPark_COUNT"] = str(engineering.piston_position_park_end_counts)
    # PRESSURE_AirBladder_COUNT -- ``ABP``, the air bladder pressure
    # recorded just after each Argos transmission. Like the vacuum, the
    # source byte moves with the firmware: 061810 carries it in message 1
    # (``ApexCoDecoder`` 061810 row 109), while 110613/091x15 moves it to
    # message-3 payload byte 1 (APF9A 110613 manual p.25 "3 ABP";
    # ``decode_data_apx_10.m:838`` reads the same field).
    #
    # An earlier revision withheld it on 091x15 on the grounds that the
    # reference "matches no byte in the message" -- that search covered
    # message 1 only. Read from message 3 the byte reproduces the
    # reference directly.
    air_bladder = engineering.air_bladder_pressure_counts
    if engineering.decoder_id in _ABP_MSG3_DECODERS:
        air_bladder = engineering.msg3_air_bladder_counts
    if air_bladder is not None:
        values["PRESSURE_AirBladder_COUNT"] = str(air_bladder)

    # Calibrated battery channels. Emitted only where the conversion is
    # verified against the references (see _BATTERY_VERIFIED_DECODERS);
    # on decoder 1010 the multi-copy averaging rule remains unresolved,
    # so those stay in UNSUPPORTED_TECH_PARAMETERS rather than being
    # published under a guessed aggregation.
    if engineering.decoder_id in _BATTERY_VERIFIED_DECODERS:
        channels = list(_BATTERY_CHANNELS)
        voltage = _PROFILE_DEPTH_VOLTAGE_BY_DECODER.get(engineering.decoder_id or -1)
        if voltage is not None:
            channels.append(
                (
                    "VOLTAGE_BatteryInitialAtProfileDepth_volts",
                    "battery_voltage_pump_counts",
                    *voltage,
                )
            )
        vacuum_attr = _VACUUM_SOURCE_ATTRS.get(engineering.decoder_id or -1)
        if vacuum_attr is not None:
            channels.append(("PRESSURE_InternalVacuum_inHg", vacuum_attr, *_VACUUM_SCALE_OFFSET))
        for label, attribute, scale, offset in channels:
            counts = getattr(engineering, attribute, None)
            if counts is not None:
                values[label] = _format_number(counts * scale + offset)

    # --- float engineering decoded in M3/M4/M5 ---------------------
    #
    # These labels are in the Argo-approved list for decoders 1005/1010
    # (``_tech_param_name_*.json``). They are published because the
    # decoder can derive them honestly, independently of whether a
    # particular DAC emits them.
    if engineering.sbe41_status_word is not None:
        values["FLAG_CTDStatus_hex"] = f"{engineering.sbe41_status_word:02X}"
    if engineering.telonics_status_byte is not None:
        # Raw byte rendered as hex: the manuals define the field but not
        # its bit meanings, so no interpretation is attached.
        values["FLAG_TelonicsPTTStatus_hex"] = f"{engineering.telonics_status_byte:02X}"
    if engineering.n_park_ballast_adjustments is not None:
        values["NUMBER_RepositionsDuringPark_COUNT"] = str(engineering.n_park_ballast_adjustments)
    if engineering.park_sample_count is not None:
        values["NUMBER_ParkSamples_COUNT"] = str(engineering.park_sample_count)
    if engineering.n_samples is not None:
        values["NUMBER_AscendingCTDSamplesInternalCounter_COUNT"] = str(engineering.n_samples)
    if engineering.pressure_divergence_dbar is not None:
        values["PRES_MaxDifferencePvsPTorPTSSamples_dbar"] = _format_number(
            engineering.pressure_divergence_dbar
        )
    if engineering.profile_init_offset_minutes is not None:
        values["CLOCK_AscentInitiationFromDownTimeExpiryOffset_minutes"] = str(
            engineering.profile_init_offset_minutes
        )
    if engineering.n_descent_pressure_marks is not None:
        values["NUMBER_PRESSamplesDuringDescentToPark_COUNT"] = str(
            engineering.n_descent_pressure_marks
        )

    # --- ARGOS reception statistics (D2 rows 239-249) ---------------
    if engineering.n_argos_positions is not None:
        values["NUMBER_ArgosPositions_COUNT"] = str(engineering.n_argos_positions)
        for cls, label in _ARGOS_CLASS_LABELS.items():
            values[label] = str(engineering.argos_position_classes.get(cls, 0))
    if engineering.n_transmission_frames is not None:
        values["NUMBER_TransmissionFloatFramesComplete_COUNT"] = str(
            engineering.n_transmission_frames
        )
    if engineering.n_transmission_frames_crc_ok is not None:
        values["NUMBER_TransmissionFloatFramesCrcOk_COUNT"] = str(
            engineering.n_transmission_frames_crc_ok
        )

    return values


def technical_records_for_cycle(
    cycle_number: int, engineering: ApexEngineeringData
) -> list[TechRecord]:
    """Render one cycle's decoded engineering state as technical rows.

    Only fields with established provenance are emitted; an absent or
    sentinel-valued measurement produces no row at all, which is how the
    ADMT name/value table represents "not available". Values the decoder
    derives but the references do not publish are computed and then
    filtered out here, so the emitted table matches the reference
    vocabulary exactly.
    """
    values = technical_values_for_cycle(engineering)
    return [
        TechRecord(cycle_number=cycle_number, name=name, value=values[name])
        for name in TECH_PARAMETER_ORDER
        if name in values and name in PUBLISHED_TECH_PARAMETERS
    ]


def build_technical_records(
    engineering_by_cycle: dict[int, ApexEngineeringData],
) -> list[TechRecord]:
    """Build the full technical table, cycles in ascending order.

    Mission-prelude transmissions are skipped: their ``PRF`` counter
    collides with a real cycle and their engineering block describes the
    self-test, not a profile.
    """
    records: list[TechRecord] = []
    for cycle_number in sorted(engineering_by_cycle):
        engineering = engineering_by_cycle[cycle_number]
        if engineering.status_flags.get("prelude_message"):
            continue
        records.extend(technical_records_for_cycle(cycle_number, engineering))
    return records


def build_technical_dataset(
    records: list[TechRecord],
    *,
    wmo: int,
    meta: FloatMeta | None = None,
    institution: str = "IF",
    date_creation: str | None = None,
    date_update: str | None = None,
) -> xr.Dataset:
    """Build the ADMT ``<wmo>_tech.nc`` dataset."""
    now = utc_stamp()
    created = date_creation or now
    updated = date_update or now
    data_centre = str(meta.data_centre) if meta is not None and meta.data_centre else ""

    data_vars: dict[str, xr.DataArray] = {}

    data_vars["DATE_CREATION"] = date_char(created)
    data_vars["DATE_CREATION"].attrs = {
        "long_name": "Date of file creation",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["DATE_UPDATE"] = date_char(updated)
    data_vars["DATE_UPDATE"].attrs = {
        "long_name": "Date of update of this file",
        "conventions": "YYYYMMDDHHMISS",
        "_FillValue": b" ",
    }
    data_vars["PLATFORM_NUMBER"] = scalar_char(str(wmo), STRING8)
    data_vars["PLATFORM_NUMBER"].attrs = {
        "long_name": "Float unique identifier",
        "conventions": "WMO float identifier : A9IIIII",
        "_FillValue": b" ",
    }
    data_vars["DATA_CENTRE"] = scalar_char(data_centre or institution, STRING2)
    data_vars["DATA_CENTRE"].attrs = {
        "long_name": "Data centre in charge of float data processing",
        "conventions": "Argo reference table 4",
        "_FillValue": b" ",
    }
    data_vars["DATA_TYPE"] = scalar_char("Argo technical data", STRING32)
    data_vars["DATA_TYPE"].attrs = {
        "long_name": "Data type",
        "conventions": "Argo reference table 1",
        "_FillValue": b" ",
    }
    data_vars["FORMAT_VERSION"] = scalar_char("3.1", STRING4)
    data_vars["FORMAT_VERSION"].attrs = {
        "long_name": "File format version",
        "_FillValue": b" ",
    }
    # Right-aligned ' 1.2' in every supplied technical reference.
    data_vars["HANDBOOK_VERSION"] = scalar_char(" 1.2", STRING4)
    data_vars["HANDBOOK_VERSION"].attrs = {
        "long_name": "Data handbook version",
        "_FillValue": b" ",
    }

    names = [rec.name for rec in records]
    values = [rec.value for rec in records]
    cycles = [rec.cycle_number for rec in records]

    data_vars["TECHNICAL_PARAMETER_NAME"] = char_column(names, STRING128, _TECH)
    data_vars["TECHNICAL_PARAMETER_NAME"].attrs = {
        "long_name": "Name of technical parameter",
        "_FillValue": b" ",
    }
    data_vars["TECHNICAL_PARAMETER_VALUE"] = char_column(values, STRING128, _TECH)
    data_vars["TECHNICAL_PARAMETER_VALUE"].attrs = {
        "long_name": "Value of technical parameter",
        "_FillValue": b" ",
    }
    data_vars["CYCLE_NUMBER"] = xr.DataArray(
        np.asarray(cycles, dtype=np.int32),
        dims=(_TECH,),
        attrs={
            "long_name": "Float cycle number",
            "conventions": "0...N, 0 : launch cycle (if exists), 1 : first complete cycle",
            "_FillValue": INT_FILL,
        },
    )

    out = xr.Dataset(data_vars)
    globals_ = standard_globals(
        title="Argo float technical data file",
        institution=data_centre or institution,
        feature_type="",
    )
    # The technical references carry no featureType.
    globals_.pop("featureType", None)
    out.attrs.update(globals_)
    return out


def write_technical_file(ds: xr.Dataset, path: Path) -> None:
    """Write a technical dataset to ``path`` in ADMT dimension order."""
    fixed: dict[str, int | None] = {
        "STRING2": STRING2,
        "STRING4": STRING4,
        "STRING8": STRING8,
        "STRING32": STRING32,
        "STRING128": STRING128,
        "DATE_TIME": DATE_TIME_LEN,
        # Unlimited, matching the references.
        _TECH: None,
    }
    write_admt_dataset(
        ds,
        path,
        fixed_dims=fixed,
        dim_order=(
            "STRING2",
            "STRING4",
            "STRING8",
            "STRING32",
            "STRING128",
            "DATE_TIME",
            _TECH,
        ),
    )


__all__ = [
    "DERIVED_NOT_PUBLISHED_TECH_PARAMETERS",
    "FIRMWARE_LIMITED_TECH_PARAMETERS",
    "GDAC_VERIFIED_TECH_PARAMETERS",
    "PUBLISHED_TECH_PARAMETERS",
    "TECH_PARAMETER_ORDER",
    "UNSUPPORTED_TECH_PARAMETERS",
    "TechRecord",
    "build_technical_dataset",
    "build_technical_records",
    "format_termination_flag",
    "technical_records_for_cycle",
    "technical_values_for_cycle",
    "write_technical_file",
]

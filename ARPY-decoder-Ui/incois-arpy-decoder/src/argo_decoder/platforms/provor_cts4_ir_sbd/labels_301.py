"""Decoder-301 label maps: NKE wire fields ↔ Coriolis label tables (Phase 2A).

Sources (read verbatim at test time; this module stores the *mapping*, and the
tests verify it against the authoritative tables)::

    decArgo_soft/config/_configParamNames/_config_param_name_301.csv  (82 rows)
    decArgo_soft/config/_techParamNames/_tech_param_name_301.csv      (64 rows)

Map values are label NAMEs exactly as stored (including ``<D>``, ``<Sensor>``,
``<Z>`` template placeholders); None means "transmitted wire field with no 301
label" (a mapping gap, decoded anyway) or "structural/reformatted field" (see
notes). Label DESCRIPTIONs are not duplicated here — the CSVs stay the
authority for wording.

Template expansions (observed in GDAC reference ``meta.nc`` / ``tech.nc``,
INCOIS 2902091):

* ``<D>`` in 255 PV labels = duration number 1..5 by position.
* ``<Sensor>`` in 250 labels = ``CTD`` / ``Optode`` / ``Flbb`` (GDAC tech
  names, e.g. ``NUMBER_FlbbAscentIridiumMessages_COUNT``).
* ``<Z>`` in 250 labels = depth-zone number 1..5 by position.
* ``<short_sensor_name>`` in 251 labels = ``CTD`` / ``Optode`` / ``Flbb``;
  ``<N>`` = zone number. Packet 251 is never transmitted unless a parameter
  changed (absent from the corpus), so its 29 labels are unvalidatable here.
"""

from __future__ import annotations

from dataclasses import dataclass

_PREFIX = "CONFIG_"

#: PT word index 0..27 → 301 CONFIG name (msg 254) or None (no 301 label).
PT_CONFIG_LABEL: dict[int, str | None] = {
    0: _PREFIX + "SurfaceValveMaxTimeAdditionalActions_csec",
    1: _PREFIX + "SurfaceValveAdditionalActions_COUNT",
    2: _PREFIX + "PressureCheckTimeBuoyancyReductionPhase_seconds",
    3: _PREFIX + "PressureCheckTimeAscent_minutes",
    4: _PREFIX + "OilVolumeMaxPerValveAction_cm^3",
    5: _PREFIX + "PumpActionMaxTimeReposition_csec",
    6: _PREFIX + "PumpActionMaxTimeAscent_csec",
    7: _PREFIX + "PumpActionTimeBuoyancyAcquisition_csec",
    8: _PREFIX + "PressureTargetToleranceForStabilisation_dbar",
    9: _PREFIX + "PressureMaxBeforeEmergencyAscent_dbar",
    10: _PREFIX + "BuoyancyReductionFirstThreshold_dbar",
    11: _PREFIX + "BuoyancyReductionSecondThreshold_dbar",
    # NOTE: NKE PT12 reads "Repositioning threshold (in dBars)" while 301/212
    # describes a COUNT of out-of-tolerance measurements. The raw word decodes
    # identically either way; the semantic conflict is documented, unresolved.
    12: _PREFIX + "NumberOfOutOfTolerancePresBeforeReposition_COUNT",
    13: _PREFIX + "GroundingMode_LOGICAL",
    14: _PREFIX + "OilVolumeMinForGroundingDetection_cm^3",
    15: _PREFIX + "GroundingModeMinPresThreshold_dbar",
    16: _PREFIX + "GroundingModePresAdjustment_dbar",
    17: _PREFIX + "PressureTargetToleranceDuringDrift_dbar",
    18: _PREFIX + "DescentSpeed_mm/s",
    19: None,  # pressure increment: transmitted, no 301 label
    20: None,  # Iridium modem timeout: transmitted, no 301 label
    21: _PREFIX + "AscentSpeedMin_mm/s",
    22: _PREFIX + "AscentSpeed_mm/s",
    23: None,  # wait on surface after emergency: transmitted, no 301 label
    24: None,  # oil volume after buoyancy reduction: transmitted, no label
    25: None,  # Iridium retries: transmitted, no 301 label
    26: _PREFIX + "InternalPressureCalibrationCoef1_NUMBER",
    27: _PREFIX + "InternalPressureCalibrationCoef2_NUMBER",
}

#: PM word index 0..52 → 301 CONFIG name (msg 255) or None.
#:
#: Only profile-1 slots are labeled (303..307); profiles 2..10 (PM8..PM52)
#: are transmitted with no 301 labels.
PM_CONFIG_LABEL: dict[int, str | None] = {
    0: _PREFIX + "NumberOfSubCycles_NUMBER",
    1: _PREFIX + "DelayBeforeMissionStart_minutes",
    2: _PREFIX + "FloatReferenceDay_FloatDay",
    3: _PREFIX + "SurfaceDay_FloatDay",
    4: _PREFIX + "SurfaceTime_HH",
    5: _PREFIX + "ParkPressure_dbar",
    6: _PREFIX + "ProfilePressure_dbar",
    7: _PREFIX + "TransmissionEndCycle_LOGICAL",
    **{index: None for index in range(8, 53)},
}

_PV_PERIOD = _PREFIX + "InternalCycleTime<D>_hours"
_PV_DD = _PREFIX + "InternalCycle<D>LastGregDay_DD"
_PV_MM = _PREFIX + "InternalCycle<D>LastGregMonth_MM"
_PV_YY = _PREFIX + "InternalCycle<D>LastGregYear_YYYY"

#: PV word index 0..22 → 301 CONFIG name (msg 255). ``<D>`` = duration 1..5.
PV_CONFIG_LABEL: dict[int, str] = {
    0: _PREFIX + "NumberOfInternalCycles_COUNT",
    1: _PREFIX + "TransmissionPeriodEndOfLife_minutes",
    2: _PREFIX + "TelemetryRepeatSessionDelay_minutes",
    3: _PV_PERIOD, 4: _PV_DD, 5: _PV_MM, 6: _PV_YY,
    7: _PV_PERIOD, 8: _PV_DD, 9: _PV_MM, 10: _PV_YY,
    11: _PV_PERIOD, 12: _PV_DD, 13: _PV_MM, 14: _PV_YY,
    15: _PV_PERIOD, 16: _PV_DD, 17: _PV_MM, 18: _PV_YY,
    19: _PV_PERIOD, 20: _PV_DD, 21: _PV_MM, 22: _PV_YY,
}

#: 301 CONFIG labels with no wire field (decoder-computed, msg 255).
DERIVED_ONLY_CONFIG_LABELS: tuple[str, ...] = (
    _PREFIX + "CycleTime_hours",  # 407: computed from PV parameters
)

#: :class:`VectorTech` field name → 301 TECH name (msg 253) or None.
TECH253_LABEL: dict[str, str | None] = {
    # NOTE: the float time is carried as Y/M/D/h/m/s components; the label
    # value is a formatted YYYYMMDDHHMMSS string (formatting, not decoding).
    "time": "CLOCK_FloatTime_YYYYMMDDHHMMSS",
    "serial": None,  # → meta PLATFORM_NUMBER, not a tech label
    "total_profiles": "NUMBER_SubCyclesDoneSinceDeployment_COUNT",
    "cycle": "NUMBER_InternalCycle_NUMBER",
    "profile": "NUMBER_SubCycle_NUMBER",
    "cycle_start_day": "CLOCK_StartInternalCycle_FloatDay",
    "cycle_start_hour": "CLOCK_StartInternalCycle_HHMM",
    "phase": None,  # transmitted, no 301 label
    "dialog_errors": "NUMBER_VectorToSensorBoardsDialogErrors_COUNT",
    "timeout_fp": "NUMBER_SBEFPCommandTimeouts_COUNT",
    "vacuum_raw": "PRESSURE_InternalVacuumAtSurface_mbar",
    "battery_raw": "VOLTAGE_BatteryPumpStartProfile_volts",
    "rtc": "FLAG_RTCStatus_LOGICAL",
    "buoy_start_day": "CLOCK_InitialValveActionDescentToPark_FloatDay",
    "buoy_start_hour": "CLOCK_InitialValveActionDescentToPark_HHMM",
    "ev_timing_min": "TIME_ValveActionsAtSurface_minutes",
    "n_valve_surface": "NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT",
    "park_desc_start_day": "CLOCK_StartDescentToPark_FloatDay",
    "park_desc_start_hour": "CLOCK_StartDescentToPark_HHMM",
    "stab_day": "CLOCK_InitialStabilizationDuringDescentToPark_FloatDay",
    "stab_hour": "CLOCK_InitialStabilizationDuringDescentToPark_HHMM",
    "park_desc_end_day": "CLOCK_EndDescentToPark_FloatDay",
    "park_desc_end_hour": "CLOCK_EndDescentToPark_HHMM",
    "n_valve_desc_park": "NUMBER_ValveActionsDuringDescentToPark_COUNT",
    "n_pump_desc_park": "NUMBER_PumpActionsDuringDescentToPark_COUNT",
    "stab_pres_bar": None,  # transmitted 1-Bar value, no 301 label
    "max_pres_desc_park_bar": None,  # transmitted 1-Bar value, no 301 label
    "n_entries_park": "NUMBER_DescentToParkEntriesInParkMargin_COUNT",
    "n_repos_park": "NUMBER_RepositionsDuringPark_COUNT",
    "min_pres_drift_park_bar": None,  # transmitted 1-Bar value, no 301 label
    "max_pres_drift_park_bar": None,  # transmitted 1-Bar value, no 301 label
    "n_valve_park": "NUMBER_ValveActionsDuringPark_COUNT",
    "n_pump_park": "NUMBER_PumpActionsDuringPark_COUNT",
    "prof_desc_start_day": "CLOCK_StartDescentToProfile_FloatDay",
    "prof_desc_start_hour": "CLOCK_StartDescentToProfile_HHMM",
    "prof_desc_end_day": "CLOCK_EndDescentToProfile_FloatDay",
    "prof_desc_end_hour": "CLOCK_EndDescentToProfile_HHMM",
    "n_valve_desc_prof": "NUMBER_ValveActionsDuringDescentToProfile_COUNT",
    "n_pump_desc_prof": "NUMBER_PumpActionsDuringDescentToProfile_COUNT",
    "max_pres_desc_prof_bar": None,  # transmitted 1-Bar value, no 301 label
    "n_entries_prof": "NUMBER_DescentToProfileEntriesInProfileMargin_COUNT",
    "n_repos_prof": "NUMBER_RepositionsAtProfileDepth_COUNT",
    "n_valve_drift_prof": "NUMBER_ValveActionsDuringProfileDrift_COUNT",
    "n_pump_drift_prof": "NUMBER_PumpActionsDuringProfileDrift_COUNT",
    "min_pres_drift_prof_bar": None,  # transmitted 1-Bar value, no 301 label
    "max_pres_drift_prof_bar": None,  # transmitted 1-Bar value, no 301 label
    "ascent_start_day": "CLOCK_StartAscentToSurface_FloatDay",
    "ascent_start_hour": "CLOCK_StartAscentToSurface_HHMM",
    # NOTE: 152/153 are named "PumpActionsAtSurface" but described as the
    # end-of-ascent stamp (matches GDAC CLOCK_PumpActionsAtSurface_* values).
    "ascent_end_day": "CLOCK_PumpActionsAtSurface_FloatDay",
    "ascent_end_hour": "CLOCK_PumpActionsAtSurface_HHMM",
    "n_pump_ascent": "NUMBER_PumpActionsDuringAscentToSurface_COUNT",
    "grounding_detected": None,  # transmitted flag, no 301 label
    "grounding_pres_bar": None,  # transmitted 1-Bar value, no 301 label
    "grounding_day": "CLOCK_TimeGrounded_FloatDay",
    "grounding_hour": "CLOCK_TimeGrounded_HHMM",
    "n_emergency": "NUMBER_EmergencyAscents_COUNT",
    "emergency1_time_min": "CLOCK_TimeOfFirstEmergencyAscent_HHMM",
    "emergency1_pres_bar": "PRES_FirstEmergencyAscent_dbar",
    "n_pump_emergency1": "NUMBER_PumpActionsOnFirstEmergencyAscent_COUNT",
    "emergency1_rel_day": "CLOCK_TimeOfFirstEmergencyAscent_FloatDay",
    "remote_rx": "FLAG_RemoteControlMessageOK_COUNT",
    "remote_rej": "FLAG_RemoteControlMessageKO_COUNT",
    # GPS components → trajectory positions, never tech labels.
    "gps_lat_deg": None,
    "gps_lat_min": None,
    "gps_lat_frac": None,
    "gps_lat_hem": None,
    "gps_lon_deg": None,
    "gps_lon_min": None,
    "gps_lon_frac": None,
    "gps_lon_hem": None,
    "gps_valid": None,
    # Show modes mirror the mission CONFIG labels (msg -1), not tech labels.
    "show_vector": None,
    "show_sensor": None,
    "spare": None,  # structural
}

#: 301 TECH labels with no wire field (decoder-derived timestamps, msg 253).
DERIVED_ONLY_TECH_LABELS: tuple[str, ...] = (
    "CLOCK_StartInternalCycle_YYYYMMDDHHMMSS",  # 104
    "CLOCK_PumpActionsAtSurface_YYYYMMDDHHMMSS",  # 154
    "CLOCK_TimeOfFirstEmergencyAscent_YYYYMMDDHHMMSS",  # 166
)

#: :class:`SensorHalf` field name → 301 TECH name template (msg 250) or None.
TECH250_LABEL: dict[str, str | None] = {
    "present": None,  # structural (filler marker)
    "sensor": None,  # feeds the <Sensor> template slot
    "cycle": None,  # structural identity
    "profile": None,  # structural identity
    "tx_descent": "NUMBER_<Sensor>DescentIridiumMessages_COUNT",
    "tx_drift": "NUMBER_<Sensor>ParkIridiumMessages_COUNT",
    "tx_ascent": "NUMBER_<Sensor>AscentIridiumMessages_COUNT",
    "acq_descent": "NUMBER_<Sensor>DescentSamplesDepthZone<Z>_COUNT",
    "acq_drift": "NUMBER_Park<Sensor>SamplesInternal_COUNT",
    "acq_ascent": "NUMBER_<Sensor>AscentSamplesDepthZone<Z>_COUNT",
    "status": "FLAG_<Sensor>Status_LOGICAL",
    "free": None,  # sensor-specific: see the CTD/FLBB/Optode free-zone maps
    "raw": None,  # structural
}

#: :class:`CtdFree` field name → 301 TECH name (msg 250) or None.
TECH250_CTD_FREE_LABEL: dict[str, str | None] = {
    "offset_p": "PRES_SurfaceOffsetBeforeReset_1cBarResolution_dbar",
    "p_sub": "PRES_LastAscentPumpedRawSample_dbar",
    "t_sub": None,  # transmitted, no 301 label
    "s_sub": None,  # transmitted, no 301 label
    "spare": None,  # structural
}

#: :class:`FlbbFree` field name → 301 TECH name (msg 250) or None.
TECH250_FLBB_FREE_LABEL: dict[str, str | None] = {
    "serial": None,  # transmitted, no 301 label (-> sensor metadata)
    "scale_chl": None,  # transmitted factory coef, no 301 label
    "dark_chl": None,  # transmitted factory coef, no 301 label
    "scale_bb": None,  # transmitted factory coef, no 301 label
    "dark_bb": None,  # transmitted factory coef, no 301 label
    "scale_chl_2": None,  # transmitted, no 301 label
    "spare": None,  # structural
}

#: ``<Sensor>`` expansion observed in GDAC reference ``tech.nc``.
SENSOR_250_NAMES: tuple[str, ...] = ("CTD", "Optode", "Flbb")

#: ``<short_sensor_name>`` expansion observed in GDAC ``meta.nc`` launch config.
SHORT_SENSOR_251_NAMES: tuple[str, ...] = ("CTD", "Optode", "Flbb")


@dataclass(frozen=True)
class CoverageReport:
    """Wire↔label coverage computed from the maps plus the label tables."""

    n_config_labels: int
    n_tech_labels: int
    mapped_pt: int
    unmapped_pt: tuple[int, ...]
    mapped_pm: int
    unmapped_pm: tuple[int, ...]
    mapped_pv_slots: int
    mapped_tech253_fields: int
    unmapped_tech253_fields: tuple[str, ...]
    mapped_tech250_fields: int
    unmapped_tech250_leaves: tuple[str, ...]
    derived_only_config: tuple[str, ...] = DERIVED_ONLY_CONFIG_LABELS
    derived_only_tech: tuple[str, ...] = DERIVED_ONLY_TECH_LABELS
    uncovered_config_names: tuple[str, ...] = ()
    uncovered_tech_names: tuple[str, ...] = ()


def coverage(
    config_labels: list[tuple[int, int, str]],
    tech_labels: list[tuple[int, int, str]],
) -> CoverageReport:
    """Compute wire↔label coverage from parsed label-table rows.

    Args:
        config_labels: ``(dec_id, msg_id, name)`` rows of the 301 config table.
        tech_labels: ``(dec_id, msg_id, name)`` rows of the 301 tech table.

    "Uncovered" names are labels no wire field maps to (expected: 251 + -1
    config labels and derived-only labels); anything else uncovered is a
    mapping bug the tests pin down.
    """
    mapped_names = (
        {name for name in PT_CONFIG_LABEL.values() if name}
        | {name for name in PM_CONFIG_LABEL.values() if name}
        | set(PV_CONFIG_LABEL.values())
        | set(DERIVED_ONLY_CONFIG_LABELS)
    )
    uncovered_config = tuple(
        sorted(
            {name for _, _, name in config_labels}
            - mapped_names
            - {name for _, msg, name in config_labels if msg in (251, -1)}
        )
    )
    mapped_tech = (
        {name for name in TECH253_LABEL.values() if name}
        | {name for name in TECH250_LABEL.values() if name}
        | {name for name in TECH250_CTD_FREE_LABEL.values() if name}
        | set(DERIVED_ONLY_TECH_LABELS)
    )
    uncovered_tech = tuple(
        sorted({name for _, _, name in tech_labels} - mapped_tech)
    )
    free_leaves = (
        tuple(f"ctd_free.{name}" for name, label in TECH250_CTD_FREE_LABEL.items()
              if label is None and name != "spare")
        + tuple(f"flbb_free.{name}" for name, label in TECH250_FLBB_FREE_LABEL.items()
                if label is None and name != "spare")
    )
    return CoverageReport(
        n_config_labels=len(config_labels),
        n_tech_labels=len(tech_labels),
        mapped_pt=sum(1 for label in PT_CONFIG_LABEL.values() if label),
        unmapped_pt=tuple(
            sorted(index for index, label in PT_CONFIG_LABEL.items() if label is None)
        ),
        mapped_pm=sum(1 for label in PM_CONFIG_LABEL.values() if label),
        unmapped_pm=tuple(
            sorted(index for index, label in PM_CONFIG_LABEL.items() if label is None)
        ),
        mapped_pv_slots=len(PV_CONFIG_LABEL),
        mapped_tech253_fields=sum(1 for label in TECH253_LABEL.values() if label),
        unmapped_tech253_fields=tuple(
            sorted(name for name, label in TECH253_LABEL.items() if label is None)
        ),
        mapped_tech250_fields=sum(1 for label in TECH250_LABEL.values() if label)
        + sum(1 for label in TECH250_CTD_FREE_LABEL.values() if label),
        unmapped_tech250_leaves=free_leaves,
        uncovered_config_names=uncovered_config,
        uncovered_tech_names=uncovered_tech,
    )


__all__ = [
    "DERIVED_ONLY_CONFIG_LABELS",
    "DERIVED_ONLY_TECH_LABELS",
    "PM_CONFIG_LABEL",
    "PT_CONFIG_LABEL",
    "PV_CONFIG_LABEL",
    "SENSOR_250_NAMES",
    "SHORT_SENSOR_251_NAMES",
    "TECH250_CTD_FREE_LABEL",
    "TECH250_FLBB_FREE_LABEL",
    "TECH250_LABEL",
    "TECH253_LABEL",
    "CoverageReport",
    "coverage",
]

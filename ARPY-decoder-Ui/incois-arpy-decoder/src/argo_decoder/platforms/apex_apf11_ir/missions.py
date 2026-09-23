"""APF11 CONFIG_MISSION_NUMBER computation.

Uses the Coriolis decoder's mapped configuration-tracking rules
(source: decArgo_soft ``update_float_config_apx_apf11_ir.m``,
``config_exists_ir_sbd_argos.m``, ``create_sampling_configuration.m``, all
vendored under ``tests/data/apex_apf11/coriolis_src/``):

* the per-cycle configuration vector = ``MissionCfg`` parameters mapped
  through the published ``get_config`` whitelist, plus the sampling
  configuration expanded to ``CONFIG_SAMPLE_/CONFIG_PROFILE_/CONFIG_MEASURE_/
  CONFIG_LISTEN_/CONFIG_POWER_`` entries;
* ``CONFIG_PPP_ParkPistonPosition`` and ``CONFIG_TPP_ProfilePistonPosition``
  (the ``ParkDescentCount``/``DeepDescentCount`` derived piston counts that
  change every cycle) are ignored in the comparison;
* derived parameters are recomputed per cycle: ``CONFIG_CT_CycleTime =
  DownTime + UpTime`` (DPF variant at cycle 1) and the
  ``ParkAndProfileCycleLength != 1`` ProfilePressure override;
* a configuration is compared NaN-strictly against every existing column;
  a new mission number is appended only when no column matches (the launch
  column #0 is never referenced by data cycles);
* a cycle without any ``MissionCfg``/``sample_cfg`` block inherits the
  running state, matching ``newConfigValues = VALUES(:, end)``.

This is content-driven: a mission number changes only when the mapped
configuration content changes. It contains no float identifiers and no
publication values.

Mission IDs are local references into one shared metadata configuration history,
not transmitted identifiers or GDAC mission numbers. Recurring states reuse their
IDs; absent echoes inherit the active state, not the most recently created
column. Full vectors and raw representatives remain available for audit. The
metadata writer currently projects the legacy configuration subset plus effective
cycle duration; this does not claim complete configuration-vocabulary coverage.
"""

from __future__ import annotations

import gzip
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# MissionCfg label -> CONFIG name mapping (get_config whitelist, verbatim)
# ---------------------------------------------------------------------------

#: labels mapped by string value with unit conversion or flags
_ON_OFF_FLAGS = {
    "ActivateRecoveryMode": "CONFIG_ARM_ActivateRecoveryModeFlag",
    "DeepProfileFirst": "CONFIG_DPF_DeepProfileFirstFloat",
    "LeakDetect": "CONFIG_LD_LeakDetectFlag",
    "PreludeSelfTest": "CONFIG_PST_PreludeSelfTestFlag",
}
#: labels mapped hex -> decimal
_HEX_PARAMS = {
    "IceMonths": "CONFIG_ICEM_IceDetectionMask",
    "VitalsMask": "CONFIG_VM_VitalsMask",
}
#: labels mapped plain numeric
_NUM_PARAMS = {
    "AscentRate": "CONFIG_AR_AscentRate",
    "AscentTimeout": "CONFIG_ASCEND_AscentTimeOut",
    "AscentTimerInterval": "CONFIG_ATI_AscentTimerInterval",
    "BuoyancyNudge": "CONFIG_NUDGE_AscentBuoyancyNudge",
    "DeepDescentCount": "CONFIG_TPP_ProfilePistonPosition",
    "DeepDescentPressure": "CONFIG_TP_ProfilePressure",
    "DeepDescentTimeout": "CONFIG_DPDP_DeepProfileDescentPeriod",
    "DeepDescentTimerInterval": "CONFIG_DDTI_DeepDescentTimerInterval",
    "DownTime": "CONFIG_DOWN_DownTime",
    "EmergencyTimerInterval": "CONFIG_ETI_EmergencyTimerInterval",
    "HyperRetractCount": "CONFIG_HRC_HyperRetractCount",
    "HyperRetractPressure": "CONFIG_HRP_HyperRetractPressure",
    "IceAscentTimeout": "CONFIG_IAT_IceAscentTimeout",
    "IceBreakupDays": "CONFIG_IBD_IceBreakupDays",
    "IceCriticalT": "CONFIG_IMLT_IceDetectionTemperature",
    "IceDescentCount": "CONFIG_IDCO_IceDescentCount",
    "IceDescentCycles": "CONFIG_IDC_IceDescentCycles",
    "IceDescentNudge": "CONFIG_IDN_IceDescentNudge",
    "IceDescentPressure": "CONFIG_IDPRES_IceDescentPressure",
    "IceDescentTimeout": "CONFIG_IDT_IceDescentTimeout",
    "IceDescentTimerInterval": "CONFIG_IDTI_IceDescentTimerInterval",
    "IceDetectionP": "CONFIG_IDP_IceDetectionMaxPres",
    "IceEvasionP": "CONFIG_IEP_IceEvasionPressure",
    "IdleTimerInterval": "CONFIG_ITI_IdleTimerInterval",
    "InitialBuoyancyNudge": "CONFIG_IBN_InitialBuoyancyNudge",
    "LogVerbosity": "CONFIG_DEBUG_LogVerbosity",
    "MActivationCount": "CONFIG_PACT_PressureActivationPistonPosition",
    "MActivationPressure": "CONFIG_MAP_MissionActivationPressure",
    "MinBuoyancyCount": "CONFIG_MBC_MinBuoyancyCount",
    "MinVacuum": "CONFIG_OK_OkInternalVacuum",
    "ParkBottomDeltaPressure": "CONFIG_PBDP_ParkBottomDeltaPressure",
    "ParkBuoyancyNudge": "CONFIG_PBN_ParkBuoyancyNudge",
    "ParkDeadBand": "CONFIG_PDB_ParkDeadBand",
    "ParkDescentCount": "CONFIG_PPP_ParkPistonPosition",
    "ParkDescentTimeout": "CONFIG_PDP_ParkDescentPeriod",
    "ParkDescentTimerInterval": "CONFIG_PDTI_ParkDescentTimerInterval",
    "ParkPressure": "CONFIG_PRKP_ParkPressure",
    "ParkTimerInterval": "CONFIG_PTI_ParkTimerInterval",
    "PnPCycleLen": "CONFIG_N_ParkAndProfileCycleLength",
    "PreludeTime": "CONFIG_PRE_MissionPreludePeriod",
    "SurfacePressure": "CONFIG_SPSPC_SurfacePressureStopPumpedCtd",
    "TelemetryInterval": "CONFIG_REP_ArgosTransmissionRepetitionPeriod",
    "TelemetryTimeout": "CONFIG_TT_IceTelemetryTimeout",
    "UpTime": "CONFIG_UP_UpTime",
}

#: parameters ignored when testing whether a configuration already exists
#: (the per-cycle derived piston counts; init_float_config_apx_apf11_ir.m).
IGNORED_CONFIG_NAMES = frozenset(
    {
        "CONFIG_PPP_ParkPistonPosition",
        "CONFIG_TPP_ProfilePistonPosition",
    }
)

_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def _num(text: str) -> float:
    """str2double semantics: plain parse, NaN when not numeric."""
    text = text.strip()
    if _NUM_RE.match(text):
        return float(text)
    return math.nan


def map_mission_cfg(mission_cfg: dict[str, str]) -> dict[str, float]:
    """Map a raw MissionCfg block to the CONFIG_ vector entries."""
    out: dict[str, float] = {}
    for label, value in mission_cfg.items():
        label = label.strip()
        value = value.strip()
        if label in ("CheckSum", "Checksum", "float_id", ""):
            continue  # explicit "not considered" cases
        if label in _ON_OFF_FLAGS:
            out[_ON_OFF_FLAGS[label]] = 0.0 if value.lower() == "off" else 1.0
        elif label in _HEX_PARAMS:
            try:
                out[_HEX_PARAMS[label]] = float(int(value, 16))
            except ValueError:
                out[_HEX_PARAMS[label]] = math.nan
        elif label == "AscentStartTimes":
            vals = [v for v in value.split() if v != "-1"]
            uniq = {v for v in vals}
            if len(uniq) == 1 and vals:
                out["CONFIG_TOD_DownTimeExpiryTimeOfDay"] = _num(vals[0])
            elif not vals:
                continue
            else:
                # Coriolis raises "Don't know how to manage multiple values";
                # we leave the entry untouched (running state persists).
                continue
        elif label == "TelemetryDays":
            vals = value.split()
            if len(vals) >= 1:
                out["CONFIG_TSD_IceTelemetryStartDay"] = _num(vals[0])
            if len(vals) >= 2:
                out["CONFIG_TED_IceTelemetryEndDay"] = _num(vals[1])
        elif label in _NUM_PARAMS:
            out[_NUM_PARAMS[label]] = _num(value)
        # unmapped labels are not tracked in the config vector
    return out


def map_sample_cfg(sample_cfg: dict[str, list[str]]) -> dict[str, float]:
    """Expand a sample_cfg block to CONFIG_SAMPLE_/PROFILE_/MEASURE_ entries.

    ``sample_cfg`` maps phase name -> list of directive lines
    (``SAMPLE``, ``PROFILE``, ``MEASURE``, ``LISTEN``, ``POWER``), following
    ``create_sampling_configuration.m`` (zone numbering 1-based after
    ascending sort on start pressure).
    """
    out: dict[str, float] = {}
    for phase, lines in sample_cfg.items():
        by_type: dict[str, dict[str, list[list[float]]]] = {}
        for line in lines:
            parts = line.split()
            if not parts:
                continue
            kind = parts[0].upper()
            body = parts[1:]
            if kind == "SAMPLE" and len(body) >= 6:
                sensor = body[0]
                start, stop, step = (_num(body[1]), _num(body[2]), _num(body[3]))
                unit = 1.0 if body[4].upper() == "DBAR" else 2.0
                count = _num(body[5])
                row = [start, stop, step, unit, count]
                if len(body) >= 7:
                    row.append(_num(body[6]))
                by_type.setdefault("SAMPLE", {}).setdefault(sensor, []).append(row)
            elif kind == "PROFILE" and len(body) >= 5:
                sensor = body[0]
                nums = [_num(t) for t in body[1:5]]
                by_type.setdefault("PROFILE", {}).setdefault(sensor, []).append(nums)
            elif kind == "MEASURE" and body:
                sensor = body[0]
                by_type.setdefault("MEASURE", {}).setdefault(sensor, []).append([1.0])
            elif kind == "LISTEN" and len(body) >= 3:
                sensor = body[0]
                by_type.setdefault("LISTEN", {}).setdefault(sensor, []).append(
                    [_num(body[1]), _num(body[2])]
                )
            elif kind == "POWER" and len(body) >= 3:
                sensor = body[0]
                by_type.setdefault("POWER", {}).setdefault(sensor, []).append(
                    [_num(body[1]), _num(body[2])]
                )
            # unknown directive types: untracked (Coriolis prints an ERROR)
        for samp_type, sensors in by_type.items():
            for sensor, rows in sensors.items():
                if samp_type == "SAMPLE":
                    rows = sorted(rows, key=lambda r: r[0])
                    out[f"CONFIG_SAMPLE_{phase}_{sensor}_NumberOfZones"] = float(len(rows))
                    for i, row in enumerate(rows, 1):
                        p = f"CONFIG_SAMPLE_{phase}_{sensor}_{i}"
                        out[f"{p}_StartPressure"], out[f"{p}_StopPressure"] = row[0], row[1]
                        if row[3] == 1.0:
                            out[f"{p}_DepthInterval"] = row[2]
                        else:
                            out[f"{p}_TimeInterval"] = row[2]
                        out[f"{p}_NumberOfSamples"] = row[4]
                        if len(row) > 5 and row[5] != 0.0:
                            out[f"{p}_MaxNumberOfSamples"] = row[5]
                elif samp_type == "PROFILE":
                    rows = sorted(rows, key=lambda r: r[0])
                    out[f"CONFIG_PROFILE_{phase}_{sensor}_NumberOfZones"] = float(len(rows))
                    for i, row in enumerate(rows, 1):
                        p = f"CONFIG_PROFILE_{phase}_{sensor}_{i}"
                        out[f"{p}_StartPressure"], out[f"{p}_StopPressure"] = row[0], row[1]
                        if sensor == "PH":
                            out[f"{p}_TimeInterval"] = row[2]
                        else:
                            out[f"{p}_BinSize"] = row[2]
                            out[f"{p}_SampleRate"] = row[3]
                elif samp_type == "MEASURE":
                    out[f"CONFIG_MEASURE_{phase}_{sensor}_NumberOfSamples"] = 10.0
                    out[f"CONFIG_MEASURE_{phase}_{sensor}_TimeInterval"] = 15.0
                elif samp_type == "LISTEN":
                    for row in rows:
                        p = f"CONFIG_LISTEN_{phase}_{sensor}"
                        out[f"{p}_StartDayTime"], out[f"{p}_Duration"] = row[0], row[1]
                elif samp_type == "POWER":
                    for row in rows:
                        p = f"CONFIG_POWER_{phase}_{sensor}"
                        out[f"{p}_StartPressure"], out[f"{p}_StopPressure"] = row[0], row[1]
    return out


def parse_system_log_config(path: str | Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Extract the last MissionCfg and sample_cfg blocks of a system_log.

    Returns ``(mission_cfg, sample_cfg)``; ``sample_cfg`` maps phase ->
    directive lines (section tags ``<PARK>``/``<ASCENT>``/... consumed).
    """
    path = Path(path)
    open_fn = gzip.open if path.suffix == ".gz" else open
    with open_fn(path, "rt", errors="replace") as fh:
        text = fh.read()

    mission_cfg: dict[str, str] = {}
    sample_cfg: dict[str, list[str]] = {}
    mc: dict[str, str] | None = None
    sc: dict[str, list[str]] | None = None
    section: str | None = None
    for line in text.splitlines():
        parts = line.rstrip("\r").split("|")
        if len(parts) < 4:
            continue
        key, payload = parts[2], parts[3]
        if key == "MissionCfg":
            if payload.startswith("-") and "Mission Parameters" in payload:
                mc = {}
                continue
            if payload.startswith("--"):
                if mc:
                    mission_cfg, mc = mc, None  # last complete block wins
                continue
            if mc is not None and " " in payload.strip():
                k, _, v = payload.partition(" ")
                mc[k.strip()] = v.rstrip()
        elif key == "sample_cfg":
            if payload.startswith("#--") and "Sample Config" in payload:
                sc, section = {}, None
                continue
            if payload.startswith("#--"):
                if sc:
                    sample_cfg, sc = sc, None
                continue
            if sc is not None:
                if payload.startswith("<") and payload.endswith(">"):
                    section = payload.strip("<>")
                elif section is not None and payload.strip():
                    sc.setdefault(section, []).append(payload.strip())
    return mission_cfg, sample_cfg


# ---------------------------------------------------------------------------
# Mission tracking
# ---------------------------------------------------------------------------


@dataclass
class MissionTracker:
    """Running configuration tracker for one float.

    ``launch_config`` provides the launch column (#0): mapped CONFIG_ ->
    value pairs from the authoritative launch metadata sheets. The first
    data cycle that differs from it (it always does: unit conventions
    differ) creates mission #1; thereafter numbers change only on mapped
    content changes.
    """

    launch_config: dict[str, float] = field(default_factory=dict)
    columns: list[dict[str, float]] = field(default_factory=list)
    numbers: list[int] = field(default_factory=lambda: [0])
    active_state: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.columns = [dict(self.launch_config)]
        self.active_state = dict(self.launch_config)

    @staticmethod
    def _matches(a: dict[str, float], b: dict[str, float]) -> bool:
        keys = (set(a) | set(b)) - set(IGNORED_CONFIG_NAMES)
        for k in keys:
            va, vb = a.get(k, math.nan), b.get(k, math.nan)
            if math.isnan(va) != math.isnan(vb):
                return False
            if not math.isnan(va) and va != vb:
                return False
        return True

    @staticmethod
    def _derive(state: dict[str, float], cycle: int) -> None:
        """Derived parameters (update_float_config_apx_apf11_ir.m tail)."""
        dpf = state.get("CONFIG_DPF_DeepProfileFirstFloat", 0.0)
        up = state.get("CONFIG_UP_UpTime", math.nan)
        down = state.get("CONFIG_DOWN_DownTime", math.nan)
        tp = state.get("CONFIG_TP_ProfilePressure", math.nan)
        if dpf == 1.0 and cycle == 1 and not (math.isnan(up) or math.isnan(tp)):
            # first cycle of a DPF float: descent at 4 cm/s + 5 min park
            state["CONFIG_CT_CycleTime"] = tp * 100.0 / (4.0 * 60.0) + 5.0 + up
        elif not (math.isnan(up) or math.isnan(down)):
            state["CONFIG_CT_CycleTime"] = up + down
        n_pnp = state.get("CONFIG_N_ParkAndProfileCycleLength", 1.0)
        if n_pnp != 1.0 and cycle > 1 and cycle % n_pnp != 0:
            park = state.get("CONFIG_PRKP_ParkPressure", math.nan)
            if not math.isnan(park):
                state["CONFIG_TP_ProfilePressure"] = park

    def assign(self, cycle: int, mission_cfg: dict[str, str] | None,
               sample_cfg: dict[str, list[str]] | None) -> int:
        """Return the CONFIG_MISSION_NUMBER for one cycle."""
        state = dict(self.active_state)
        if mission_cfg:
            for name, val in map_mission_cfg(mission_cfg).items():
                state[name] = val
        if sample_cfg:
            # clear the sampling sets, then refill (verbatim behaviour)
            for name in list(state):
                if name.startswith(("CONFIG_SAMPLE_", "CONFIG_PROFILE_", "CONFIG_MEASURE_")):
                    state[name] = math.nan
            for name, val in map_sample_cfg(sample_cfg).items():
                state[name] = val
        if mission_cfg or sample_cfg:
            # new sample-config entries extend the name space with NaN history
            for name in state:
                for col in self.columns:
                    col.setdefault(name, math.nan)
        self._derive(state, cycle)

        self.active_state = dict(state)
        for num, col in zip(reversed(self.numbers), reversed(self.columns)):
            if num > 0 and self._matches(state, col):
                return num
        if cycle > 0:
            num = max(self.numbers) + 1
            self.numbers.append(num)
            self.columns.append(state)
            return num
        # cycle 0: configuration update is not possible; reference the
        # launch column (verbatim rule).
        return 0

@dataclass
class ConfigurationHistory:
    """One local mission identity space for metadata, profiles and trajectory.

    Representative raw dictionaries retain the existing metadata projection;
    effective vectors retain the complete mapped identity evidence.
    """
    cycle_missions: dict[int, int] = field(default_factory=dict)
    states: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    effective_states: dict[int, dict[str, float]] = field(default_factory=dict)


def configuration_history_from_states(states) -> ConfigurationHistory:
    tracker = MissionTracker()
    history = ConfigurationHistory()
    raw = {}
    seen = set()
    for cycle, mission, sample in sorted(states, key=lambda row: row[0]):
        if cycle <= 0:
            continue
        if mission:
            raw.update(mission)
        if not raw and not sample and not history.states:
            continue  # unknown, not an invented mission zero/one
        number = tracker.assign(cycle, mission, sample)
        history.cycle_missions[cycle] = number
        if number not in seen:
            seen.add(number)
            history.states.append((number, dict(raw)))
            history.effective_states[number] = dict(tracker.active_state)
    return history


def build_configuration_history(syslogs_by_cycle, cycles=None) -> ConfigurationHistory:
    """Use the last complete echoed mission/sample block and real cycle context."""
    states = []
    for cycle in sorted(set(syslogs_by_cycle) | set(cycles or [])):
        mission = sample = None
        for path in syslogs_by_cycle.get(cycle, []):
            m, s = parse_system_log_config(path)
            if m:
                mission = m
            if s:
                sample = s
        states.append((cycle, mission, sample))
    return configuration_history_from_states(states)


def config_version_missions(syslogs_by_cycle: "dict[int, list[Path]]") -> dict[int, int]:
    """Compatibility API: IDs refer to shared mapped configuration history.

    Not a counter of raw string changes; recurring configurations reuse IDs.
    """
    return build_configuration_history(syslogs_by_cycle).cycle_missions


__all__ = [
    "IGNORED_CONFIG_NAMES",
    "MissionTracker",
    "map_mission_cfg",
    "map_sample_cfg",
    "parse_system_log_config",
]

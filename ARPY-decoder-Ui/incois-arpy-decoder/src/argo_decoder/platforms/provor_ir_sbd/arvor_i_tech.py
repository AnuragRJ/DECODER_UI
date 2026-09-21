"""ARVOR-I technical (``<wmo>_tech.nc``) product model — Phase 4A.

Builds the per-cycle technical-parameter rows consumed by the NetCDF writer
(:mod:`argo_decoder.nc.technical_arvor`), mirroring the Coriolis emitters for
the ARVOR-I decoder family (decIds 222/223/225/232; the label tables of 222
and 232 are byte-identical, verified against the vendored JSONs).

Coriolis call chain mirrored here (all sources read end-to-end, toolbox
20250516_076a; see ``docs/phase_reports/ARVOR_I_PHASE4A_TECH_MAPPING_2026-08-26.md``
-- the authoritative investigation this module implements):

* ``process_decoded_data.m`` case {222}/{232} -- per-buffer emission order:
  ``store_received_packet_type_info_for_nc`` (1001-1010) -> ``store_tech1``
  (100-136) -> ``store_tech2`` (200-243) -> ``store_misc`` (1012-1015);
  cycle -1 buffers return before any emission.
* ``get_decoded_data.m`` -- duplicate rows cleaned (keep first); NKE
  grounding-day fix on Tech#2 items 23/28 before emission.
* ``finalize_technical_data_ir_sbd.m`` -- missing statistical params
  1001-1010 zero-filled (all on the last row's cycle, table-wide setdiff),
  then ALL rows sorted by TECHNICAL_PARAMETER_NAME (stable).
* ``create_nc_tech_file_3_1.m`` -- rows whose name starts ``TECH_AUX`` go to
  the aux file and rows starting ``META_`` are dropped: neither reaches
  ``_tech.nc``.  Within the file: cycles ascending, table order within a
  cycle (= alphabetical by parameter name).

Mapping (item k == ``fields[k]``; ``tabTechN(k + 1)`` in MATLAB == item k).
Every row PROVEN from the emitter sources unless noted:

===  =========================  =================  ==============  ==========
id   TECHNICAL_PARAMETER_NAME   source item(s)     conversion      gate
===  =========================  =================  ==============  ==========
100  CLOCK_..._YYYYMMDD         T1 7,6,5           date+2000       always
101  CLOCK_..._FloatDay         T1 8               raw             always
102  CLOCK_..._HHMM             T1 9               hhmm            always
103  TIME_ValveActionsAtSurf    T1 10              raw             always
104  NUMBER_ValveActAtSurf      T1 11              raw             always
105  FLAG_Beached_NUMBER        T1 12              raw             always
106  CLOCK_StartDescentProf     T1 13              hhmm            deep
107  CLOCK_InitialStabiliz      T1 14              hhmm            deep
108  CLOCK_EndDescentToPark     T1 15              hhmm            deep
109  NUMBER_ValveActDescent     T1 16              raw             deep
110  NUMBER_PumpActDescent      T1 17              raw             deep
111  CLOCK_EndDescentToPark_DD  T1 20              %02d str        deep
112  NUMBER_DescToParkEntries   T1 21              raw             deep
113  NUMBER_ReposDuringPark     T1 22              raw             deep
114  NUMBER_ValveActionsPark    T1 25              raw             deep
115  NUMBER_PumpActionsPark     T1 26              raw             deep
116  CLOCK_StartDescToProf      T1 27              hhmm            deep
117  CLOCK_EndDescToProfile     T1 28              hhmm            deep
118  NUMBER_ValveActDescProf    T1 29              raw             deep
119  NUMBER_PumpActDescProf     T1 30              raw             deep
120  NUMBER_DescToProfEntry     T1 32              raw             deep
121  NUMBER_ReposAtProfDep      T1 33              raw             deep
122  NUMBER_ValveActProfDrift   T1 34              raw             deep
123  NUMBER_PumpActProfDrift    T1 35              raw             deep
124  CLOCK_StartAscToSurface    T1 38              hhmm            deep
125  CLOCK_TransmissionStart    T1 39              hhmm            deep
126  NUMBER_PumpActionsAscent   T1 40              raw             deep
127  PRES_SurfaceOffset_dbar    T1 47              twos8/10        deep
128  PRES_InternalVacuumSurf    T1 48              x5              deep
129  VOLTAGE_BatteryPumpStart   T1 49              15-i/10         deep
130  FLAG_RTCStatus_LOGICAL     T1 50              inverted        deep
131  NUMBER_CTDError_COUNT      T1 51              raw             deep
132  TIME_IridiumGPSFix_s       T1 62              raw             deep
133  TIME_PumpActAddGPS_s       T1 64              raw             deep
134  FLAG_AntennaStatus_NUM     T1 65              raw             deep
135  CLOCK_EOLStart_YMDHMS      T1 72,71,70,67-69  date6+2000      d, i66==1
136  CLOCK_FloatTimeCorr        T1 73              mmss signed/3600  d, i61==1
200  NUMBER_DescIridiumPkts     T2 3               raw             deep
201  NUMBER_ParkIridiumPkts     T2 4               raw             deep
202  NUMBER_AscIridiumPkts      T2 5               raw             deep
203  NUMBER_NearSurfIridPkts    T2 6               raw             deep
204  NUMBER_InAirIridiumPkts    T2 7               raw             deep
205  NUMBER_DescProfReducUp     T2 8               raw             deep
206  NUMBER_DescProfReducLo     T2 9               raw             deep
207  NUMBER_ParkCTDSampInt      T2 10              raw             deep
208  NUMBER_AscProfReducUp      T2 11              raw             deep
209  NUMBER_AscProfReducLo      T2 12              raw             deep
210  NUMBER_NearSurfSamples     T2 13              raw             deep
211  NUMBER_InAirSamples        T2 14              raw             deep
212  PRES_LastAscPumpedRaw      T2 15 (16,17 gate)  sensor pres     d, tri!=0
213  FLAG_Grounded_NUMBER       T2 21              raw             deep
214  CLOCK_TimeGrounded_Day     T2 23 post-fix     raw             d, i21>0
215  CLOCK_TimeGrounded_HHMM    T2 24              hhmm            d, i21>0
216  FLAG_FirstGroundingPh      T2 25              raw             d, i21>0
217  NUMBER_ValveAct1stGrnd     T2 26              raw             d, i21>0
218  CLOCK_TimeGrounded_Day     T2 28 post-fix     raw             d, i21>1
219  CLOCK_TimeGrounded_HHMM    T2 29              hhmm            d, i21>1
220  FLAG_SecondGroundingPh     T2 30              raw             d, i21>1
221  NUMBER_ValveAct2ndGrnd     T2 31              raw             d, i21>1
222  NUMBER_EmergencyAscents    T2 32              raw             deep
223  CLOCK_1stEmergAsc_HHMM     T2 33              hhmm            d, i32>0
224  PRES_FirstEmergAscent      T2 34              sensor pres     d, i32>0
225  NUMBER_PumpAct1stEmerg     T2 35              raw             d, i32>0
226  CLOCK_1stEmergAsc_Day      T2 36              raw             d, i32>0
227  FLAG_RemoteCtrlMsgOK       T2 37              raw             deep
228  FLAG_RemoteCtrlMsgKO       T2 38              raw             deep
229  NUMBER_RemoteCtrlCmdOK     T2 39              raw             deep
230  NUMBER_RemoteCtrlCmdKO     T2 40              raw             deep
231  TIME_PrevIridiumSession    T2 41              raw             deep
232  NUMBER_IridiumMsgsRxPrv    T2 42              raw             deep
233  NUMBER_IridiumMsgsTxPrv    T2 43              raw             deep
234  NUMBER_PumpActStartAsc     T2 44              raw             deep
235  PRES_InternalVacuumProf    T2 45              x5              deep
236  CLOCK_LastReset_YMDHMS     T2 51,50,49,46-48  date6+2000      deep
237  FLAG_InitCheckErr_LOG      T2 52              raw             deep
238  FLAG_InitCheckErr_NUM      T2 53              raw             deep
239  FLAG_InitMemoryIntegr      T2 54              raw             deep
240  FLAG_StatusBladderState    T2 55              raw             deep
241  FLAG_CTDStatus_NUMBER      T2 56              raw             deep
242  FLAG_CTDErrorCyclePhase    T2 57              raw             deep
===  =========================  =================  ==============  ==========

Aux-destined rows (computed for bookkeeping, never written to ``_tech.nc``):
``1000`` (T1 item 61), ``1001``-``1010`` (received packet-type counts: 1001-1004
deep-gated, 1010 gated on a type-7 packet ever received), ``1012``-``1015``
(buffer deep/delayed/completed flags, ICE-activation flag), ``243`` (T2 item 59,
gated on type-7 ever received AND CONFIG_IC00 != 0), and the +10000 "non-deep"
(surface-cycle) variants of the tech1/tech2 sets.  The non-deep branch exists
for surface cycles (no measurement packets); no such cycle exists in either
evidence dataset, so it is implemented for family completeness only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorTech1Packet,
    ArvorTech2Packet,
    counts_to_pres,
    counts_to_temp,
    twos_complement,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_cycles import StreamPacket
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ArvorScienceResult,
    _dedup_buffer,
)

# ---------------------------------------------------------------------------
# Label table (id -> TECHNICAL_PARAMETER_NAME).
#
# Transcribed mechanically from the vendored Coriolis JSONs
# ``_techParamNames/_tech_param_name_222.json`` and ``..._232.json``
# (toolbox 20250516_076a).  The two files are byte-identical in mapping;
# ``tests/unit/test_arvor_i_tech.py`` asserts the transcription against both
# vendored files so the copy can never drift.
# ---------------------------------------------------------------------------
TECH_PARAM_NAMES_222_232: dict[int, str] = {
    100: "CLOCK_InitialValveActionDescentToPark_YYYYMMDD",
    101: "CLOCK_InitialValveActionDescentToPark_FloatDay",
    102: "CLOCK_InitialValveActionDescentToPark_HHMM",
    103: "TIME_ValveActionsAtSurface_seconds",
    104: "NUMBER_ValveActionsAtSurfaceDuringDescent_COUNT",
    105: "FLAG_Beached_NUMBER",
    106: "CLOCK_StartDescentProfile_HHMM",
    107: "CLOCK_InitialStabilizationDuringDescentToPark_HHMM",
    108: "CLOCK_EndDescentToPark_HHMM",
    109: "NUMBER_ValveActionsDuringDescentToPark_COUNT",
    110: "NUMBER_PumpActionsDuringDescentToPark_COUNT",
    111: "CLOCK_EndDescentToPark_DD",
    112: "NUMBER_DescentToParkEntriesInParkMargin_COUNT",
    113: "NUMBER_RepositionsDuringPark_COUNT",
    114: "NUMBER_ValveActionsDuringPark_COUNT",
    115: "NUMBER_PumpActionsDuringPark_COUNT",
    116: "CLOCK_StartDescentToProfile_HHMM",
    117: "CLOCK_EndDescentToProfile_HHMM",
    118: "NUMBER_ValveActionsDuringDescentToProfile_COUNT",
    119: "NUMBER_PumpActionsDuringDescentToProfile_COUNT",
    120: "NUMBER_DescentToProfileEntriesInProfileMargin_COUNT",
    121: "NUMBER_RepositionsAtProfileDepth_COUNT",
    122: "NUMBER_ValveActionsDuringProfileDrift_COUNT",
    123: "NUMBER_PumpActionsDuringProfileDrift_COUNT",
    124: "CLOCK_StartAscentToSurface_HHMM",
    125: "CLOCK_TransmissionStart_HHMM",
    126: "NUMBER_PumpActionsDuringAscentToSurface_COUNT",
    127: "PRES_SurfaceOffsetCorrectedNotResetNegative_1cBarResolution_dbar",
    128: "PRESSURE_InternalVacuumAtSurface_mbar",
    129: "VOLTAGE_BatteryPumpStartProfile_volts",
    130: "FLAG_RTCStatus_LOGICAL",
    131: "NUMBER_CTDError_COUNT",
    132: "TIME_IridiumGPSFix_seconds",
    133: "TIME_PumpActionsAdditionalAtSurfaceForGPSAcquisition_seconds",
    134: "FLAG_AntennaStatus_NUMBER",
    135: "CLOCK_EOLStart_YYYYMMDDHHMMSS",
    136: "CLOCK_FloatTimeCorrection_MMSS",
    200: "NUMBER_DescentIridiumPackets_COUNT",
    201: "NUMBER_ParkIridiumPackets_COUNT",
    202: "NUMBER_AscentIridiumPackets_COUNT",
    203: "NUMBER_NearSurfaceIridiumPackets_COUNT",
    204: "NUMBER_InAirIridiumPackets_COUNT",
    205: "NUMBER_DescendingProfileReductionUpperPart_COUNT",
    206: "NUMBER_DescendingProfileReductionLowerPart_COUNT",
    207: "NUMBER_ParkCTDSamplesInternal_COUNT",
    208: "NUMBER_AscendingProfileReductionUpperPart_COUNT",
    209: "NUMBER_AscendingProfileReductionLowerPart_COUNT",
    210: "NUMBER_NearSurfaceSamples_COUNT",
    211: "NUMBER_InAirSamples_COUNT",
    212: "PRES_LastAscentPumpedRawSample_dbar",
    213: "FLAG_Grounded_NUMBER",
    214: "CLOCK_TimeGrounded_FloatDay",
    215: "CLOCK_TimeGrounded_HHMM",
    216: "FLAG_FirstGroundingCyclePhase_NUMBER",
    217: "NUMBER_ValveActionsForFirstGroundingDetection_COUNT",
    218: "CLOCK_TimeGrounded_FloatDay",
    219: "CLOCK_TimeGrounded_HHMM",
    220: "FLAG_SecondGroundingCyclePhase_NUMBER",
    221: "NUMBER_ValveActionsForSecondGroundingDetection_COUNT",
    222: "NUMBER_EmergencyAscents_COUNT",
    223: "CLOCK_TimeOfFirstEmergencyAscent_HHMM",
    224: "PRES_FirstEmergencyAscent_dbar",
    225: "NUMBER_PumpActionsOnFirstEmergencyAscent_COUNT",
    226: "CLOCK_TimeOfFirstEmergencyAscent_FloatDay",
    227: "FLAG_RemoteControlMessageOK_COUNT",
    228: "FLAG_RemoteControlMessageKO_COUNT",
    229: "NUMBER_RemoteControlCommandOK_COUNT",
    230: "NUMBER_RemoteControlCommandKO_COUNT",
    231: "TIME_PreviousIridiumSession_seconds",
    232: "NUMBER_IridiumMessagesReceivedPreviousSession_COUNT",
    233: "NUMBER_IridiumMessagesSentPreviousSession_COUNT",
    234: "NUMBER_PumpActionsToStartAscent_COUNT",
    235: "PRESSURE_InternalVacuumProfileStart_mbar",
    236: "CLOCK_LastReset_YYYYMMDDHHMMSS",
    237: "FLAG_InitialCheckError_LOGICAL",
    238: "FLAG_InitialCheckError_NUMBER",
    239: "FLAG_InitialMemoryIntegrityCheck_LOGICAL",
    240: "FLAG_StatusBladderStateAtLaunch_NUMBER",
    241: "FLAG_CTDStatus_NUMBER",
    242: "FLAG_CTDErrorCyclePhase_NUMBER",
    243: "TECH_AUX_FLAG_FloatIceDetected_NUMBER",
    400: "TECH_AUX_FLAG_IceIsaDetectionAlarm_LOGICAL",
    401: "TECH_AUX_FLAG_IceHangingDetectionAlarm_LOGICAL",
    402: "TECH_AUX_FLAG_IceNoSurfacePeriod_LOGICAL",
    403: "TECH_AUX_FLAG_IceForcedAscentAlarm_LOGICAL",
    404: "TECH_AUX_FLAG_IceSatMaskDetectionAlarm_LOGICAL",
    405: "TECH_AUX_FLAG_IceProfileAbortAlarm_LOGICAL",
    406: "PRES_IceAvoidance_dbar",
    407: "FLAG_IceDetected_bit",
    408: "TECH_AUX_FLAG_IceAlgorithmStatus_bit",
    409: "TECH_AUX_PRES_OffsetNotSampledAtSurface_dbar",
    1000: "TECH_AUX_FLAG_GPSValidFix_LOGICAL",
    1001: "TECH_AUX_NUMBER_DescentIridiumPacketsReceived_COUNT",
    1002: "TECH_AUX_NUMBER_ParkIridiumPacketsReceived_COUNT",
    1003: "TECH_AUX_NUMBER_AscentIridiumPacketsReceived_COUNT",
    1004: "TECH_AUX_NUMBER_NearSurfaceIridiumPacketsReceived_COUNT",
    1005: "TECH_AUX_NUMBER_InAirIridiumPacketsReceived_COUNT",
    1006: "TECH_AUX_NUMBER_HydraulicIridiumPacketsReceived_COUNT",
    1007: "TECH_AUX_NUMBER_TechnicalMessage1Received_COUNT",
    1008: "TECH_AUX_NUMBER_TechnicalMessage2Received_COUNT",
    1009: "TECH_AUX_NUMBER_ParameterMessage1Received_COUNT",
    1010: "TECH_AUX_NUMBER_ParameterMessage2Received_COUNT",
    1012: "TECH_AUX_FLAG_IceAlgorithmActivated_LOGICAL",
    1013: "TECH_AUX_FLAG_DeepCycleTransmission_LOGICAL",
    1014: "TECH_AUX_FLAG_TransmissionDelayed_NUMBER",
    1015: "TECH_AUX_FLAG_TransmissionCompleted_LOGICAL",
}

# get_nc_tech_parameters_json.m: for non-APEX/PFV2 decoders every entry is
# duplicated at load time with id + 10000 and a TECH_AUX_SURFACE_ name; those
# duplicates resolve the "+10000" (non-deep) emissions.
_AUX_DUPLICATION_OFFSET = 10000
_SURFACE_PREFIX = "TECH_AUX_SURFACE_"


def tech_param_name(param_id: int) -> str:
    """Resolve a TECH_PARAM_DEC_ID to its TECHNICAL_PARAMETER_NAME.

    Follows ``get_nc_tech_parameters_json.m`` exactly: base ids resolve
    directly; ids >= 10000 resolve to the runtime-duplicated
    ``TECH_AUX_SURFACE_<name>`` entries (an aux-prefixed base name has its
    ``TECH_AUX_`` prefix replaced, like the MATLAB ``regexprep``).
    """

    if param_id in TECH_PARAM_NAMES_222_232:
        return TECH_PARAM_NAMES_222_232[param_id]
    base = param_id - _AUX_DUPLICATION_OFFSET
    if base > 0 and base in TECH_PARAM_NAMES_222_232:
        name = TECH_PARAM_NAMES_222_232[base]
        if name.startswith("TECH_AUX_"):
            return _SURFACE_PREFIX + name[len("TECH_AUX_") :]
        return _SURFACE_PREFIX + name
    raise KeyError(f"unknown technical parameter id {param_id}")


# ---------------------------------------------------------------------------
# Value formatters (format_time_hhmm_dec_argo.m / format_time_mmss_dec_argo.m,
# replicated statement by statement, including their quirks).
# ---------------------------------------------------------------------------


def format_hhmm_dec_argo(minutes: int) -> str:
    """``format_time_hhmm_dec_argo`` of ``item / 60`` (input: whole minutes).

    Negative times wrap by +24; seconds round with a 60 carry; a zero
    seconds field is dropped, so the result is ``HHMM`` when s == 0 and
    ``HHMMSS`` otherwise (MATLAB drops the last two characters).
    """

    a_time = minutes / 60.0
    if a_time < 0:
        a_time = a_time + 24
    a_time = abs(a_time)
    h = int(a_time)  # MATLAB fix(): truncation toward zero
    m = int((a_time - h) * 60)
    s = round(((a_time - h) * 60 - m) * 60)
    if s == 60:
        s = 0
        m = m + 1
        if m == 60:
            m = 0
            h = h + 1
    out = f"{h:02d}{m:02d}{s:02d}"
    if s == 0:
        out = out[:-2]
    return out


def format_mmss_dec_argo(seconds: int) -> str:
    """``format_time_mmss_dec_argo`` of ``item / 3600`` (input: seconds).

    Output ``MM:SS`` with the total minute count ``h*60+m``; a negative
    input keeps its sign as ``"- MM:SS"`` -- sign, space, digits, exactly
    the MATLAB ``sprintf('%c %02d:%02d', ...)``.
    """

    a_time = seconds / 3600.0
    sign = "" if a_time >= 0 else "-"
    a_time = abs(a_time)
    h = int(a_time)
    m = int((a_time - h) * 60)
    s = round(((a_time - h) * 60 - m) * 60)
    if s == 60:
        s = 0
        m = m + 1
        if m == 60:
            m = 0
            h = h + 1
    total_minutes = h * 60 + m
    if not sign:
        return f"{total_minutes:02d}:{s:02d}"
    return f"{sign} {total_minutes:02d}:{s:02d}"


def num2str_dec_argo(value: float | int) -> str:
    """MATLAB ``num2str`` for the value ranges of this product.

    Integer-valued numbers render as integers, everything else through
    ``%g``; identical to the GDAC-validated convention of the APEX writer
    (``nc/technical.py::_format_number``), which was proven against Coriolis
    technical files.  Every value this module emits has at most one decimal
    digit, where the two renderings coincide exactly.
    """

    v = float(value)
    if v.is_integer():
        return str(int(v))
    return f"{v:g}"


# ---------------------------------------------------------------------------
# Product model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TechParamRow:
    """One (cycle, parameter) row of the technical table."""

    cycle_number: int  # buffer cycle number (MATLAB index columns 2 and 6)
    param_id: int  # TECH_PARAM_DEC_ID (MATLAB index column 5)
    name: str  # resolved TECHNICAL_PARAMETER_NAME
    value: str  # formatted value (num2str / sprintf semantics)
    source: str  # provenance, e.g. "tech1 item 8" / "tech2 item 21"


@dataclass
class ArvorTechDataset:
    """Full technical row table for one float, in final writer order.

    ``rows`` keeps EVERY emitted row, including the aux-destined ones
    (nothing is silently discarded); ``tech_rows`` is the ``_tech.nc``
    subset in final order (cycles ascending, alphabetical by name within a
    cycle -- the ``finalize_technical_data_ir_sbd`` sort regrouped by the
    writer's cycle loop); ``aux_rows`` the TECH_AUX/META_ subset.
    """

    dec_id: int
    wmo: int | None = None
    rows: list[TechParamRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Float-clock timestamp per cycle (Tech#1 items 41-46, LAST packet of
    #: the buffer -- the same selection the row emission uses). Internal
    #: decode retention: the GDAC-shape publication layer splits it into
    #: CLOCK_FloatTime_hours/_minutes/_seconds rows; it is not a row of the
    #: canonical Coriolis table.
    float_times: dict[int, datetime] = field(default_factory=dict)

    @property
    def tech_rows(self) -> list[TechParamRow]:
        return [r for r in self.rows if not _is_aux_row(r)]

    @property
    def aux_rows(self) -> list[TechParamRow]:
        return [r for r in self.rows if _is_aux_row(r)]


def _is_aux_row(row: TechParamRow) -> bool:
    # create_nc_tech_file_3_1.m: names starting TECH_AUX move to the aux
    # file, names starting META_ are dropped; neither is written here.
    return row.name.startswith("TECH_AUX") or row.name.startswith("META_")


# ---------------------------------------------------------------------------
# Emitters (store_*_for_nc_*.m, one function per MATLAB source)
# ---------------------------------------------------------------------------


def _row(
    rows: list[TechParamRow],
    cycle: int,
    param_id: int,
    value: float | int | str,
    source: str,
) -> None:
    text = value if isinstance(value, str) else num2str_dec_argo(value)
    rows.append(
        TechParamRow(
            cycle_number=cycle,
            param_id=param_id,
            name=tech_param_name(param_id),
            value=text,
            source=source,
        )
    )


def store_packet_type_info_rows(
    rows: list[TechParamRow],
    cycle: int,
    packets: list[StreamPacket],
    deep: bool,
    type_7_seen: bool,
) -> None:
    """``store_received_packet_type_info_for_nc`` case {212,222,214,217,223..227,231,232}."""

    def count(*types: int) -> int:
        return sum(1 for sp in packets if sp.pack_type in types)

    if deep:
        _row(rows, cycle, 1001, count(1), "packet-count type 1")
        _row(rows, cycle, 1002, count(2), "packet-count type 2")
        _row(rows, cycle, 1003, count(3), "packet-count type 3")
        _row(rows, cycle, 1004, count(13), "packet-count type 13")
    _row(rows, cycle, 1005, count(14), "packet-count type 14")
    _row(rows, cycle, 1006, count(6), "packet-count type 6")
    _row(rows, cycle, 1007, count(0), "packet-count type 0")
    _row(rows, cycle, 1008, count(4), "packet-count type 4")
    _row(rows, cycle, 1009, count(5), "packet-count type 5")
    if type_7_seen:
        _row(rows, cycle, 1010, count(7), "packet-count type 7")


def store_tech1_rows(
    rows: list[TechParamRow],
    cycle: int,
    t1: ArvorTech1Packet,
    deep: bool,
) -> None:
    """``store_tech1_data_for_nc_222_to_227_231_232`` (LAST Tech#1 of the buffer)."""

    f = t1.fields  # f[k] == MATLAB item k

    _row(rows, cycle, 100, f"{f[7] + 2000:04d}{f[6]:02d}{f[5]:02d}", "tech1 items 7/6/5")
    _row(rows, cycle, 101, f[8], "tech1 item 8")
    _row(rows, cycle, 102, format_hhmm_dec_argo(f[9]), "tech1 item 9")
    _row(rows, cycle, 103, f[10], "tech1 item 10")
    _row(rows, cycle, 104, f[11], "tech1 item 11")
    _row(rows, cycle, 105, f[12], "tech1 item 12")

    if not deep:
        # surface cycle: the reduced set under TECH_AUX_SURFACE_ names
        # (id + 10000); never reaches _tech.nc.
        offset = _AUX_DUPLICATION_OFFSET
        _row(rows, cycle, 127 + offset, f[47], "tech1 item 47 (surface)")
        _row(rows, cycle, 128 + offset, f[48] * 5, "tech1 item 48 x5 (surface)")
        _row(rows, cycle, 129 + offset, 15 - f[49] / 10, "tech1 item 49 (surface)")
        _row(rows, cycle, 130 + offset, 0 if f[50] else 1, "tech1 item 50 inverted (surface)")
        _row(rows, cycle, 131 + offset, f[51], "tech1 item 51 (surface)")
        _row(rows, cycle, 1000 + offset, f[61], "tech1 item 61 (surface)")
        _row(rows, cycle, 132 + offset, f[62], "tech1 item 62 (surface)")
        _row(rows, cycle, 133 + offset, f[64], "tech1 item 64 (surface)")
        _row(rows, cycle, 134 + offset, f[65], "tech1 item 65 (surface)")
        if f[66]:  # non-deep gate is "nonzero" (diverges from the deep "== 1")
            _row(
                rows,
                cycle,
                135 + offset,
                (f"{f[72] + 2000:04d}{f[71]:02d}{f[70]:02d}{f[67]:02d}{f[68]:02d}{f[69]:02d}"),
                "tech1 items 72..67 (surface)",
            )
        if f[61] == 1:
            _row(
                rows,
                cycle,
                136 + offset,
                format_mmss_dec_argo(twos_complement(f[73], 16)),
                "tech1 item 73 signed (surface)",
            )
        return

    _row(rows, cycle, 106, format_hhmm_dec_argo(f[13]), "tech1 item 13")
    _row(rows, cycle, 107, format_hhmm_dec_argo(f[14]), "tech1 item 14")
    _row(rows, cycle, 108, format_hhmm_dec_argo(f[15]), "tech1 item 15")
    _row(rows, cycle, 109, f[16], "tech1 item 16")
    _row(rows, cycle, 110, f[17], "tech1 item 17")
    _row(rows, cycle, 111, f"{f[20]:02d}", "tech1 item 20")
    _row(rows, cycle, 112, f[21], "tech1 item 21")
    _row(rows, cycle, 113, f[22], "tech1 item 22")
    _row(rows, cycle, 114, f[25], "tech1 item 25")
    _row(rows, cycle, 115, f[26], "tech1 item 26")
    _row(rows, cycle, 116, format_hhmm_dec_argo(f[27]), "tech1 item 27")
    _row(rows, cycle, 117, format_hhmm_dec_argo(f[28]), "tech1 item 28")
    _row(rows, cycle, 118, f[29], "tech1 item 29")
    _row(rows, cycle, 119, f[30], "tech1 item 30")
    _row(rows, cycle, 120, f[32], "tech1 item 32")
    _row(rows, cycle, 121, f[33], "tech1 item 33")
    _row(rows, cycle, 122, f[34], "tech1 item 34")
    _row(rows, cycle, 123, f[35], "tech1 item 35")
    _row(rows, cycle, 124, format_hhmm_dec_argo(f[38]), "tech1 item 38")
    _row(rows, cycle, 125, format_hhmm_dec_argo(f[39]), "tech1 item 39")
    _row(rows, cycle, 126, f[40], "tech1 item 40")
    _row(rows, cycle, 127, twos_complement(f[47], 8) / 10, "tech1 item 47 twos8/10")
    _row(rows, cycle, 128, f[48] * 5, "tech1 item 48 x5")
    _row(rows, cycle, 129, 15 - f[49] / 10, "tech1 item 49")
    _row(rows, cycle, 130, 0 if f[50] else 1, "tech1 item 50 inverted")
    _row(rows, cycle, 131, f[51], "tech1 item 51")
    # 1000 (GPS valid fix) sits between 131 and 132 in the MATLAB emission
    # order; it is TECH_AUX-prefixed so it never reaches _tech.nc.
    _row(rows, cycle, 1000, f[61], "tech1 item 61")
    _row(rows, cycle, 132, f[62], "tech1 item 62")
    _row(rows, cycle, 133, f[64], "tech1 item 64")
    _row(rows, cycle, 134, f[65], "tech1 item 65")
    if f[66] == 1:  # deep gate is "== 1"
        _row(
            rows,
            cycle,
            135,
            (f"{f[72] + 2000:04d}{f[71]:02d}{f[70]:02d}{f[67]:02d}{f[68]:02d}{f[69]:02d}"),
            "tech1 items 72..67",
        )
    if f[61] == 1:  # GPS valid fix
        _row(
            rows,
            cycle,
            136,
            format_mmss_dec_argo(twos_complement(f[73], 16)),
            "tech1 item 73 signed",
        )


def store_tech2_rows(
    rows: list[TechParamRow],
    cycle: int,
    t2_fields: list[int],
    deep: bool,
    *,
    ice_detection_enabled: bool,
) -> None:
    """``store_tech2_data_for_nc_212_214_217_222_223_225_232``.

    ``t2_fields`` must already carry the NKE grounding-day fix (see
    :func:`apply_grounding_day_fix`).
    """

    f = t2_fields

    if deep:
        for param_id, item in zip(range(200, 212), range(3, 15), strict=True):
            _row(rows, cycle, param_id, f[item], f"tech2 item {item}")
        pres = counts_to_pres(f[15])
        temp = counts_to_temp(f[16])
        psal = f[17] / 1000
        if pres != 0 or temp != 0 or psal != 0:
            _row(rows, cycle, 212, pres, "tech2 item 15 sensor pres")
        _row(rows, cycle, 213, f[21], "tech2 item 21")
        if f[21] > 0:
            _row(rows, cycle, 214, f[23], "tech2 item 23")
            _row(rows, cycle, 215, format_hhmm_dec_argo(f[24]), "tech2 item 24")
            _row(rows, cycle, 216, f[25], "tech2 item 25")
            _row(rows, cycle, 217, f[26], "tech2 item 26")
            if f[21] > 1:
                _row(rows, cycle, 218, f[28], "tech2 item 28")
                _row(rows, cycle, 219, format_hhmm_dec_argo(f[29]), "tech2 item 29")
                _row(rows, cycle, 220, f[30], "tech2 item 30")
                _row(rows, cycle, 221, f[31], "tech2 item 31")
        _row(rows, cycle, 222, f[32], "tech2 item 32")
        if f[32] > 0:
            _row(rows, cycle, 223, format_hhmm_dec_argo(f[33]), "tech2 item 33")
            _row(rows, cycle, 224, counts_to_pres(f[34]), "tech2 item 34 sensor pres")
            _row(rows, cycle, 225, f[35], "tech2 item 35")
            _row(rows, cycle, 226, f[36], "tech2 item 36")
        for param_id, item in zip(range(227, 235), range(37, 45), strict=True):
            _row(rows, cycle, param_id, f[item], f"tech2 item {item}")
        _row(rows, cycle, 235, f[45] * 5, "tech2 item 45 x5")
        _row(
            rows,
            cycle,
            236,
            (f"{f[51] + 2000:04d}{f[50]:02d}{f[49]:02d}{f[46]:02d}{f[47]:02d}{f[48]:02d}"),
            "tech2 items 46..51",
        )
        for param_id, item in zip(range(237, 243), range(52, 58), strict=True):
            _row(rows, cycle, param_id, f[item], f"tech2 item {item}")
        # 243 only when a type-7 packet was received and CONFIG_IC00 != 0;
        # TECH_AUX-prefixed so it never reaches _tech.nc either way.
        if ice_detection_enabled:
            _row(rows, cycle, 243, f[59], "tech2 item 59")
        return

    # surface cycle: 204/211 base rows + the +10000 set under
    # TECH_AUX_SURFACE_ names; never reaches _tech.nc.
    offset = _AUX_DUPLICATION_OFFSET
    _row(rows, cycle, 204, f[7], "tech2 item 7 (surface)")
    _row(rows, cycle, 211, f[14], "tech2 item 14 (surface)")
    for param_id, item in zip(range(227 + offset, 234 + offset), range(37, 44), strict=True):
        _row(rows, cycle, param_id, f[item], f"tech2 item {item} (surface)")
    _row(
        rows,
        cycle,
        236 + offset,
        (f"{f[51] + 2000:04d}{f[50]:02d}{f[49]:02d}{f[46]:02d}{f[47]:02d}{f[48]:02d}"),
        "tech2 items 46..51 (surface)",
    )
    for param_id, item in zip(range(237 + offset, 243 + offset), range(52, 58), strict=True):
        _row(rows, cycle, param_id, f[item], f"tech2 item {item} (surface)")


def store_misc_rows(
    rows: list[TechParamRow],
    cycle: int,
    *,
    deep: bool,
    delayed: int,
    completed: bool,
    dec_id: int,
    ice_activated: bool,
) -> None:
    """``store_misc_tech_data_for_nc_212_214_216_to_218_222_to_232``.

    1012 is not emitted for decoderId 216 (Arvor Deep IFREMER).  All rows
    are TECH_AUX-prefixed for this family: aux file only.
    """

    if dec_id != 216:
        _row(rows, cycle, 1012, 1 if ice_activated else 0, "ice activation flag")
    _row(rows, cycle, 1013, int(deep), "buffer deep flag")
    _row(rows, cycle, 1014, delayed, "buffer delayed flag")
    _row(rows, cycle, 1015, int(completed), "buffer completed flag")


# ---------------------------------------------------------------------------
# get_decoded_data.m pre-emission fix
# ---------------------------------------------------------------------------


def apply_grounding_day_fix(t2_fields: list[int], t1_first_item8: int | None) -> list[int]:
    """NKE grounding-day correction (``get_decoded_data.m`` L166-184).

    A grounding that occurred during cycle phase 2 is transmitted as an
    absolute float day; the decoder converts it to a day relative to the
    cycle start (item 8 of the FIRST Tech#1 row of the buffer).
    """

    f = list(t2_fields)
    if t1_first_item8 is None:
        return f
    if f[21] > 0 and f[25] == 2:
        f[23] = f[23] - t1_first_item8
    if f[21] > 1 and f[31] == 2:
        f[28] = f[28] - t1_first_item8
    return f


# ---------------------------------------------------------------------------
# finalize_technical_data_ir_sbd.m
# ---------------------------------------------------------------------------


def finalize_technical_data(rows: list[TechParamRow]) -> list[TechParamRow]:
    """Statistical zero-fill + name sort (``finalize_technical_data_ir_sbd``).

    Missing statistical parameters (1001-1010 for this family) are appended
    with value 0 on the LAST row's cycle, table-wide setdiff, exactly as
    coded; every one of them is TECH_AUX-prefixed, so none reaches
    ``_tech.nc``.  The table is then stable-sorted by parameter name, which
    is the order the writer preserves within each cycle.
    """

    if not rows:
        return rows
    emitted = {r.param_id for r in rows}
    last_cycle = rows[-1].cycle_number
    for param_id in range(1001, 1011):
        if param_id not in emitted:
            rows.append(
                TechParamRow(
                    cycle_number=last_cycle,
                    param_id=param_id,
                    name=tech_param_name(param_id),
                    value="0",
                    source="statistical zero-fill",
                )
            )
    return sorted(rows, key=lambda r: r.name)


# ---------------------------------------------------------------------------
# Top-level builder
# ---------------------------------------------------------------------------


def resolve_dec_id(result: ArvorScienceResult) -> int | None:
    """Derive the representative decoder id from any Tech#1 firmware checksum.

    Returns 232 for the ENGINE_232 layout and 222 for the 222/223/225
    family (their label tables are identical; the id is provenance only).
    """

    for cyc in result.cycles:
        t1 = cyc.tech1
        if t1 is None and cyc.buffer is not None:
            t1s = [
                sp.packet for sp in cyc.buffer.packets if isinstance(sp.packet, ArvorTech1Packet)
            ]
            t1 = t1s[-1] if t1s else None
        if t1 is not None and t1.firmware_checksum is not None:
            from argo_decoder.platforms.provor_ir_sbd.arvor_i import resolve_engine

            engine, _ids = resolve_engine(t1.firmware_checksum)
            return 232 if engine == "232" else 222
    return None


def build_arvor_tech_dataset(
    result: ArvorScienceResult,
    *,
    wmo: int | None = None,
    dec_id: int | None = None,
) -> ArvorTechDataset:
    """Build the technical row table from a Phase-3 ``ArvorScienceResult``.

    Mirrors the MATLAB chain per buffer (cycles processed in buffer order;
    the final row order is fixed by :func:`finalize_technical_data` plus the
    writer's cycle-ascending regrouping):
    duplicate rows cleaned (keep first) -> grounding-day fix -> packet-type
    counts -> tech1 (LAST of buffer) -> tech2 (LAST of buffer) -> misc ->
    finalize (zero-fill + name sort) -> cycle-ascending stable regroup.
    """

    resolved_dec_id = dec_id if dec_id is not None else resolve_dec_id(result)
    if resolved_dec_id is None:
        raise ValueError("no Tech#1 packet found: cannot resolve decoder id")

    dataset = ArvorTechDataset(dec_id=resolved_dec_id, wmo=wmo)

    # g_decArgo_7TypePacketReceivedCyNum: set by the first type-7 packet of
    # any ranked buffer (get_decoded_data.m); None when never seen.
    type_7_cycle: int | None = None
    for cyc in result.cycles:
        if cyc.buffer is None:
            continue
        for sp in cyc.buffer.packets:
            if sp.pack_type == 7 and type_7_cycle is None:
                type_7_cycle = cyc.cycle_number
                break
        if type_7_cycle is not None:
            break

    ic00 = result.float_config.get("IC00") if result.float_config is not None else None
    ice_detection_enabled = type_7_cycle is not None and ic00 is not None and ic00 != 0

    rows: list[TechParamRow] = []
    for cyc in result.cycles:
        cycle = cyc.cycle_number
        if cycle == -1:
            # process_decoded_data: cycle -1 buffers carry parameters only;
            # the store block is never reached.
            dataset.notes.append("cycle -1: parameter-only buffer, no tech rows")
            continue
        if cyc.buffer is None:
            dataset.notes.append(f"cycle {cycle}: no buffer, no tech rows")
            continue

        # get_decoded_data: clean duplicates first, keep the first row.
        packets, dropped = _dedup_buffer(cyc.buffer.packets)
        for sp, reason in dropped:
            dataset.notes.append(
                f"cycle {cycle}: excluded duplicate row from tech emission "
                f"({sp.pack_type}-packet, {reason})"
            )

        t1s = [sp.packet for sp in packets if isinstance(sp.packet, ArvorTech1Packet)]
        t2s = [sp.packet for sp in packets if isinstance(sp.packet, ArvorTech2Packet)]
        t1 = t1s[-1] if t1s else None  # MATLAB: idF1(end), warn + last
        t2 = t2s[-1] if t2s else None
        if t1 is not None and t1.float_time is not None:
            dataset.float_times[cycle] = t1.float_time
        if len(t1s) > 1:
            dataset.notes.append(f"cycle {cycle}: {len(t1s)} Tech#1 in buffer, using the last")
        if len(t2s) > 1:
            dataset.notes.append(f"cycle {cycle}: {len(t2s)} Tech#2 in buffer, using the last")

        deep = bool(cyc.deep)

        # store_received_packet_type_info_for_nc
        store_packet_type_info_rows(rows, cycle, packets, deep, type_7_cycle is not None)

        # store_tech1_data_for_nc
        if t1 is not None:
            store_tech1_rows(rows, cycle, t1, deep)

        # store_tech2_data_for_nc (grounding fix applied on a field copy)
        if t2 is not None:
            t1_first_item8 = t1s[0].fields[8] if t1s else None
            t2_fields = apply_grounding_day_fix(t2.fields, t1_first_item8)
            store_tech2_rows(
                rows,
                cycle,
                t2_fields,
                deep,
                ice_detection_enabled=ice_detection_enabled,
            )

        # store_misc_tech_data_for_nc
        ice_activated = type_7_cycle is not None and cycle >= type_7_cycle
        store_misc_rows(
            rows,
            cycle,
            deep=deep,
            delayed=cyc.delayed,
            completed=cyc.completed,
            dec_id=resolved_dec_id,
            ice_activated=ice_activated,
        )

    # finalize_technical_data_ir_sbd: zero-fill + name sort, then the
    # writer's cycle-ascending grouping (stable, so the name order within a
    # cycle is preserved).
    rows = finalize_technical_data(rows)
    rows = sorted(rows, key=lambda r: r.cycle_number)
    dataset.rows = rows

    dataset.notes.append(
        f"{len(dataset.tech_rows)} _tech.nc rows, "
        f"{len(dataset.aux_rows)} aux-destined rows (TECH_AUX/META_; "
        "not written to _tech.nc)"
    )
    if type_7_cycle is None:
        dataset.notes.append(
            "no type-7 (Param#2) packet ever received: ICE paths inert "
            "(params 1012 flag stays 0, 1010/243 not emitted)"
        )
    return dataset


__all__ = [
    "TECH_PARAM_NAMES_222_232",
    "ArvorTechDataset",
    "TechParamRow",
    "apply_grounding_day_fix",
    "build_arvor_tech_dataset",
    "finalize_technical_data",
    "format_hhmm_dec_argo",
    "format_mmss_dec_argo",
    "num2str_dec_argo",
    "resolve_dec_id",
    "store_misc_rows",
    "store_packet_type_info_rows",
    "store_tech1_rows",
    "store_tech2_rows",
    "tech_param_name",
]

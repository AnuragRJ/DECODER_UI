"""Decoding of PROVOR CTS4 parameter packets 255 and 254 (Phase 2A).

Implementation contract: ``provor_bio_irsbd/PROVOR_CTS4_PHASE1_DESIGN_NOTE.md``
§1/§6 as extended by the Phase-2A scope (decode only; no calibration, no
emission, no CSV writes).

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7.2.4.4
(packet 255, mission parameters) and §7.2.4.5 (packet 254, technical
parameters). Both share the 10-byte header already split by
:mod:`packets` (date bytes1-6 ``DD MM YY HH MM SS``, cycle bytes7-8 u16be,
profile byte9); parameter words start at byte 10.

Packet 255 layout (all integers big-endian, ``UC`` = 1 byte, ``UI`` = 2 bytes)::

    byte 10:      PV0 number of different cycle durations (1-5)
    bytes 11-12:  PV1 Iridium end-of-life period (minutes)
    byte 13:      PV2 Iridium 2nd-session waiting time (minutes)
    bytes 14-38:  5 x (period hours UI + end DD/MM/YY 3xUC)  (PV3..PV22)
    byte 39:      PM0 number of requested profiles
    bytes 40-41:  PM1 delay before mission (minutes; unit per GDAC
                  ``CONFIG_DelayBeforeMissionStart_minutes``)
    byte 42:      PM2 reference day
    bytes 43-112: 10 x (surfacing day UC + surfacing hour UC + parking
                  depth UI + profile depth UI + transmission UC)  (PM3..PM52)
    bytes 113-139: spare, zeros (27 bytes)

Parking/profile depths are labeled **Bar** (u16) by the manual, but the wire
carries dbar numerals: every corpus slot reads 1000/2000 (1000 Bar would be
10000 dbar — absurd for a 2000 m float), matching the GDAC reference
(``CONFIG_ParkPressure_dbar = 1000`` etc.). The fields are therefore named
``*_dbar``; the raw u16 value is carried unchanged (×1 reading).

Packet 254 layout: 28 parameter words ``PT0..PT27`` (u16be) at bytes
``10+2*i``, spare zeros at bytes 66-139 (74 bytes). Word semantics
(:data:`PT_NAMES` / :data:`PT_UNITS`) follow NKE §7.2.4.5 verbatim.

Known authority conflict (carried, not resolved here): NKE PT12 reads
"Repositioning threshold (in dBars)" while Coriolis decoder-301 label 212
(``CONFIG_NumberOfOutOfTolerancePresBeforeReposition_COUNT``) describes a
*count* of out-of-tolerance measurements. The raw word decodes identically
either way; see :mod:`labels_301` for the mapping note.

PT26/PT27 ("Coef 1"/"Coef 2") are the internal-pressure calibration
coefficients (Coriolis 226/227 descriptions: "used to compute float internal
pressure in mBars from sensor counts"). GDAC reference floats show non-integer
coef1 (1.524) and negative coef2 (-442), so the raw u16 words need a scaling /
signed reinterpretation that telemetry values adjudicate; the words are carried
raw here (see :func:`internal_pressure_coefs` once confirmed).
"""

from __future__ import annotations

from dataclasses import dataclass

from argo_decoder.platforms.provor_cts4_ir_sbd.packets import (
    PacketDate,
    PacketType,
    ParamPacket,
)

#: Full 140-byte rows (the framer guarantees this; checked loudly anyway).
PACKET_LEN = 140
#: Offset where 255/254 parameter words start (after the 10-byte header).
PARAMS_OFFSET = 10

# --- packet 255 offsets -------------------------------------------------------
#: Byte offsets of the scalar PV/PM words (NKE §7.2.4.4).
PV0_OFFSET = 10
PV1_OFFSET = 11
PV2_OFFSET = 13
#: Start of the 5 cycle-duration blocks; each block is
#: ``(period_hours UI, end DD UC, end MM UC, end YY UC)``.
PV_DURATIONS_OFFSET = 14
PV_DURATION_STRIDE = 5
N_PV_DURATIONS = 5
PM0_OFFSET = 39
PM1_OFFSET = 40
PM2_OFFSET = 42
#: Start of the 10 mission-profile blocks; each block is
#: ``(surfacing day, surfacing hour, parking depth, profile depth,
#: transmission)`` = ``(UC, UC, UI, UI, UC)``.
PM_PROFILES_OFFSET = 43
PM_PROFILE_STRIDE = 7
N_PM_PROFILES = 10
#: Spare tail of packet 255 (27 zero bytes).
MISSION_SPARE_OFFSET = 113
MISSION_SPARE_LEN = 27

# --- packet 254 offsets -------------------------------------------------------
#: 28 technical-parameter words ``PT0..PT27`` (u16be) from byte 10.
N_PT_WORDS = 28
PT_STRIDE = 2
#: Spare tail of packet 254 (74 zero bytes).
TECH_SPARE_OFFSET = 66
TECH_SPARE_LEN = 74

#: Short wire-order names for PT0..PT27 (NKE §7.2.4.5 wording, condensed).
PT_NAMES: tuple[str, ...] = (
    "max_ev_activation_surface_csec",  # PT0
    "valve_activations_target_count",  # PT1
    "pres_check_period_buoyancy_reduction_s",  # PT2 (unit per GDAC config name)
    "pres_check_period_ascent_min",  # PT3
    "max_oil_volume_ev_descent_reposition_cm3",  # PT4 (unit per GDAC config name)
    "max_pump_duration_reposition_csec",  # PT5
    "pump_duration_ascent_csec",  # PT6
    "pump_duration_surfacing_csec",  # PT7
    "pres_delta_positioning_dbar",  # PT8
    "max_pres_before_emergency_dbar",  # PT9
    "buoyancy_reduction_threshold1_dbar",  # PT10
    "buoyancy_reduction_threshold2_dbar",  # PT11
    "repositioning_threshold_dbar",  # PT12 (NKE wording; conflicts with 301/212)
    "grounding_mode",  # PT13 (0 = pressure switch, 1 = stay grounded)
    "max_oil_volume_grounding_detection_cm3",  # PT14
    "grounding_pressure_dbar",  # PT15
    "grounding_switch_pressure_dbar",  # PT16
    "pres_delta_drift_dbar",  # PT17
    "avg_descent_speed_mm_s",  # PT18
    "pres_increment_dbar",  # PT19 (transmitted; no 301 label)
    "iridium_modem_timeout_min",  # PT20 (transmitted; no 301 label)
    "min_ascent_speed_mm_s",  # PT21
    "avg_ascent_speed_mm_s",  # PT22
    "wait_surface_after_emergency_min",  # PT23 (transmitted; no 301 label)
    "oil_volume_after_buoyancy_reduction_cm3",  # PT24 (transmitted; no 301 label)
    "iridium_retries_count",  # PT25 (transmitted; no 301 label)
    "internal_pres_calib_coef1",  # PT26 (raw u16; scaling TBD, see module doc)
    "internal_pres_calib_coef2",  # PT27 (raw u16; signedness TBD, see module doc)
)

#: Wire units for PT0..PT27 (``None`` where the NKE wording carries no unit).
PT_UNITS: tuple[str | None, ...] = (
    "csec",
    "count",
    "s",
    "min",
    "cm3",
    "csec",
    "csec",
    "csec",
    "dbar",
    "dbar",
    "dbar",
    "dbar",
    "dbar",  # per NKE; 301/212 says count (conflict, see module docstring)
    "logical",
    "cm3",
    "dbar",
    "dbar",
    "dbar",
    "mm/s",
    "dbar",
    "min",
    "mm/s",
    "mm/s",
    "min",
    "cm3",
    "count",
    "raw",
    "raw",
)


@dataclass(frozen=True)
class CycleDuration:
    """One PV cycle-duration block: period + end date (``DD MM YY``)."""

    period_hours: int
    end_dd: int
    end_mm: int
    end_yy: int


@dataclass(frozen=True)
class MissionProfile:
    """One PM mission-profile block (7 bytes, NKE §7.2.4.4).

    Depths are the raw u16 wire values, read as dbar (the manual labels them
    Bar, but corpus values 1000/2000 plus the GDAC dbar configuration settle
    the unit; see the module docstring). Values are carried unchanged.
    """

    surfacing_day: int
    surfacing_hour: int
    parking_dbar: int
    profile_dbar: int
    transmission: int


@dataclass(frozen=True)
class MissionParams:
    """Decoded packet 255 (NKE §7.2.4.4).

    All five duration blocks and all ten profile blocks are carried verbatim,
    regardless of the ``n_durations`` / ``n_profiles`` counts (those counts are
    mission metadata, not a reason to drop wire data).
    """

    date: PacketDate
    cycle: int
    profile: int
    n_durations: int
    eol_period_min: int
    second_session_wait_min: int
    durations: tuple[CycleDuration, ...]
    n_profiles: int
    delay_before_mission_min: int
    reference_day: int
    profiles: tuple[MissionProfile, ...]
    spare: bytes

    @property
    def spare_ok(self) -> bool:
        """True when the 27-byte spare tail is all zeros (NKE: filled)."""
        return self.spare == bytes(MISSION_SPARE_LEN)


@dataclass(frozen=True)
class TechParams:
    """Decoded packet 254: 28 raw words ``PT0..PT27`` (NKE §7.2.4.5).

    Words are carried as raw u16 values; see :data:`PT_NAMES` /
    :data:`PT_UNITS` for semantics. Use :meth:`named` for a name→value view.
    """

    date: PacketDate
    cycle: int
    profile: int
    pt: tuple[int, ...]
    spare: bytes

    @property
    def spare_ok(self) -> bool:
        """True when the 74-byte spare tail is all zeros (NKE: filled)."""
        return self.spare == bytes(TECH_SPARE_LEN)

    def named(self) -> dict[str, int]:
        """Wire values keyed by :data:`PT_NAMES` (wire order preserved)."""
        return dict(zip(PT_NAMES, self.pt, strict=True))


def _u16be(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def decode_255(packet: ParamPacket) -> MissionParams:
    """Decode a 255 mission-parameter packet (NKE §7.2.4.4).

    Raises:
        ValueError: if the packet is not a 255 packet or not 140 bytes.
    """
    if packet.kind is not PacketType.MISSION_PARAMS:
        raise ValueError(f"not a 255 packet (kind={packet.kind})")
    raw = packet.raw
    if len(raw) != PACKET_LEN:
        raise ValueError(f"255 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    durations: list[CycleDuration] = []
    for block in range(N_PV_DURATIONS):
        base = PV_DURATIONS_OFFSET + block * PV_DURATION_STRIDE
        durations.append(
            CycleDuration(
                period_hours=_u16be(raw, base),
                end_dd=raw[base + 2],
                end_mm=raw[base + 3],
                end_yy=raw[base + 4],
            )
        )
    profiles: list[MissionProfile] = []
    for block in range(N_PM_PROFILES):
        base = PM_PROFILES_OFFSET + block * PM_PROFILE_STRIDE
        profiles.append(
            MissionProfile(
                surfacing_day=raw[base],
                surfacing_hour=raw[base + 1],
                parking_dbar=_u16be(raw, base + 2),
                profile_dbar=_u16be(raw, base + 4),
                transmission=raw[base + 6],
            )
        )
    return MissionParams(
        date=packet.date,
        cycle=packet.cycle,
        profile=packet.profile,
        n_durations=raw[PV0_OFFSET],
        eol_period_min=_u16be(raw, PV1_OFFSET),
        second_session_wait_min=raw[PV2_OFFSET],
        durations=tuple(durations),
        n_profiles=raw[PM0_OFFSET],
        delay_before_mission_min=_u16be(raw, PM1_OFFSET),
        reference_day=raw[PM2_OFFSET],
        profiles=tuple(profiles),
        spare=bytes(raw[MISSION_SPARE_OFFSET:]),
    )


def decode_254(packet: ParamPacket) -> TechParams:
    """Decode a 254 technical-parameter packet (NKE §7.2.4.5).

    Raises:
        ValueError: if the packet is not a 254 packet or not 140 bytes.
    """
    if packet.kind is not PacketType.TECH_PARAMS:
        raise ValueError(f"not a 254 packet (kind={packet.kind})")
    raw = packet.raw
    if len(raw) != PACKET_LEN:
        raise ValueError(f"254 packet must be {PACKET_LEN} bytes, got {len(raw)}")
    words = tuple(
        _u16be(raw, PARAMS_OFFSET + index * PT_STRIDE) for index in range(N_PT_WORDS)
    )
    return TechParams(
        date=packet.date,
        cycle=packet.cycle,
        profile=packet.profile,
        pt=words,
        spare=bytes(raw[TECH_SPARE_OFFSET:]),
    )


__all__ = [
    "MISSION_SPARE_LEN",
    "MISSION_SPARE_OFFSET",
    "N_PM_PROFILES",
    "N_PT_WORDS",
    "N_PV_DURATIONS",
    "PACKET_LEN",
    "PARAMS_OFFSET",
    "PM_PROFILES_OFFSET",
    "PM_PROFILE_STRIDE",
    "PT_NAMES",
    "PT_STRIDE",
    "PT_UNITS",
    "PV_DURATIONS_OFFSET",
    "PV_DURATION_STRIDE",
    "TECH_SPARE_LEN",
    "TECH_SPARE_OFFSET",
    "CycleDuration",
    "MissionParams",
    "MissionProfile",
    "TechParams",
    "decode_254",
    "decode_255",
]

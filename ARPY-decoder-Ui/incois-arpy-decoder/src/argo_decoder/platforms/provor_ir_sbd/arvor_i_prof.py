"""ARVOR-I mono-profile (``R<WMO>_<NNN>.nc``) adapter — Coriolis production semantics.

Implements the ascent mono-profile product per
``docs/phase_reports/ARVOR_I_MONO_PROFILE_MAPPING_2026-08-27.md`` (every rule
below is PROVEN there unless noted) on top of the generic, unmodified
``argo_decoder.nc.mono_profile`` builder/writer:

* one file per cycle, **direct** cycle numbering (the +1 renumbering is a
  legacy Rtraj-pipeline behaviour, mapping §6);
* levels: ``ascent_shallow`` block followed by the ``ascent_deep`` block,
  each reversed to pressure-ascending, concatenated into one strictly
  pressure-ascending series (deep-only cycles carry the deep block alone);
* ``JULD`` = reception time of the first non-pre-launch mail of the cycle's
  Iridium session — so retransmitted cycles keep the retransmission arrival
  date — with ``JULD_LOCATION = JULD``, ``JULD_QC = '1'``;
* position: the cycle's Tech#1 GPS fix truncated to arc-minutes
  (``POSITIONING_SYSTEM = 'GPS'``); without a fresh GPS fix, the cycle's
  first usable Iridium mail fix at full precision
  (``POSITIONING_SYSTEM = 'IRIDIUM'`` — see :func:`first_mail_fix`);
  ``POSITION_QC = '1'``;
* per-level ``QC = '0'`` (``g_decArgo_qcStrNoQc``), fill levels ``' '``;
* ``VERTICAL_SAMPLING_SCHEME = 'Primary sampling: averaged []'`` (constant
  for these floats) and ``CONFIG_MISSION_NUMBER`` = fill ``99999`` (no USE
  table in the decoded float config — never fabricated).

Differences vs the GDAC references that this adapter deliberately does NOT
reproduce (classified publication-layer, mapping §7): INCOIS RTQC level
flags ``'1'``/``'A'`` (and the single TEMP ``'3'``), ``CONFIG_MISSION_NUMBER
= 1``, float-json metadata strings (PROJECT_NAME, PI_NAME, serial,
firmware, ``DATA_CENTRE``/institution), INQC ``HISTORY`` rows / ``DATE_UPDATE``
batches, and the stale-fix reuse on retransmitted cycles.

Descent publication policy (explicit decision, 2026-08-27 directive)
--------------------------------------------------------------------
Raw telemetry *does* carry descent measurements (6990711 / 7902408 cycle 1)
and the science layer reconstructs them; the Coriolis writer supports
``R<WMO>_<NNN>D.nc`` files.  INCOIS GDAC publishes **no** descent file for
these floats (mapping §7.3: UNKNOWN whether publication omission or a
production descProf drop).  ``PUBLISH_DESCENT_PROFILES`` therefore defaults
to ``False``: this adapter builds ascent files only.  The descent path stays
implemented and unit-tested — flip the flag to emit ``D`` files — so the
suppression is a revisitable publication policy, not removed capability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import xarray as xr

from argo_decoder.metadata.models import FloatMeta
from argo_decoder.nc.admt import institution_for_data_centre
from argo_decoder.nc.mono_profile import build_mono_profile_dataset, write_mono_profile
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import (
    ArvorCycle,
    ArvorMeasurement,
    ArvorScienceResult,
    MailInfo,
    datetime_from_days,
)

#: Constant for these floats (mapping §5): empty CONFIG_PMxx zone list.
VERTICAL_SAMPLING_SCHEME = "Primary sampling: averaged []"

#: No USE table in the decoded float config → ADMT int fill, never fabricated.
CONFIG_MISSION_NUMBER_FILL = 99999

#: Publication policy (see module docstring): GDAC publishes no ``D`` files.
PUBLISH_DESCENT_PROFILES = False

_PARAMS = ("PRES", "TEMP", "PSAL")
_NO_QC_CHARS = (b" ", b"0", b"9")  # qcStrDef / qcStrNoQc / qcStrMissing


# ---------------------------------------------------------------------------
# Coriolis-chain rules (pure functions)
# ---------------------------------------------------------------------------


def truncate_arc_minutes(deg: float) -> float:
    """Truncate a position to whole arc-minutes (Coriolis GPS publication rule).

    PROVEN on 6990711 cycle 1 (2.9410316 deg -> 2.93333; -64.54295 ->
    -64.53333) and 7902408 cycles 1-4, mapping §4.  Truncation, not
    rounding: 70.08330 -> 70.06667.
    """
    minutes = math.floor(abs(deg) * 60.0)
    return math.copysign(minutes / 60.0, deg)


def first_mail_time(mails: list[MailInfo], cycle: int) -> float | None:
    """Reception time of the cycle's first non-pre-launch Iridium mail.

    Mirrors ``compute_first_last_msg_time_from_iridium_mail`` selection as
    used by the production mono-profile chain: mails are grouped by their
    leading packet-cycle tag; the minimum session time wins, so a
    retransmitted cycle keeps the *retransmission* arrival date (PROVEN:
    6990711 ``_005`` / ``_015``-style cases, mapping §4).  Same selection
    rule as the 4B Rtraj first-message-time helper.
    """
    times = [
        m.time_of_session for m in mails if m.cycles and m.cycles[0] == cycle and not m.pre_launch
    ]
    return min(times) if times else None


def coriolis_profile_qc(qc_chars: np.ndarray) -> str:
    """``compute_profile_quality_flag`` port (vendored .m, L30-62).

    When every flag is one of ``' '`` (qcStrDef), ``'0'`` (qcStrNoQc) or
    ``'9'`` (qcStrMissing) the MATLAB function returns ``qcStrDef`` — i.e.
    ``' '`` — without computing a ratio.  Otherwise the percentage-of-good
    letter (A/B/C/D/E/F) is returned.  The generic builder's
    ``_profile_qc_flag`` counts ``'0'`` as a useful-but-not-good level and
    would emit ``'F'`` for Coriolis no-QC columns; this port supplies the
    chain-accurate letter.
    """
    flags = [bytes(ch)[:1] for ch in np.asarray(qc_chars, dtype="S1").reshape(-1)]
    if not flags or all(ch in _NO_QC_CHARS for ch in flags):
        return " "
    useful = [ch for ch in flags if ch not in _NO_QC_CHARS]
    good = [ch for ch in useful if ch in (b"1", b"2", b"5", b"8")]
    ratio = 100.0 * len(good) / len(useful)
    if ratio == 0:
        return "F"
    if ratio < 25:
        return "E"
    if ratio < 50:
        return "D"
    if ratio < 75:
        return "C"
    if ratio < 100:
        return "B"
    return "A"


def apply_coriolis_profile_qc(admt: xr.Dataset) -> xr.Dataset:
    """Replace the builder's ``PROFILE_<P>_QC`` letters with chain-accurate ones."""
    for name in _PARAMS:
        key = f"PROFILE_{name}_QC"
        if key not in admt.data_vars:
            continue
        letter = coriolis_profile_qc(np.asarray(admt[f"{name}_QC"].values, dtype="S1"))
        old = admt[key]
        admt[key] = xr.DataArray(
            np.array([letter.encode("ascii")], dtype="S1"),
            dims=old.dims,
            attrs=old.attrs,
        )
    return admt


def apply_coriolis_var_order(admt: xr.Dataset) -> xr.Dataset:
    """Reorder variables to the Coriolis mono-profile writer layout.

    The generic builder appends ``PROFILE_<P>_QC`` after the science
    block and each ``<P>_ADJUSTED_ERROR`` directly after its parameter
    group; the Coriolis ``create_nc_mono_prof_c_files_3_1`` writer
    defines ``PROFILE_<P>_QC`` directly after ``POSITIONING_SYSTEM``
    (before ``VERTICAL_SAMPLING_SCHEME``), groups all three
    ``<P>_ADJUSTED_ERROR`` variables after the last science parameter,
    and defines ``HISTORY_QCTEST`` after ``HISTORY_PREVIOUS_VALUE`` —
    the order all 23 GDAC reference files carry (verified 2026-08-27).
    Content is unchanged; only definition order moves.
    """
    order = list(admt.data_vars)
    prof_qc = [f"PROFILE_{p}_QC" for p in _PARAMS if f"PROFILE_{p}_QC" in order]
    if prof_qc and "POSITIONING_SYSTEM" in order:
        for name in prof_qc:
            order.remove(name)
        anchor = order.index("POSITIONING_SYSTEM") + 1
        order = order[:anchor] + prof_qc + order[anchor:]
    errors = [f"{p}_ADJUSTED_ERROR" for p in _PARAMS if f"{p}_ADJUSTED_ERROR" in order]
    if errors and "PARAMETER" in order:
        for name in errors:
            order.remove(name)
        anchor = order.index("PARAMETER")
        order = order[:anchor] + errors + order[anchor:]
    if "HISTORY_QCTEST" in order and "HISTORY_PREVIOUS_VALUE" in order:
        # Writer defines HISTORY_QCTEST last, after HISTORY_PREVIOUS_VALUE.
        order.remove("HISTORY_QCTEST")
        order.insert(order.index("HISTORY_PREVIOUS_VALUE") + 1, "HISTORY_QCTEST")
    return admt[order]


# ---------------------------------------------------------------------------
# Level assembly
# ---------------------------------------------------------------------------


def _ascending(block: list[ArvorMeasurement]) -> list[ArvorMeasurement]:
    """Reverse a science block (stored deep-first) to pressure-ascending."""
    return list(reversed(block))


def ascent_measurement_rows(cyc: ArvorCycle) -> list[ArvorMeasurement]:
    """One strictly pressure-ascending ascent series: shallow block first.

    ``build_profile_measurements`` sorts both blocks pressure-descending
    (deep first), so each is reversed before concatenation; because the
    split at ``subSurfacePres`` keeps every shallow level shallower than
    every deep level, ``shallow + deep`` is globally ascending (PROVEN
    level ordering vs GDAC, mapping §2/§8).  Deep-only cycles return the
    deep block alone.
    """
    shallow = deep = []
    for prof in cyc.profiles:
        if prof.kind == "ascent_shallow":
            shallow = prof.measurements
        elif prof.kind == "ascent_deep":
            deep = prof.measurements
    return _ascending(shallow) + _ascending(deep)


def descent_measurement_rows(cyc: ArvorCycle) -> list[ArvorMeasurement]:
    """Descent series reversed to pressure-ascending (kept capable, mapping §7.3)."""
    for prof in cyc.profiles:
        if prof.kind == "descent":
            return _ascending(prof.measurements)
    return []


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------


@dataclass
class ArvorProfRecord:
    """One mono-profile product plus the provenance of its header fields."""

    wmo: int
    cycle: int
    direction: str  # 'A' (published) | 'D' (publication-policy suppressed)
    n_levels: int
    juld: float
    juld_source: str
    position_source: str  # 'gps-truncated' | 'iridium-mail' | 'interpolated' | ...
    positioning_system: str
    dataset: xr.Dataset
    notes: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        suffix = "D" if self.direction == "D" else ""
        return f"R{self.wmo}_{self.cycle:03d}{suffix}.nc"


def first_mail_fix(mails: list[MailInfo], cycle: int) -> tuple[float, float] | None:
    """Iridium fix of the cycle's first usable mail (production RT behavior).

    The two chain sources weigh Iridium fixes by CEP —
    ``compute_profile_location_from_iridium_locations_ir_sbd`` (CEP < 5 km)
    and ``compute_profile_location2_...`` (minimum CEP; both vendored) —
    but with the full mail snapshot neither reproduces the published GDAC
    positions for 7902408 ``_014``/``_015`` or 6990711 ``_006``.  All four
    (plus ``_013``) equal the **first mail's own fix**, including the
    ``_006`` fix whose CEP is 415 km (excluded by both CEP rules), and
    each file's ``DATE_CREATION`` is the first-mail day: production
    computed the location when only the first mail of the cycle had
    arrived, where both MATLAB rules degenerate to that single fix
    (INFERRED; 5/5 files exact — mapping-report §4 refinement, recorded
    in ``IMPLEMENTATION_PROGRESS.md`` 2026-08-27).
    """
    candidates = [
        m
        for m in mails
        if m.cycles
        and m.cycles[0] == cycle
        and not m.pre_launch
        and m.lat is not None
        and m.lon is not None
        and m.cep_radius_km not in (None, 0)
    ]
    if not candidates:
        return None
    first = min(candidates, key=lambda m: m.time_of_session)
    return float(first.lat), float(first.lon)


def _cycle_position(
    cyc: ArvorCycle, mails: list[MailInfo], direction: str
) -> tuple[float | None, float | None, str, str]:
    """(lat, lon, positioning_system, source) per the Coriolis rules.

    Ascent: fresh Tech#1 GPS fix truncated to arc-minutes (mapping §4),
    else the cycle's first usable Iridium mail fix (``first_mail_fix``
    rule above).  Descent: the *previous* cycle's GPS fix (science-layer
    rule mirroring the MATLAB ``cycleNumber-1`` convention), else the
    previous cycle's first usable mail fix.
    """
    kinds = ("descent",) if direction == "D" else ("ascent_deep", "ascent_shallow")
    prof = next((p for p in cyc.profiles if p.kind in kinds), None)
    if prof is not None and prof.location.source == "gps" and prof.location.lat is not None:
        # Tech#1 fix published truncated to arc-minutes (mapping §4).
        loc = prof.location
        return (
            truncate_arc_minutes(loc.lat),
            truncate_arc_minutes(loc.lon),
            "GPS",
            "gps-truncated",
        )
    mail_cycle = cyc.cycle_number - 1 if direction == "D" else cyc.cycle_number
    fix = first_mail_fix(mails, mail_cycle)
    if fix is not None:
        return fix[0], fix[1], "IRIDIUM", "first-mail-fix"
    return None, None, " ", "none"


def _profile_input_dataset(
    cyc: ArvorCycle,
    rows: list[ArvorMeasurement],
    *,
    wmo: int,
    direction: str,
    juld: float,
    lat: float | None,
    lon: float | None,
    psys: str,
    decoder_id: int | None,
) -> xr.Dataset:
    """Flat decoder dataset in the shape ``build_mono_profile_dataset`` expects."""

    def col(attr: str) -> np.ndarray:
        return np.array(
            [getattr(m, attr) if getattr(m, attr) is not None else np.nan for m in rows],
            dtype=np.float64,
        )

    def qc(attr: str) -> np.ndarray:
        # Coriolis raw-parameter rule (c-writer L1421-1431): non-fill level
        # -> '0' (no QC performed); fill level -> qcStrDef ' '.
        return np.array([b"0" if getattr(m, attr) is not None else b" " for m in rows], dtype="S1")

    data_vars: dict[str, xr.DataArray] = {
        "PRES": xr.DataArray(col("pres"), dims=("N_LEVELS",)),
        "TEMP": xr.DataArray(col("temp"), dims=("N_LEVELS",)),
        "PSAL": xr.DataArray(col("psal"), dims=("N_LEVELS",)),
        "PRES_QC": xr.DataArray(qc("pres"), dims=("N_LEVELS",)),
        "TEMP_QC": xr.DataArray(qc("temp"), dims=("N_LEVELS",)),
        "PSAL_QC": xr.DataArray(qc("psal"), dims=("N_LEVELS",)),
        "JULD": xr.DataArray(np.float64(juld)),
        "JULD_LOCATION": xr.DataArray(np.float64(juld)),
        "JULD_QC": xr.DataArray(np.bytes_(b"1")),
        "DIRECTION": xr.DataArray(np.bytes_(direction.encode("ascii"))),
        "DATA_MODE": xr.DataArray(np.bytes_(b"R")),
    }
    if lat is not None and lon is not None:
        data_vars["LATITUDE"] = xr.DataArray(np.float64(lat))
        data_vars["LONGITUDE"] = xr.DataArray(np.float64(lon))
        data_vars["POSITION_QC"] = xr.DataArray(np.bytes_(b"1"))
    else:
        data_vars["LATITUDE"] = xr.DataArray(np.float64(99999.0))
        data_vars["LONGITUDE"] = xr.DataArray(np.float64(99999.0))
        data_vars["POSITION_QC"] = xr.DataArray(np.bytes_(b"0"))

    attrs = {
        "wmo": wmo,
        "cycle": cyc.cycle_number,
        "decoder": "provor_ir_sbd",
        "platform_type": "ARVOR-I",
        "vertical_sampling_scheme": VERTICAL_SAMPLING_SCHEME,
        # Argo convention (reference table on CONFIG_MISSION_NUMBER):
        # 1...N with 1 = first complete mission. These floats are all on
        # their launch configuration (no config change is detectable in
        # the four-CSV metadata or the telemetry), so the launch mission
        # is mission 1; the sheet's placeholder 0 / the fill sentinel
        # would both be wrong to publish. GDAC reference files carry 1.
        "config_mission_number": 1,
        "positioning_system": psys,
    }
    if decoder_id is not None:
        attrs["decoder_id"] = decoder_id
    return xr.Dataset(data_vars, attrs=attrs)


def build_arvor_mono_profiles(
    result: ArvorScienceResult,
    *,
    wmo: int,
    publish_descent: bool = PUBLISH_DESCENT_PROFILES,
    meta: FloatMeta | None = None,
    firmware_version: str | None = None,
) -> list[ArvorProfRecord]:
    """Build one ADMT mono-profile dataset per (cycle x direction) to publish.

    Ascent files are always built.  Descent files are built only when
    ``publish_descent`` is True (publication policy, module docstring).
    Cycles without measurements or without a first-mail time are skipped
    (recorded in ``result.notes`` semantics — no silent discard).
    """
    from argo_decoder.platforms.provor_ir_sbd.arvor_i_tech import resolve_dec_id

    decoder_id = resolve_dec_id(result)
    records: list[ArvorProfRecord] = []

    for cyc in result.cycles:
        if cyc.cycle_number < 0:  # parameter-only buffers carry no CTD data
            continue
        groups: list[tuple[str, list[ArvorMeasurement]]] = [("A", ascent_measurement_rows(cyc))]
        if publish_descent:
            groups.append(("D", descent_measurement_rows(cyc)))
        for direction, rows in groups:
            notes: list[str] = []
            if not rows:
                notes.append(f"cycle {cyc.cycle_number} {direction}: no measurements")
                continue
            juld = first_mail_time(result.mails, cyc.cycle_number)
            if juld is None:
                notes.append(f"cycle {cyc.cycle_number} {direction}: no first-mail time — skipped")
                continue
            lat, lon, psys, pos_source = _cycle_position(cyc, result.mails, direction)
            ds = _profile_input_dataset(
                cyc,
                rows,
                wmo=wmo,
                direction=direction,
                juld=juld,
                lat=lat,
                lon=lon,
                psys=psys,
                decoder_id=decoder_id,
            )
            institution = (
                institution_for_data_centre(meta.data_centre) if meta is not None else "CORIOLIS"
            )
            admt = build_mono_profile_dataset(
                ds,
                wmo=wmo,
                cycle=cyc.cycle_number,
                meta=meta,
                institution=institution,
                firmware_version=firmware_version,
                date_creation=datetime_from_days(juld).astimezone(UTC).strftime("%Y%m%d%H%M%S"),
            )
            admt = apply_coriolis_profile_qc(admt)
            admt = apply_coriolis_var_order(admt)
            records.append(
                ArvorProfRecord(
                    wmo=wmo,
                    cycle=cyc.cycle_number,
                    direction=direction,
                    n_levels=len(rows),
                    juld=juld,
                    juld_source="first-mail-time",
                    position_source=pos_source,
                    positioning_system=psys,
                    dataset=admt,
                    notes=notes,
                )
            )
    return records


def write_arvor_mono_profiles(records: list[ArvorProfRecord], out_dir: Path) -> dict[str, Path]:
    """Write ``R<WMO>_<NNN>[D].nc`` files; returns filename → path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for rec in records:
        path = out_dir / rec.filename
        write_mono_profile(rec.dataset, path)
        written[rec.filename] = path
    return written


def write_datetime() -> datetime:  # pragma: no cover - trivial helper
    """UTC now (exposed for tests/validators needing the run stamp)."""
    return datetime.now(UTC)

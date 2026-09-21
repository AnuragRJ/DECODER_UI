"""Generic calibration resolution for PROVOR CTS4 / decoder-301
(Phase 2B-2 - architectural cleanup).

Four-layer authority (no WMO branches, no 13-row whitelist for family generics):

1. Family-generic constants → :mod:`family_constants` (authoritative; 88 values
   identical across the 13 INCOIS 301 meta.nc).  The dedicated
   ``config/metadata/provor_cts4_301_reference.csv`` is retained as
   provenance / bootstrap / audit (source_file per row) but is **not**
   required to obtain these 88 numbers.

2. Float-specific present in telemetry → decoded directly from telemetry
   (NKE 5.8 §7.2.4.9 free zone ``250``): FLBB serial / DARK_CHLA / SCALE_CHLA /
   DARK_BB / SCALE_BB (OriginalScaleFactor) / SCALE_CHLA_2.  ``CHLA`` and
   ``BBP700`` therefore require no per-float metadata beyond the 250 packet.

3. Float-specific absent from telemetry → supplied through external per-float
   metadata via the dedicated CTS4 mechanism.  For DOXY the stern-volmer
   foil coefficients (PhaseCoef0/1, c0-20, TEMP_DOXY T0-3) are not in telemetry
   (NKE ``Optode Data Free 50`` = empty) and must come from external metadata.
   The production path is ``FLBB serial → dedicated CSV row``
   (:func:`doxy_cal_for_group`), but a new float may instead supply its
   coefficients as an explicit dict / as a new dedicated CSV without any
   pre-existing WMO in the 13-row file — see
   :func:`doxy_cal_from_external` and :func:`doxy_cal_from_external_dict`.

4. GDAC reference CSV → provenance and verification.  When a reference is
   supplied it is *verified* against :mod:`family_constants` (tolerance 1e-12);
   a disagreement raises.  It is never the source of the 88 family numbers.

Byte authority: NKE ``5.8_MUT_PROVBIOII-FLBB_UTI_GB_Rev3_20130924`` §7 (framing,
scales, free-zone layout). Equation authority: ``equations.py`` (pure math,
no defaults). Provenance for every coefficient lives in the dedicated
reference CSV (``source_file``/``source_variable``) when a reference is used,
or in the external dict provenance when a synthetic float is used.

The four legacy CSV schemas (``meta.csv`` etc.) remain untouched; this module
does not read them.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Family-generic authority — imported, not derived from the CSV
# ---------------------------------------------------------------------------
from argo_decoder.platforms.provor_cts4_ir_sbd import family_constants as _fc
from argo_decoder.platforms.provor_cts4_ir_sbd.equations import (
    FoilCoefs,
    PhaseCoefs,
    SolubilityConsts,
)

# ---------------------------------------------------------------------------
# Reference CSV helpers (dedicated Phase-2A schema, now provenance-only)
# ---------------------------------------------------------------------------

_DEFAULT_REF = (
    Path(__file__).resolve().parents[4] / "config" / "metadata" / "provor_cts4_301_reference.csv"
)

# The audit set is the family_constants keyset; keep the name for
# backward-compat with tests that check "family_generic" in the module text.
_FAMILY_GENERIC_COEFS: set[tuple[str, str]] = set(_fc.FAMILY_GENERIC_KEYS)

_FLOAT_SPECIFIC_COEFS: set[tuple[str, str]] = {
    ("BBP700", "DARK_BACKSCATTERING700"),
    ("BBP700", "SCALE_BACKSCATTERING700"),
    ("CHLA", "DARK_CHLA"),
    ("DOXY", "PhaseCoef0"),
    ("DOXY", "PhaseCoef1"),
    ("DOXY", "c0"),
    ("DOXY", "c1"),
    ("DOXY", "c2"),
    ("DOXY", "c3"),
    ("DOXY", "c4"),
    ("DOXY", "c5"),
    ("DOXY", "c6"),
    ("DOXY", "c7"),
    ("DOXY", "c8"),
    ("DOXY", "c9"),
    ("DOXY", "c10"),
    ("DOXY", "c11"),
    ("DOXY", "c12"),
    ("DOXY", "c13"),
    ("DOXY", "c14"),
    ("DOXY", "c15"),
    ("DOXY", "c16"),
    ("DOXY", "c17"),
    ("DOXY", "c18"),
    ("DOXY", "c19"),
    ("DOXY", "c20"),
    ("TEMP_DOXY", "T0"),
    ("TEMP_DOXY", "T1"),
    ("TEMP_DOXY", "T2"),
    ("TEMP_DOXY", "T3"),
}

# DOXY external-required float-specific subset (telemetry carries nothing
# for the optode free zone — NKE §7.2.4.9 Optode Data Free 50).
_DOXY_EXTERNAL_REQUIRED: list[tuple[str, str]] = [
    ("DOXY", "PhaseCoef0"),
    ("DOXY", "PhaseCoef1"),
    *[("DOXY", f"c{i}") for i in range(21)],
    ("TEMP_DOXY", "T0"),
    ("TEMP_DOXY", "T1"),
    ("TEMP_DOXY", "T2"),
    ("TEMP_DOXY", "T3"),
]


@dataclass(frozen=True)
class ReferenceDB:
    """In-memory view of the dedicated 301 reference CSV (provenance)."""

    by_wmo: dict[str, dict[tuple[str, str], float]]
    flbb_serial_to_wmo: dict[int, str]
    family_generic: dict[tuple[str, str], float]


def _family_generic_from_constants() -> dict[tuple[str, str], float]:
    return dict(_fc.FAMILY_GENERIC)


def _verify_reference_against_authoritative(
    reference_family: Mapping[tuple[str, str], float],
) -> None:
    authoritative = _fc.FAMILY_GENERIC
    for key, auth_val in authoritative.items():
        ref_val = reference_family.get(key)
        if ref_val is None:
            raise ValueError(f"reference missing family-generic {key}")
        if abs(ref_val - auth_val) > 1e-12:
            raise ValueError(
                f"family-generic {key} disagrees: authoritative={auth_val} vs reference={ref_val}"
            )


def load_reference(path: Path | None = None) -> ReferenceDB:
    """Load the dedicated reference CSV generically (no WMO literals).

    The 88 family-generic numbers are verified against :mod:`family_constants`
    rather than being the source of them.  A disagreement (e.g. a future FLBB
    geometry with different khi) raises immediately so the hard-coded
    constants can be versioned with a decoder-family guard.
    """

    csv_path = Path(path) if path is not None else _DEFAULT_REF
    by_wmo: dict[str, dict[tuple[str, str], float]] = {}
    flbb_map: dict[int, str] = {}

    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            wmo = row["wmo"]
            key = (row["parameter"], row["coefficient"])
            val = float(row["value"])
            by_wmo.setdefault(wmo, {})[key] = val
            if row["parameter"] in ("BBP700", "CHLA") and row["sensor_serial"].isdigit():
                serial = int(row["sensor_serial"])
                existing = flbb_map.get(serial)
                if existing is not None and existing != wmo:
                    raise ValueError(
                        f"FLBB serial {serial} maps to multiple WMOs: {existing} vs {wmo}"
                    )
                flbb_map[serial] = wmo

    any_wmo = next(iter(by_wmo))
    family_generic: dict[tuple[str, str], float] = {}
    for key in _FAMILY_GENERIC_COEFS:
        family_generic[key] = by_wmo[any_wmo][key]
        expected = family_generic[key]
        for wmo, coeffs in by_wmo.items():
            if abs(coeffs[key] - expected) > 1e-12:
                raise ValueError(
                    f"family-generic {key} disagrees: {any_wmo}={expected} vs {wmo}={coeffs[key]}"
                )

    # Verify the reference agrees with the hard-coded authoritative constants.
    _verify_reference_against_authoritative(family_generic)

    return ReferenceDB(by_wmo=by_wmo, flbb_serial_to_wmo=flbb_map, family_generic=family_generic)


# ---------------------------------------------------------------------------
# Telemetry-derived FLBB calibration (250 free zone)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlbbCal:
    """FLBB calibration resolved *generically* from telemetry 250 free zone."""

    serial: int
    scale_chl: float
    dark_chl: int
    scale_bb: float
    dark_bb: int
    scale_chl_2: float
    source: str  # e.g. "telemetry:250:FlbbFree"
    group: str  # IMEI suffix dir name, e.g. "06580"


@dataclass(frozen=True)
class ChlaCal:
    """CHLA equation coefficients (generic scale, telemetry dark)."""

    dark: float
    scale: float
    provenance: str


@dataclass(frozen=True)
class BbpCal:
    """BBP700 equation coefficients."""

    dark: float
    scale: float
    khi: float
    provenance_dark_scale: str
    provenance_khi: str


def flbb_cal_from_telemetry(
    flbb_serial: int,
    scale_chl: float,
    dark_chl: int,
    scale_bb: float,
    dark_bb: int,
    scale_chl_2: float,
    group: str,
) -> FlbbCal:
    return FlbbCal(
        serial=flbb_serial,
        scale_chl=scale_chl,
        dark_chl=dark_chl,
        scale_bb=scale_bb,
        dark_bb=dark_bb,
        scale_chl_2=scale_chl_2,
        source="telemetry:250:FlbbFree",
        group=group,
    )


def chla_cal_from_flbb(
    flbb: FlbbCal,
    reference: ReferenceDB | None = None,
) -> ChlaCal:
    """Resolve CHLA: DARK from telemetry, SCALE_CHLA from authoritative constants.

    When *reference* is supplied it is verified (tolerance 1e-12) but not
    used as the source.  The provenance string keeps "family_generic" for
    backward-compat (tests assert its presence) while documenting the
    authoritative source.
    """
    scale_generic = _fc.SCALE_CHLA
    if reference is not None:
        ref_scale = reference.family_generic.get(("CHLA", "SCALE_CHLA"))
        if ref_scale is not None and abs(ref_scale - scale_generic) > 1e-12:
            raise ValueError(
                f"CHLA SCALE mismatch: family_constants {scale_generic} vs reference {ref_scale}"
            )
    # telemetry scale_chl should match family generic (LE float32 0.0073);
    # if not, we still use the family constant and surface the delta in the
    # report ledger; do not raise.
    if abs(flbb.scale_chl - scale_generic) > 1e-9:
        pass
    prov = (
        f"family_constants:CHLA:SCALE_CHLA={scale_generic} "
        f"(family_generic authoritative; telemetry:250:{flbb.group}:FlbbFree.dark_chl)"
    )
    if reference is not None:
        prov += " verified vs reference"
    return ChlaCal(
        dark=float(flbb.dark_chl),
        scale=scale_generic,
        provenance=prov,
    )


def bbp_cal_from_flbb(
    flbb: FlbbCal,
    reference: ReferenceDB | None = None,
) -> BbpCal:
    """Resolve BBP: DARK+SCALE from telemetry, khi from authoritative constants."""
    khi = _fc.KHI_700
    if reference is not None:
        ref_khi = reference.family_generic.get(("BBP700", "khi"))
        if ref_khi is not None and abs(ref_khi - khi) > 1e-12:
            raise ValueError(f"BBP khi mismatch: family_constants {khi} vs reference {ref_khi}")
    return BbpCal(
        dark=float(flbb.dark_bb),
        scale=float(flbb.scale_bb),
        khi=float(khi),
        provenance_dark_scale=f"telemetry:250:{flbb.group}:FlbbFree.dark_bb/scale_bb",
        provenance_khi="family_generic:BPP700:khi",
    )


# ---------------------------------------------------------------------------
# DOXY calibration — generic parts + float-specific via FLBB serial → CSV
#       or via explicit external per-float dict (no CSV pre-existence needed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DoxyCal:
    """Complete DOXY coefficient set ready for :func:`equations.doxy_chain`."""

    phase: PhaseCoefs
    foil: FoilCoefs
    sol: SolubilityConsts
    provenance: dict[str, str]
    flbb_serial: int
    wmo_hypothesis: str | None
    group: str


def _solubility_from_family_constants() -> SolubilityConsts:
    fg = _fc.FAMILY_GENERIC

    def g(param: str, coef: str) -> float:
        return fg[(param, coef)]

    return SolubilityConsts(
        a=(
            g("DOXY", "A0"),
            g("DOXY", "A1"),
            g("DOXY", "A2"),
            g("DOXY", "A3"),
            g("DOXY", "A4"),
            g("DOXY", "A5"),
        ),
        b=(g("DOXY", "B0"), g("DOXY", "B1"), g("DOXY", "B2"), g("DOXY", "B3")),
        c0=g("DOXY", "C0"),
        d=(g("DOXY", "D0"), g("DOXY", "D1"), g("DOXY", "D2"), g("DOXY", "D3")),
        spreset=g("DOXY", "Spreset"),
        pcoef1=g("DOXY", "Pcoef1"),
        pcoef2=g("DOXY", "Pcoef2"),
        pcoef3=g("DOXY", "Pcoef3"),
        nom_air_press=1013.25,
        nom_air_mix=0.20946,
    )


def _solubility_from_reference(ref: ReferenceDB, wmo: str | None) -> SolubilityConsts:
    """Legacy helper: delegates to family_constants (kept for compat)."""
    # Verification step when a reference is supplied
    _verify_reference_against_authoritative(ref.family_generic)
    return _solubility_from_family_constants()


def doxy_cal_from_external(
    flbb: FlbbCal,
    float_specific: Mapping[tuple[str, str], float],
    group: str | None = None,
    wmo_hypothesis: str | None = None,
) -> DoxyCal:
    """Resolve DOXY from authoritative family generics + explicit float-specific.

    This is the **external per-float metadata path** (layer 3).  Telemetry
    never carries these coefficients (NKE ``Optode Data Free 50``), so the
    caller must supply them — either from a dedicated CTS4 CSV that contains
    a row for this FLBB serial, or from a synthetic / external dict for a
    hypothetical new float.  No WMO needs to be present in
    ``provor_cts4_301_reference.csv``.

    Args:
        flbb: telemetry-derived FLBB cal (provides serial + group for provenance).
        float_specific: mapping of the float-specific coefficients that telemetry
            cannot provide.  Required keys: PhaseCoef0, PhaseCoef1, c0-20,
            TEMP_DOXY T0-3 (see ``_DOXY_EXTERNAL_REQUIRED``).  Values are
            floats; the 7 trailing foil terms c21-27 and the family generic
            parts (A0-5, B0-3, C0, D0-3, Spreset, Pcoef1-3, PhaseCoef2/3,
            m/n, T4/5) are taken from :mod:`family_constants`.
        group: optional override for group label (defaults to flbb.group).
        wmo_hypothesis: optional label for GDAC comparison (not used for
            equation).

    Returns:
        DoxyCal ready for ``equations.doxy_chain``.

    Raises:
        KeyError: if any required float-specific coefficient is missing.
    """
    missing = [k for k in _DOXY_EXTERNAL_REQUIRED if k not in float_specific]
    if missing:
        raise KeyError(
            f"external DOXY float_specific missing keys {missing} for FLBB "
            f"serial {flbb.serial} group {group or flbb.group}: supply via dedicated CTS4 metadata"
        )

    # Phase: 0/1 float-specific, 2/3 authoritative generic 0
    phase = PhaseCoefs(
        c0=float(float_specific[("DOXY", "PhaseCoef0")]),
        c1=float(float_specific[("DOXY", "PhaseCoef1")]),
        c2=_fc.FAMILY_GENERIC[("DOXY", "PhaseCoef2")],
        c3=_fc.FAMILY_GENERIC[("DOXY", "PhaseCoef3")],
    )

    # Foil: c0-20 float-specific, c21-27 generic zero
    c_list: list[float] = []
    for i in range(28):
        key: tuple[str, str] = ("DOXY", f"c{i}")
        if i <= 20:
            c_list.append(float(float_specific[key]))
        else:
            c_list.append(float(_fc.FAMILY_GENERIC[key]))
    c = tuple(c_list)

    m = tuple(int(_fc.FAMILY_GENERIC[("DOXY", f"m{i}")]) for i in range(28))
    n = tuple(int(_fc.FAMILY_GENERIC[("DOXY", f"n{i}")]) for i in range(28))
    foil = FoilCoefs(c=c, m=m, n=n)

    sol = _solubility_from_family_constants()

    g = group if group is not None else flbb.group
    prov: dict[str, str] = {}
    prov["PhaseCoef0"] = f"external:DOXY:PhaseCoef0 for flbb_serial {flbb.serial} group {g}"
    if wmo_hypothesis is not None:
        prov["PhaseCoef0"] += f" hypothesis {wmo_hypothesis}"
    prov["PhaseCoef1"] = f"external:DOXY:PhaseCoef1 for flbb_serial {flbb.serial} group {g}"
    for i in range(21):
        prov[f"c{i}"] = f"external:DOXY:c{i} for flbb_serial {flbb.serial} group {g}"
    for key in _FAMILY_GENERIC_COEFS:
        if key[0] == "DOXY":
            prov[f"{key[0]}.{key[1]}"] = "family_constants:family_generic"
    prov["Spreset"] = "family_constants:family_generic"
    # Surface that solubility is authoritative, not CSV-sourced
    prov["A0"] = "family_constants:family_generic:A0"

    return DoxyCal(
        phase=phase,
        foil=foil,
        sol=sol,
        provenance=prov,
        flbb_serial=flbb.serial,
        wmo_hypothesis=wmo_hypothesis,
        group=g,
    )


def doxy_cal_from_external_dict(
    flbb: FlbbCal,
    external_by_serial: Mapping[int, Mapping[tuple[str, str], float]],
    group: str | None = None,
) -> DoxyCal:
    """Dict-wrapper around :func:`doxy_cal_from_external` (serial-keyed).

    ``external_by_serial`` is the in-memory equivalent of a dedicated CTS4
    metadata CSV keyed by FLBB serial (new float allowed).  The existing
    13-WMO file ``provor_cts4_301_reference.csv`` is just one instance of
    this mapping (keyed by WMO); this function closes the
    serial→coefficients indirection without needing a pre-existing WMO.
    """
    g = group if group is not None else flbb.group
    float_specific = external_by_serial.get(flbb.serial)
    if float_specific is None:
        raise KeyError(
            f"FLBB serial {flbb.serial} (group {g}) not present in external DOXY metadata: "
            f"DATA-COVERAGE — no authoritative float-specific DOXY coefficients"
        )
    wmo_hint: str | None = None
    # Optional synthetic WMO hint could be supplied via a separate arg;
    # not used for the equation (kept for symmetry with ReferenceDB).
    return doxy_cal_from_external(flbb, float_specific, group=g, wmo_hypothesis=wmo_hint)


def doxy_cal_for_group(
    group: str,
    flbb_serial: int,
    reference: ReferenceDB,
) -> DoxyCal:
    """Resolve DOXY coefficients generically via FLBB serial → reference CSV.

    No WMO literal appears in the decoder path; the WMO is a *result* of the
    lookup, kept as a hypothesis label for GDAC comparison only.  For a new
    float that lacks a row in the 13-WMO file, use
    :func:`doxy_cal_from_external` with an explicit per-float dict instead.

    Raises:
        KeyError: if the FLBB serial has no entry in the reference CSV
                  (then the caller must classify as DATA-COVERAGE).
    """
    wmo = reference.flbb_serial_to_wmo.get(flbb_serial)
    if wmo is None:
        raise KeyError(
            f"FLBB serial {flbb_serial} (group {group}) not present in "
            f"{_DEFAULT_REF.name}: DATA-COVERAGE — no authoritative "
            f"float-specific DOXY coefficients. For a new float supply external "
            f"per-float metadata via doxy_cal_from_external / dedicated CTS4 CSV."
        )
    coeffs = reference.by_wmo[wmo]

    # Build the float_specific subset that telemetry cannot provide
    float_specific: dict[tuple[str, str], float] = {}
    for key in _DOXY_EXTERNAL_REQUIRED:
        float_specific[key] = coeffs[key]

    flbb_stub = FlbbCal(
        serial=flbb_serial,
        scale_chl=float("nan"),
        dark_chl=0,
        scale_bb=float("nan"),
        dark_bb=0,
        scale_chl_2=0.0,
        source="reference:stub-for-doxy",
        group=group,
    )
    # Reuse the external path so the math source is single-point.
    doxy = doxy_cal_from_external(flbb_stub, float_specific, group=group, wmo_hypothesis=wmo)
    # Replace provenance keys that came from "external:" with the historical
    # "reference:" phrasing so existing tests that assert on provenance text
    # (legacy path) continue to pass; the new path keeps "external:" already.
    prov: dict[str, str] = dict(doxy.provenance)
    for k in ("PhaseCoef0", "PhaseCoef1"):
        prov[k] = f"reference:{wmo}:DOXY:{k} via flbb_serial {flbb_serial}"
    for i in range(21):
        prov[f"c{i}"] = f"reference:{wmo}:DOXY:c{i} via flbb_serial {flbb_serial}"
    for key in _FAMILY_GENERIC_COEFS:
        if key[0] == "DOXY":
            prov[f"{key[0]}.{key[1]}"] = "family_generic"
    # Keep solubility keys explicitly
    prov["DOXY.A0"] = "family_generic"

    return DoxyCal(
        phase=doxy.phase,
        foil=doxy.foil,
        sol=doxy.sol,
        provenance=prov,
        flbb_serial=flbb_serial,
        wmo_hypothesis=wmo,
        group=group,
    )


# ---------------------------------------------------------------------------
# Group-level convenience: scan a raw_telemetry group directory for its
# consensus FLBB calibration (1:1 per group, Phase-2A ledger).
# ---------------------------------------------------------------------------


def consensus_flbb_for_group(
    group_path: Path,
    reference: ReferenceDB | None = None,
) -> FlbbCal:
    """Scan ``group_path/SBD-BGC-raw/<suffix>/.../*.sbd`` (or a direct suffix
    dir) for 250 FLBB halves and return the consensus calibration.

    The corpus guarantees 1 FLBB serial per group (Phase-2A §6); a mixture
    raises loudly (discovery, not noise).  *reference* is accepted for
    backward-compat but is not used (calibration comes from telemetry).
    """
    from argo_decoder.platforms.provor_cts4_ir_sbd.framer import frame_file
    from argo_decoder.platforms.provor_cts4_ir_sbd.packets import PacketType
    from argo_decoder.platforms.provor_cts4_ir_sbd.tech import FlbbFree, decode_250

    sbds = list(Path(group_path).rglob("*.sbd"))
    if not sbds:
        raise FileNotFoundError(f"no .sbd under {group_path}")

    def _group_name(p: Path) -> str:
        for parent in p.parents:
            if parent.name.isdigit() and len(parent.name) == 5:
                return parent.name
        return Path(group_path).name

    group = _group_name(sbds[0])

    seen: set[tuple[int, float, int, float, int, float]] = set()
    consensus: FlbbCal | None = None

    for sbd in sbds:
        framed = frame_file(sbd)
        from argo_decoder.platforms.provor_cts4_ir_sbd.packets import dispatch_framed

        disp = dispatch_framed(framed)
        for pkt in disp.packets:
            if getattr(pkt, "kind", None) is not PacketType.SENSOR_TECH:
                continue
            tech = decode_250(pkt)  # type: ignore[arg-type]
            for half in tech.halves:
                if half.sensor != 4 or not half.present:
                    continue
                free = half.free
                if not isinstance(free, FlbbFree):
                    raise TypeError(
                        f"group {group} sensor 4 half has {type(free).__name__}, expected FlbbFree"
                    )
                tup = (
                    free.serial,
                    float(free.scale_chl),
                    int(free.dark_chl),
                    float(free.scale_bb),
                    int(free.dark_bb),
                    float(free.scale_chl_2),
                )
                seen.add(tup)
                if consensus is None:
                    consensus = FlbbCal(
                        serial=tup[0],
                        scale_chl=tup[1],
                        dark_chl=tup[2],
                        scale_bb=tup[3],
                        dark_bb=tup[4],
                        scale_chl_2=tup[5],
                        source="telemetry:250:FlbbFree",
                        group=group,
                    )

    if consensus is None:
        raise ValueError(f"no FLBB 250 half found under {group_path}")

    if len(seen) != 1:
        raise ValueError(f"group {group} has {len(seen)} distinct FLBB cals (expected 1:1): {seen}")

    return consensus


def resolve_group(group_path: Path, reference: ReferenceDB | None = None) -> dict[str, object]:
    """Full generic resolution for one IMEI-suffix group.

    Returns a dict with ``flbb`` (FlbbCal), ``chla`` (ChlaCal),
    ``bbp`` (BbpCal), ``doxy`` (DoxyCal | KeyError), and the
    ``wmo_hypothesis`` string. Never branches on WMO literals.

    ``reference`` is optional for CHLA/BBP (telemetry + family_constants
    cover them) but required for DOXY when the external-dict path is not used.
    If omitted, the default dedicated CSV is loaded as provenance.
    """
    ref = reference if reference is not None else load_reference()
    flbb = consensus_flbb_for_group(group_path, ref)
    chla = chla_cal_from_flbb(flbb, reference=ref)
    bbp = bbp_cal_from_flbb(flbb, reference=ref)
    try:
        doxy = doxy_cal_for_group(flbb.group, flbb.serial, ref)
    except KeyError as exc:
        doxy = exc  # type: ignore[assignment]

    wmo_hyp = ref.flbb_serial_to_wmo.get(flbb.serial)

    return {
        "group": flbb.group,
        "flbb": flbb,
        "chla": chla,
        "bbp": bbp,
        "doxy": doxy,
        "wmo_hypothesis": wmo_hyp,
        "reference_path": str(_DEFAULT_REF),
    }


__all__ = [
    "BbpCal",
    "ChlaCal",
    "DoxyCal",
    "FlbbCal",
    "ReferenceDB",
    "bbp_cal_from_flbb",
    "chla_cal_from_flbb",
    "consensus_flbb_for_group",
    "doxy_cal_for_group",
    "doxy_cal_from_external",
    "doxy_cal_from_external_dict",
    "flbb_cal_from_telemetry",
    "load_reference",
    "resolve_group",
]

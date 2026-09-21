"""Fleet genericity — all 10 raw PROVOR-Bio/CTS4 groups, one code path.

These ten IMEI-suffix groups are all the same decoder-301 / NKE 5.8 family.
CTD / O2 / FLBB are internal sensor packet subtypes, not separate float
families, so every group must flow through the identical production chain:

    raw SBD -> decode_group -> resolve_group -> build_external_meta_from_gdac
              -> process_float -> R/BR + meta + tech + Rtraj

The tests pin three things:

1. STATIC — no WMO / IMEI-suffix / FLBB-serial / cycle literal appears in any
   executable conditional in the decoder package.
2. DYNAMIC — every group that reaches publication records the identical
   ordered call trace, so there is no per-float code path.
3. PRODUCTS — every resolvable group produces the full product set, and the
   only per-float variation is the calibration carried by its own telemetry.

Direct R/BR GDAC parity is a SEPARATE question, asserted only for 2902093 in
``test_provor_cts4_direct_gdac_parity.py``; nothing here claims fleet-wide
GDAC parity.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_cts4_ir_sbd import cts4_realtime
from argo_decoder.platforms.provor_cts4_ir_sbd import external_meta_io
from argo_decoder.platforms.provor_cts4_ir_sbd import resolve as resolve_mod

WORKSPACE = Path(__file__).resolve().parents[2]
ROOT = WORKSPACE / "provor_bio_irsbd/raw_telemetry/SBD-BGC-raw"
META_DIR = WORKSPACE / "provor_bio_irsbd/ref/gdac_incois_301"
PKG = (Path(__file__).resolve().parents[1] / "src" / "argo_decoder"
       / "platforms" / "provor_cts4_ir_sbd")

pytestmark = pytest.mark.skipif(
    not ROOT.is_dir(), reason="raw SBD fleet corpus not present"
)

# Any literal that would identify one float / one cycle in a branch.
ID_RE = re.compile(
    r"\b(2902\d{3}|3042|3043|3044|3046|3065|2658|2659|2660|2661|2663"
    r"|00530|03530|03580|06580|06640|12170|17960|20000|25980|29030)\b"
)

#: The ten supplied raw groups.
GROUPS = ["00530", "03530", "03580", "06580", "06640",
          "12170", "17960", "20000", "25980", "29030"]

#: Groups whose FLBB serial has no row in authoritative metadata, so no WMO
#: exists and nothing may be published (never inferred from the IMEI).
#:
#: Empty as of the freeze gate. 03530 (FLBB 3043) and 03580 (FLBB 3044) were
#: previously here because the local 13-file INCOIS snapshot predated their
#: publication; the live GDAC carries them at WMO 2902130 and 2902131
#: (https://data-argo.ifremer.fr/dac/incois/2902130/ and .../2902131/, both
#: PROVOR_III / WMO_INST_TYPE 836 with the same 11-parameter BGC set). Their
#: authoritative metadata and calibration were added to the reference, so both
#: now resolve by serial exactly like the other eight. The mechanism was never
#: changed -- only its input coverage.
NO_WMO: set[str] = set()


def _groups() -> list[str]:
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir())


def test_all_ten_raw_groups_present() -> None:
    assert _groups() == GROUPS


def test_no_float_identity_branch_in_decoder() -> None:
    """No WMO / suffix / serial / cycle literal in an executable conditional."""
    offenders: list[tuple[str, int, object]] = []
    scanned = 0
    for f in sorted(PKG.glob("*.py")):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.IfExp, ast.Assert)):
                subjects = [node.test]
            elif isinstance(node, ast.Match):
                subjects = [node.subject]
            elif isinstance(node, ast.Compare):
                subjects = [node.left, *node.comparators]
            else:
                continue
            scanned += 1
            for sub in subjects:
                for lit in ast.walk(sub):
                    if isinstance(lit, ast.Constant) and isinstance(
                            lit.value, (str, int)):
                        if ID_RE.search(str(lit.value)):
                            offenders.append((f.name, node.lineno, lit.value))
    assert scanned > 100, "AST scan found suspiciously few conditionals"
    assert offenders == [], f"float-identity branches: {offenders[:5]}"


@pytest.fixture(scope="module")
def fleet(tmp_path_factory) -> dict:
    """Decode + resolve every group once; publish those with a WMO."""
    out = tmp_path_factory.mktemp("cts4_fleet")
    ref = resolve_mod.load_reference()
    per: dict[str, dict] = {}
    for g in _groups():
        gdir = ROOT / g
        cycles = cts4_realtime.decode_group(gdir)
        cals = resolve_mod.resolve_group(gdir)
        wmo = ref.flbb_serial_to_wmo.get(cals["flbb"].serial)
        rec = {"cycles": cycles, "cals": cals, "wmo": wmo, "res": None}
        if wmo is not None:
            meta_nc = META_DIR / f"incois_{wmo}_meta.nc"
            if meta_nc.is_file():
                em = external_meta_io.build_external_meta_from_gdac(
                    meta_nc, wmo)
                rec["res"] = cts4_realtime.process_float(gdir, wmo, out, em)
        per[g] = rec
    return {"per": per, "out": out}


def test_wmo_comes_from_serial_not_imei(fleet) -> None:
    """WMO is a result of the FLBB-serial lookup, never the IMEI suffix."""
    for g in _groups():
        rec = fleet["per"][g]
        serial = rec["cals"]["flbb"].serial
        if g in NO_WMO:
            assert rec["wmo"] is None, g
            # the IMEI suffix must never be promoted to a WMO
            assert g not in str(rec["wmo"])
        else:
            assert rec["wmo"] is not None, g
            assert rec["wmo"] != g, "WMO must not be the IMEI suffix"
            assert len(rec["wmo"]) == 7 and rec["wmo"].isdigit()
            assert serial is not None


def test_unresolvable_groups_publish_nothing(fleet) -> None:
    for g in NO_WMO:
        rec = fleet["per"][g]
        assert rec["res"] is None
        assert not list(fleet["out"].glob(f"*/{g}*"))


def test_every_resolvable_group_produces_full_product_set(fleet) -> None:
    published = [g for g in _groups() if g not in NO_WMO]
    assert len(published) == len(GROUPS) - len(NO_WMO)
    for g in published:
        res = fleet["per"][g]["res"]
        assert res is not None, g
        assert res.meta_nc.is_file(), g
        assert res.tech_nc.is_file(), g
        assert res.rtraj_nc.is_file(), g
        assert res.tech_rows > 0, g
        assert res.rtraj_rows > 0, g
        assert len(res.r_files) > 0, g
        assert len(res.br_files) > 0, g
        # exactly one meta / tech / Rtraj per float, never per cycle
        fdir = fleet["out"] / res.wmo
        assert len(list(fdir.rglob("*_meta.nc"))) == 1, g
        assert len(list(fdir.rglob("*_tech.nc"))) == 1, g
        assert len(list(fdir.rglob("*_Rtraj.nc"))) == 1, g
        # no delayed-mode products anywhere in the fleet
        assert not list(fdir.rglob("D*.nc")), g
        assert not list(fdir.rglob("BD*.nc")), g


def test_tech_row_count_is_95_per_published_cycle(fleet) -> None:
    """The 95-row GDAC tech contract holds for every float, not just one."""
    for g in _groups():
        res = fleet["per"][g]["res"]
        if res is None:
            continue
        import netCDF4
        import numpy as np
        with netCDF4.Dataset(str(res.tech_nc)) as ds:
            cyc = np.asarray(ds.variables["CYCLE_NUMBER"][:]).astype(int)
        n_pub = len({c for c in cyc})
        assert len(cyc) == n_pub * 95, (g, len(cyc), n_pub)


def test_only_calibration_varies_between_floats(fleet) -> None:
    """Per-float differences come from telemetry, not from code."""
    serials: dict[int, str] = {}
    for g in _groups():
        f = fleet["per"][g]["cals"]["flbb"]
        serials[f.serial] = g
        # family-generic coefficient is identical everywhere
        assert f.scale_chl == pytest.approx(0.0073, rel=1e-6), g
    # ten distinct FLBB serials => ten distinct floats, no collision
    assert len(serials) == 10
    # the float-specific BBP scale genuinely differs (so the telemetry, not a
    # hard-coded constant, is what drives it)
    scales = {fleet["per"][g]["cals"]["flbb"].scale_bb for g in _groups()}
    assert len(scales) >= 8


def test_decoder_chain_is_identical_for_every_published_group(fleet) -> None:
    """Re-run each published group under a call recorder; traces must match."""
    traces: dict[str, list[str]] = {}
    orig = {
        "decode_group": cts4_realtime.decode_group,
        "resolve_group": resolve_mod.resolve_group,
        "build_external_meta_from_gdac": (
            external_meta_io.build_external_meta_from_gdac),
        "process_float": cts4_realtime.process_float,
    }
    cur: list[str] = [""]

    def rec(name):
        def wrap(*a, **k):
            traces[cur[0]].append(name)
            return orig[name](*a, **k)
        return wrap

    ref = resolve_mod.load_reference()
    try:
        for name, fn in (("decode_group", cts4_realtime),
                         ("resolve_group", resolve_mod),
                         ("build_external_meta_from_gdac", external_meta_io),
                         ("process_float", cts4_realtime)):
            setattr(fn, name, rec(name))
        for g in _groups():
            if g in NO_WMO:
                continue
            cur[0] = g
            traces[g] = []
            gdir = ROOT / g
            cals = orig["resolve_group"](gdir)
            wmo = ref.flbb_serial_to_wmo.get(cals["flbb"].serial)
            em = orig["build_external_meta_from_gdac"](
                META_DIR / f"incois_{wmo}_meta.nc", wmo)
            cts4_realtime.process_float(gdir, wmo, fleet["out"], em)
    finally:
        for name, fn in (("decode_group", cts4_realtime),
                         ("resolve_group", resolve_mod),
                         ("build_external_meta_from_gdac", external_meta_io),
                         ("process_float", cts4_realtime)):
            setattr(fn, name, orig[name])

    uniq = {tuple(t) for t in traces.values()}
    assert len(traces) == len(GROUPS) - len(NO_WMO)
    assert len(uniq) == 1, f"per-float code paths detected: {uniq}"
    # The chain is driven here, so the recorder sees the two calls that happen
    # *inside* production code: process_float itself, and the decode_group it
    # re-invokes internally. Both must appear for every float, in that order.
    assert next(iter(uniq)) == ("process_float", "decode_group")

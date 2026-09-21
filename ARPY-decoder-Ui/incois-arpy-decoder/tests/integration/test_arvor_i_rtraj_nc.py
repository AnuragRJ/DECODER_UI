"""Integration tests: ARVOR-I ``_Rtraj.nc`` product over both raw datasets.

Phase 4B.  Expectations pinned from the vendored 076a chain and the raw
stream (mapping report §§3-4, 9):

* 6990711 — 7 deep cycles; GPS valid on cycles 1-4 and 7 (5 fixes total,
  one Iridium mail location per non-pre-launch mail: 35); cycles 5/6
  re-transmitted stale data (no fresh GPS) but still emit full skeletons.
* 7902408 — cycles 1-12 with Tech#1/Tech#2, cycle 13 without (fill
  skeleton, data mode R); mails tagged 14/15 with no packets become
  finalize's surface-only records (GROUNDED 'U'); 19 valid GPS fixes of
  which 7 are pre-launch (excluded).
* layout: NETCDF3_CLASSIC, fixed dimension set, the 102-variable order,
  dtypes and attributes of the GDAC references (which fix the writer's
  layout even though their *values* come from a legacy production
  pipeline — mapping report §7).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import netCDF4
import pytest

from argo_decoder.nc.rtraj_arvor import (
    arvor_rtraj_publication_rows,
    build_arvor_rtraj_nc_dataset,
    write_arvor_rtraj_file,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_prof import truncate_arc_minutes
from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import (
    MC,
    build_arvor_rtraj_dataset,
)
from argo_decoder.platforms.provor_ir_sbd.arvor_i_science import reconstruct_science

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"
GDAC_ROOT = WORKSPACE / "gdac_arvor_i_ref"

LAUNCH_6990711 = datetime(2025, 3, 2, 5, 16, tzinfo=UTC)
LAUNCH_7902408 = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)

requires_raw = pytest.mark.skipif(
    not RAW_ROOT.exists(), reason="raw ARVOR-I .eml datasets not in workspace"
)
requires_gdac = pytest.mark.skipif(
    not GDAC_ROOT.exists(), reason="GDAC reference files not in workspace"
)


def _science(wmo: int):
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / str(wmo)).glob("*.eml"))]
    launch = LAUNCH_6990711 if wmo == 6990711 else LAUNCH_7902408
    return reconstruct_science(msgs, launch)


@pytest.fixture(scope="module")
def dataset_6990711():
    return build_arvor_rtraj_dataset(_science(6990711), wmo=6990711)


@pytest.fixture(scope="module")
def dataset_7902408():
    return build_arvor_rtraj_dataset(_science(7902408), wmo=7902408)


@requires_raw
class TestRowContent:
    def test_6990711_cycle_and_row_counts(self, dataset_6990711):
        ds = dataset_6990711
        assert [c.cycle_number for c in ds.cycles] == list(range(1, 8))
        mc = Counter(r.measurement_code for r in ds.rows)
        # every deep cycle contributes the full skeleton + surface rows
        for code in (
            MC.CYCLE_START,
            MC.DST,
            MC.FST,
            MC.PST,
            MC.PET,
            MC.DPST,
            MC.AST,
            MC.AET,
            MC.TST,
            MC.FMT,
            MC.LMT,
            MC.TET,
        ):
            assert mc[code] == 7, code
        assert mc[MC.SURFACE] == 5 + 35  # 5 GPS fixes + 35 mail locations (one per mail)
        assert mc[MC.GROUNDED] == 0

    def test_6990711_row_order_within_cycle(self, dataset_6990711):
        from argo_decoder.platforms.provor_ir_sbd.arvor_i_rtraj import MC_RANK

        rows = [r for r in dataset_6990711.rows if r.cycle_number == 2]
        codes = [r.measurement_code for r in rows]
        ranks = [MC_RANK[c] for c in codes]
        assert ranks == sorted(ranks)
        # skeleton precedes surface rows; TET after the surface block
        assert codes.index(MC.DST) < codes.index(MC.FMT) < codes.index(MC.TET)
        # surface rows are date-sorted among themselves
        surf = [r.juld for r in rows if r.measurement_code == MC.SURFACE]
        assert surf == sorted(surf)

    def test_6990711_cycle5_dates_follow_float_clock(self, dataset_6990711):
        rec = dataset_6990711.cycles[4]
        assert rec.cycle_number == 5
        offset = -38.0 / 86400.0
        # clockOffset field stores the seconds offset in days
        assert rec.clock_offset == pytest.approx(offset)
        # The N_CYCLE dates are the CLOCK-ADJUSTED values. Argo User's
        # Manual 3.44.0 §2.3.5 (CLOCK_OFFSET): "For "A" mode files,
        # JULD_ADJUSTED = JULD - CLOCK_OFFSET". These RTC-derived
        # timings therefore carry the raw float-clock date minus the
        # offset; the raw values are 27485.657638888886 /
        # 27486.16597222222.
        assert rec.descent_start == pytest.approx(27485.657638888886 - offset, abs=1e-9)
        assert rec.park_start == pytest.approx(27486.16597222222 - offset, abs=1e-9)

    def test_6990711_tet_is_next_cycle_start(self, dataset_6990711):
        for prev, cur in pairwise(dataset_6990711.cycles):
            tet = next(
                r
                for r in dataset_6990711.rows
                if r.cycle_number == prev.cycle_number and r.measurement_code == MC.TET
            )
            cst = next(
                r
                for r in dataset_6990711.rows
                if r.cycle_number == cur.cycle_number and r.measurement_code == MC.CYCLE_START
            )
            expected = cst.juld_adj if cst.juld_adj is not None else cst.juld
            offset_days = prev.clock_offset or 0.0
            assert tet.juld == pytest.approx(expected + offset_days, abs=1e-9)
            assert tet.juld_adj == pytest.approx(expected, abs=1e-9)
            assert prev.trans_end == pytest.approx(expected, abs=1e-9)

    def test_6990711_jamstec_qc_on_fixes(self, dataset_6990711):
        rows = [
            r
            for r in dataset_6990711.rows
            if r.measurement_code == MC.SURFACE and r.pos_accuracy == "G"
        ]
        assert len(rows) == 5
        assert {r.pos_qc for r in rows} == {"1"}

    def test_7902408_cycle_records(self, dataset_7902408):
        ds = dataset_7902408
        assert [c.cycle_number for c in ds.cycles] == list(range(1, 16))
        modes = {c.cycle_number: c.data_mode for c in ds.cycles}
        assert all(modes[c] == "A" for c in range(1, 13))
        assert modes[13] == "R" and modes[14] == "R" and modes[15] == "R"
        grounded = {c.cycle_number: c.grounded for c in ds.cycles}
        # c14/15 are trailing-buffer cycles (go=2) with hydraulic data and
        # no grounding evidence -> 'N'; the former mail-only 'U' status was
        # an artefact of dropping their buffers (reclassified 2026-08-27)
        assert all(grounded[c] == "N" for c in range(1, 16))

    def test_7902408_fill_skeleton_on_cycle13(self, dataset_7902408):
        rows = [r for r in dataset_7902408.rows if r.cycle_number == 13]
        codes = Counter(r.measurement_code for r in rows)
        # cycle 13 buffer has no Tech#1: skeleton rows exist but undated
        dst = next(r for r in rows if r.measurement_code == MC.DST)
        assert dst.juld is None
        # it still carries surface rows (mails exist for cycle 13)
        assert codes[MC.FMT] == 1 and codes[MC.LMT] == 1

    def test_7902408_no_pre_launch_fix_rows(self, dataset_7902408):
        rows = [
            r
            for r in dataset_7902408.rows
            if r.measurement_code == MC.SURFACE and r.pos_accuracy == "G"
        ]
        # 12 cycle fixes (cycles 1-12); the 7 pre-launch fixes are excluded
        assert len(rows) == 12

    def test_aux_rows_bookkept(self, dataset_6990711, dataset_7902408):
        assert len(dataset_6990711.aux_rows) == 19
        assert len(dataset_7902408.aux_rows) == 261
        params = {a.parameter for a in dataset_7902408.aux_rows}
        assert params == {"VALVE_ACTION_DURATION", "PUMP_ACTION_DURATION"}

    def test_no_launch_row_without_position(self, dataset_6990711, dataset_7902408):
        assert not any(r.measurement_code == MC.LAUNCH for r in dataset_6990711.rows)
        assert not any(r.measurement_code == MC.LAUNCH for r in dataset_7902408.rows)
        assert any("DATA-COVERAGE" in n for n in dataset_6990711.notes)


@requires_raw
@requires_gdac
class TestWrittenLayout:
    @pytest.fixture(scope="class")
    def written(self, tmp_path_factory):
        out = {}
        for wmo, dataset in (
            (6990711, build_arvor_rtraj_dataset(_science(6990711), wmo=6990711)),
            (7902408, build_arvor_rtraj_dataset(_science(7902408), wmo=7902408)),
        ):
            path = tmp_path_factory.mktemp(f"rtraj_{wmo}") / f"{wmo}_Rtraj.nc"
            nc_ds = build_arvor_rtraj_nc_dataset(dataset, data_centre="IN")
            write_arvor_rtraj_file(nc_ds, path)
            out[wmo] = path
        return out

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_layout_matches_reference(self, written, wmo):
        nc = netCDF4.Dataset(written[wmo])
        ref = netCDF4.Dataset(GDAC_ROOT / f"{wmo}_Rtraj.nc")
        assert nc.file_format == "NETCDF3_CLASSIC"
        assert set(nc.dimensions) == set(ref.dimensions)
        # create_nc_traj_c_file_3_1.m L242: N_MEASUREMENT is the record
        # dimension (NC_UNLIMITED); GDAC references have it unlimited.
        assert nc.dimensions["N_MEASUREMENT"].isunlimited()
        assert ref.dimensions["N_MEASUREMENT"].isunlimited()
        assert list(nc.variables) == list(ref.variables)
        for v in ref.variables:
            ours, theirs = nc[v], ref[v]
            assert str(ours.dtype) == str(theirs.dtype), v
            assert ours.dimensions == theirs.dimensions, v
            ours_attrs = {a: ours.getncattr(a) for a in ours.ncattrs()}
            ref_attrs = {a: theirs.getncattr(a) for a in theirs.ncattrs()}
            assert ours_attrs == ref_attrs, v
        nc.close()
        ref.close()

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_header_and_semantics(self, written, wmo):
        nc = netCDF4.Dataset(written[wmo])
        nc.set_auto_mask(False)
        assert bytes(nc["PLATFORM_NUMBER"][:]).decode().startswith(str(wmo))
        assert bytes(nc["DATA_TYPE"][:]).decode().rstrip() == "Argo trajectory"
        assert bytes(nc["FORMAT_VERSION"][:]).decode().rstrip() == "3.1"
        assert bytes(nc["REFERENCE_DATE_TIME"][:]).decode() == "19500101000000"
        params = [b"".join(r).decode().rstrip() for r in nc["TRAJECTORY_PARAMETERS"][:]]
        assert params == ["PRES", "TEMP", "PSAL"]
        # unlimited dimension grows to the row count
        n = len(nc.dimensions["N_MEASUREMENT"])
        assert n == len(nc["CYCLE_NUMBER"][:])
        # JULD fill present on undated rows; adjusted only where data mode A
        juld = nc["JULD"][:]
        assert (juld == 999999.0).sum() > 0
        nc.close()

    def test_round_trip_values(self, written):
        nc = netCDF4.Dataset(written[6990711])
        nc.set_auto_mask(False)
        rows = build_arvor_rtraj_dataset(_science(6990711), wmo=6990711)
        published = arvor_rtraj_publication_rows(rows.rows)
        assert len(nc["JULD"][:]) == len(published)
        modes = {c.cycle_number: c.data_mode for c in rows.cycles}
        juld_adj = nc["JULD_ADJUSTED"][:]
        status_adj = nc["JULD_ADJUSTED_STATUS"][:]
        filled = 0
        for i, row in enumerate(published):
            if row.juld_adj is not None and modes.get(row.cycle_number) == "A":
                assert juld_adj[i] == pytest.approx(row.juld_adj)
                assert status_adj[i].decode() == (row.juld_adj_status or " ")
                filled += 1
        assert filled > 0
        nc.close()

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_published_file_is_the_gdac_projection(self, written, wmo):
        """The written N_MEASUREMENT block == arvor_rtraj_publication_rows
        of the internal model (published rows only; diagnostics and the
        GPS-'G' fix row stay internal)."""
        nc = netCDF4.Dataset(written[wmo])
        nc.set_auto_mask(False)
        rows = build_arvor_rtraj_dataset(_science(wmo), wmo=wmo)
        published = arvor_rtraj_publication_rows(rows.rows)
        mc = nc["MEASUREMENT_CODE"][:].tolist()
        assert mc == [r.measurement_code for r in published]
        cyc = nc["CYCLE_NUMBER"][:].tolist()
        assert cyc == [r.cycle_number for r in published]
        juld = nc["JULD"][:]
        for i, row in enumerate(published):
            if row.juld is not None:
                assert juld[i] == pytest.approx(row.juld)
        nc.close()


@requires_gdac
class TestGdacPublicationProjection:
    """Phase-2 publication contract (RTRAJ_PUBLICATION_PARITY_PHASE1.md §2/§8)."""

    _ORDER = (100, 200, 250, 300, 400, 500, 600, 700, 702, 703, 704, 800)
    _FAMILIES = frozenset({0, *_ORDER})

    @pytest.fixture(scope="class")
    def model(self):
        return {
            wmo: build_arvor_rtraj_dataset(_science(wmo), wmo=wmo) for wmo in (6990711, 7902408)
        }

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_family_set_is_gdac_exactly(self, model, wmo):
        published = arvor_rtraj_publication_rows(model[wmo].rows)
        expected = set(self._FAMILIES)
        if not any(r.measurement_code == 0 for r in model[wmo].rows):
            expected.discard(0)  # no launch position supplied -> no MC 0 row
        assert {r.measurement_code for r in published} == expected

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_canonical_block_order_and_launch_first(self, model, wmo):
        published = arvor_rtraj_publication_rows(model[wmo].rows)
        if any(r.measurement_code == 0 for r in model[wmo].rows):
            assert published[0].measurement_code == 0
            assert published[0].cycle_number == -1
        for cyc in sorted({r.cycle_number for r in published if r.measurement_code != 0}):
            seq = [r.measurement_code for r in published if r.cycle_number == cyc]
            collapsed = [k for i, k in enumerate(seq) if i == 0 or seq[i - 1] != k]
            assert collapsed == list(self._ORDER), cyc

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_det_is_pst_twin_and_ddet_is_dpst_sourced(self, model, wmo):
        published = arvor_rtraj_publication_rows(model[wmo].rows)
        for cyc in sorted({r.cycle_number for r in published if r.measurement_code != 0}):
            by = {
                code: next(
                    r for r in published if r.cycle_number == cyc and r.measurement_code == code
                )
                for code in (200, 250, 400, 500)
            }
            # DET 200 and PST 250 are the same instant -> twins.
            assert (by[200].juld, by[200].juld_status) == (by[250].juld, by[250].juld_status)
            # DDET 400 is NOT an AST twin: Trajectory Cookbook 6.1 Annex
            # 9.3 lists DDET (arrival at profile depth / start of deep
            # park drift) and AST (end of that drift) as separate ARVOR
            # events, and GDAC has 400 != 500 in 100% of cycles. DDET is
            # published from the decoded DPST 450 instant
            # (descent_to_prof_end), so it must precede or equal AST --
            # equality occurs only when the deep park drift is
            # zero-length.
            if by[400].juld is not None and by[500].juld is not None:
                assert by[400].juld <= by[500].juld

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_gps_fix_row_retained_internally_dropped_from_publication(self, model, wmo):
        internal_g = [
            r for r in model[wmo].rows if r.measurement_code == 703 and r.pos_accuracy == "G"
        ]
        published_g = [
            r
            for r in arvor_rtraj_publication_rows(model[wmo].rows)
            if r.measurement_code == 703 and r.pos_accuracy == "G"
        ]
        assert internal_g, "internal model must keep the GPS-'G' fix rows"
        assert not published_g

    @pytest.mark.parametrize("wmo", [6990711, 7902408])
    def test_positions_follow_proven_derivations(self, model, wmo):
        published = arvor_rtraj_publication_rows(model[wmo].rows)
        for cyc in sorted({r.cycle_number for r in published if r.measurement_code != 0}):
            rows = {r.measurement_code: r for r in published if r.cycle_number == cyc}
            fixes = [r for r in published if r.cycle_number == cyc and r.measurement_code == 703]
            if not fixes:
                continue
            assert (rows[700].latitude, rows[700].longitude) == (
                fixes[0].latitude,
                fixes[0].longitude,
            )
            assert (rows[702].latitude, rows[702].longitude) == (
                fixes[0].latitude,
                fixes[0].longitude,
            )
            assert (rows[704].latitude, rows[704].longitude) == (
                fixes[-1].latitude,
                fixes[-1].longitude,
            )
            assert (rows[800].latitude, rows[800].longitude) == (
                fixes[-1].latitude,
                fixes[-1].longitude,
            )
            gps = next(
                (
                    r
                    for r in model[wmo].rows
                    if r.cycle_number == cyc and r.measurement_code == 703 and r.pos_accuracy == "G"
                ),
                None,
            )
            if gps is not None and gps.latitude is not None:
                assert rows[600].latitude == truncate_arc_minutes(gps.latitude)
                assert rows[600].longitude == truncate_arc_minutes(gps.longitude)

    def test_data_state_indicator_is_publication_constant(self):
        ds = build_arvor_rtraj_nc_dataset(
            build_arvor_rtraj_dataset(_science(6990711), wmo=6990711), data_centre="IN"
        )
        value = "".join(ds["DATA_STATE_INDICATOR"].values.astype(str))
        assert value == "2B  "

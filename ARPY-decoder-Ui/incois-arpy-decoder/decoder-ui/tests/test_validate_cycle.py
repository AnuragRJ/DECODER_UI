"""Regression tests for the Stage-0 vs Stage-1 evaluation harness.

`prediction/validate_cycle.py` produced every number in
`prediction-validation/STAGE1_REPORT.md`, so its protocol is itself a deliverable:
the label rule, the paired served series, the fallback accounting, the ship-gate
arithmetic and the artefact schema all need to be pinned. This module builds a
**synthetic trajectory corpus** (real `_Rtraj.nc` files in a tmp dir, written with
netCDF4) whose sampling is deliberately irregular, so the harness's behaviour on
bursts and multi-cycle gaps is checked without the 30-float Ifremer corpus and
without network access.

What is asserted:
  * the target label obeys the deployed rule (later cycle AND ΔJULD >= 0.5 x interval,
    within 2 x interval), and cases with no such observation are counted, not scored;
  * both stages are scored on identical cases, paired one-for-one;
  * Stage-1 inherits the Stage-0 branch when it has no cycle-scale window;
  * a multi-cycle gap is normalised by whole cycles, and the case says so;
  * appending a *future* fix cannot change any prediction that was already scoreable
    (harness-level leakage proof);
  * the written artefact is a Stage-1 artefact: its own four methods, its own
    ship-gate block, default mode `off`, and no Stage-0 method or radius inside it.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import netCDF4
import numpy as np
import pytest

_TMP = tempfile.mkdtemp(prefix="decoder-ui-validate-cycle-test-")
os.environ["ARGO_UI_DATA_DIR"] = _TMP

from prediction import validate_cycle as vc  # noqa: E402
from prediction.calibrate import STAGE1_METHODS  # noqa: E402

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
EPOCH = datetime(1950, 1, 1, tzinfo=UTC)
#: Arabian Sea: a real region box, so the harness's region lookup is exercised.
LAT0, LON0 = 14.0, 65.0

#: Sampling patterns the harness must handle. Each entry is a list of "days ago"
#: (smaller = more recent). The numbers are chosen so the corpus exercises all three
#: sampling classes the audit found in the real fleet, with the harness's interval
#: rule in mind (median of hops in [0.5, 60] d, 10 d default below three samples):
#:
#:  * 2900010 — regular decadal sampling; every newest hop is ~1.0 x the interval.
#:  * 2900011 — a burst cluster (0.7 d hops) sitting 30.7 d after the previous fix,
#:    followed by a normal fix 8.6 d later. The 30.7 d hop exceeds
#:    MAX_TRANSITION_DAYS and is not a transition, so the interval stays 10 d, the
#:    newest eligible hop is 0.7 d (sub-cycle), and from that fix the only spans are
#:    0.7 d (below the band) and 30.7 d (above the 3-cycle cap) — i.e. Stage 1 has
#:    no admissible window and must inherit the Stage-0 branch.
#:  * 2900012 — a 30 d silence after six regular hops: the newest hop is 3.0 x the
#:    interval and must be normalised by whole cycles, not used as one cycle.
PATTERNS: dict[int, list[float]] = {
    2900010: [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0],
    2900011: [70, 60, 50, 40, 9.3, 8.6, 0],
    2900012: [100, 90, 80, 70, 60, 50, 40, 10, 0],
}


def juld(days_ago: float) -> float:
    return ((NOW - timedelta(days=days_ago)) - EPOCH).total_seconds() / 86400.0


def write_traj(path: Path, days_ago: list[float], *, drift_deg_per_day: float = 0.05) -> None:
    """A minimal but variable-complete `_Rtraj.nc`, as `load_fixes` reads it."""
    ds = netCDF4.Dataset(path, "w", format="NETCDF4")
    try:
        n = len(days_ago)
        ds.createDimension("N_MEASUREMENT", n)
        cyc = ds.createVariable("CYCLE_NUMBER", "i4", ("N_MEASUREMENT",))
        when = ds.createVariable("JULD", "f8", ("N_MEASUREMENT",))
        lat = ds.createVariable("LATITUDE", "f8", ("N_MEASUREMENT",))
        lon = ds.createVariable("LONGITUDE", "f8", ("N_MEASUREMENT",))
        qc = ds.createVariable("POSITION_QC", "S1", ("N_MEASUREMENT",))
        mc = ds.createVariable("MEASUREMENT_CODE", "f8", ("N_MEASUREMENT",))
        # cycle numbers must increase with time, as they do in the real files
        for i, ago in enumerate(sorted(days_ago, reverse=True)):
            cyc[i] = i + 1
            when[i] = juld(ago)
            # a slow, unidirectional drift keeps every step physically plausible
            travel = (max(days_ago) - ago) * drift_deg_per_day
            lat[i] = LAT0 + travel * 0.5
            lon[i] = LON0 + travel
            qc[i] = np.array(b"1", dtype="S1")
            mc[i] = 703.0
    finally:
        ds.close()


def build_corpus(directory: Path, patterns: dict[int, list[float]] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for wmo, days_ago in (patterns or PATTERNS).items():
        write_traj(directory / f"{wmo}_Rtraj.nc", days_ago)
    return directory


def index(cases: list[dict]) -> dict[tuple, dict]:
    return {(c["wmo"], round(c["cycle"], 6), round(c["target_juld"], 6)): c for c in cases}


def served(meta: dict, stage: str) -> list[dict]:
    """The paired per-case series (`score()` keeps them in meta, `main()` folds them in)."""
    return meta["served"][stage]


# --------------------------------------------------------------------- protocol
def test_the_synthetic_corpus_exercises_all_three_sampling_classes():
    corpus = build_corpus(Path(_TMP) / "corpus-classes")
    cases, meta = vc.score({}, corpus)
    classes = meta["availability"]["hop_class_counts"]
    assert classes.get("cycle_scale", 0) > 0, classes
    assert classes.get("sub_cycle", 0) > 0, classes
    assert classes.get("multi_cycle", 0) > 0, classes


def test_label_rule_is_the_deployed_one():
    """Every scored case must have a real observation near the target time."""
    corpus = build_corpus(Path(_TMP) / "corpus-label")
    cases, meta = vc.score({}, corpus)
    scored = served(meta, "stage0")
    assert scored, "no cases were scored"
    for case in scored:
        interval = case["interval_days"]
        assert case["label_ratio"] >= vc.LABEL_MIN_RATIO - 1e-9
        assert case["label_ratio"] <= vc.LABEL_MAX_RATIO + 1e-9
        # the label is a real, strictly later observation at least half a cycle out
        assert case["target_juld"] > 0 and case["hop_days"] is not None
        assert case["label_ratio"] * interval >= vc.LABEL_MIN_RATIO * interval - 1e-9
        assert case["interval_days"] > 0
    # candidates that had no admissible observation are counted as unscoreable
    assert meta["availability"]["unscoreable"] > 0
    assert (
        meta["availability"]["candidates"]
        == meta["availability"]["cases"] + meta["availability"]["unscoreable"]
    )


def test_both_stages_are_scored_on_identical_paired_cases():
    corpus = build_corpus(Path(_TMP) / "corpus-paired")
    cases, meta = vc.score({}, corpus)
    stage0 = index(served(meta, "stage0"))
    stage1 = index(served(meta, "stage1"))
    assert stage0 and stage0.keys() == stage1.keys()  # same cases, paired one-for-one
    assert len(served(meta, "stage0")) == len(served(meta, "stage1"))
    assert len(served(meta, "stage1_scoped")) == len(served(meta, "stage0"))


def test_stage1_inherits_the_stage0_branch_when_it_has_no_window():
    """The burst-only window must fall back, not be stretched into a cycle."""
    corpus = build_corpus(Path(_TMP) / "corpus-fallback")
    cases, meta = vc.score({}, corpus)
    stage0 = index(served(meta, "stage0"))
    stage1 = index(served(meta, "stage1"))

    burst = [c for c in served(meta, "stage0") if c["hop_class"] == "sub_cycle"]
    assert burst, "the fixture produced no sub-cycle case"
    for case in burst:
        twin = stage1[(case["wmo"], round(case["cycle"], 6), round(case["target_juld"], 6))]
        assert twin["inherited_stage0"] is True, "Stage 1 served a case it had no window for"
        assert twin["route"] == case["route"]
        assert twin["error_km"] == pytest.approx(case["error_km"])  # identical position
    assert meta["availability"]["unavailable_by_float"].get("2900011", 0) >= 1
    reasons = " ".join(meta["availability"]["unavailable_reasons"])
    assert "no window within" in reasons
    # and the sub-cycle hop really is what Stage-0 applied: 0.7 d of drift, not a cycle
    assert all(c["hop_days"] is not None and c["hop_days"] < 1.0 for c in burst)


def test_multi_cycle_gap_is_normalised_and_reported_per_case():
    corpus = build_corpus(Path(_TMP) / "corpus-gap")
    cases, meta = vc.score({}, corpus)
    multi = [c for c in served(meta, "stage0") if c["hop_class"] == "multi_cycle"]
    assert multi, "the fixture produced no multi-cycle case"
    for case in multi:
        assert case["hop_days"] is not None and case["hop_days"] > 1.5 * case["interval_days"]
    gapped = [
        c for c in cases[vc.METHOD_CYCLE_WINDOW]
        if c.get("step_cycles", 1) > 1 and c["hop_class"] == "multi_cycle"
    ]
    assert gapped, "no case normalised a multi-cycle gap"
    for case in gapped:
        assert case["gap_normalised"] is True
        assert 2 <= case["step_cycles"] <= 3
        assert case["step_cycles"] == round(case["hop_days"] / case["interval_days"])


# -------------------------------------------------------------------- leakage
def test_appending_a_future_fix_cannot_change_already_scoreable_predictions():
    """The harness must never let a later fix influence an earlier prediction."""
    base_dir = build_corpus(Path(_TMP) / "corpus-leak-a")
    base_cases, base_meta = vc.score({}, base_dir)

    extended = dict(PATTERNS)
    extended[2900010] = PATTERNS[2900010] + [-10.0]  # ten days *after* every other fix
    extended_dir = build_corpus(Path(_TMP) / "corpus-leak-b", extended)
    extended_cases, extended_meta = vc.score({}, extended_dir)

    for stage in ("stage0", "stage1"):
        before = index(served(base_meta, stage))
        after = index(served(extended_meta, stage))
        shared = set(before) & set(after)
        assert shared, "the two runs share no cases"
        for key in shared:
            assert before[key]["error_km"] == pytest.approx(after[key]["error_km"])
            assert before[key]["hop_class"] == after[key]["hop_class"]


def test_scoring_is_deterministic():
    corpus = build_corpus(Path(_TMP) / "corpus-repeat")
    first, first_meta = vc.score({}, corpus)
    second, second_meta = vc.score({}, corpus)
    for stage in ("stage0", "stage1", "stage1_scoped"):
        assert json.dumps(served(first_meta, stage), sort_keys=True) == \
            json.dumps(served(second_meta, stage), sort_keys=True)


# ------------------------------------------------------------------- artefact
def test_written_artefact_is_stage1_only_and_records_the_gate(tmp_path):
    corpus = build_corpus(tmp_path / "corpus-artefact")
    out = tmp_path / "prediction_calibration_stage1.json"
    report = tmp_path / "comparison.csv"
    full = tmp_path / "comparison.json"
    assert vc.main([
        "--corpus", str(corpus),
        "--out", str(out),
        "--report", str(report),
        "--json", str(full),
    ]) == 0

    artefact = json.loads(out.read_text())
    assert artefact["stage"] == vc.STAGE_STAGE1
    assert set(artefact["methods"]) == set(STAGE1_METHODS)
    assert not set(artefact["methods"]) & {"history_prior", "persistence", "regional_prior",
                                          "trajectory_extrapolation"}
    for method, blob in artefact["methods"].items():
        default = blob["default"]
        # shape, not magnitude: this corpus is a near-perfect drift, so its radii are
        # tiny by construction (the real 30-float artefact carries 18-37 km values)
        assert default["n"] > 0, f"{method} entered the artefact with no scored cases"
        assert default["r50_km"] >= 0 and default["r90_km"] >= default["r50_km"]
        assert default["metrics"]["n"] == default["n"]
        for key, metrics in blob["strata"].items():
            assert metrics["n"] > 0, f"{method}/{key} is an empty stratum"
    gate = artefact["ship_gate"]
    assert gate["default_mode"] == "off"
    assert isinstance(gate["passed"], bool)
    assert gate["criterion"]["median_improvement_pct_min"] == 5.0
    assert "no Stage-0 R50/R90 is reused" in artefact["baseline"]["note"]

    comparison = json.loads(full.read_text())
    assert comparison["criterion"]["passed"] == gate["passed"]
    assert comparison["as_served"]["paired_cases"] == comparison["cases"]
    assert comparison["as_served"]["stage0_as_served"]["n"] == comparison["cases"]
    assert comparison["as_served"]["stage1_as_served"]["n"] == comparison["cases"]
    assert report.read_text().splitlines()[0].startswith("method,region,cycle_class")

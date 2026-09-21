"""Integration tests: full raw-dataset decode for both ARVOR-I floats.

Runs the Phase-1 foundation (eml → sbd → packets) over the complete
read-only telemetry of the two supplied floats and asserts the properties
established during the read-only investigation:

* 6990711 — dead/end-of-mission float (fw 5.47 → decoder id 222 family,
  checksum 11415): 35 messages, 2025-03-04 → 2025-05-02, cycles 1-7, final
  burst transmitting cycle 7 first, then buffered cycles 5 and 6; no EOL
  flag anywhere; cycles 5/6 reuse cycle 4's GPS fix.
* 7902408 — active float (fw 5.54 → decoder id 232, checksum 13872):
  64 messages, factory tests 2025-09-19 (Hyderabad), launch 2026-03-25,
  cycles 0-15 at 10-day period; cycles 13-15 lack type-0/4 metadata
  sessions (missing e-mails — data-coverage limitation, not float
  misbehaviour); several cycles are missing measurement packets.

The operator CTD reference files (Ascctd/Desctd/Subctd) are decoded
physical values from a superset of the e-mail stream; where both exist
they must agree exactly with this decoder's output.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorIEngine,
    decode_arvor_i_sbd,
    find_identical_payloads,
    read_arvor_i_eml,
    resolve_engine,
)

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"

EXPECTED_HISTOGRAMS = {
    "6990711": {0: 7, 1: 4, 2: 13, 3: 49, 4: 7, 6: 15},
    "7902408": {0: 19, 1: 4, 2: 23, 3: 74, 4: 19, 5: 7, 6: 38},
}
EXPECTED_MESSAGES = {"6990711": 35, "7902408": 64}
EXPECTED_PADDING_ROWS = {"6990711": 10, "7902408": 8}
EXPECTED_MOMSN_GAPS = {
    "6990711": [(72, 74), (78, 80), (84, 86), (90, 92)],
    "7902408": [
        (32, 34),
        (34, 36),
        (36, 38),
        (38, 40),
        (40, 42),
        (42, 44),
        (44, 46),
        (51, 53),
        (54, 56),
        (57, 59),
        (62, 65),
        (69, 71),
        (72, 74),
        (75, 77),
        (77, 79),
        (80, 83),
        (83, 85),
        (87, 89),
        (91, 95),
        (99, 101),
        (104, 107),
        (109, 111),
        (111, 113),
        (117, 121),
        (121, 126),
        (127, 132),
        (132, 134),
    ],
}


def _load(flt: str):
    d = RAW_ROOT / flt
    msgs = [read_arvor_i_eml(p) for p in sorted(d.glob("*.eml"))]
    decoded = [decode_arvor_i_sbd(m.payload) for m in msgs]
    return msgs, decoded


def _packets(decoded):
    return [pk for dec in decoded for pk in dec.packets]


# ---------------------------------------------------------------------------
# Whole-dataset structural properties
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flt", ["6990711", "7902408"])
def test_message_counts_and_payload_preservation(flt: str) -> None:
    msgs, decoded = _load(flt)
    assert len(msgs) == EXPECTED_MESSAGES[flt]
    for m, dec in zip(msgs, decoded, strict=True):
        assert dec.payload == m.payload == m.source_path.with_suffix(".sbd").read_bytes()
        assert m.session.message_size_bytes == 300 == len(m.payload)


@pytest.mark.parametrize("flt", ["6990711", "7902408"])
def test_packet_histograms_and_padding(flt: str) -> None:
    _, decoded = _load(flt)
    hist = Counter(pk.pack_type for pk in _packets(decoded))
    assert dict(hist) == EXPECTED_HISTOGRAMS[flt]
    padding = sum(len(dec.padding_rows) for dec in decoded)
    assert padding == EXPECTED_PADDING_ROWS[flt]
    # no unsupported packet types occur in the real data
    assert all(pk.pack_type in (0, 1, 2, 3, 4, 5, 6) for pk in _packets(decoded))


@pytest.mark.parametrize("flt", ["6990711", "7902408"])
def test_engine_identification_consistent(flt: str) -> None:
    _, decoded = _load(flt)
    tech1 = [pk for pk in _packets(decoded) if pk.pack_type == 0]
    engines = {resolve_engine(pk.firmware_checksum)[0] for pk in tech1}
    assert engines == {
        ArvorIEngine.FAMILY_222_223_225 if flt == "6990711" else ArvorIEngine.ENGINE_232
    }
    checksums = {pk.firmware_checksum for pk in tech1}
    assert checksums == {11415 if flt == "6990711" else 13872}


@pytest.mark.parametrize("flt", ["6990711", "7902408"])
def test_no_duplicate_payloads_and_no_packet_loss(flt: str) -> None:
    """Byte-identical mail duplicates: none in this dataset (flag-only API);
    every non-padding row decodes to exactly one structured packet."""

    msgs, decoded = _load(flt)
    assert find_identical_payloads(msgs) == []
    for dec in decoded:
        assert len(dec.packets) + len(dec.padding_rows) == 3


def test_momsn_gaps_match_investigation() -> None:
    for flt, expected in EXPECTED_MOMSN_GAPS.items():
        msgs, _ = _load(flt)
        momsns = sorted(m.session.momsn for m in msgs)
        gaps = list(pairwise(momsns))
        gaps = [(a, b) for a, b in gaps if b - a > 1]
        assert gaps == expected


# ---------------------------------------------------------------------------
# Operator CTD reference parity (independent ground truth)
# ---------------------------------------------------------------------------


def _cycle_packets(flt: str, cycle: int, pack_type: int):
    _, decoded = _load(flt)
    return [pk for pk in _packets(decoded) if pk.pack_type == pack_type and pk.cycle == cycle]


def _operator_profile(flt: str, stem: str) -> list[tuple[float, float, float]]:
    lines = (RAW_ROOT / flt / "ctd" / f"{stem}.txt").read_text().splitlines()
    return [tuple(float(x) for x in ln.split()) for ln in lines if ln.strip()]  # type: ignore[misc]


@pytest.mark.parametrize(
    ("flt", "cycle", "pack_type", "stem"),
    [
        ("6990711", 1, 3, "Ascctd001"),
        ("6990711", 2, 3, "Ascctd002"),
        ("6990711", 3, 3, "Ascctd003"),
        ("6990711", 4, 3, "Ascctd004"),
        ("6990711", 5, 3, "Ascctd005"),
        ("6990711", 6, 3, "Ascctd006"),
        ("6990711", 7, 3, "Ascctd007"),
        ("6990711", 1, 2, "Subctd001"),
        ("6990711", 1, 1, "Desctd001"),
        ("7902408", 1, 3, "Ascctd001"),
    ],
)
def test_operator_ctd_parity(flt: str, cycle: int, pack_type: int, stem: str) -> None:
    """Every operator reference point appears in our decoded triplets."""

    pks = _cycle_packets(flt, cycle, pack_type)
    ours = set()
    for pk in pks:
        for p, t, s in zip(pk.pres(), pk.temp(), pk.psal(), strict=True):
            if p is not None:
                ours.add((round(p, 2), round(t, 3), round(s, 3)))
    ref = {(round(p, 2), round(t, 3), round(s, 3)) for p, t, s in _operator_profile(flt, stem)}
    assert ref, f"empty operator file {stem}"
    assert ref <= ours, (
        f"{flt} cycle {cycle} type {pack_type}: {len(ref - ours)} reference points "
        f"missing from decoded packets"
    )


def test_operator_psal_unsigned_convention() -> None:
    """Salinity counts are unsigned: the operator values match counts/1000
    without any sign flip even for high counts."""

    ref = _operator_profile("6990711", "Ascctd001")
    max_sal = max(sal for _, _, sal in ref)
    assert max_sal > 34.0  # sanity: counts would exceed 34000 (would look
    # negative if misread as two's complement)


# ---------------------------------------------------------------------------
# Active float (7902408) sequence properties
# ---------------------------------------------------------------------------


def test_active_float_cycle_coverage_and_period() -> None:
    msgs, decoded = _load("7902408")
    by_cycle_t0 = {}
    for m, dec in zip(msgs, decoded, strict=True):
        for pk in dec.packets:
            if pk.pack_type == 0:
                by_cycle_t0[pk.cycle] = m.session.session_time_utc
    assert sorted(by_cycle_t0) == list(range(0, 13))
    # 10-day cycle rhythm (cycle 1: 2026-03-27, cycle 12: 2026-07-12)
    assert by_cycle_t0[1] == datetime(2026, 3, 27, 5, 55, 5, tzinfo=UTC)
    assert by_cycle_t0[12] == datetime(2026, 7, 12, 23, 8, 53, tzinfo=UTC)
    surfacing_days = [by_cycle_t0[c] for c in range(1, 13)]
    gaps = [(b - a).days for a, b in pairwise(surfacing_days)]
    assert all(9 <= g <= 11 for g in gaps)


def test_active_float_incomplete_late_cycles() -> None:
    """Cycles 13-15 have measurement packets but no type-0/4/5 metadata
    (their first sessions' e-mails are missing) — documented data-coverage
    limitation; the packets we do have must all decode."""

    pks = _packets(_load("7902408")[1])
    for cycle, types in ((13, {2, 3}), (14, {2, 3, 6}), (15, {2, 3, 6})):
        got = {pk.pack_type for pk in pks if pk.cycle == cycle}
        assert got == types
        assert 0 not in got and 4 not in got and 5 not in got


def test_active_float_incomplete_measurement_cycles() -> None:
    """Expected (descent, drift, ascent) from Tech#2 vs received packets —
    the corrected mapping shows exactly which cycles lost e-mails."""

    _, decoded = _load("7902408")
    pks = _packets(decoded)
    received = {}
    expected = {}
    for pk in pks:
        if pk.pack_type in (1, 2, 3):
            key = (pk.cycle, pk.pack_type)
            received[key] = received.get(key, 0) + 1
        elif pk.pack_type == 4 and pk.cycle >= 1:
            expected[pk.cycle] = (pk.n_descent_packets, pk.n_drift_packets, pk.n_ascent_packets)
    complete, incomplete = set(), set()
    for cycle, (e1, e2, e3) in expected.items():
        r = (received.get((cycle, 1), 0), received.get((cycle, 2), 0), received.get((cycle, 3), 0))
        (complete if r == (e1, e2, e3) else incomplete).add(cycle)
    assert complete == {1, 4, 9, 12}  # PROVEN during investigation
    assert incomplete == {2, 3, 5, 6, 7, 8, 10, 11}


# ---------------------------------------------------------------------------
# Dead float (6990711) end-of-mission behaviour
# ---------------------------------------------------------------------------


def test_dead_float_no_eol_flag_anywhere() -> None:
    pks = _packets(_load("6990711")[1])
    tech1 = [pk for pk in pks if pk.pack_type == 0]
    assert len(tech1) == 7
    assert all(pk.eol_flag == 0 for pk in tech1)


def test_dead_float_final_burst_order() -> None:
    """Final surfacing 2025-05-01/02: cycle 7 transmitted first, then
    buffered cycles 5 and 6 (manual §6.1 stored-packet order)."""

    msgs, decoded = _load("6990711")
    order = []
    for m, dec in zip(msgs, decoded, strict=True):
        for pk in dec.packets:
            if pk.pack_type == 0 and pk.cycle in (5, 6, 7):
                order.append((m.session.session_time_utc, pk.cycle))
                break
    cycles_in_time_order = [c for _, c in sorted(order)]
    assert cycles_in_time_order == [7, 5, 6]
    t = [dt for dt, _ in sorted(order)]
    assert t[0].strftime("%Y-%m-%d") == "2025-05-01"
    assert t[2].strftime("%Y-%m-%d") in {"2025-05-01", "2025-05-02"}


def test_dead_float_all_cycles_complete() -> None:
    """All seven cycles of the dead float are complete under the corrected
    Tech#2 mapping (the retransmitted buffered cycles 5/6 delivered all
    their packets)."""

    _, decoded = _load("6990711")
    pks = _packets(decoded)
    received = {}
    expected = {}
    for pk in pks:
        if pk.pack_type in (1, 2, 3):
            key = (pk.cycle, pk.pack_type)
            received[key] = received.get(key, 0) + 1
        elif pk.pack_type == 4:
            expected[pk.cycle] = (pk.n_descent_packets, pk.n_drift_packets, pk.n_ascent_packets)
    for cycle in range(1, 8):
        e = expected[cycle]
        r = (received.get((cycle, 1), 0), received.get((cycle, 2), 0), received.get((cycle, 3), 0))
        assert r == e, f"cycle {cycle}: received {r} != expected {e}"


def test_content_retransmissions_preserved() -> None:
    """Distinct messages carrying identical *content* packets must never be
    de-duplicated (only byte-identical whole payloads may be flagged)."""

    _, decoded = _load("7902408")
    # count type-3 rows in cycle 9 (operator shows the ascent was sent twice)
    n_c9 = sum(1 for dec in decoded for pk in dec.packets if pk.pack_type == 3 and pk.cycle == 9)
    assert n_c9 == 7  # all 7 distinct packets present in our e-mail subset

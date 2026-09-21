"""Integration tests: cycle reconstruction over the full raw datasets (Phase 2).

Runs the Phase-2 reconstruction (packets -> sessions -> decoding buffers ->
completion classification -> ordered cycles) over the complete read-only
telemetry of both supplied floats and asserts the validation targets fixed
during the investigation:

* 6990711 (dead float, launch 2025-03-02 05:16 UTC): 7 logical cycles, ALL
  complete, no EOL flags.  Final burst on 2025-05-01/02 transmits cycle 7
  FIRST, then buffered cycles 5 and 6 (original ranks 5 < 6 < 7 for cycles
  7 < 5 < 6): the session's first cycle (7) goes through the main loop
  (delayed 0); cycles 5/6 are leftover (session, cycle) pairs handled by
  the remaining loop -> delayed = 1 ("ice delayed").  rankByCycle still
  emits buffers in cycle order 1..7.  The 10-minute merge rule keeps the
  three transmissions in ONE session (dead float, ~minutes apart, cycle
  changes between base packets).
* 7902408 (active float, launch 2026-03-25 17:44 UTC per investigation
  metadata): factory tests 2025-09-19 (MOMSN 32/34/36) are pre-launch and
  deleted (9 packets); the four deck-test sessions of launch day
  (2026-03-25, MOMSN 38-44, before 17:44) are ALSO pre-launch — all 21
  pre-launch packets go, keeping only the LAST type-5 (MOMSN 44, 12:08).
  Validation: complete cycles {1, 4, 9, 12}; incomplete {2, 3, 5, 6, 7, 8,
  10, 11} (1-5 measurement packets missing each, matching the MOMSN gaps =
  unreceived e-mails, a data-coverage limitation); cycles 13-15 have no
  Tech#1/Tech#2 (whole first sessions missing: MOMSN 118-125, 128-131);
  cycle 13 is force-emitted incomplete.  Since 2026-08-27 the reconstruction
  default matches Coriolis production (g_decArgo_processRemainingBuffers =
  1 in decode_provor_2_nc.m and decode_provor_2_nc_dm.m): trailing cycles
  14/15 are emitted with go = 2, completed = 0 and the local delayed value
  (0 — the delayed = 1 variant is the remaining-loop path); with the flag
  disabled they stay pending (go = 0) in unranked_packets.

Completion uses the corrected Tech#2 expected-count mapping (items 3/4/5 =
descent/drift/ascent — manual §6.3 + raw evidence); the Coriolis as-coded
reading (items 4/5/6) is exposed alongside and, as proven, never completes
a deep cycle for these floats.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from argo_decoder.platforms.provor_ir_sbd.arvor_i import read_arvor_i_eml
from argo_decoder.platforms.provor_ir_sbd.arvor_i_cycles import (
    reconstruct_cycles,
)

ARGO_PY_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ARGO_PY_ROOT.parent
RAW_ROOT = WORKSPACE / "arvor_raw" / "ARVOR-I-raw-files" / "20260819"

LAUNCH_6990711 = datetime(2025, 3, 2, 5, 16, tzinfo=UTC)
LAUNCH_7902408 = datetime(2026, 3, 25, 17, 44, tzinfo=UTC)


def _reconstruct(wmo: str, launch: datetime, **kw):
    msgs = [read_arvor_i_eml(p) for p in sorted((RAW_ROOT / wmo).glob("*.eml"))]
    return reconstruct_cycles(msgs, launch_date=launch, **kw)


class Test6990711:
    def test_seven_logical_cycles_all_complete(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        assert [b.cycle_number for b in res.buffers] == [1, 2, 3, 4, 5, 6, 7]
        assert all(b.completed for b in res.buffers)
        assert all(b.go == 1 for b in res.buffers)
        assert not res.dropped_packets
        assert not res.pre_launch_discarded
        assert not res.unranked_packets
        assert not res.resets

    def test_expected_vs_received_counts_per_cycle(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        by = {b.cycle_number: b for b in res.buffers}
        # cycle 1 is the descent cycle: (desc, drift, asc) = (4, 1, 7)
        assert by[1].expected_counts == (4, 1, 7)
        assert by[1].received_counts == (4, 1, 7)
        # cycles 2+ are drift-only profiles: (0, 2, 7)
        for c in range(2, 8):
            assert by[c].expected_counts == (0, 2, 7)
            assert by[c].received_counts == (0, 2, 7)
        assert all(b.deep for b in res.buffers)

    def test_final_burst_order_7_then_5_then_6(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        by = {b.cycle_number: b for b in res.buffers}
        # original ranks preserve transmission order: 7 first, then 5, 6
        assert by[7].rank < by[5].rank < by[6].rank
        # main loop took the session's first cycle (7); the leftover cycles
        # 5/6 come from the remaining loop -> delayed = 1 (ice delayed)
        assert by[7].delayed == 0
        assert by[5].delayed == 1 and by[5].ice_delayed
        assert by[6].delayed == 1 and by[6].ice_delayed

    def test_final_burst_is_one_merged_session(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        # 5 sessions: cycles 1-4 plus the merged final burst {7, 5, 6}
        assert len(res.sessions) == 5
        # the burst session contains packets of cycles 7, 5 and 6
        by = {b.cycle_number: b for b in res.buffers}
        burst_sessions = by[7].session_ids
        assert by[5].session_ids == burst_sessions
        assert by[6].session_ids == burst_sessions
        dates = [b.packets[0].date for b in (by[7], by[5], by[6])]
        assert all(d.year == 2025 and d.month == 5 and d.day in (1, 2) for d in dates)

    def test_no_eol_anywhere(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        for b in res.buffers:
            assert all(sp.eol_flag == 0 for sp in b.packets)

    def test_packet_conservation(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        total = res.stream_size
        assert total == 95  # Phase-1 histogram total
        accounted = (
            sum(len(b.packets) for b in res.buffers)
            + len(res.unranked_packets)
            + len(res.pre_launch_discarded)
            + len(res.kept_pre_launch_param_packets)
            + len(res.dropped_packets)
        )
        assert accounted == total

    def test_as_coded_completion_unreachable_for_deep_cycles(self):
        res = _reconstruct("6990711", LAUNCH_6990711)
        # Coriolis as-coded (items 4/5/6) would expect (1,7,0) for cycle 1
        # and (2,7,0) for cycles 2+: 0 descent packets received -> never
        # complete; the corrected mapping completes everything.
        for b in res.buffers:
            assert b.completed and not b.completed_coriolis_as_coded
        by = {b.cycle_number: b for b in res.buffers}
        assert by[2].expected_counts_coriolis_as_coded == (2, 7, 0)


class Test7902408:
    def test_completion_pattern(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        by = {b.cycle_number: b for b in res.buffers}
        complete = sorted(c for c, b in by.items() if b.completed)
        incomplete = sorted(c for c, b in by.items() if not b.completed and b.go == 1)
        assert complete == [1, 4, 9, 12]
        assert incomplete == [-1, 2, 3, 5, 6, 7, 8, 10, 11, 13]

    def test_pre_launch_handling(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        # factory tests 2025-09-19 (9 packets) + launch-day deck tests
        # (12 packets) all pre-launch; only the LAST type-5 is kept
        assert len(res.pre_launch_discarded) == 20
        assert len(res.kept_pre_launch_param_packets) == 1
        kept = res.kept_pre_launch_param_packets[0]
        assert kept.pack_type == 5
        assert kept.date == datetime(2026, 3, 25, 12, 8, 30, tzinfo=UTC)
        assert kept.message.session.momsn == 44
        # the kept param forms a forced-incomplete cycle -1 buffer
        by = {b.cycle_number: b for b in res.buffers}
        assert -1 in by
        assert [p.pack_type for p in by[-1].packets] == [5]
        assert by[-1].why_incomplete == [
            "Tech1 packet is missing",
            "Tech2 packet is missing",
        ]

    def test_incomplete_cycles_match_momsn_gaps(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        by = {b.cycle_number: b for b in res.buffers}
        # received counts pinned from the raw stream (MOMSN gap analysis)
        assert by[2].received_counts == (0, 1, 5)  # 1 drift + 2 asc missing
        assert by[3].received_counts == (0, 2, 5)  # 2 asc missing
        assert by[8].received_counts == (0, 2, 2)  # 5 asc missing (truncated)
        assert by[11].received_counts == (0, 2, 4)  # 3 asc missing
        for c in (2, 3, 5, 6, 7, 8, 10, 11):
            assert by[c].expected_counts == (0, 2, 7)
            assert not by[c].completed
        # why-strings carry the count deltas
        assert by[8].why_incomplete == ["5 ascending data packets are MISSING"]

    def test_cycles_13_15_metadata_less(self):
        # production default (process_remaining_buffers=True): 13 forced,
        # 14/15 emitted as trailing-buffer cycles (go=2, completed=0)
        res = _reconstruct("7902408", LAUNCH_7902408)
        by = {b.cycle_number: b for b in res.buffers}
        # cycle 13: force-emitted (two later deep sessions), no Tech packets
        assert 13 in by
        assert by[13].expected_counts is None
        assert by[13].why_incomplete == [
            "Tech1 packet is missing",
            "Tech2 packet is missing",
        ]
        assert by[13].go == 1 and not by[13].completed
        # cycles 14/15: trailing buffers, go=2 (Coriolis
        # create_decoding_buffers L278-296), never silently discarded
        assert 14 in by and 15 in by
        for c in (14, 15):
            assert by[c].go == 2
            assert not by[c].completed
            assert by[c].delayed == 0 and not by[c].ice_delayed
            assert by[c].expected_counts is None
        assert res.unranked_packets == []
        # legacy drop behaviour remains reachable via the explicit flag
        res_off = _reconstruct("7902408", LAUNCH_7902408, process_remaining_buffers=False)
        by_off = {b.cycle_number: b for b in res_off.buffers}
        assert 14 not in by_off and 15 not in by_off
        pending = sorted({sp.packet.cycle for sp in res_off.unranked_packets})
        assert pending == [14, 15]

    def test_pending_cycles_with_process_remaining_buffers(self):
        res = _reconstruct("7902408", LAUNCH_7902408, process_remaining_buffers=True)
        by = {b.cycle_number: b for b in res.buffers}
        assert 14 in by and 15 in by
        for c in (14, 15):
            assert by[c].go == 2 and not by[c].completed
            # main-loop processRemaining branch keeps the local delayed (0);
            # only the REMAINING loop's go=2 path sets delayed = 1
            assert by[c].delayed == 0 and not by[c].ice_delayed
            assert by[c].expected_counts is None

    def test_sessions_and_split_reasons(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        # 16 sessions: kept param + cycles 1-12 + 3 half-day splits (13-15)
        assert len(res.sessions) == 3 + 13
        split = [s for s in res.sessions if s.created_by == "0.5-day-split"]
        assert len(split) == 3

    def test_packet_conservation(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        total = res.stream_size
        assert total == 184  # Phase-1 histogram total
        accounted = (
            sum(len(b.packets) for b in res.buffers)
            + len(res.unranked_packets)
            + len(res.pre_launch_discarded)
            + len(res.dropped_packets)
        )
        # kept pre-launch params live inside buffers (not double-counted)
        assert accounted == total

    def test_transport_metadata_preserved(self):
        res = _reconstruct("7902408", LAUNCH_7902408)
        for b in res.buffers:
            for sp in b.packets:
                # provenance kept: message, MOMSN, row index, session time
                assert sp.message is not None
                assert sp.momsn >= 32
                assert 0 <= sp.row_index <= 2
                assert sp.date.tzinfo is not None

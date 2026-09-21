"""Unit tests: ARVOR-I cycle reconstruction rules (Phase 2).

Each test pins ONE rule of the Coriolis buffer algorithm
(create_decoding_buffers_222_223_225_232.m, vendored under
tests/data/arvor_i/coriolis_src/) against the Python port
``arvor_i_cycles``.  Synthetic packets drive the algorithm directly;
raw-dataset behaviour is covered by the integration tests.

Pinned source facts (line numbers refer to the vendored .m):

* NB_SESSION_MAX = 3 — incomplete buffer emitted when
  ``max(tabSessionDeep) - min(session_deep of buffer) >= 2``.
* Pre-launch rule (lines 50-64): post-launch type-5/7 with cyNum==0
  exists -> delete ALL cyNum==-1; otherwise keep the LAST type-5 and
  LAST type-7 among them.
* Session rules: new session at 0/4/5 with higher cycle AND later date,
  or type-0 same cycle later date; > 0.5-day gap splits; a base packet
  < 10 min after the previous packet with a DIFFERENT cycle merges back;
  EOL-flagged packet splits.
* check_buffer: exactly one Tech#1 and one Tech#2 required (Prog waived
  for 222/223/225/232), all-zero expected counts -> surface completion,
  otherwise received >= expected for desc/drift/asc; why-strings match
  the MATLAB diagnostics verbatim.
* Expected counts: corrected mapping = items 3/4/5 (manual §6.3 + raw);
  Coriolis as-coded = items 4/5/6 (off-by-one, unreachable-complete for
  the evidence floats).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from argo_decoder.platforms.provor_ir_sbd.arvor_i_cycles import (
    StreamPacket,
    check_buffer,
    reconstruct_stream,
)


@dataclass
class FakePacket:
    """Minimal duck-typed packet for driving the algorithm."""

    pack_type: int
    cycle: int | None
    iridium_session: int | None = None
    eol_flag: int | None = None
    last_reset: datetime | None = None
    fields: dict = field(default_factory=dict)
    n_descent_packets: int | None = None
    n_drift_packets: int | None = None
    n_ascent_packets: int | None = None


class DummyMessage:
    """Stand-in message; only provenance accessors are used."""

    class _S:
        momsn = 0

    session = _S()
    payload = b""


def sp(pack_type, cycle, when, *, eol=None, irsess=None, reset=None, t2=None, pre=False):
    """Build a StreamPacket; ``t2`` = (fields3..7) for type 4."""
    fields = {}
    nd = ndr = na = None
    if t2 is not None:
        f3, f4, f5, f6, f7 = t2
        fields = {3: f3, 4: f4, 5: f5, 6: f6, 7: f7}
        nd, ndr, na = f3, f4, f5  # corrected mapping: items 3/4/5
    pk = FakePacket(
        pack_type=pack_type,
        cycle=cycle,
        iridium_session=irsess,
        eol_flag=eol,
        last_reset=reset,
        fields=fields,
        n_descent_packets=nd,
        n_drift_packets=ndr,
        n_ascent_packets=na,
    )
    return StreamPacket(packet=pk, message=DummyMessage(), row_index=0, date=when, pre_launch=pre)


def d(day, hh=0, mm=0):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return base + timedelta(days=day - 1, hours=hh, minutes=mm)


def t1(cycle, when, **kw):
    return sp(0, cycle, when, **kw)


def t2(cycle, when, exp=(0, 0, 0, 0, 0), **kw):
    return sp(4, cycle, when, t2=exp, **kw)


def meas(ptype, cycle, when, **kw):
    return sp(ptype, cycle, when, **kw)


# ---------------------------------------------------------------------------
# check_buffer
# ---------------------------------------------------------------------------


class TestCheckBuffer:
    def _mk(self, ptypes, exp=(0, 0, 0, 0, 0)):
        return [
            sp(
                4 if t == "T2" else 0 if t == "T1" else int(t),
                1,
                d(1, i),
                t2=exp if t == "T2" else None,
            )
            for i, t in enumerate(ptypes)
        ]

    def test_surface_cycle_completes_with_zero_expected(self):
        stream = self._mk(["T1", "T2"], exp=(0, 0, 0, 0, 0))
        ok, deep, _ = check_buffer([0, 1], stream, as_coded=False, why_flag=False)
        assert ok and not deep

    def test_deep_cycle_completes_when_received_meets_expected(self):
        # expected desc 1, drift 1, asc 2 (corrected items 3/4/5)
        stream = self._mk(["T1", "T2", "1", "2", "3", "3"], exp=(1, 1, 2, 0, 0))
        ok, deep, _ = check_buffer(list(range(6)), stream, as_coded=False, why_flag=False)
        assert ok and deep

    def test_missing_packets_reported_verbatim(self):
        stream = self._mk(["T1", "T2", "3"], exp=(1, 1, 2, 0, 0))
        ok, deep, why = check_buffer([0, 1, 2], stream, as_coded=False, why_flag=True)
        assert not ok and deep
        assert why == [
            "1 descending data packets are MISSING",
            "1 drift data packets are MISSING",
            "1 ascending data packets are MISSING",
        ]

    def test_unexpected_packets_reported(self):
        stream = self._mk(["T1", "T2", "3", "3"], exp=(0, 0, 1, 0, 0))
        ok, _, why = check_buffer([0, 1, 2, 3], stream, as_coded=False, why_flag=True)
        assert ok  # extra packets still complete (received >= expected)
        # why strings are gated on ~completed in MATLAB (extras only print)
        assert why == []

    def test_unexpected_packets_reported_when_incomplete(self):
        # extra ascent received but drift missing -> NOT EXPECTED + MISSING
        stream = self._mk(["T1", "T2", "3", "3"], exp=(0, 1, 1, 0, 0))
        ok, _, why = check_buffer([0, 1, 2, 3], stream, as_coded=False, why_flag=True)
        assert not ok
        assert why == [
            "1 drift data packets are MISSING",
            "1 ascending data packets are NOT EXPECTED",
        ]

    def test_multiple_tech1_never_completes_and_why_stays_empty(self):
        stream = self._mk(["T1", "T1", "T2"], exp=(0, 0, 0, 0, 0))
        ok, _, why = check_buffer([0, 1, 2], stream, as_coded=False, why_flag=True)
        assert not ok and why == []  # MATLAB prints only (msgFlag); whyStr empty

    def test_tech2_missing_diagnosed(self):
        stream = self._mk(["T1", "3", "3"])
        ok, _, why = check_buffer([0, 1, 2], stream, as_coded=False, why_flag=True)
        assert not ok
        assert why == ["Tech2 packet is missing"]

    def test_tech1_missing_diagnosed_with_counts(self):
        stream = self._mk(["T2", "3"], exp=(0, 0, 2, 0, 0))
        ok, _, why = check_buffer([0, 1], stream, as_coded=False, why_flag=True)
        assert not ok
        assert why == ["Tech1 packet is missing", "1 ascending data packets are MISSING"]

    def test_corrected_vs_as_coded_mapping_diverge(self):
        # items 3/4/5 = (0,2,7) corrected; items 4/5/6 = (2,7,0) as-coded
        stream = self._mk(
            ["T1", "T2", "2", "2", "3", "3", "3", "3", "3", "3", "3"], exp=(0, 2, 7, 0, 0)
        )
        idx = list(range(11))
        ok_corr, _, _ = check_buffer(idx, stream, as_coded=False, why_flag=False)
        ok_code, _, why_code = check_buffer(idx, stream, as_coded=True, why_flag=True)
        assert ok_corr  # 2 drift + 7 ascent received
        assert not ok_code  # as-coded expects 2 desc + 7 drift, 0 asc
        assert why_code == [
            "2 descending data packets are MISSING",
            "5 drift data packets are MISSING",
            "7 ascending data packets are NOT EXPECTED",
        ]

    def test_prog_packet_waived_for_this_family(self):
        # type-5 in buffer must neither block completion nor be required
        stream = self._mk(["T1", "T2", "5"], exp=(0, 0, 0, 0, 0))
        ok, _, why = check_buffer([0, 1, 2], stream, as_coded=False, why_flag=True)
        assert ok and why == []


# ---------------------------------------------------------------------------
# pre-launch rule
# ---------------------------------------------------------------------------


class TestPreLaunchRule:
    def test_all_minus_one_deleted_when_post_launch_prog_exists(self):
        stream = [
            t1(0, d(1), pre=True),
            t2(0, d(1), pre=True),
            sp(5, 0, d(1), pre=True),
            t1(0, d(10)),
            t2(0, d(10), exp=(0, 0, 1, 0, 0)),
            sp(5, 0, d(10)),  # post-launch type-5, cycle 0
            meas(3, 0, d(10)),
        ]
        res = reconstruct_stream(stream)
        assert len(res.pre_launch_discarded) == 3
        assert res.kept_pre_launch_param_packets == []
        cycles = [b.cycle_number for b in res.buffers]
        assert 0 in cycles and -1 not in cycles

    def test_last_prog_kept_when_no_post_launch_prog(self):
        stream = [
            sp(5, 0, d(1, 0), pre=True),
            sp(5, 0, d(1, 1), pre=True),
            sp(5, 0, d(1, 2), pre=True),
            t1(1, d(5)),
            t2(1, d(5), exp=(0, 0, 1, 0, 0)),
            meas(3, 1, d(5)),
            t1(2, d(15)),
            t2(2, d(15), exp=(0, 0, 1, 0, 0)),
            meas(3, 2, d(15)),
        ]
        res = reconstruct_stream(stream)
        assert len(res.pre_launch_discarded) == 2  # first two type-5
        assert len(res.kept_pre_launch_param_packets) == 1  # the LAST one
        assert res.kept_pre_launch_param_packets[0].date == d(1, 2)
        # kept param is cycle -1; two later deep sessions force its emission
        assert res.buffers[0].cycle_number == -1
        assert [p.pack_type for p in res.buffers[0].packets] == [5]
        assert not res.buffers[0].completed and res.buffers[0].go == 1


# ---------------------------------------------------------------------------
# session segmentation
# ---------------------------------------------------------------------------


class TestSessions:
    def test_new_session_on_higher_cycle_base_packet(self):
        stream = [
            t1(1, d(1)),
            t2(1, d(1)),
            meas(3, 1, d(1)),
            t1(2, d(11)),
            t2(2, d(11)),
            meas(3, 2, d(11)),
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 2

    def test_type0_same_cycle_later_date_starts_session(self):
        stream = [
            t1(1, d(1)),
            t2(1, d(1)),
            t1(1, d(5)),  # same cycle, later date -> new session
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 2

    def test_type4_same_cycle_later_date_does_not_start_session(self):
        stream = [
            t1(1, d(1, 0)),
            t2(1, d(1, 0)),
            t2(1, d(1, 6)),  # 6 h later, inside the 0.5-day window
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 1

    def test_half_day_gap_splits_session(self):
        stream = [
            t1(1, d(1, 0)),
            t2(1, d(1, 0)),
            meas(3, 1, d(1, 0)),
            meas(3, 1, d(2, 12)),  # 1.5 days later, no new base
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 2
        assert res.sessions[1].created_by == "0.5-day-split"

    def test_ten_minute_merge_on_cycle_change(self):
        stream = [
            t1(1, d(1, 0, 0)),
            t2(1, d(1, 0, 0)),
            meas(3, 1, d(1, 0, 0)),
            # base packet 8 minutes later with a DIFFERENT cycle -> merge back
            t1(2, d(1, 0, 8)),
            t2(2, d(1, 0, 8)),
            meas(3, 2, d(1, 0, 8)),
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 1
        assert res.sessions[0].merged_into_previous is False
        # but both cycles are reconstructed as separate buffers
        assert sorted(b.cycle_number for b in res.buffers) == [1, 2]

    def test_ten_minute_no_merge_when_same_cycle(self):
        stream = [
            t1(1, d(1, 0, 0)),
            t2(1, d(1, 0, 0)),
            t1(1, d(1, 0, 8)),  # same cycle -> separate session retained
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 2

    def test_eol_flag_splits_session(self):
        # eol_flag is a Tech#1 field; equal dates isolate the EOL rule
        stream = [
            t1(1, d(1)),
            t2(1, d(1)),
            sp(0, 1, d(1), eol=1),  # EOL retransmission, same session time
            t2(1, d(1)),
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 2
        assert res.sessions[1].created_by == "eol-split"

    def test_consecutive_eol_packets_each_split(self):
        # as-coded: every EOL packet adjacent to its predecessor splits again
        stream = [
            t1(1, d(1)),
            t2(1, d(1)),
            sp(0, 1, d(1), eol=1),
            sp(0, 1, d(1), eol=1),
        ]
        res = reconstruct_stream(stream)
        assert len(res.sessions) == 3


# ---------------------------------------------------------------------------
# reset handling
# ---------------------------------------------------------------------------


class TestReset:
    def test_rising_reset_offsets_cycles_from_raw(self):
        reset_a = datetime(2026, 1, 1, tzinfo=UTC)
        reset_b = datetime(2026, 3, 1, tzinfo=UTC)
        stream = [
            t1(1, d(1), reset=reset_a),
            t2(1, d(1), reset=reset_a, exp=(0, 0, 1, 0, 0)),
            meas(3, 1, d(1), reset=reset_a),
            t1(2, d(11), reset=reset_a),
            t2(2, d(11), reset=reset_a, exp=(0, 0, 1, 0, 0)),
            meas(3, 2, d(11), reset=reset_a),
            # mission reset: cycle numbering restarts at 1 after 2026-03-01
            t1(1, datetime(2026, 3, 5, tzinfo=UTC), reset=reset_b),
            t2(1, datetime(2026, 3, 5, tzinfo=UTC), reset=reset_b, exp=(0, 0, 1, 0, 0)),
            meas(3, 1, datetime(2026, 3, 5, tzinfo=UTC), reset=reset_b),
        ]
        res = reconstruct_stream(stream)
        assert len(res.resets) == 1
        assert res.resets[0].cycle_offset == 3  # max prior cycle (2) + 1
        # post-reset raw cycle 1 becomes effective cycle 4
        assert sorted(b.cycle_number for b in res.buffers) == [1, 2, 4]

    def test_constant_reset_date_is_noop(self):
        reset_a = datetime(2026, 1, 1, tzinfo=UTC)
        stream = [
            t1(1, d(1), reset=reset_a),
            t2(1, d(1), reset=reset_a, exp=(0, 0, 1, 0, 0)),
            meas(3, 1, d(1)),
            t1(2, d(11), reset=reset_a),
            t2(2, d(11), reset=reset_a, exp=(0, 0, 1, 0, 0)),
            meas(3, 2, d(11)),
        ]
        res = reconstruct_stream(stream)
        assert res.resets == []
        assert sorted(b.cycle_number for b in res.buffers) == [1, 2]


# ---------------------------------------------------------------------------
# emission logic (main loop / remaining loop / forcing / go codes)
# ---------------------------------------------------------------------------


def complete_cycle(cycle, day, n_asc=1):
    return [
        t1(cycle, d(day)),
        t2(cycle, d(day), exp=(0, 0, n_asc, 0, 0)),
    ] + [meas(3, cycle, d(day)) for _ in range(n_asc)]


class TestEmission:
    def test_completed_buffer_go1_delayed0(self):
        res = reconstruct_stream(complete_cycle(1, 1))
        assert len(res.buffers) == 1
        b = res.buffers[0]
        assert b.completed and b.go == 1 and b.delayed == 0 and not b.ice_delayed
        assert b.why_incomplete == []

    def test_incomplete_pending_stays_unranked_go0(self):
        # missing ascent packets, nothing after -> pending
        stream = [t1(1, d(1)), t2(1, d(1), exp=(0, 0, 3, 0, 0)), meas(3, 1, d(1))]
        res = reconstruct_stream(stream, process_remaining_buffers=False)
        assert res.buffers == []
        assert len(res.unranked_packets) == 3
        # production default since 2026-08-27 (Coriolis
        # g_decArgo_processRemainingBuffers = 1): the buffer is emitted
        # with go=2; the MAIN loop keeps the local delayed value (0 here)
        res2 = reconstruct_stream(stream)
        assert len(res2.buffers) == 1
        assert res2.buffers[0].go == 2 and not res2.buffers[0].completed
        assert res2.buffers[0].delayed == 0

    def test_pending_leftover_cycle_go2_delayed1(self):
        # remaining-loop go=2 path sets delayed = 1 (ice delayed)
        stream = [*complete_cycle(1, 1), meas(3, 2, d(1))]  # leftover cycle 2
        res = reconstruct_stream(stream, process_remaining_buffers=True)
        by = {b.cycle_number: b for b in res.buffers}
        assert by[1].go == 1 and by[1].delayed == 0
        assert by[2].go == 2 and by[2].delayed == 1 and by[2].ice_delayed

    def test_forced_emission_after_two_later_deep_sessions(self):
        # NB_SESSION_MAX = 3: two or more later deep sessions force emission
        stream = [
            *[t1(1, d(1)), t2(1, d(1), exp=(0, 0, 3, 0, 0)), meas(3, 1, d(1))],  # incomplete
            *complete_cycle(2, 11),
            *complete_cycle(3, 21),
            *complete_cycle(4, 31),
        ]
        res = reconstruct_stream(stream)
        assert [b.cycle_number for b in res.buffers] == [1, 2, 3, 4]
        assert res.buffers[0].completed is False and res.buffers[0].go == 1

    def test_one_later_session_does_not_force(self):
        stream = [
            *[t1(1, d(1)), t2(1, d(1), exp=(0, 0, 3, 0, 0)), meas(3, 1, d(1))],
            *complete_cycle(2, 11),
        ]
        res = reconstruct_stream(stream, process_remaining_buffers=False)
        assert [b.cycle_number for b in res.buffers] == [2]
        assert len(res.unranked_packets) == 3  # cycle 1 still pending

    def test_delayed_append_from_later_session(self):
        # cycle-1 ascent packet transmitted one session later
        stream = [
            t1(1, d(1, 0)),
            t2(1, d(1, 0), exp=(0, 0, 2, 0, 0)),
            meas(3, 1, d(1, 0)),
            meas(3, 1, d(2, 12)),  # next session (0.5-day split), same cycle
        ]
        res = reconstruct_stream(stream, process_remaining_buffers=False)
        assert len(res.buffers) == 1
        b = res.buffers[0]
        assert b.completed and b.delayed == 2 and not b.ice_delayed
        assert len(b.packets) == 4 and sorted(b.session_ids) == [1, 2]

    def test_delayed_append_cut_at_next_base_packet(self):
        stream = [
            t1(1, d(1, 0)),
            t2(1, d(1, 0), exp=(0, 0, 2, 0, 0)),
            meas(3, 1, d(1, 0)),
            meas(3, 1, d(2, 12)),
            # later-session same-cycle run stops at the next base packet:
            t1(2, d(3, 12)),
            t2(2, d(3, 12), exp=(0, 0, 1, 0, 0)),
            meas(3, 2, d(3, 12)),
        ]
        res = reconstruct_stream(stream, process_remaining_buffers=False)
        b1 = next(b for b in res.buffers if b.cycle_number == 1)
        b2 = next(b for b in res.buffers if b.cycle_number == 2)
        # the stray cycle-1 packet belongs to buffer 1 (appended), buffer 2 intact
        assert len(b1.packets) == 4 and b1.delayed == 2
        assert len(b2.packets) == 3 and b2.delayed == 0

    def test_remaining_loop_leftover_cycle_is_ice_delayed(self):
        # merged final burst: session transmits cycle 7 FIRST, then 5 and 6
        stream = (
            complete_cycle(4, 21)
            + complete_cycle(7, 41)
            + complete_cycle(5, 41, 0)
            + complete_cycle(6, 41, 0)
        )
        # cycles 5/6 retransmitted with their own Tech packets minutes after
        # cycle 7 within the same session (the 10-minute rule merges them)
        stream = (
            complete_cycle(4, 21)
            + complete_cycle(7, 41)
            + complete_cycle(5, 41)
            + complete_cycle(6, 41)
        )
        res = reconstruct_stream(stream)
        by_cyc = {b.cycle_number: b for b in res.buffers}
        assert by_cyc[7].delayed == 0  # first cycle of its session
        # leftover (session, cycle) pairs -> delayed = 1 (ice delayed)
        assert by_cyc[5].delayed == 1 and by_cyc[5].ice_delayed
        assert by_cyc[6].delayed == 1 and by_cyc[6].ice_delayed
        # original ranks preserve transmission order 7 -> 5 -> 6
        assert by_cyc[7].rank < by_cyc[5].rank < by_cyc[6].rank
        # rankByCycle orders buffers by cycle number
        assert [b.cycle_number for b in res.buffers] == [4, 5, 6, 7]


# ---------------------------------------------------------------------------
# EOL rules
# ---------------------------------------------------------------------------


class TestEolRules:
    def test_eol_retransmission_of_completed_cycle_drops_measurements(self):
        stream = complete_cycle(1, 1)  # completed cycle 1
        # EOL retransmission of the same cycle in a later session
        stream += [
            sp(0, 1, d(9), eol=1),  # eol flag carried by Tech#1
            t2(1, d(9), exp=(0, 0, 1, 0, 0)),
            meas(3, 1, d(9)),
        ]
        res = reconstruct_stream(stream)
        b1 = next(b for b in res.buffers if b.cycle_number == 1)
        # measurements from the EOL retransmission are dropped (kept with reason)
        assert len(res.dropped_packets) == 1
        dropped, reason = res.dropped_packets[0]
        # the dropped packet is the EOL retransmission's measurement
        assert dropped.pack_type == 3 and "EOL retransmission" in reason
        assert dropped not in b1.packets
        # the EOL session itself still forms a buffer (Tech1/Tech2 only)
        eol_bufs = [b for b in res.buffers if any(p.eol_flag for p in b.packets)]
        assert len(eol_bufs) == 1 and len(eol_bufs[0].packets) == 2

    def test_duplicated_eol_parameter_packets_keep_last(self):
        stream = complete_cycle(1, 1)
        stream += [
            sp(0, 1, d(9), eol=1),  # only Tech#1 carries the EOL flag
            sp(4, 1, d(9), t2=(0, 0, 1, 0, 0)),
            meas(3, 1, d(9)),
            sp(5, 1, d(9, 0, 1)),
            sp(5, 1, d(9, 0, 2)),  # duplicate: keep the last
        ]
        # two later deep sessions force the (multiple-Prog) EOL buffer out
        stream += complete_cycle(2, 19) + complete_cycle(3, 29)
        res = reconstruct_stream(stream)
        eol_bufs = [b for b in res.buffers if any(p.eol_flag for p in b.packets)]
        kept5 = [p for b in eol_bufs for p in b.packets if p.pack_type == 5]
        assert len(eol_bufs) == 1
        assert len(kept5) == 1 and kept5[0].date == d(9, 0, 2)
        assert any("duplicated EOL parameter" in r for _, r in res.dropped_packets)

    def test_second_iridium_session_splits_buffer(self):
        # Tech#1/2 with iridium_session=1 arriving AFTER the 1st-session
        # buffer marks the first part deep and splits the buffer
        # a second transmission attempt inside the SAME session (equal
        # session timestamp, so no session split) carries iridium_session=1;
        # the buffer mixes both attempts -> the split rule separates them
        stream = [
            t1(1, d(1, 0), irsess=0),
            t2(1, d(1, 0), exp=(0, 0, 1, 0, 0), irsess=0),
            meas(3, 1, d(1, 0)),
            t1(1, d(1, 0), irsess=1),
            t2(1, d(1, 0), exp=(0, 0, 1, 0, 0), irsess=1),
            meas(3, 1, d(1, 0)),
        ]
        # two Tech#1/Tech#2 -> multiple-packet case -> incomplete; force it
        stream += complete_cycle(2, 11) + complete_cycle(3, 21)
        res = reconstruct_stream(stream)
        cyc1 = [b for b in res.buffers if b.cycle_number == 1]
        assert len(cyc1) == 2
        assert all(b.go == 1 for b in cyc1)
        # the first-session part is flagged deep by the split rule
        first = min(cyc1, key=lambda b: b.buffer_id)
        assert first.deep
        assert {p.ir_session for p in first.packets} == {0}
        second = max(cyc1, key=lambda b: b.buffer_id)
        assert {p.ir_session for p in second.packets} == {1}


# ---------------------------------------------------------------------------
# ordering + conservation
# ---------------------------------------------------------------------------


class TestOrderingAndConservation:
    def test_rank_by_cycle_orders_buffers_by_cycle(self):
        stream = complete_cycle(3, 21) + complete_cycle(1, 41) + complete_cycle(2, 41, 0)
        stream += [meas(3, 2, d(41))]
        res = reconstruct_stream(stream)
        assert [b.cycle_number for b in res.buffers] == [1, 2, 3]

    def test_no_packet_silently_discarded(self):
        stream = [
            t1(0, d(1), pre=True),
            t2(0, d(1), pre=True),
            sp(5, 0, d(1), pre=True),
            t1(1, d(5)),
            t2(1, d(5), exp=(0, 0, 3, 0, 0)),
            meas(3, 1, d(5)),
            complete_cycle(2, 15)[0],
        ]
        res = reconstruct_stream(stream)
        total = res.stream_size
        accounted = (
            sum(len(b.packets) for b in res.buffers)
            + len(res.unranked_packets)
            + len(res.pre_launch_discarded)
            + len(res.dropped_packets)
        )
        # kept pre-launch params are inside buffers/unranked (not double-counted)
        assert accounted == total

"""ARVOR-I cycle reconstruction — port of Coriolis buffer semantics (Phase 2).

Faithful behavioural port of ``create_decoding_buffers_222_223_225_232.m``
(Coriolis data-processing chain) over the Phase-1 structured packets:

    ordered packet stream -> session segmentation -> per-(session, cycle)
    decoding buffers -> completion / delayed / deep / GO classification ->
    ordered reconstructed cycles (rankByCycle)

Scope stops at classification.  No profile assembly, no NetCDF.

Two documented, deliberate divergences from the MATLAB (see the Phase-2
report for the full evidence):

* **Expected-count mapping** — the manual (33-16-033 Rev14 §6.3) and the raw
  telemetry prove Tech#2 items 3/4/5 = expected descent/drift/ascent packet
  counts; Coriolis reads items 4/5/6 (off-by-one).  The primary
  ``completed`` flag uses the corrected mapping;
  ``completed_coriolis_as_coded`` exposes the Coriolis reading for parity
  investigation.  (As-coded completion is unreachable for the ARVOR-I
  evidence datasets — every cycle would compare 0 received descent packets
  against the drift expectation.)
* **Nothing is silently discarded** — packets dropped by Coriolis (rank
  set to -1: EOL retransmission of completed cycles, duplicated EOL
  parameter packets) and pre-launch packets are retained in the result with
  reasons; callers decide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from argo_decoder.io.sbd_email import SbdSessionInfo
from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    ArvorIPacket,
    ArvorIridiumMessage,
    decode_arvor_i_sbd,
    read_arvor_i_eml,
)

_log = logging.getLogger(__name__)

# Maximum number of transmission sessions (after deep cycles) to look for
# expected data before emitting an incomplete buffer (MATLAB: NB_SESSION_MAX).
NB_SESSION_MAX = 3

# Session segmentation thresholds (MATLAB: ONE_DAY/2 and TEN_MINUTES).
HALF_DAY = 0.5  # days
TEN_MINUTES = 10.0 / 1440.0  # days

# Packet types carrying cycle-start ("base") semantics in this family.
BASE_PACKET_TYPES = frozenset({0, 4, 5})
# Measurement packet types that mark a session as "after a deep cycle"
# (MATLAB: [1 2 3 8 9 10 11 13]).
DEEP_PACKET_TYPES = frozenset({1, 2, 3, 8, 9, 10, 11, 13})
# Buffer completion counts packets of these unions per phase (MATLAB
# check_buffer idPackDesc/Drift/Asc).
DESC_TYPES = frozenset({1, 8})
DRIFT_TYPES = frozenset({2, 9})
ASC_TYPES = frozenset({3, 10})


# ---------------------------------------------------------------------------
# Ordered packet stream (with provenance)
# ---------------------------------------------------------------------------


@dataclass
class StreamPacket:
    """One decoded packet plus its transport provenance."""

    packet: ArvorIPacket
    message: ArvorIridiumMessage
    row_index: int  # 0-based position of the 100-byte row inside the payload
    date: datetime  # transport session time (mail date) — NOT float time
    pre_launch: bool = False

    @property
    def momsn(self) -> int:
        return self.message.session.momsn or 0

    @property
    def pack_type(self) -> int:
        return self.packet.pack_type

    @property
    def cycle_raw(self) -> int:
        """Effective cycle number (pre-launch override to -1 like MATLAB)."""

        if self.pre_launch:
            return -1
        # Unsupported/unknown packet types carry cyNumRaw = -1 in MATLAB.
        cyc = getattr(self.packet, "cycle", None)
        return -1 if cyc is None else cyc

    @property
    def ir_session(self) -> int:
        """1st/2nd Iridium session indicator (only Tech#1/Tech#2 carry it)."""

        ses = getattr(self.packet, "iridium_session", None)
        return 0 if ses is None else ses

    @property
    def eol_flag(self) -> int:
        eol = getattr(self.packet, "eol_flag", None)
        return 0 if eol is None else eol

    @property
    def reset_date(self) -> datetime | None:
        return getattr(self.packet, "last_reset", None)


def build_packet_stream(
    messages: list[ArvorIridiumMessage],
    launch_date: datetime | None = None,
) -> list[StreamPacket]:
    """Chronologically ordered packet stream (mail-date sort, like Coriolis).

    ``get_list_files_info_ir_sbd.m`` chronologically sorts the mail files
    before decoding; the equivalent ordering here is by transport session
    time, with MOMSN as tie-break (transmission order).
    """

    stream: list[StreamPacket] = []
    for msg in messages:
        if not msg.payload:
            continue
        for row_idx, pk in enumerate(decode_arvor_i_sbd(msg.payload).packets):
            date = msg.session.session_time_utc or datetime.min.replace(tzinfo=UTC)
            pre = bool(launch_date and date < launch_date)
            stream.append(
                StreamPacket(packet=pk, message=msg, row_index=row_idx, date=date, pre_launch=pre)
            )
    stream.sort(key=lambda sp: (sp.date, sp.momsn, sp.row_index))
    return stream


# ---------------------------------------------------------------------------
# Session / buffer records
# ---------------------------------------------------------------------------


@dataclass
class SessionRecord:
    """One transmission session as segmented by the Coriolis rules."""

    session_id: int
    packet_indices: list[int]
    created_by: str = "base-packet"  # base-packet | 0.5-day-split | eol-split
    merged_into_previous: bool = False  # 10-minute merge


@dataclass
class ResetEvent:
    """An on-sea reset detected from rising Tech#2 last-reset dates."""

    reset_date: datetime
    first_packet_index: int
    cycle_offset: int


@dataclass
class BufferResult:
    """One reconstructed decoding buffer (one rankByCycle entry)."""

    buffer_id: int  # rankByCycle number (1-based emission order)
    cycle_number: int  # effective (post-reset, pre-launch) cycle
    packets: list[StreamPacket] = field(default_factory=list)
    session_ids: list[int] = field(default_factory=list)
    rank: int = -1  # original within-cycle rank (pre-rankByCycle)
    delayed: int = 0  # 0 nominal | 1 leftover (session, cycle) | 2 later-session append
    ice_delayed: bool = False  # MATLAB tabIceDelayed == (delayed == 1)
    deep: bool = False
    go: int = 0  # 0 not emitted | 1 emitted | 2 emitted via processRemainingBuffers
    completed: bool = False  # corrected expected-count mapping
    completed_coriolis_as_coded: bool = False  # items 4/5/6 mapping (parity only)
    expected_counts: tuple[int, int, int] | None = None  # corrected (desc, drift, asc)
    expected_counts_coriolis_as_coded: tuple[int, int, int] | None = None
    received_counts: tuple[int, int, int] = (0, 0, 0)  # (desc, drift, asc)
    why_incomplete: list[str] = field(default_factory=list)
    why_incomplete_as_coded: list[str] = field(default_factory=list)


@dataclass
class CycleReconstructionResult:
    """Full Phase-2 output: ordered buffers plus provenance and discards."""

    buffers: list[BufferResult] = field(default_factory=list)  # rankByCycle order
    sessions: list[SessionRecord] = field(default_factory=list)
    resets: list[ResetEvent] = field(default_factory=list)
    pre_launch_discarded: list[StreamPacket] = field(default_factory=list)
    kept_pre_launch_param_packets: list[StreamPacket] = field(default_factory=list)
    dropped_packets: list[tuple[StreamPacket, str]] = field(default_factory=list)
    unranked_packets: list[StreamPacket] = field(default_factory=list)  # go == 0
    stream_size: int = 0


# ---------------------------------------------------------------------------
# check_buffer port
# ---------------------------------------------------------------------------


def _expected_counts(sp: StreamPacket, *, as_coded: bool) -> tuple[int, int, int]:
    """Expected (desc, drift, asc) packet counts from a Tech#2 packet.

    Corrected mapping (manual §6.3 + raw evidence): items 3/4/5.
    Coriolis as-coded mapping: items 4/5/6.
    """

    if sp.pack_type != 4:
        return (0, 0, 0)
    nd = getattr(sp.packet, "n_descent_packets", None)
    if nd is None:
        return (0, 0, 0)
    f = sp.packet.fields
    if as_coded:
        return (f[4], f[5], f[6])
    return (nd or 0, sp.packet.n_drift_packets or 0, sp.packet.n_ascent_packets or 0)


def check_buffer(
    indices: list[int],
    stream: list[StreamPacket],
    *,
    as_coded: bool,
    why_flag: bool,
) -> tuple[bool, bool, list[str]]:
    """Port of the local ``check_buffer`` subfunction.

    Returns ``(completed, deep, why)``.  For the 222/223/225/232 family the
    parameter packet (type 5) requirement is waived (MATLAB forces
    ``idPackProg = -1``); Tech#1 (type 0) and Tech#2 (type 4) are mandatory
    and must be unique.  A buffer whose expected counts are all zero is a
    surface cycle and completes without measurements; otherwise completion
    requires received >= expected for descent, drift and ascent phases.
    """

    completed = False
    deep = False
    why: list[str] = []

    n_tech1 = sum(1 for i in indices if stream[i].pack_type == 0)
    n_tech2 = sum(1 for i in indices if stream[i].pack_type == 4)
    n_prog = sum(1 for i in indices if stream[i].pack_type == 5)

    if n_tech1 > 1 or n_tech2 > 1 or n_prog > 1:
        # MATLAB only prints (msgFlag) here; whyStr stays empty.
        return completed, deep, why

    rec_desc = sum(1 for i in indices if stream[i].pack_type in DESC_TYPES)
    rec_drift = sum(1 for i in indices if stream[i].pack_type in DRIFT_TYPES)
    rec_asc = sum(1 for i in indices if stream[i].pack_type in ASC_TYPES)
    deep = bool(rec_desc or rec_drift or rec_asc)

    exp_desc = exp_drift = exp_asc = 0
    if n_tech2 == 1:
        t2 = next(stream[i] for i in indices if stream[i].pack_type == 4)
        exp_desc, exp_drift, exp_asc = _expected_counts(t2, as_coded=as_coded)
        if n_tech1 >= 1:
            if exp_desc == 0 and exp_drift == 0 and exp_asc == 0:
                completed = True  # surface cycle
            else:
                completed = rec_desc >= exp_desc and rec_drift >= exp_drift and rec_asc >= exp_asc
                deep = True

    if why_flag and not completed:
        if n_tech1 == 0:
            why.append("Tech1 packet is missing")
        if n_tech2 == 0:
            why.append("Tech2 packet is missing")
        if n_tech2 == 1:
            for label, rec, exp in (
                ("descending", rec_desc, exp_desc),
                ("drift", rec_drift, exp_drift),
                ("ascending", rec_asc, exp_asc),
            ):
                if rec != exp:
                    if exp > rec:
                        why.append(f"{exp - rec} {label} data packets are MISSING")
                    else:
                        why.append(f"{rec - exp} {label} data packets are NOT EXPECTED")

    return completed, deep, why


# ---------------------------------------------------------------------------
# Session segmentation (MATLAB "SET SESSION NUMBERS" + split/merge rules)
# ---------------------------------------------------------------------------


def _segment_sessions(stream: list[StreamPacket]) -> tuple[list[int], list[bool], list[str]]:
    """Returns (session ids, base flags, creation reasons) per packet."""

    n = len(stream)
    session = [-1] * n
    base = [False] * n
    reason = [""] * n

    start = next((i for i in range(n) if stream[i].pack_type in BASE_PACKET_TYPES), None)
    if start is None:
        return session, base, reason
    ses = 1

    def _is_new_session_candidate(i: int, start: int) -> bool:
        si = stream[start]
        ci = stream[i]
        new_cycle = (
            ci.pack_type in BASE_PACKET_TYPES and ci.cycle_raw > si.cycle_raw and ci.date > si.date
        )
        same_cycle_t0 = ci.pack_type == 0 and ci.cycle_raw == si.cycle_raw and ci.date > si.date
        return (new_cycle or same_cycle_t0) and i > start

    while start is not None:
        stop = next((i for i in range(n) if _is_new_session_candidate(i, start)), None)
        end = n if stop is None else stop
        for i in range(start, end):
            session[i] = ses
        base[start] = True
        reason[start] = "base-packet"
        ses += 1
        start = stop
    max_session = ses - 1

    # > 0.5-day transmission gap splits the session (MATLAB idTransDelay).
    for i in range(1, n):
        gap_days = (stream[i].date - stream[i - 1].date).total_seconds() / 86400.0
        if gap_days > HALF_DAY and session[i - 1] == session[i]:
            for j in range(i, n):
                session[j] += 1
            base[i] = True
            reason[i] = "0.5-day-split"
            max_session += 1

    # < 10-minute base packet whose cycle differs from the previous packet
    # merges back into the previous session (MATLAB 10-minute rule).
    for i in range(1, n):
        if not base[i] or reason[i] not in ("base-packet",):
            continue
        diff_days = (stream[i].date - stream[i - 1].date).total_seconds() / 86400.0
        if diff_days < TEN_MINUTES and stream[i].cycle_raw != stream[i - 1].cycle_raw:
            for j in range(i, n):
                session[j] -= 1
            base[i] = False
            reason[i] = "merged-10min"
            max_session -= 1

    # EOL-flagged packets start their own session (MATLAB idEol loop).
    for i in range(1, n):
        if stream[i].eol_flag == 1 and session[i] == session[i - 1]:
            for j in range(i, n):
                session[j] += 1
            base[i] = True
            reason[i] = "eol-split"
            max_session += 1

    return session, base, reason


# ---------------------------------------------------------------------------
# Main reconstruction
# ---------------------------------------------------------------------------


def reconstruct_cycles(
    messages: list[ArvorIridiumMessage],
    launch_date: datetime | None = None,
    process_remaining_buffers: bool = True,
) -> CycleReconstructionResult:
    """Reconstruct per-cycle decoding buffers from decoded messages.

    ``launch_date`` feeds the pre-launch rule (packets from sessions before
    launch get effective cycle -1 and are removed, keeping the last
    pre-launch parameter packet when no post-launch one exists) — Coriolis
    takes it from float metadata (json_float_info LAUNCH_DATE); here it is
    an explicit parameter.

    ``process_remaining_buffers`` defaults to True: Coriolis production
    hard-sets ``g_decArgo_processRemainingBuffers = 1`` in both the RT and
    DM drivers (decode_provor_2_nc.m L45-46, decode_provor_2_nc_dm.m
    L52-53); trailing open buffers are emitted as cycles with
    ``completed=0, go=2`` (create_decoding_buffers L278-296). Pass False
    only to reproduce the pre-2026-08-27 drop behaviour.
    """

    stream = build_packet_stream(messages, launch_date=launch_date)
    return reconstruct_stream(stream, process_remaining_buffers=process_remaining_buffers)


def reconstruct_stream(
    stream: list[StreamPacket],
    process_remaining_buffers: bool = True,
) -> CycleReconstructionResult:
    """Core reconstruction over an ordered stream (unit-testable core)."""

    result = CycleReconstructionResult()
    full_stream = stream
    result.stream_size = len(full_stream)

    # ---- pre-launch rule (MATLAB lines 50-64) ----
    id_prog_post = [
        i
        for i, sp in enumerate(full_stream)
        if sp.pack_type in (5, 7) and not sp.pre_launch and sp.packet.cycle == 0
    ]
    stream: list[StreamPacket] = []
    orig_index: list[int] = []  # map stream position -> full_stream position
    if id_prog_post:
        for i, sp in enumerate(full_stream):
            if sp.cycle_raw == -1:
                result.pre_launch_discarded.append(sp)
            else:
                stream.append(sp)
                orig_index.append(i)
    else:
        last5 = max((i for i, sp in enumerate(full_stream) if sp.pack_type == 5), default=None)
        last7 = max((i for i, sp in enumerate(full_stream) if sp.pack_type == 7), default=None)
        keep = {last5, last7}
        for i, sp in enumerate(full_stream):
            if sp.cycle_raw == -1 and i not in keep:
                result.pre_launch_discarded.append(sp)
            elif sp.cycle_raw == -1:
                result.kept_pre_launch_param_packets.append(sp)
                stream.append(sp)
                orig_index.append(i)
            else:
                stream.append(sp)
                orig_index.append(i)

    n = len(stream)
    if n == 0:
        return result

    tab_cycle = [sp.cycle_raw for sp in stream]
    tab_eol = [sp.eol_flag for sp in stream]

    # ---- reset handling (MATLAB MANAGE FLOAT RESET) ----
    tab_cycle_adj = list(tab_cycle)
    t4_idx = [i for i in range(n) if stream[i].pack_type == 4]
    for k in range(1, len(t4_idx)):
        prev_reset = stream[t4_idx[k - 1]].reset_date
        cur_reset = stream[t4_idx[k]].reset_date
        if prev_reset is None or cur_reset is None or cur_reset <= prev_reset:
            continue
        rid = t4_idx[k]
        reset_dt = cur_reset
        cycles_before = [tab_cycle_adj[i] for i in range(n) if stream[i].date < reset_dt]
        cyc_prev = max(cycles_before) if cycles_before else 0
        first_pack = next((i for i in range(n) if stream[i].date >= reset_dt), 0)
        offset = cyc_prev + 1 if cyc_prev > 0 else 0
        if offset:
            # MATLAB re-bases from the RAW cycle numbers (no accumulation)
            for i in range(first_pack, n):
                tab_cycle_adj[i] = tab_cycle[i] + offset
        result.resets.append(
            ResetEvent(reset_date=reset_dt, first_packet_index=rid, cycle_offset=offset)
        )

    # ---- session segmentation ----
    session, _base, reason = _segment_sessions(stream)
    n_sessions = max(session) if session else 0

    # ---- deep-session numbering (tabSessionDeep) ----
    session_deep = list(session)
    for s in range(1, n_sessions + 1):
        idxs = [i for i in range(n) if session[i] == s]
        if not idxs:
            continue
        if not any(stream[i].pack_type in DEEP_PACKET_TYPES for i in idxs):
            first = idxs[0]
            for j in range(first, n):
                session_deep[j] -= 1

    # ---- per-packet result state ----
    rank: list[int] = [-1] * n
    deep: list[bool] = [False] * n
    done: list[bool] = [False] * n
    delayed: list[int] = [0] * n
    completed: list[bool] = [False] * n
    go: list[int] = [0] * n
    next_rank = 1

    def later_same_cycle(ses_num: int, cyc: int) -> list[int]:
        """Indices of same-cycle packets in strictly later sessions,
        truncated before the first 0/4/5 among them (MATLAB idRemaining)."""

        rem = [i for i in range(n) if session[i] > ses_num and tab_cycle_adj[i] == cyc]
        cut = next((k for k, i in enumerate(rem) if stream[i].pack_type in BASE_PACKET_TYPES), None)
        return rem if cut is None else rem[:cut]

    def force_condition(idxs: list[int]) -> bool:
        ses_deep_min = min(session_deep[i] for i in idxs)
        return (max(session_deep) - ses_deep_min) >= NB_SESSION_MAX - 1

    session_list = sorted({s for s in session if s > 0})

    # ---- main loop: first cycle of each session ----
    for ses_num in session_list:
        ses_idx = [i for i in range(n) if session[i] == ses_num]
        if not ses_idx:
            continue
        cyc = tab_cycle_adj[ses_idx[0]]
        idxs = [i for i in ses_idx if tab_cycle_adj[i] == cyc]
        if not idxs:
            continue
        ok, dp, _ = check_buffer(idxs, stream, as_coded=False, why_flag=False)
        dly = 0
        rem = later_same_cycle(ses_num, cyc)
        if rem:
            idxs = idxs + rem
            dly = 2
            ok, dp, _ = check_buffer(idxs, stream, as_coded=False, why_flag=False)
        if ok:
            for i in idxs:
                rank[i] = next_rank
                deep[i] = dp
                done[i] = True
                delayed[i] = dly
                completed[i] = True
                go[i] = 1
            next_rank += 1
        elif force_condition(idxs):
            for i in idxs:
                rank[i] = next_rank
                deep[i] = dp
                done[i] = True
                delayed[i] = dly
                go[i] = 1
            next_rank += 1
        else:
            for i in idxs:
                deep[i] = dp
                done[i] = True
            if process_remaining_buffers:
                for i in idxs:
                    rank[i] = next_rank
                    delayed[i] = dly
                    go[i] = 2
                next_rank += 1

    # ---- remaining loop: leftover (session, cycle) pairs, delayed = 1 ----
    for ses_num in session_list:
        left = [i for i in range(n) if session[i] == ses_num and not done[i]]
        if not left:
            continue
        for cyc in sorted({tab_cycle_adj[i] for i in left}):
            idxs = [i for i in range(n) if session[i] == ses_num and tab_cycle_adj[i] == cyc]
            ok, dp, _ = check_buffer(idxs, stream, as_coded=False, why_flag=False)
            rem = later_same_cycle(ses_num, cyc)
            if rem:
                idxs = idxs + rem
                ok, dp, _ = check_buffer(idxs, stream, as_coded=False, why_flag=False)
            if ok:
                for i in idxs:
                    rank[i] = next_rank
                    deep[i] = dp
                    done[i] = True
                    delayed[i] = 1
                    completed[i] = True
                    go[i] = 1
                next_rank += 1
            elif force_condition(idxs):
                for i in idxs:
                    rank[i] = next_rank
                    deep[i] = dp
                    done[i] = True
                    delayed[i] = 1
                    go[i] = 1
                next_rank += 1
            elif process_remaining_buffers:
                for i in idxs:
                    rank[i] = next_rank
                    deep[i] = dp
                    done[i] = True
                    delayed[i] = 1
                    go[i] = 2
                next_rank += 1
            else:
                for i in idxs:
                    deep[i] = dp
                    done[i] = True

    # ---- EOL retransmission dedup (MATLAB EOL loops) ----
    eol_cycles = sorted({tab_cycle_adj[i] for i in range(n) if tab_eol[i] == 1})
    for cyc in eol_cycles:
        eol_idxs = [i for i in range(n) if tab_eol[i] == 1 and tab_cycle_adj[i] == cyc]
        if not eol_idxs:
            continue
        first_eol = eol_idxs[0]
        prev = [
            i
            for i in range(n)
            if tab_cycle_adj[i] == cyc and stream[i].ir_session == 0 and tab_eol[i] == 0
        ]
        if prev and completed[prev[-1]]:
            r = rank[first_eol]
            if r > 0:
                id_all = [i for i in range(n) if rank[i] == r]
                for i in id_all:
                    deep[i] = False
                for i in id_all:
                    if stream[i].pack_type not in (0, 4, 5, 7):
                        rank[i] = -1
                        result.dropped_packets.append(
                            (stream[i], "EOL retransmission of completed cycle")
                        )
        # duplicated EOL parameter packets: keep the last of each type
        # (MATLAB iterates unique(tabRank(idEol)) INCLUDING -1, so the rule
        # also cleans duplicates among pending EOL packets)
        eol_ranks = sorted({rank[i] for i in eol_idxs})
        for r in eol_ranks:
            id_all = [i for i in range(n) if rank[i] == r]
            for ptype in (5, 7):
                pts = [i for i in id_all if stream[i].pack_type == ptype]
                for i in pts[:-1]:
                    rank[i] = -1
                    result.dropped_packets.append(
                        (stream[i], "duplicated EOL parameter packet (kept last)")
                    )

    # ---- second Iridium session split (irSession == 1) ----
    rank_snapshot = sorted({rank[i] for i in range(n) if rank[i] > 0})
    for r in rank_snapshot:
        id_all = [i for i in range(n) if rank[i] == r]
        ses_flags = {stream[i].ir_session for i in id_all}
        if 0 in ses_flags and 1 in ses_flags:
            id2 = [i for i in id_all if stream[i].ir_session == 1]
            extra5 = [i for i in id_all if stream[i].pack_type == 5 and i > max(id2)]
            id2 = id2 + extra5
            extra7 = [i for i in id_all if stream[i].pack_type == 7 and i > max(id2)]
            id2 = id2 + extra7
            id1 = [i for i in id_all if i not in id2]
            for i in range(n):
                if rank[i] > r:
                    rank[i] += 1
            for i in id2:
                rank[i] += 1
            for i in id1:
                deep[i] = True
            for i in id_all:
                go[i] = 1

    # ---- rankByCycle renumbering ----
    rank_by_cycle = [-1] * n
    new_rank = 1
    for cyc in sorted({c for c in tab_cycle_adj}):
        id_cyc = [i for i in range(n) if tab_cycle_adj[i] == cyc]
        for r in sorted({rank[i] for i in id_cyc} - {-1}):
            for i in range(n):
                if tab_cycle_adj[i] == cyc and rank[i] == r:
                    rank_by_cycle[i] = new_rank
            new_rank += 1

    # ---- final completion re-evaluation per emitted buffer ----
    buffers: dict[int, BufferResult] = {}
    for bid in range(1, new_rank):
        idxs = [i for i in range(n) if rank_by_cycle[i] == bid]
        if not idxs:
            continue
        ok, dp, why = check_buffer(idxs, stream, as_coded=False, why_flag=True)
        ok_code, _, why_code = check_buffer(idxs, stream, as_coded=True, why_flag=True)
        cyc = tab_cycle_adj[idxs[0]]
        t2 = next((stream[i] for i in idxs if stream[i].pack_type == 4), None)
        buf = BufferResult(
            buffer_id=bid,
            cycle_number=cyc,
            packets=[stream[i] for i in idxs],
            session_ids=sorted({session[i] for i in idxs}),
            rank=rank[idxs[0]],
            delayed=max(delayed[i] for i in idxs),
            ice_delayed=any(delayed[i] == 1 for i in idxs),
            deep=all(deep[i] for i in idxs) if idxs else False,
            go=max(go[i] for i in idxs),
            completed=ok,
            completed_coriolis_as_coded=ok_code,
            expected_counts=_expected_counts(t2, as_coded=False) if t2 else None,
            expected_counts_coriolis_as_coded=(_expected_counts(t2, as_coded=True) if t2 else None),
            received_counts=(
                sum(1 for i in idxs if stream[i].pack_type in DESC_TYPES),
                sum(1 for i in idxs if stream[i].pack_type in DRIFT_TYPES),
                sum(1 for i in idxs if stream[i].pack_type in ASC_TYPES),
            ),
            why_incomplete=why,
            why_incomplete_as_coded=why_code,
        )
        buffers[bid] = buf
    result.buffers = [buffers[bid] for bid in sorted(buffers)]
    result.unranked_packets = [
        stream[i] for i in range(n) if rank_by_cycle[i] == -1 and rank[i] == -1
    ]
    # note: rank[i] == -1 with done[i] True and go 0 -> pending (unranked)

    # ---- session records ----
    for s in range(1, n_sessions + 1):
        idxs = [i for i in range(n) if session[i] == s]
        if idxs:
            first = idxs[0]
            result.sessions.append(
                SessionRecord(
                    session_id=s,
                    packet_indices=idxs,
                    created_by=reason[first] or "base-packet",
                    merged_into_previous=(reason[first] == "merged-10min"),
                )
            )

    return result


# ---------------------------------------------------------------------------
# Convenience: full chain from .eml files
# ---------------------------------------------------------------------------


def reconstruct_from_directory(
    directory: str | Path,
    launch_date: datetime | None = None,
    process_remaining_buffers: bool = True,
) -> tuple[list[ArvorIridiumMessage], CycleReconstructionResult]:
    """Read every .eml in a float directory and reconstruct its cycles."""

    d = Path(directory)
    messages = [read_arvor_i_eml(p) for p in sorted(d.glob("*.eml"))]
    result = reconstruct_cycles(
        messages, launch_date=launch_date, process_remaining_buffers=process_remaining_buffers
    )
    return messages, result


__all__ = [
    "BASE_PACKET_TYPES",
    "DEEP_PACKET_TYPES",
    "NB_SESSION_MAX",
    "BufferResult",
    "CycleReconstructionResult",
    "ResetEvent",
    "SbdSessionInfo",
    "SessionRecord",
    "StreamPacket",
    "build_packet_stream",
    "check_buffer",
    "reconstruct_cycles",
    "reconstruct_from_directory",
    "reconstruct_stream",
]

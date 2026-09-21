"""C1: ARGOS multi-day dumps must split into one burst per surfacing.

An ARGOS ground-station dump is a *time window*, not a cycle. Several
files in the INCOIS archive carry two or three surfacings, written in
arbitrary order -- WMO 2902206's ``..._2026-01-10_..._360.txt`` opens
with its newest pass and steps backwards to 2026-01-05.

Coriolis groups the receptions by time: ``read_argos_file_fmt1_rough.m:99``
returns ``sort(unique(dates))`` and ``split_argos_file.m:47-51``
differences *that*, then files each satellite pass by comparing its own
``min(dataDateList)`` against the split date (lines 74-88).

These tests run against the real raw files in the repository, so they
pin the behaviour on genuine telemetry rather than on a fixture that
could be reshaped to fit the implementation.
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import pytest

from argo_decoder.platforms.apex_argos.frames import (
    iter_argos_messages_from_payload,
    reception_count,
    select_redundant_messages,
    split_transmission_text,
    transmission_time_span,
)
from argo_decoder.platforms.apex_argos.profile import decode_profile, layout_for_decoder

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_ROOT = REPO_ROOT / "phase4_reference" / "raw" / "raw-files"
FRAME_LENGTH = 31

pytestmark = pytest.mark.skipif(not RAW_ROOT.is_dir(), reason="raw archive not present")


def _payload(relative: str) -> bytes:
    path = RAW_ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} not in the local archive")
    return path.read_bytes()


def _spans(parts: list[bytes]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for part in parts:
        span = transmission_time_span(part)
        assert span is not None
        out.append((span[0].strftime("%Y-%m-%d %H:%M"), span[1].strftime("%Y-%m-%d %H:%M")))
    return out


def _profile_id(part: bytes, decoder_id: int) -> int | None:
    messages = list(iter_argos_messages_from_payload(part, frame_length=FRAME_LENGTH))
    decoded = decode_profile(
        select_redundant_messages(messages),
        layout=layout_for_decoder(decoder_id),
        cycle_number_wrap=0,
    )
    return decoded.profile_number


# ---------------------------------------------------------------------------
# The three files the audit identified, plus the 2011 file that already worked
# ---------------------------------------------------------------------------


def test_2902206_360_splits_into_three_surfacings() -> None:
    """The file that defeated the running-maximum rule entirely.

    262 of its 293 message boundaries step backwards and the newest pass
    is written first, so the high-water mark was saturated on line 1 and
    the old rule found zero cuts. All three surfacings merged, and the
    earliest reception then set ``JULD_FIRST_MESSAGE`` 119 h early.
    """
    parts = split_transmission_text(_payload("152397/152397_2026-01-10_2902206_360.txt"))
    assert len(parts) == 3
    assert _spans(parts) == [
        ("2026-01-05 13:39", "2026-01-05 20:58"),
        ("2026-01-08 07:39", "2026-01-08 07:46"),
        ("2026-01-10 12:41", "2026-01-10 14:31"),
    ]


def test_2902222_329_separates_two_different_profile_ids() -> None:
    """Proof from telemetry that the merged bursts were different cycles.

    The two substantive bursts carry profile ids 74 and 73. Merging them
    let redundancy selection keep one and silently discard the other.
    """
    parts = split_transmission_text(_payload("152389/152389_2026-01-14_2902222_329.txt"))
    assert len(parts) == 3
    assert [_profile_id(part, 1010) for part in parts] == [None, 74, 73]


def test_2902203_360_splits_a_fragment_from_the_surfacing() -> None:
    parts = split_transmission_text(_payload("152398/152398_2026-01-05_2902203_360.txt"))
    assert len(parts) == 2
    assert _spans(parts) == [
        ("2026-01-04 18:22", "2026-01-04 18:31"),
        ("2026-01-05 15:43", "2026-01-05 20:58"),
    ]


def test_2901304_deployment_file_still_splits_prelude_from_cycle_one() -> None:
    """The chronologically ordered file that the old rule handled.

    84 receptions from the deployment self test on the 13th and 153 from
    cycle 1 on the 14th. This is the DPF case ``split_argos_file.m`` was
    written for; the new rule must not regress it.
    """
    parts = split_transmission_text(_payload("102525/102525_2011-02-13.txt"))
    assert len(parts) == 2
    assert [_profile_id(part, 1005) for part in parts] == [16, 1]


# ---------------------------------------------------------------------------
# Invariants that must hold for every archive file
# ---------------------------------------------------------------------------

_ALL_ARGOS_FILES = sorted(RAW_ROOT.glob("*/*.txt")) if RAW_ROOT.is_dir() else []


@pytest.mark.parametrize("path", _ALL_ARGOS_FILES, ids=lambda p: p.name)
def test_split_conserves_every_reception(path: Path) -> None:
    """No telemetry may be lost or duplicated by the split.

    The bug this guards against is a slicing error that drops the lines
    between two bursts, or repeats them in both.
    """
    payload = path.read_bytes()
    parts = split_transmission_text(payload)
    assert sum(reception_count(part) for part in parts) == reception_count(payload)


@pytest.mark.parametrize("path", _ALL_ARGOS_FILES, ids=lambda p: p.name)
def test_split_conserves_crc_valid_messages(path: Path) -> None:
    """Valid telemetry survives the split intact.

    Counted on parsed messages rather than text lines, so a split that
    corrupted a frame boundary would show up as a lost CRC-valid copy.
    """
    payload = path.read_bytes()
    whole = list(iter_argos_messages_from_payload(payload, frame_length=FRAME_LENGTH))
    total = 0
    crc_ok = 0
    for part in split_transmission_text(payload):
        messages = list(iter_argos_messages_from_payload(part, frame_length=FRAME_LENGTH))
        total += len(messages)
        crc_ok += sum(1 for message in messages if message.crc_ok)
    assert total == len(whole)
    assert crc_ok == sum(1 for message in whole if message.crc_ok)


@pytest.mark.parametrize("path", _ALL_ARGOS_FILES, ids=lambda p: p.name)
def test_bursts_are_ordered_and_disjoint_in_time(path: Path) -> None:
    """Bursts come back oldest-first and never overlap.

    The old rule returned near-duplicate bursts spanning most of the
    file: WMO 2902206's ``_359`` file produced three, two of which both
    started at 2025-12-31 13:02. Overlapping bursts mean the same
    surfacing is decoded twice under different cycle numbers.
    """
    parts = split_transmission_text(path.read_bytes())
    spans = [transmission_time_span(part) for part in parts]
    assert all(span is not None for span in spans)
    for earlier, later in pairwise(spans):
        assert earlier is not None and later is not None
        assert earlier[1] < later[0]


def test_bursts_are_returned_in_time_order_not_discovery_order() -> None:
    """Oldest burst first, whatever order the ground station wrote them.

    Eight files in this archive list their bursts in an order that is not
    chronological -- WMO 2902201's ``..._360.txt`` writes its newest
    burst first, so discovery order is ``[6, 0, 1, 2, 3, 4, 5]``.

    Order matters downstream: the extra bursts take successively lower
    provisional keys and ``_resolve_sentinel_cycles`` reads that sequence
    as transmission order. Returning them as encountered would place a
    later surfacing before an earlier one.
    """
    parts = split_transmission_text(_payload("152399/152399_2026-01-14_2902201_360.txt"))
    assert len(parts) == 7
    starts = [transmission_time_span(part) for part in parts]
    assert all(span is not None for span in starts)
    firsts = [span[0] for span in starts if span is not None]
    assert firsts == sorted(firsts)
    # The dominant burst is last in time and must not be reported first.
    assert max(range(len(parts)), key=lambda i: reception_count(parts[i])) == len(parts) - 1


@pytest.mark.parametrize("path", _ALL_ARGOS_FILES, ids=lambda p: p.name)
def test_each_burst_is_shorter_than_a_cycle(path: Path) -> None:
    """A surfacing lasts hours, not days.

    A float transmits for a few hours then dives for the rest of the
    cycle, so any burst spanning more than a day is really two
    surfacings that were not separated.
    """
    for part in split_transmission_text(path.read_bytes()):
        span = transmission_time_span(part)
        assert span is not None
        assert (span[1] - span[0]).total_seconds() < 24 * 3600

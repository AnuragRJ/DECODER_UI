"""APEX ARGOS frame parsing and redundancy selection."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise

_HEX_PAIR_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{2})(?![0-9A-Fa-f])")
_LONG_HEX_RE = re.compile(r"(?<![0-9A-Fa-f])([0-9A-Fa-f]{32,})(?![0-9A-Fa-f])")
# CLS/Coriolis ARGOS format-1 satellite-pass header, e.g.
#   02602 152389  89 31 R 1 2026-01-04 06:17:06 -53.854 -158.095  0.000 401649803
# fields: programme, PTT, n_lines, frame length, satellite, location class,
#         date, time, latitude, longitude, altitude, frequency.
_FMT1_PASS_RE = re.compile(
    r"^\s*(?P<programme>\d+)\s+(?P<ptt>\d+)\s+(?P<n_lines>\d+)\s+(?P<frame_len>\d+)\s+"
    r"(?P<satellite>[A-Z0-9])\s+(?P<loc_class>[0-9A-Z])\s+"
    r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(?P<lat>-?\d+\.\d+)\s+(?P<lon>-?\d+\.\d+)"
)
_FMT1_MESSAGE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+"
    r"(?P<occ>\d+)\s+(?P<data>.*)$"
)


@dataclass(frozen=True)
class ArgosMessage:
    """One received APEX ARGOS message."""

    raw: bytes
    received_at: datetime | None = None

    @property
    def crc(self) -> int:
        return self.raw[0]

    @property
    def message_number(self) -> int:
        return self.raw[1]

    @property
    def payload(self) -> bytes:
        return self.raw[2:]

    @property
    def crc_ok(self) -> bool:
        return check_crc(self.raw)


@dataclass(frozen=True)
class ArgosFix:
    """One ARGOS satellite location fix from a format-1 pass header.

    ``location_class`` is the CLS quality class: ``3``/``2``/``1``/``0``
    for decreasing accuracy, or ``A``/``B``/``Z`` for unvalidated fixes.
    """

    at: datetime
    latitude: float
    longitude: float
    location_class: str
    satellite: str = ""


def parse_argos_fixes(payload: bytes) -> list[ArgosFix]:
    """Extract the ARGOS satellite location fixes from a raw ARGOS file.

    Format-1 files repeat the same satellite pass once per contained
    message block, so duplicates are collapsed. The result is sorted by
    acquisition time.
    """
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return []
    seen: dict[tuple[str, float, float], ArgosFix] = {}
    for line in text.splitlines():
        match = _FMT1_PASS_RE.match(line)
        if match is None:
            continue
        at = _parse_datetime_utc(match.group("date"), match.group("time"))
        if at is None:
            continue
        latitude = float(match.group("lat"))
        longitude = float(match.group("lon"))
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            continue
        key = (at.isoformat(), latitude, longitude)
        if key in seen:
            continue
        seen[key] = ArgosFix(
            at=at,
            latitude=latitude,
            longitude=longitude,
            location_class=match.group("loc_class"),
            satellite=match.group("satellite"),
        )
    return sorted(seen.values(), key=lambda fix: fix.at)


@dataclass(frozen=True)
class SelectedArgosMessage:
    """One message selected after CRC/redundancy processing."""

    message_number: int
    payload: bytes
    redundancy: int
    received_at: datetime | None = None
    crc_ok: bool = True

    @property
    def matlab_row(self) -> bytes:
        """Return MATLAB-style selected row: redundancy, message number, payload."""
        return bytes([self.redundancy & 0xFF, self.message_number & 0xFF]) + self.payload


def hasard(byte_value: int) -> int:
    """One WRC APEX CRC LFSR step from MATLAB ``check_crc_apx.m``."""
    byte_value &= 0xFF
    if byte_value == 0:
        return 127
    parity = sum(1 for mask in (1, 4, 8, 16) if byte_value & mask)
    shifted = byte_value // 2
    if parity & 1:
        shifted += 128
    return shifted & 0xFF


def compute_crc(data: bytes | Sequence[int]) -> int:
    """Compute WRC APEX CRC for bytes after the received CRC byte."""
    data_bytes = bytes(int(v) & 0xFF for v in data)
    if not data_bytes:
        raise ValueError("APEX ARGOS CRC requires at least one data byte")
    byte_n = data_bytes[0]
    for value in data_bytes[1:]:
        byte_n = hasard(byte_n)
        byte_n ^= value
    return hasard(byte_n)


def check_crc(sensor: bytes | Sequence[int]) -> bool:
    sensor_bytes = bytes(int(v) & 0xFF for v in sensor)
    if len(sensor_bytes) < 2:
        return False
    return sensor_bytes[0] == compute_crc(sensor_bytes[1:])


def build_frame(
    message_number: int, payload: bytes | Sequence[int], *, frame_length: int = 31
) -> bytes:
    """Build a CRC-clean frame for tests and synthetic fixtures."""
    if frame_length < 2:
        raise ValueError("frame_length must include CRC and message-number bytes")
    payload_bytes = bytes(int(v) & 0xFF for v in payload)
    wanted_payload = frame_length - 2
    if len(payload_bytes) > wanted_payload:
        raise ValueError(
            f"payload has {len(payload_bytes)} bytes but frame_length={frame_length} "
            f"allows only {wanted_payload}"
        )
    data = bytes([message_number & 0xFF]) + payload_bytes.ljust(wanted_payload, b"\x00")
    return bytes([compute_crc(data)]) + data


def combine_bits(messages: Sequence[bytes | Sequence[int]]) -> bytes:
    """Combine repeated bad copies byte/bit-wise like MATLAB ``combine_bits_apx``."""
    rows = [bytes(int(v) & 0xFF for v in msg) for msg in messages]
    if not rows:
        raise ValueError("at least one message is required")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("all messages must have the same length")
    out = bytearray(width)
    n_rows = len(rows)
    for byte_idx in range(width):
        bits = [[(row[byte_idx] >> (7 - bit_idx)) & 1 for bit_idx in range(8)] for row in rows]
        sums = [sum(row_bits[bit_idx] for row_bits in bits) for bit_idx in range(8)]
        result: list[int] = []
        tied: list[int] = []
        for bit_idx, bit_sum in enumerate(sums):
            if bit_sum > n_rows / 2:
                result.append(1)
            elif bit_sum < n_rows / 2:
                result.append(0)
            else:
                result.append(0)
                tied.append(bit_idx)
        if tied:
            non_tied = [idx for idx in range(8) if idx not in tied]
            best_idx = 0
            best_score = -1
            for row_idx, row_bits in enumerate(bits):
                score = sum(row_bits[idx] == result[idx] for idx in non_tied)
                if score > best_score:
                    best_score = score
                    best_idx = row_idx
            for bit_idx in tied:
                result[bit_idx] = bits[best_idx][bit_idx]
        value = 0
        for bit in result:
            value = (value << 1) | bit
        out[byte_idx] = value
    return bytes(out)


def parse_argos_frame(
    raw: bytes | Sequence[int], *, frame_length: int = 31, received_at: datetime | None = None
) -> ArgosMessage:
    raw_bytes = bytes(int(v) & 0xFF for v in raw)
    if len(raw_bytes) != frame_length:
        raise ValueError(f"expected {frame_length} bytes, got {len(raw_bytes)}")
    return ArgosMessage(raw=raw_bytes, received_at=received_at)


def _parse_datetime_utc(date_text: str, time_text: str) -> datetime | None:
    raw = f"{date_text} {time_text.split('.', 1)[0]}"
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_format1_text(text: str, *, frame_length: int) -> list[ArgosMessage]:
    """Parse CLS/Coriolis ARGOS format-1 multiline text files."""
    messages: list[ArgosMessage] = []
    current: list[int] = []
    current_dt: datetime | None = None
    current_occ = 1

    def flush_if_complete() -> None:
        nonlocal current, current_dt, current_occ
        if len(current) < frame_length:
            return
        raw = bytes(current[:frame_length])
        for _ in range(max(1, current_occ)):
            messages.append(ArgosMessage(raw=raw, received_at=current_dt))
        current = []
        current_dt = None
        current_occ = 1

    for line in text.splitlines():
        match = _FMT1_MESSAGE_RE.match(line)
        if match is not None:
            current = []
            current_dt = _parse_datetime_utc(match.group("date"), match.group("time"))
            current_occ = int(match.group("occ"))
            current.extend(int(tok, 16) for tok in _HEX_PAIR_RE.findall(match.group("data")))
            flush_if_complete()
            continue
        if current:
            current.extend(int(tok, 16) for tok in _HEX_PAIR_RE.findall(line))
            flush_if_complete()
    return messages


def iter_argos_messages_from_payload(
    payload: bytes, *, frame_length: int = 31, received_at: datetime | None = None
) -> list[ArgosMessage]:
    """Extract APEX ARGOS messages from binary, hex, or format-1 text payloads."""
    if len(payload) == frame_length:
        return [parse_argos_frame(payload, frame_length=frame_length, received_at=received_at)]
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return []

    messages = _parse_format1_text(text, frame_length=frame_length)
    if messages:
        return messages

    messages = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        for match in _LONG_HEX_RE.finditer(stripped):
            token = match.group(1)
            if len(token) >= frame_length * 2 and len(token) % 2 == 0:
                raw = bytes.fromhex(token[: frame_length * 2])
                messages.append(
                    parse_argos_frame(raw, frame_length=frame_length, received_at=received_at)
                )
                break
        else:
            pairs = _HEX_PAIR_RE.findall(stripped)
            if len(pairs) >= frame_length:
                raw = bytes(int(tok, 16) for tok in pairs[-frame_length:])
                messages.append(
                    parse_argos_frame(raw, frame_length=frame_length, received_at=received_at)
                )
    return messages


def _mask_frozen(raw: bytes, frozen_positions: Sequence[int]) -> bytes:
    if not frozen_positions:
        return raw
    masked = bytearray(raw)
    for pos in frozen_positions:
        idx = int(pos) - 1
        if 0 <= idx < len(masked):
            masked[idx] = 0
    return bytes(masked)


def _restore_frozen(masked: bytes, original: bytes, frozen_positions: Sequence[int]) -> bytes:
    if not frozen_positions:
        return masked
    restored = bytearray(masked)
    for pos in frozen_positions:
        idx = int(pos) - 1
        if 0 <= idx < len(restored) and idx < len(original):
            restored[idx] = original[idx]
    return bytes(restored)


#: A float surfaces for a few hours, transmits, then dives for the rest of
#: the cycle. Receptions therefore arrive in tight bursts separated by most
#: of a cycle. Six hours cleanly separates the bursts without splitting one:
#: in the WMO 2901304 archive the widest within-burst gap is under 6 h while
#: the two files that hold a second transmission show gaps of 17.4 h and
#: 24.7 h.
TRANSMISSION_GAP_HOURS = 6.0


def transmission_time_span(payload: bytes) -> tuple[datetime, datetime] | None:
    """Earliest and latest reception time in a format-1 payload.

    Returns ``None`` when the payload carries no readable message line,
    so callers can tell "no times" apart from "one time".
    """
    stamps = [stamp for _, stamp in _message_line_stamps(payload.decode("ascii", "replace"))]
    if not stamps:
        return None
    return min(stamps), max(stamps)


def reception_count(payload: bytes) -> int:
    """Number of format-1 message lines in a payload."""
    return len(_message_line_stamps(payload.decode("ascii", "replace")))


def _message_line_stamps(text: str) -> list[tuple[int, datetime]]:
    """``(line index, reception time)`` for every format-1 message line."""
    out: list[tuple[int, datetime]] = []
    for index, line in enumerate(text.splitlines()):
        match = _FMT1_MESSAGE_RE.match(line)
        if match is None:
            continue
        try:
            stamp = datetime.strptime(
                f"{match.group('date')} {match.group('time')[:8]}", "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=UTC)
        except ValueError:
            continue
        out.append((index, stamp))
    return out


def split_transmission_text(
    payload: bytes, *, gap_hours: float = TRANSMISSION_GAP_HOURS
) -> list[bytes]:
    """Split a format-1 ARGOS text dump into one payload per transmission.

    An ARGOS ground-station dump is a time window, not a cycle. When a
    satellite pass straddles two surfacings the file holds both: WMO
    2901304's ``102525_2011-02-13.txt`` carries 84 receptions from the
    deployment self test on the 13th and 165 from cycle 1 on the 14th,
    separated by a 17.4 hour gap. Treating the file as one cycle lets
    redundancy selection keep the majority copy and silently discard the
    other transmission, which is how cycle 1 went missing.

    The split is done on the text so each part re-parses exactly as the
    original format-1 reader expects. The file header is repeated on
    every part. A payload that is not format-1 text, or that holds a
    single burst, is returned unchanged as a single element.
    """
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return [payload]
    lines = text.splitlines()
    starts = _message_line_stamps(text)
    if len(starts) < 2:
        return [payload]

    # Group the receptions by *time*, never by their position in the file.
    #
    # A ground-station dump is a time window, not a cycle, and the passes
    # inside it are not written in chronological order. WMO 2902206's
    # ``..._2026-01-10_..._360.txt`` opens with the newest pass and then
    # steps backwards on 262 of its 293 message boundaries, spanning back
    # to 2026-01-05.
    #
    # Reading the file in order therefore cannot find the boundaries:
    #
    # * differencing consecutive lines fires on every backward step, so
    #   one burst is reported many times over;
    # * differencing against a running maximum is defeated whenever the
    #   newest pass comes first, because the high-water mark is saturated
    #   on the very first line and nothing can ever exceed it again --
    #   that file yielded zero cuts and merged three surfacings into one.
    #
    # Coriolis avoids both by working on sorted, de-duplicated reception
    # dates: ``read_argos_file_fmt1_rough.m:99`` returns
    # ``sort(unique(...))`` and ``split_argos_file.m:47-51`` differences
    # *that*. Each satellite pass is then filed by comparing its own
    # ``min(dataDateList)`` against the split date
    # (``split_argos_file.m:74-88``) -- by time, not by position.
    #
    # We do the same, with one deliberate generalisation: Coriolis cuts
    # only at the single largest gap because it only ever needs to peel a
    # DPF prelude off the first deep cycle, whereas these archives hold up
    # to three surfacings in one file. Cutting at *every* gap wider than
    # ``gap_hours`` is the same rule applied consistently; with a single
    # boundary present the two are identical.
    order = sorted(range(len(starts)), key=lambda i: (starts[i][1], starts[i][0]))
    groups: list[list[int]] = [[order[0]]]
    for previous, current in pairwise(order):
        if (starts[current][1] - starts[previous][1]).total_seconds() > gap_hours * 3600:
            groups.append([current])
        else:
            groups[-1].append(current)
    if len(groups) < 2:
        return [payload]

    # A satellite pass header ("02602 102525 129 31 L 2 <date> ...")
    # introduces the messages received during that pass, so a message
    # carries any header lines that sit immediately above it. Attaching
    # the message alone leaves the pass -- and the Argos fix it carries --
    # with the wrong burst, which is how WMO 2901304 cycle 1 lost its
    # 02:12:23 fix and with it the reference JULD.
    def _with_leading_pass(index: int) -> int:
        begin = index
        while begin > 0 and _FMT1_PASS_RE.match(lines[begin - 1]):
            begin -= 1
        return begin

    # Each message block runs from its own (header-extended) start to the
    # start of the next block *in file order*, so the text is sliced
    # exactly once however the groups are arranged in time.
    line_starts = [_with_leading_pass(index) for index, _ in starts]
    block_bounds: list[tuple[int, int]] = []
    for position, begin in enumerate(line_starts):
        end = line_starts[position + 1] if position + 1 < len(line_starts) else len(lines)
        block_bounds.append((begin, max(begin, end)))

    header = lines[: line_starts[0]]
    parts: list[bytes] = []
    # ``groups`` is already oldest-first: it is built by walking ``order``,
    # which is sorted by time. Callers rely on that -- the extra bursts
    # take successively lower provisional keys and the sentinel recovery
    # reads the sequence as transmission order.
    for group in groups:
        block: list[str] = list(header)
        # Keep the original file order within a burst: the redundancy
        # selector and the fix parser both expect a normal format-1 dump.
        for member in sorted(group, key=lambda i: line_starts[i]):
            begin, end = block_bounds[member]
            block.extend(lines[begin:end])
        parts.append(("\n".join(block) + "\n").encode("ascii"))
    return parts


#: Message-1 payload offsets whose value is resolved by per-byte majority
#: across the CRC-valid copies instead of by whole-frame group size.
#:
#: The APF9 re-samples these analogue channels for *each* ARGOS
#: transmission, so copies of the same message legitimately disagree --
#: on WMO 2901304 cycle 20 the eleven CRC-ok copies of message 1 split
#: 6/5 on the status word alone. Whole-frame selection then picks a
#: single arbitrary copy, which is why these fields matched the GDAC
#: reference on only some cycles (13/23 for the profile-depth current)
#: while the stable fields matched 23/23.
#:
#: Taking the majority *per byte* reproduces the reference on 22/23
#: cycles for the profile-depth current and 23/23 for the internal
#: vacuum, and leaves every already-exact field unchanged, since a
#: byte that is identical in all copies has itself as its majority.
#:
#: Scoped to the analogue engineering bytes that were shown to vary
#: between copies: the vacuum byte (9) and the four (voltage, current)
#: couples at 18-25. The status word is deliberately excluded -- see
#: ``format_termination_flag``.
_MAJORITY_BYTE_OFFSETS: frozenset[int] = frozenset({9, 18, 19, 20, 21, 22, 23, 24, 25})


def _majority_bytes(raw: bytes, copies: Sequence[ArgosMessage], offsets: frozenset[int]) -> bytes:
    """Overwrite ``offsets`` with the most common value across ``copies``.

    Ties resolve to the lowest byte value, so the result is a pure
    function of the copy set and does not depend on reception order.
    """
    if len(copies) < 2:
        return raw
    out = bytearray(raw)
    for offset in offsets:
        # ``raw`` is the whole frame; the payload starts two bytes in.
        index = offset + 2
        if index >= len(out):
            continue
        seen = [copy.raw[index] for copy in copies if index < len(copy.raw)]
        if not seen:
            continue
        counts = Counter(seen)
        best = max(counts.values())
        out[index] = min(value for value, count in counts.items() if count == best)
    return bytes(out)


def select_redundant_messages(
    messages: Iterable[ArgosMessage],
    *,
    frozen_bytes_by_message: Mapping[int, Sequence[int]] | None = None,
) -> list[SelectedArgosMessage]:
    """Select one message per message number using MATLAB redundancy rules."""
    frozen_bytes_by_message = frozen_bytes_by_message or {}
    by_number: dict[int, list[ArgosMessage]] = defaultdict(list)
    for msg in messages:
        by_number[msg.message_number].append(msg)

    selected: list[SelectedArgosMessage] = []
    for msg_num in sorted(by_number):
        group = by_number[msg_num]
        candidates = [msg for msg in group if msg.crc_ok]
        if candidates:
            frozen = frozen_bytes_by_message.get(msg_num, ())
            masked_to_messages: dict[bytes, list[ArgosMessage]] = defaultdict(list)
            for msg in candidates:
                masked_to_messages[_mask_frozen(msg.raw, frozen)].append(msg)
            masked, copies = max(
                masked_to_messages.items(),
                key=lambda item: (
                    len(item[1]),
                    -(item[1][0].received_at.timestamp() if item[1][0].received_at else 0),
                ),
            )
            restored = _restore_frozen(masked, copies[0].raw, frozen)
            if msg_num == 1:
                restored = _majority_bytes(restored, candidates, _MAJORITY_BYTE_OFFSETS)
            selected.append(
                SelectedArgosMessage(
                    msg_num, restored[2:], len(copies), copies[0].received_at, True
                )
            )
            continue
        if len(group) <= 1:
            continue
        frozen = frozen_bytes_by_message.get(msg_num, ())
        combined_masked = combine_bits([_mask_frozen(msg.raw, frozen) for msg in group])
        for msg in group:
            combined = bytes([msg.raw[0]]) + _restore_frozen(combined_masked, msg.raw, frozen)[1:]
            if check_crc(combined):
                selected.append(
                    SelectedArgosMessage(msg_num, combined[2:], 0, msg.received_at, False)
                )
                break
    return selected


__all__ = [
    "TRANSMISSION_GAP_HOURS",
    "ArgosMessage",
    "SelectedArgosMessage",
    "build_frame",
    "check_crc",
    "combine_bits",
    "compute_crc",
    "hasard",
    "iter_argos_messages_from_payload",
    "parse_argos_frame",
    "reception_count",
    "select_redundant_messages",
    "split_transmission_text",
    "transmission_time_span",
]

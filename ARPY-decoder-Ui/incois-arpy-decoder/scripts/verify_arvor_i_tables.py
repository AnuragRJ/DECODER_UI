#!/usr/bin/env python3
"""Verify arvor_i.py width tables bit-for-bit against the MATLAB sources.

Parses every ``tabNbBits = [...]`` vector from decode_prv_data_ir_sbd_222_223_225.m
and decode_prv_data_ir_sbd_232.m (handling ``repmat(w, 1, n)`` and ``...``
continuations) and compares against the Python tables, in declaration order.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[0] / "src"))
from argo_decoder.platforms.provor_ir_sbd.arvor_i import (
    CTD_WIDTHS,
    PARAM1_WIDTHS_222_FAMILY,
    PARAM1_WIDTHS_232,
    PUMP_EV_WIDTHS,
    TECH1_WIDTHS,
    TECH2_WIDTHS,
)


def parse_tabnb_bits(src: str) -> list[tuple[str, list[int]]]:
    out = []
    idx = 0
    while True:
        m0 = re.search(r"tabNbBits\s*=\s*\[", src[idx:])
        if m0 is None:
            break
        lb = idx + m0.end() - 1  # position of '['
        # scan to matching ']' with nesting depth (repmat(...) adds one level)
        depth = 0
        end = None
        for i in range(lb, len(src)):
            if src[i] == "[":
                depth += 1
            elif src[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            break
        body = src[lb + 1 : end]
        body = re.sub(r"%[^\n]*", "", body)
        body = body.replace("...", " ")

        def _rep_scalar(m):
            return " ".join([m.group(1)] * int(m.group(2)))

        def _rep_array(m):
            vals = m.group(1).split()
            return " ".join(vals * int(m.group(2)))

        body = re.sub(r"repmat\(\[([\d\s]+)\],\s*1,\s*(\d+)\)", _rep_array, body)
        body = re.sub(r"repmat\((\d+),\s*1,\s*(\d+)\)", _rep_scalar, body)
        nums = [int(tok) for tok in body.split() if tok.isdigit()]
        out.append(nums)
        idx = end + 1
    return out


def main() -> int:
    base = Path(__file__).resolve().parents[1] / "tests" / "data" / "arvor_i" / "coriolis_src"
    ok = True
    for fname, expected in (
        (
            "decode_prv_data_ir_sbd_222_223_225.m",
            [
                TECH1_WIDTHS,
                TECH2_WIDTHS,
                CTD_WIDTHS,
                None,
                PARAM1_WIDTHS_222_FAMILY,
                None,
                PUMP_EV_WIDTHS,
            ],
        ),  # order in file: t0, t4, ctd, ctdo(unimpl), t5, t7(unimpl), t6
        (
            "decode_prv_data_ir_sbd_232.m",
            [TECH1_WIDTHS, TECH2_WIDTHS, CTD_WIDTHS, None, PARAM1_WIDTHS_232, None, PUMP_EV_WIDTHS],
        ),
    ):
        src = (base / fname).read_text()
        tables = parse_tabnb_bits(src)
        print(f"{fname}: {len(tables)} tabNbBits vectors; sizes={[len(t) for t in tables]}")
        for i, (got, exp) in enumerate(zip(tables, expected, strict=False)):
            if exp is None:
                print(
                    f"  [{i}] table not implemented in Python (CTDO/type-7): skipped, "
                    f"len={len(got)}, bits={sum(got)}"
                )
                continue
            label = f"  [{i}]"
            if got == exp:
                print(f"{label} MATCH len={len(got)} bits={sum(got)}")
            else:
                ok = False
                print(f"{label} MISMATCH: matlab={got} python={exp}")
    for name, t in (
        ("TECH1", TECH1_WIDTHS),
        ("TECH2", TECH2_WIDTHS),
        ("CTD", CTD_WIDTHS),
        ("PARAM1_222", PARAM1_WIDTHS_222_FAMILY),
        ("PARAM1_232", PARAM1_WIDTHS_232),
        ("PUMP_EV", PUMP_EV_WIDTHS),
    ):
        print(f"{name}: {len(t)} items, {sum(t)} bits")
        assert sum(t) == 792, f"{name} does not sum to 792 bits"
    print("ALL OK" if ok else "MISMATCHES FOUND")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

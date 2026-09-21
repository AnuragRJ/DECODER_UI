#!/usr/bin/env python3
"""Run the Docker/MCR oracle shadow over every WMO registered in ``registry.csv``.

This is **M1b** of Phase 3: the nightly continuous-comparison harness
that produces per-WMO JSON diff reports (``argo-decoder shadow``) and
a single aggregate ``shadow_nightly_summary.json`` so the cutover gate
(zero error mismatches on the full corpus) can be tracked over time.

Designed to run on the user's local machine where the Docker daemon
and the MATLAB oracle image are available. The sandbox has no Docker,
so this script is not exercised by sandbox CI; it is invoked nightly
from the developer workstation / build host.

Usage
-----
From a checkout with the package installed editable::

    python scripts/shadow_nightly.py \
        --registry config/registry.csv \
        --input-root  /data/argo/input/archive/cycle \
        --output-root /data/argo/shadow/$(date +%Y%m%d) \
        --config      /data/argo/config/decoder_conf.json \
        --info-dir    /data/argo/config/json_float_info \
        --meta-dir    /data/argo/config/json_float_meta_ir_sbd

The script:

1. Reads ``registry.csv`` and iterates every WMO that has an
   ``input/archive/cycle/<ptt>/`` directory.
2. Creates ``<output-root>/<wmo>/{oracle,python,report.json}`` by
   shelling out to ``argo-decoder shadow <wmo>``.
3. Records pass/fail/error counts, per-WMO max abs diff for CNDC/DOXY,
   and an overall ``status`` (``pass`` only if zero mismatches above
   tolerance AND oracle exited cleanly).
4. Writes ``shadow_nightly_summary.json`` with a list of per-WMO
   results plus aggregate counts and a timestamp.

Exit code is 0 on full convergence (cutover gate passes), 1 if any
WMO has mismatches or errors. This makes it suitable as a cron job
or CI gate once Docker is available.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class WmoResult:
    wmo: int
    ptt: int | None
    status: str  # "pass" | "mismatch" | "error" | "skipped"
    oracle_ok: bool = False
    python_cycles: int = 0
    oracle_cycles: int = 0
    mismatched_vars: list[str] = field(default_factory=list)
    max_abs_diff: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_registry(registry_path: Path) -> list[tuple[int, int | None]]:
    """Return (wmo, ptt) pairs from the registry CSV."""
    out: list[tuple[int, int | None]] = []
    with registry_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                wmo = int(row["wmo"])
            except (KeyError, TypeError, ValueError):
                continue
            ptt_raw = row.get("ptt", "").strip()
            ptt = int(ptt_raw) if ptt_raw.isdigit() else None
            out.append((wmo, ptt))
    return out


def _find_input_dir(input_root: Path, wmo: int, ptt: int | None) -> Path | None:
    """Locate the SBD email directory for a float.

    Layout A: ``<input_root>/<ptt>/`` (canonical Coriolis layout).
    Layout B: ``<input_root>/<wmo>/`` (flat layout, useful for tests).
    """
    candidates: list[Path] = []
    if ptt is not None:
        candidates.append(input_root / str(ptt))
    candidates.append(input_root / str(wmo))
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _run_shadow(
    *,
    wmo: int,
    inp: Path,
    out: Path,
    config: Path | None,
    info_dir: Path | None,
    meta_dir: Path | None,
    image: str,
    ref: Path | None,
    timeout_s: int,
) -> WmoResult:
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "report.json"
    cmd: list[str] = [
        sys.executable,
        "-m",
        "argo_decoder.cli.main",
        "shadow",
        str(wmo),
        "--input",
        str(inp),
        "--out",
        str(out),
        "--image",
        image,
        "--report",
        str(report_path),
    ]
    if config is not None:
        cmd += ["--config", str(config)]
    if info_dir is not None:
        cmd += ["--info-dir", str(info_dir)]
    if meta_dir is not None:
        cmd += ["--meta-dir", str(meta_dir)]
    if ref is not None:
        cmd += ["--ref", str(ref)]

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return WmoResult(
            wmo=wmo,
            ptt=None,
            status="error",
            error=f"shadow timed out after {timeout_s}s: {exc}",
            elapsed_s=time.monotonic() - t0,
        )
    except OSError as exc:
        return WmoResult(
            wmo=wmo,
            ptt=None,
            status="error",
            error=f"failed to launch argo-decoder: {exc}",
            elapsed_s=time.monotonic() - t0,
        )
    elapsed = time.monotonic() - t0

    # Parse the per-WMO report.json if it was written.
    parsed: dict[str, Any] = {}
    if report_path.exists():
        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return WmoResult(
                wmo=wmo,
                ptt=None,
                status="error",
                error=f"could not parse report.json: {exc}",
                elapsed_s=elapsed,
            )

    mismatched_vars: list[str] = []
    max_abs_diff: dict[str, float] = {}
    for var, info in (parsed.get("mismatches") or {}).items():
        mismatched_vars.append(var)
        mad = info.get("max_abs_diff")
        if isinstance(mad, (int, float)):
            max_abs_diff[var] = float(mad)

    oracle_ok = bool(parsed.get("oracle_ok", proc.returncode == 0))
    python_cycles = int(parsed.get("python_cycles", 0) or 0)
    oracle_cycles = int(parsed.get("oracle_cycles", 0) or 0)

    if proc.returncode != 0 and not parsed:
        return WmoResult(
            wmo=wmo,
            ptt=None,
            status="error",
            error=(proc.stderr or proc.stdout)[-2000:],
            elapsed_s=elapsed,
        )
    # Cutover gate: any mismatched variable fails the run; if the oracle
    # container itself did not exit cleanly we mark "error" rather than
    # "mismatch" so operators can distinguish infrastructure failures
    # from numerical differences.
    if not oracle_ok:
        status = "error"
    elif mismatched_vars:
        status = "mismatch"
    else:
        status = "pass"
    return WmoResult(
        wmo=wmo,
        ptt=None,
        status=status,
        oracle_ok=oracle_ok,
        python_cycles=python_cycles,
        oracle_cycles=oracle_cycles,
        mismatched_vars=mismatched_vars,
        max_abs_diff=max_abs_diff,
        error=None if oracle_ok else (proc.stderr or proc.stdout)[-2000:],
        elapsed_s=elapsed,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--registry", type=Path, required=True, help="config/registry.csv")
    ap.add_argument("--input-root", type=Path, required=True)
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--info-dir", type=Path, default=None)
    ap.add_argument("--meta-dir", type=Path, default=None)
    ap.add_argument("--ref", type=Path, default=None, help="Reference-data dir (GEBCO, WOA)")
    ap.add_argument(
        "--image",
        default="ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m",
    )
    ap.add_argument("--wmo", type=int, action="append", help="Only run these WMOs (repeatable)")
    ap.add_argument("--timeout", type=int, default=1800, help="Per-float timeout seconds")
    ap.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first float that is not a clean pass",
    )
    args = ap.parse_args(argv)

    entries = _read_registry(args.registry)
    if args.wmo:
        selected = set(args.wmo)
        entries = [(w, p) for (w, p) in entries if w in selected]

    args.output_root.mkdir(parents=True, exist_ok=True)
    results: list[WmoResult] = []
    counts = {"pass": 0, "mismatch": 0, "error": 0, "skipped": 0}
    t_start = time.monotonic()

    for wmo, ptt in entries:
        inp = _find_input_dir(args.input_root, wmo, ptt)
        per_out = args.output_root / str(wmo)
        if inp is None:
            r = WmoResult(wmo=wmo, ptt=ptt, status="skipped", error="no input directory")
            results.append(r)
            counts["skipped"] += 1
            print(f"[skip] WMO {wmo}: no input dir under {args.input_root}")
            continue
        print(f"[run ] WMO {wmo} ptt={ptt} -> {per_out}")
        r = _run_shadow(
            wmo=wmo,
            inp=inp,
            out=per_out,
            config=args.config,
            info_dir=args.info_dir,
            meta_dir=args.meta_dir,
            image=args.image,
            ref=args.ref,
            timeout_s=args.timeout,
        )
        r.ptt = ptt
        results.append(r)
        counts[r.status] = counts.get(r.status, 0) + 1
        n_mis = len(r.mismatched_vars)
        msg = f"       -> {r.status} ({r.python_cycles} py cycles, {n_mis} mismatches"
        if r.mismatched_vars:
            msg += f": {', '.join(r.mismatched_vars)}"
        msg += f", {r.elapsed_s:.1f}s)"
        print(msg)
        if args.fail_fast and r.status != "pass":
            print("fail-fast: stopping on first non-pass")
            break

    summary = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "image": args.image,
        "input_root": str(args.input_root),
        "output_root": str(args.output_root),
        "total_wmos": len(entries),
        "counts": counts,
        "elapsed_s": time.monotonic() - t_start,
        "results": [r.to_dict() for r in results],
        "cutover_gate_passed": counts["pass"] == len(entries) and counts["error"] == 0,
    }
    summary_path = args.output_root / "shadow_nightly_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print()
    print(
        f"Nightly shadow complete: {counts['pass']} pass, "
        f"{counts['mismatch']} mismatch, {counts['error']} error, "
        f"{counts['skipped']} skipped "
        f"in {summary['elapsed_s']:.1f}s"
    )
    print(f"Summary -> {summary_path}")
    return 0 if summary["cutover_gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

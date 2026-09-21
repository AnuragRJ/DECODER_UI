# Filename suffix semantics — what does `_001` / `_011` / `_345` mean?

**Date:** 2026-08-19 · **Type:** investigation only — no code modified.
**Question:** what does the `<NNN>` suffix in
`<ptt>_<YYYY-MM-DD>_<wmo>_<NNN>.txt` represent, and does the proposed
2902224 runner fix remain correct and generic?

---

## 1. Method

For every raw file of all 11 APF9 floats (operator bundle + `ref2902224/`
+ `uploads/`), each with its own CRC-verified transmission, we recorded:

- filename suffix and filename date;
- transmitted **PRF** (modal, CRC-ok message 1);
- reception span (first/last fix);
- **true cycle**, from two independent sources:
  - GDAC `_Rtraj.nc` MC 702 (first-fix) JULD date match (available for
    2901304, 2902203, 2902222, 2902223, 2902224 — GDAC Rtraj for 2901339
    only covers cycles 114+, 2902201/06 stop at 350/352);
  - else the Coriolis-style time fallback
    `round((first_reception − launch) / 10 d)`, calibrated against the
    GDAC-covered floats (exact to the cycle).

Hypotheses tested per file: suffix == true cycle, == PRF, == PRF+1,
== our decoded cycle, == day-of-year.

## 2. Results — per float

| float | file (date) | suffix | PRF | true cycle (GDAC/time) | suffix == true? |
|---|---|---|---|---|---|
| 2901304 (uploads) | 2010-11-30, 2010-12-15 | 000 | 16 (sentinel) | pre-deployment | **000 reused for 2 distinct transmissions** |
| 2901304 (uploads) | 2011-02-13 (launch) | 001 | 16 (sentinel) | 1 | ✓ |
| 2901304 (uploads) | 2011-02-24 / 03-06 | 002 / 003 | 2 / 3 | 2 / 3 | ✓ |
| 2901339 | 2011-12-17 (launch) | 000 | 16 | launch | 000 |
| 2901339 | 2011-12-27 … 2013-11-26 | 001…072 | 2…72 | 1…72 | ✓ (suffix = cycle) |
| 2902201 | 2025-12-25 … 2026-01-14 | 358…360 | 103–105 | 358…360 (time) | ✓ |
| 2902203 | 2025-12-26 … 2026-01-15 | 359…361 | 103–105 | 359…361 (GDAC) | ✓ |
| 2902206 | 2025-12-31 … 2026-01-20 | 359…361 | 104–105 | 359…361 (time) | ✓ |
| 2902222 | 2025-12-25 … 2026-01-14 | 327…329 | 71–74 | **327…329 (GDAC)** | ✓ |
| **2902223** | 2025-12-26 … 2026-01-15 | 326…328 | 71–73 | **327…329 (GDAC)** | **✗ = true − 1** |
| **2902224** | 2026-01-01/02 (cycle 325) | **001, 011, 011** | 69 | **325 (GDAC)** | **✗ unrelated** |
| **2902224** | 2026-01-11/12 (cycle 326) | **001, 001** | 70 | **326 (GDAC)** | **✗ unrelated** |
| 2902224 | 2026-07-20 (cycle 345) | 345 | 89 | 345 (time) | ✓ |

Key GDAC anchors (MC 702 first-fix JULD): 2902222 cyc 327 =
2025-12-25 07:25; 2902223 cyc 327 = **2025-12-26 00:01** (our file
`_326`'s surfacing); 2902224 cyc 325 = **2026-01-01 19:24:55** (exactly
the first reception of `Jan1_011`), cyc 326 = 2026-01-11 17:33.

## 3. What the suffix is

The suffix is **INCOIS's operator-assigned cycle label** — usually the
true cycle number (2901304 uploads, 2901339, 2902201/03/06, 2902222,
2902224-July), with `000` used for the launch/pre-deployment era. It is
**not** a CLS/ARGOS artifact (no match to any header field; headers carry
reception counts and message ids unrelated to the suffix), **not**
day-of-year (Jan-11 file = 001 ≠ 011), and **not** a transmission
sequence.

**But it is demonstrably unreliable — three independent failure modes:**
1. **2902223: consistently true − 1.** Sister float of 2902222 (launch
   one day apart, same era, same suffix scheme), yet `_326` labels the
   cycle GDAC numbers 327. Our decoder correctly emits 327 (PRF 71 +
   256); INCOIS's label is off by one on every file.
2. **2902224 (January 2026): unrelated to the cycle.** Cycles 325 and 326
   are both labelled `001` (plus `011` for two passes of cycle 325);
   only the July file (345) happens to equal the true cycle. Whatever
   batch/process produced the January labels, it was not counting
   cycles.
3. **Suffix reuse across distinct transmissions.** 2901304's two
   pre-deployment dumps both `000`; 2902224's two *different* surfacings
   (325 and 326) both `001`. A label is not unique per transmission.

**Coriolis never uses it.** `decode_apex_cycle_number.m` derives the
cycle from the transmitted profile number (with redundancy check), and
`move_and_rename_apx_argos_files.m` *writes* the cycle into file names —
the number comes first, the name follows. Their time-based fallback
(`round(Δt/cycleDuration)`) covers unreadable telemetry. Nothing in the
reference chain treats the suffix as authoritative.

## 4. Consequences for cycle grouping — revised recommendation

The suffix may be used as a **hint**, never as the grouping authority:

1. **A repeated suffix must never merge files.** Demonstrated harm:
   2902224 (two surfacings fused → Frankenstein profile, cycle 326
   dropped) and the latent 2901304-uploads `000` collision documented in
   `docs/DECODE_LOCALLY.md` §4. **The proposed runner fix stands
   unchanged in direction and is confirmed correct and generic.**
2. **Refinement of the proposed implementation** (so demoted keys cannot
   collide with the date-only provisional range `-1..-(n−1)`):
   demoted keys start at `CYCLE_FROM_TELEMETRY − (len(files) + 1) −
   position` (strictly decreasing, all < −n), preserving the
   transmission-order invariant the sentinel resolution relies on. Same
   six-line scope, `pipeline/runner.py` only.
3. **Why unique-but-wrong suffixes (2902223) are already harmless:** the
   decoder overrides the filename cycle with `PRF + wrap + np0` whenever
   PRF is readable (verified: our 2902223 cycles = GDAC cycles). The
   filename value only survives when PRF is unreadable — and there the
   Coriolis-consistent fix is a **time-based fallback**, not the
   filename. That is a separate, larger enhancement (recommended as a
   follow-up, not part of this fix): replace the final
   `output_cycle = cycle.cycle` fallback with
   `round((first_reception − launch)/cycle_duration)` (+ np0), exactly
   as `move_and_rename_apx_argos_files.m` does.
4. **Impact of the runner fix re-verified against the semantics table:**
   only floats with repeated suffixes change behaviour — 2902224
   (corrected: cycles 325/326/345, science parity restored) and the
   uploads-2901304 case (no longer merged; sentinel resolution handles
   the two `000` pre-deployment dumps — to be covered by a unit test).
   Floats with unique suffixes (2901339, 2902201/03/06, 2902222,
   2902223, 2902224-July file) take the identical path → byte-identical
   outputs.

## 5. Counterexamples that any alternative scheme must respect

- 2902223 `_326` ↔ true 327 (off-by-one label, unique suffix — must not
  be "corrected" by shifting; only telemetry decides).
- 2902224 Jan-1 `_001`/`_011` and Jan-11 `_001` (two different
  surfacings sharing `001`).
- 2902224 Jan-2 `_011` (same surfacing as Jan-1 `_011`, split across
  files — the richer-kept policy must still yield one cycle 325).
- 2901339 launch `_000` + 2901304 two `_000` (000 = pre-deployment era,
  not cycle 0).

## 6. Classification

- **Suffix semantics:** operator cycle label, correct on most batches,
  **unreliable in three demonstrated ways** (off-by-one float; unrelated
  batch values; reuse across transmissions). Evidence: 88 suffixed files
  across 7 floats, GDAC-anchored.
- **Proposed fix:** confirmed correct and generic; refined only in the
  demotion-key formula. No WMO branch; no assumption that the suffix is
  a cycle; telemetry (PRF + wrap + np0) remains the cycle source, with
  richer-kept dedup and (follow-up) time-based fallback.
- **Confidence: HIGH.**

*No source, test, or configuration file was modified by this
investigation.*

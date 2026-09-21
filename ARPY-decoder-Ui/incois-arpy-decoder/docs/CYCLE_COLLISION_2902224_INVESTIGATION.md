# 2902224 cycle-collision defect — investigation and proposed fix

**Date:** 2026-08-19 · **Type:** investigation only — **no code modified**.
**Scope:** the newly discovered 2902224 cycle-collision (fleet audit of
2026-08-19, §8 of `APF9_PARITY_STATE.md`): two distinct surfacings merged
into one output cycle (325), the real cycle 326 missing, 174/174 mono
science cells differing from GDAC cycle 325.

---

## 1. Evidence chain

### 1.1 APF9 manual/specification — cycle identity is telemetry, not filename

- APF9A 061810 manual p.20 ("Data Message 1"): **`PRF Profile number (wraps
  to 0 from 255)`**; the STATUS word bit `0x8000 PrfIdOverflow` flags the
  8-bit counter wrap. The transmitted profile counter **is** the cycle
  identity in the APF9 protocol; the true cycle = PRF + wrap + deployment
  offset.
- No APF9A manual defines any filename convention — `<ptt>_<date>_<wmo>_<NNN>.txt`
  is an **operator/CLS export convention only**, and nothing in the
  specification guarantees `NNN` is the cycle number.
- Our own decoder documentation states the same principle
  (`platforms/apex_argos/decoder.py`): *"The transmitted profile id is the
  primary cycle source."*

### 1.2 Coriolis source — cycle number is decoded from telemetry; filenames follow it

- `decArgo_soft/soft/sub/decode_apex_cycle_number.m` (GitHub `main`,
  fetched 2026-08-19): the cycle number is **decoded from the "Profile
  number" transmitted in the ARGOS data messages** (it reads the cycle
  files and derives the number from their content, including test-message
  handling) — never read from the file name.
- `decArgo_soft/soft/sub/get_argos_path_file_name.m`: Coriolis **constructs**
  the file name from a cycle number it already knows (`a_cycleNum` input);
  i.e. in Coriolis's chain the cycle number is authoritative and the
  filename follows it (the DAC renames incoming files per cycle), never
  the reverse.
- Conclusion: **the reference implementation never trusts a filename
  suffix over telemetry.** Any rule that merges raw files by filename
  cycle alone is our own convenience, not a Coriolis behaviour.

### 1.3 Raw telemetry — the six 2902224 files and their true surfacings

All files are single-transmission CLS dumps (project trusted parser,
`split_transmission_text` + `iter_argos_messages_from_payload`):

| file | filename cycle (suffix) | transmitted PRF (crc-ok msg1) | reception span (UTC) | true surfacing |
|---|---|---|---|---|
| `152390_2026-01-01_2902224_001.txt` | 1 | **69** | 01-01 22:37 → 22:45 | Jan-1 (cycle 325) |
| `152390_2026-01-01_2902224_011.txt` | 11 | **69** | 01-01 19:24 → 23:49 | Jan-1 (cycle 325) |
| `152390_2026-01-02_2902224_011.txt` | 11 | **69** | 01-02 00:16 → 03:11 | Jan-1/2 (cycle 325) |
| `152390_2026-01-11_2902224_001.txt` | 1 | **70** | 01-11 17:32 → 23:41 | Jan-11 (cycle 326) |
| `152390_2026-01-12_2902224_001.txt` | 1 | **70** | 01-12 00:11 → 02:09 | Jan-11/12 (cycle 326) |
| `152390_2026-07-20_2902224_345.txt` | 345 | **89** | 07-20 21:03 → 07-21 02:40 | Jul-20 (cycle 345) |

- True cycles: PRF 69 + wrap 256 = **325**; PRF 70 + 256 = **326**;
  PRF 89 + 256 = **345** (10-day cycle, launch 2017-02-16 — the same wrap
  the decoder already computes for the July file).
- The suffix `001` repeats on **two distinct surfacings** (Jan-1 and
  Jan-11) and `011` repeats within one surfacing; only `345` happens to
  equal the true cycle. The suffix is an operator batch number, not a
  cycle.

### 1.4 Current Python — exact mechanism of the merge (verified by simulation)

Code path:

1. **Discovery** (`io/rsync.py` `_ARGOS_DATE_RE`):
   `<ptt>_<YYYY-MM-DD>_<wmo>_<NNN>.txt` → `cycle = int(NNN)`. So
   Jan-1 `_001` → cycle 1; Jan-1 `_011` and Jan-2 `_011` → cycle 11;
   Jan-11 `_001` and Jan-12 `_001` → **cycle 1 (collide with Jan-1)**;
   Jul `_345` → cycle 345.
2. **Runner** (`pipeline/runner.py`, cycle-building loop):
   `cd = cycles.setdefault(key, CycleData(...)); cd.frames.append(...)`
   — files sharing a key are **merged into one `CycleData`** (3 frames for
   key 1: Jan-1 + Jan-11 + Jan-12).
3. **Decoder** (`apex_argos/decoder.py` `decode_float`):
   - `_split_multi_transmission_cycles` only splits cycles with exactly
     **one** frame (`if len(cycle.frames) != 1: out.append(cycle);
     continue`); the 3-frame bucket is passed through unsplit.
   - The bucket's messages (all three files) are redundancy-selected and
     profile-decoded as **one** cycle.
4. **Observed result of the merge (simulated with the project parser):**
   the merged bucket's selected msg1 has **PRF 69** (→ output cycle 325),
   but its sample content is **Jan-11's (PRF 70) profile truncated to 58
   levels** (Jan-11 alone decodes to 59; Jan-1 alone to 58) — a
   Frankenstein profile labelled 325. This exactly explains the audit
   findings: our mono `R2902224_325.nc` carries Jan-11 science (58
   levels), Rtraj cycle 325 holds fixes from **both** surfacings
   (JULD 27759.9…27770.1) with MC 704 +9.96 d, and the true cycle 326 is
   never emitted.
5. The duplicate-output-cycle policy (`_should_replace_existing_profile`,
   richer kept) then prefers the corrupted 3-file bucket over the
   legitimate Jan-1 bucket (key 11), so the bad profile wins.

**Root cause:** the runner merges raw files by filename-cycle key without
checking whether they belong to the same surfacing. When the suffix is
not the true cycle (2902224), two distinct surfacings are fused before
the telemetry-based cycle recovery can act.

## 2. Generic rule (proposed)

> **Never merge two raw files into one cycle on the strength of a shared
> filename suffix. Cycle identity comes from the transmitted profile id
> (PRF + wrap + np0). A file whose filename cycle is already taken is
> given its own provisional key; the existing telemetry recovery assigns
> its true cycle, and the existing per-output-cycle "richest kept"
> policy resolves any remaining duplicates.**

This is generic (no WMO branch), consistent with the spec (§1.1) and
Coriolis (§1.2), and reuses machinery that is already implemented and
tested: provisional `CYCLE_FROM_TELEMETRY` keys, PRF+wrap recovery, and
the richer-kept dedup for mono profile / trajectory / engineering per
output cycle.

## 3. Proposed minimal change (not implemented)

**File:** `src/argo_decoder/pipeline/runner.py` — cycle-building loop only
(≈6 added lines). No change to discovery, decoder, writers, or config.

Current:
```python
key = (
    cf.cycle
    if cf.cycle != CYCLE_FROM_TELEMETRY
    else CYCLE_FROM_TELEMETRY - (len(files) - 1 - position)
)
cd = cycles.setdefault(key, CycleData(wmo=wmo_int, cycle=key))
```

Proposed:
```python
key = (
    cf.cycle
    if cf.cycle != CYCLE_FROM_TELEMETRY
    else CYCLE_FROM_TELEMETRY - (len(files) - 1 - position)
)
if key in cycles:
    # A repeated filename cycle is not trustworthy: the suffix can be an
    # operator batch number rather than the float's cycle (2902224:
    # ``_001``/``_011`` repeat across distinct surfacings). Merging such
    # files would fuse two surfacings into one cycle. Give this file its
    # own provisional key and let telemetry recover its true cycle; the
    # per-output-cycle "richest kept" policy resolves duplicates.
    key = CYCLE_FROM_TELEMETRY - (len(files) - 1 - position)
    while key in cycles:
        key -= 1
cd = cycles.setdefault(key, CycleData(wmo=wmo_int, cycle=key))
```

Why this is the smallest correct change: unique filename cycles (all ten
other floats) take the identical path as today — zero behaviour change;
only repeated keys are demoted, and only when they repeat. Files of the
*same* surfacing with the same suffix (Jan-1 `_011` + Jan-2 `_011`)
simply become two candidates for the same output cycle, resolved by the
existing richer-kept policy (content identical; only redundancy union is
lost, which is not required for correctness).

(Alternative, not recommended: generalising `_split_multi_transmission_cycles`
to split multi-frame cycles by surfacing — larger change, duplicates
PRF/date parsing, touches a carefully documented splitter; higher
regression risk for the same outcome.)

## 4. Expected impact (after the change is approved and implemented)

| product | 2902224 | other 10 floats |
|---|---|---|
| Cycles | **{325, 326, 345}** (was {325, 345}); 325 = Jan-1 (PRF 69, 58 levels), 326 = Jan-11 (PRF 70, 59 levels), 345 unchanged | unchanged |
| Mono profiles | R325 science = Jan-1 (matches GDAC 325), R326 = Jan-11 (matches GDAC 326), R345 unchanged → **0 science mismatches** vs GDAC on shared levels (was 174) | unchanged (byte-identical outputs) |
| prof.nc | N_PROF 2 → 3, cycles 325/326/345 | unchanged |
| Rtraj | 325 rows: only Jan-1 fixes (MC 702/703 JULD ≈ 27759.5–27759.95); 326 rows: Jan-11 fixes (27769.9–27770.1); **MC 704 anomaly (+9.96 d) gone**; park PRES (MC 290/296) from the correct surfacing's engineering | unchanged |
| tech.nc | cycles 325/326/345 each with their own VAC/ABP; vacuum cells remain the approved `-28.009` divergence; ABP per the existing classification | unchanged |
| meta.nc | no change (meta is telemetry-independent) | unchanged |
| GDAC parity | 2902224 science goes from "174-cell mismatch" to parity; tech/vacuum/ABP classifications unchanged | unchanged |

**Regression tests to add:**
1. Unit (runner): two `CycleFile`s with the same filename cycle but
   distinct PRF payloads → not merged into one `CycleData`; decode yields
   two distinct output cycles.
2. Unit (runner): two files, same filename cycle, same PRF (same
   surfacing) → separate provisional keys, single output cycle, richer
   kept, no crash.
3. Integration: decode 2902224 from its 6 raw files → output cycles
   {325, 326, 345}; mono science vs GDAC `R2902224_325/326/345` = 0
   mismatches (N_LEVELS 58/59/59); Rtraj per-cycle fix spans; tech rows
   325/326/345.
4. Fleet byte-regression: re-decode the other 10 floats → outputs
   identical to the pre-change baseline (run-time stamps excluded);
   full `pytest` suite (1732) green.

## 5. Files modified / created this run

- Created: this report only (`docs/CYCLE_COLLISION_2902224_INVESTIGATION.md`).
- No source, test, configuration, metadata, or generated-NC changes.

## 6. Cleanup performed

- `/tmp` — removed: `fresh/` (regenerable decode outputs),
  `argo_decoder/` (runtime meta cache), `decode_apex_cycle_number.m` /
  `get_argos_path_file_name.m` (redownloadable Coriolis sources).
- `/tmp` — kept (required evidence, per instructions): `abp_raw/`
  (operator raw-telemetry bundle, 39 MB), `gdac/` (current GDAC fixtures
  incl. mono profiles, 44 MB).
- Workspace — nothing to remove (no temporary artifacts were created;
  `ref2902224/`, `phase4_reference/`, `phase5_reference/`, reports and
  docs are all required and untouched).

*Investigation complete — awaiting approval before implementing the
runner change.*

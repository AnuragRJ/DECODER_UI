# ARVOR-I Phase 4A — `_tech.nc` Product Implementation

**Date:** 2026-08-27
**Status:** COMPLETE — implementation + validation only, per directive.
Phase 4B (`_Rtraj.nc`) NOT begun.
**Authoritative mapping source:**
`docs/phase_reports/ARVOR_I_PHASE4A_TECH_MAPPING_2026-08-26.md` (§1–§8).
That report supersedes the migration doc §8 investigation sections; its
mapping, TECH_AUX routing, corrected item indexing, final row ordering,
writer layout, and 467/804 row counts were treated as source of truth and
are NOT re-investigated here.

---

## 1. Deliverables

| File | Role |
|---|---|
| `src/argo_decoder/platforms/provor_ir_sbd/arvor_i_tech.py` | Product model: 222/232 label table, `hhmm`/`mmss`/`num2str` formatters, per-emitter `store_*` row builders, NKE grounding-day fix, finalize, `build_arvor_tech_dataset`. Full mapping table as module docstring. |
| `src/argo_decoder/nc/technical_arvor.py` | ARVOR `_tech.nc` writer reusing `nc/admt.py` (`char_column`, `scalar_char`, fills, `write_admt_dataset`). APEX `nc/technical.py` untouched. |
| `tests/unit/test_arvor_i_tech.py` | 46 unit tests (label table vs BOTH vendored JSONs, formatters, gates, indexing, finalize, split). |
| `tests/integration/test_arvor_i_tech_nc.py` | 19 integration tests over both raw datasets incl. writer round-trip. |
| `scripts/validate_arvor_i_tech.py` | Formal 54-check validation; writes `validation_phase4a_tech/{6990711,7902408}_tech.nc`. |

## 2. Implementation notes (behaviour, not investigation)

* **Packet selection:** LAST Tech#1/Tech#2 of each cycle buffer (re-selected
  from `buffer.packets`; `ArvorCycle.tech1/.tech2` hold FIRST-of-buffer and
  are not used for emission). Cycle −1 buffers emit nothing.
* **Emission order per cycle** mirrors `process_decoded_data.m` case 222/232:
  packet-type counts (1001–1010) → tech1 (100–136) → tech2 (200–243) → misc
  (1012–1015); duplicates keep-first; NKE grounding-day fix (items 23/28 −= 8
  under flags 25/31 == 2) applied to the Tech#2 fields BEFORE 214/218
  emission.
* **Corrected Tech#2 expected-count indexing:** 200–211 ← items 3–14
  (the off-by-one vs items 2–13 is fixed as PROVEN in mapping §3).
* **Gates:** 135 ⇔ deep ∧ item66==1; 136 ⇔ deep ∧ item61==1 (136 value =
  `mmss(signed item73/3600)`); 212 ⇔ any of the CONVERTED pres/temp/psal
  triplet ≠ 0 (raw zero counts → pres 1000.0 ≠ 0, so the row is emitted —
  MATLAB semantics, unit-tested); 214–217 ⇔ item21>0; 218–221 ⇔ item21>1;
  223–226 ⇔ item32>0; 243 ⇔ type-7 ever seen ∧ CONFIG_IC00 ≠ 0; 1012 skipped
  when decId == 216 (not reachable for 222/232 — kept for family parity).
* **Non-deep (surface) cycles:** always rows 100–105, then the +10000 set
  (10127–10131, 11000, 10132–10134; 10135 ⇔ item66≠0; 10136 ⇔ item61≠0);
  names = `tech_param_name(id + 10000)` → `TECH_AUX_SURFACE_` prefix
  (REPLACES a leading `TECH_AUX_`). No surface cycle exists in either
  dataset; branch is unit-tested only.
* **Finalize:** zero-fill missing 1001–1010 (all on the last row's cycle,
  table-wide setdiff; 1010 needs a type-7 ever seen — none here), stable
  sort by name; final file order = cycles ascending, then alphabetical by
  `TECHNICAL_PARAMETER_NAME`.
* **TECH_AUX routing:** `1000`, `1001–1010`, `1012–1015`, `243`, and all
  +10000 names go to `ArvorTechDataset.aux_rows` (bookkept, never written);
  `META_*` dropped at write. Writer parses NO raw SBD packets.
* **Writer layout** (`create_nc_tech_file_3_1.m` parity): NETCDF3_CLASSIC;
  dims `DATE_TIME(14), STRING128, STRING32, STRING8, STRING4, STRING2,
  N_TECH_PARAM(unlimited)`; variables in MATLAB order; `HANDBOOK_VERSION`
  = `'1.2 '` (left-aligned); `DATA_CENTRE` two spaces when unknown;
  institution centre-mapped (IF→IFREMER) else `'CORIOLIS'`;
  `Conventions 'Argo-3.1 CF-1.6'`; SPACE padding throughout (verified —
  the earlier "NUL padding" observation was a read-side auto-mask
  artifact, `set_auto_mask(False)` confirms space padding, same as the
  validated APEX parity outputs).

## 3. Validation results (both floats, formal script: 54/54 PASS)

| Check | 6990711 (decId 222) | 7902408 (decId 232) |
|---|---|---|
| tech rows | **467** | **804** |
| aux rows bookkept | 99 | 182 |
| cycles in file | 1–7 (67/67/67/67/66/66/67) | 1–12 (67 each) |
| cycle 13 | — | no rows (no Tech#1/2; counts/misc are aux-only) |
| param 136 cycles | 1,2,3,4,7 (5/6 stale GPS) | 1–12 |
| never emitted | 135, 214–221, 223–226, 243, all 10xx | same |
| ordering | cycles ↑, alphabetical within cycle | same |
| layout | NETCDF3_CLASSIC, dims/vars/attrs/dtypes per spec, space padding | same |
| round-trip | file rows == product rows (names/values/cycles) | same |

Cycle-1 value spot-checks (13 params incl. 100/101/102/111/127/128/129/132/
136/200/204/212/236/242) re-derived independently from packet `fields` —
exact match on both floats. Final file rows are the alphabetically-last
names within the last cycle (e.g. `VOLTAGE_BatteryPumpStartProfile_volts`),
with the `NUMBER_*_COUNT` packet counts sitting inside each cycle — this
follows from cycle-ascending + alphabetical final ordering.

Outputs: `/home/user/argo_workspace/validation_phase4a_tech/6990711_tech.nc`
(120 KiB), `7902408_tech.nc` (206 KiB).

## 4. Test and lint status

* New tests: 46 unit + 19 integration = **65**, all passing.
* Full suite: **1954 passed** (1889 pre-existing after the 08-26
  mapping-report validation — the Phase-4A step-1 baseline was 1887 before
  those +2 — plus 65 new). No existing test weakened or deleted.
* `ruff check` and `ruff format` clean on all five changed files.
* mypy not run (per standing instruction).

Unit-suite coverage highlights: label table asserted against BOTH vendored
JSONs (`_techParamName/` 222 and 232 — byte-identical); id-range and +10000
naming (incl. `TECH_AUX_` replacement); `hhmm`/`mmss`/`num2str` edge cases
(neg→+24 rollover, 60-carries, `"- MM:SS"`, s==0 → HHMM); t1/t2 deep and
surface emission orders with every gate (incl. 212 converted-triplet
semantics, 243 ice gate); corrected 200–211 ← items 3–14 mapping; grounding
day fix; 1001–1010 counts; 1012/decId-216 skip; misc rows; finalize
(zero-fill + stable sort); tech/aux split.

## 5. Discrepancy ledger

Empty — every emitted row/value is PROVEN from the mapping report's emitter
read. Two apparent anomalies during validation were both resolved as
read-side/expectation artifacts, recorded to prevent re-litigation:

1. "NUL padding" in written char columns — false alarm; netCDF4 auto-mask
   renders the `b" "` fill as masked/NUL. Unmasked reads show space padding,
   byte-identical convention to validated APEX outputs. No writer change.
2. "Final row should be a packet count" — wrong expectation; final order is
   alphabetical within cycle, so `VOLTAGE_*` legitimately closes the file.

## 6. PROVEN / INFERRED / UNKNOWN

* PROVEN: mapping table, gates, indexing fix, grounding fix, finalize
  semantics, writer layout/attrs, row counts 467/804, all emitted values.
* INFERRED: none this phase (nothing emitted without a PROVEN source).
* UNKNOWN: none.

## 7. Limitations (explicitly classified)

* **[DATA-COVERAGE] Telemetry events absent from the evidence datasets.**
  No type-7 packet exists in either dataset, so 1010, 243, and the ICE
  paths are inert on real data (unit-tested with synthetic fields only);
  grounding/emergency rows (214–221/223–226) are implemented and
  unit-tested but not exercised by either float (item21 == item32 == 0);
  no surface (non-deep) cycle exists, so the +10000 branch is
  unit-tested only. No values were fabricated to cover these gaps.
* **[TOOL-AVAILABILITY] Argo FileChecker not run.** The FileChecker jar is
  not present in the environment and has not been supplied; the formal
  GDAC format-compliance check therefore could not be executed.
  Mitigation: MATLAB-parity validation (layout, ordering, values vs the
  Coriolis chain, plus layout conventions shared with the FileChecker-
  validated APEX parity outputs). Remains open until the jar is provided.
* **[DATA-COVERAGE] No direct ARVOR-I GDAC comparison.** The workspace
  holds no published ARVOR-I `_tech.nc` reference files for 6990711 or
  7902408 (the only GDAC tech references are APEX, under
  `phase5_reference/gdac_reference_dataset/`), so no row-by-row diff
  against GDAC-published ARVOR outputs was possible. Parity was
  established against the Coriolis MATLAB chain semantics and the
  APEX-validated ADMT layout only. Closes if/when ARVOR-I GDAC reference
  files are supplied.

## 8. Next steps

STOP after Phase 4A, per directive. Phase 4B (`_Rtraj.nc`) awaits explicit
instruction.

---

## Addendum (2026-08-27, later same day): regeneration under
`process_remaining_buffers=True`

Products regenerated by re-running `scripts/validate_arvor_i_tech.py`
(writes into `validation_phase4a_tech/`); **54/54 checks passed**,
including the updated aux-bookkeeping expectation (99 / 208).

* **6990711 `_tech.nc`: byte-identical** to the prior file (`cmp`).
  No trailing buffers → flag flip is a no-op here.
* **7902408 `_tech.nc`: content-identical** to the prior file (all
  variables, attrs, and global attrs compared equal; only the
  deterministic content is present, so bytes match as well).  File rows
  remain 804 (cycles 1–12 × 67): GDAC-layout tech files never contain
  `TECH_AUX`/`META` names, and cycles 1–12 buffers were already complete
  under `False`.
* **What did change** is the bookkept (non-file) aux-row count:
  182 → **208** — cycle 13 13→12 (its `ParameterMessage2Received` count
  row re-attributed to cycle 15), cycle 14 0→13, cycle 15 0→14
  (c1–12 ×14 unchanged, plus 1 zero-filled param-1010 row).  Aux rows
  are recorded, not silently discarded (no-discard rule preserved).

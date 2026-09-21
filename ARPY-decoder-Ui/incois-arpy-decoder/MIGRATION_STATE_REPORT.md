# MIGRATION STATE REPORT

**Prepared:** 2026-08-17 (new chat, session 2)
**Task:** reconstruct the project state from the downloaded workspace before continuing APF9 work.
**Method:** everything below was re-verified in this session from the actual workspace (fresh decode, fresh test/lint runs, direct inspection of code, manuals, Coriolis sources, and GDAC references). No source file was modified. The only files added: this report and the fresh decode under `/tmp/fresh`.

---

## 1. Workspace status

- **Archive:** Google Drive file `1KtJYga9zsWMx1Qio8WTMb3MOFshaDfVf` (125 026 847 B zip, 7 224 entries) downloaded and unpacked **exactly as provided**; no CRC errors; nothing re-ordered or filtered.
- **Repository root:** `argo-decoder-python/` (no `.git` metadata present — expected; the drive export has none).
- **Key contents (all present):**
  - `src/argo_decoder/` — 72 Python sources; active platform `platforms/apex_argos/`.
  - `tests/` — unit/integration/golden suites; `config/` — registry CSVs + four-CSV metadata (`config/metadata/{meta,sensor-info,calib,config_params}.csv`, 5+ floats).
  - `docs/` incl. **`docs/reference_extracts/`** — 21 APF9A firmware-manual text extracts + 15 ApexCoDecoder spreadsheet extracts + Coriolis decoder-manual V1.10 extract. (The earlier "manuals unavailable / LFS stubs" conclusion is **superseded**: the extracted text is here and was used this session. The original LFS PDFs live separately in `apf9_docs/LFS-documents-found/`.)
  - `phase4_reference/raw/raw-files/` — raw ARGOS telemetry, **7 APF9 PTTs only**; `phase5_reference/gdac_reference_dataset/` — GDAC `_meta/_tech/_Rtraj` + selected profiles for 2901339, 2902201, 2902203, 2902206, 2902222, 2902223.
  - `parity_fresh_nc3/` — pre-Part-A outputs (08-14 audit; 336 files, all NC3) + 10 `_meta.nc` FileChecker reports.
  - `Coriolis-data-processing-chain-for-Argo-floats-container/` (sibling) — MATLAB reference, read-only, 523 `.m` files.
  - Aux: `apf9_docs/`, `profan/`, `ref2902224/` (2902224 GDAC + raw), `uploads/` (5 early 2901304 raw files + image).
- **Gap vs the 08-14 fleet audit:** raw telemetry for **2901305 (PTT 102526) and 2901350 (PTT 75415) is NOT in the repo** (only 7 of 9 in-repo-decodable floats). Those two floats' parity numbers below rest on the committed 08-14 report, not on a fresh local run.

## 2. Current code state (what Part A actually did)

Part A is **present in source** and confined to the claimed files:

| File | Part A change | Verified |
|---|---|---|
| `platforms/apex_argos/engineering.py` | `APF9_ENG_1010.msg3_vacuum_offset = 0`; `decode_engineering_message_3()` reads msg3 payload byte 0 → `msg3_vacuum_counts`, byte 1 → `msg3_air_bladder_counts` (only when offset set; 1005 unchanged) | ✅ present |
| `nc/technical.py` | `_ABP_MSG3_DECODERS = {1010}` (ABP from msg3); `_VACUUM_SOURCE_ATTRS = {1001/1005: "vacuum_counts" (msg1), 1010: "msg3_vacuum_counts"}`; `_VACUUM_SCALE_OFFSET = (0.293, −29.767)`; emission branches for both parameters | ✅ present |
| `tests/unit/test_apex_engineering.py` | +3 msg3-head tests (1010 reads VAC/ABP; 1005 doesn't; park sample undisturbed) | ✅ present |
| `tests/unit/test_technical_nc.py` | +3 tests (ABP msg3-on-1010; ABP msg1-on-1005; vacuum source byte differs by firmware) | ✅ present |

**The 1005 vacuum change is NOT present (reverted as claimed):** 1005 still reads message-1 payload byte 9 (`vacuum_counts`) and matches GDAC 994/994 on 2901339 (all shared `(cycle,name)` rows, incl. every vacuum row). No msg3-based vacuum on 1005.

**Stale code-internal docstrings that contradict the implementation** (documentation debt, no behaviour effect): `nc/technical.py` module docstring ("message 1 ABP firmware 061810 only"; vacuum "not emitted") and `FIRMWARE_LIMITED_TECH_PARAMETERS` ("It still is not emitted for 1010") both describe the pre-Part-A state. `_ABP_VERIFIED_DECODERS` no longer exists anywhere.

## 3. Part A claims — re-verified this session (fresh decode, current code)

Fresh decode of the five 1010 floats (`--registry config/metadata`, 4-CSV backend) compared against committed GDAC `_tech.nc`:

| Claim | Result |
|---|---|
| `PRESSURE_AirBladder_COUNT` previously absent, now present | ✅ all 5 floats now publish **14/14** names (was 12) |
| ABP 8/12 exact, 4 differ by exactly one count | ✅ **exactly reproduced**: 2902203 3/3; 2902206 2/3 (+1 cyc361 122 vs 121); 2902222 1/3 (+2 cyc328/329 123 vs 122); 2902223 2/3 (+1 cyc329 125 vs 126) |
| ABP ±1 = copy-selection, not byte location | ✅ raw msg3 ABP bytes vary between copies (e.g. 2902222 cyc328: {96:1, 122:8, 123:56, 124:32}); **GDAC's value always exists among the transmitted copies**; our modal selection picks a different copy on 4 cells |
| Vacuum now emitted, 12 differences | ✅ 12/12 shared cells differ (3 cycles × 4 floats); GDAC value is **frozen −28.009** (349/350, 366/374, 361/361, 344/348, 341/347 rows) |
| **New, stronger evidence found:** our decoded vacuum equals GDAC's few **non-frozen** values **exactly** on the same floats' other cycles: 2902201 cyc339 −5.741, 2902222 cyc26/30/34/36 −6.327, 2902223 cyc11/12 −6.034 & cyc156 −5.448 — all reproduced bit-for-bit from raw msg3 byte 0 (80/82/83/81 counts). | ✅ |
| Only the 5 1010 `_tech.nc` changed | ✅ variable-by-variable vs `parity_fresh_nc3`: meta/Rtraj/prof/profiles byte-identical (run-time stamps aside) on all 10 floats; 1005 tech files byte-identical; 1010 tech differs **only** by the two added names |
| 1005 ABP matching / 1005 vacuum 7 cells | ✅ 2901339 994/994 incl. ABP; vacuum parity holds there. The 7-cell 1005 residue (2901328×6, 2901305×1) is documented in the 08-14 report; 2901328's GDAC ref is not committed, so not re-measurable in-repo |
| 1005 vacuum reverted | ✅ consistent: message-1 path active; 2901339 exact |
| Tests 1726 → 1732 | ✅ `pytest -q` → **1732 passed** (the 08-14 audit documents the 1726 baseline) |
| Ruff / format clean | ✅ `ruff check` clean; `ruff format --check` 131 files clean |
| mypy clean | ⚠️ **not reproducible**: see §7 |
| 20/20 FileChecker accepted | ⚠️ only **10/10 `_meta.nc` FILE-ACCEPTED** reports are committed (FileChecker `-r1324`, Spec `-r1181`); no jar and no `_tech.nc` filecheck reports in-workspace, so "20/20" cannot be confirmed here |
| Output NC3 | ✅ fresh decode 234/234 files `NETCDF3_CLASSIC` (verified programmatically) |

## 4. Evidence chain for the Part A byte mapping (re-verified)

1. **APF9A 110613 manual p.25 ("Data Message 3 – N")**: spec bytes `0 CRC, 1 MSG, 2 VAC, 3 ABP, 4–5 PMT`, then park sample first (T,S,P × 2 B) — i.e. **payload bytes 0 = VAC, 1 = ABP** (payload excludes CRC+MSG); park sample T at payload 4. Matches `msg3_vacuum_offset=0`, ABP at +1, `park_sample_offset=4` exactly. ✅
2. **ApexCoDecoder 110613_090413 rows 189–194** ("Data #3" section): byte 03→VAC (techId **1021**, `PRESSURE_InternalVacuumParkEnd_inHg`), byte 04→ABP (techId **1022**, `PRESSURE_AirBladder_COUNT`), byte 05→PMT. Same offsets, spreadsheet numbering. ✅
3. **Vacuum conversion** `V = counts × 0.293 − 29.767` with worked example `0x56 → 86 → −4.5 inHg`: present in **both** the 061810 manual (p.28) and the 110613 manual. `_VACUUM_SCALE_OFFSET` matches. ✅
4. **Coriolis allow-lists** `decArgo_soft/config/_techParamNames/_tech_param_name_{1005,1010}.json`: both contain `PRESSURE_AirBladder_COUNT` and `PRESSURE_InternalVacuumParkEnd_inHg` (1010: dec=1021/1022). `PRESSURE_InternalVacuum_inHg` is the INCOIS-published spelling (Coriolis 1005 list lacks it — the INCOIS vocabulary wins for emission, as the module documents). ✅
5. **Not verifiable in this checkout:** the cited Coriolis lines `decode_data_apx_10.m:784/838`, `decode_data_apx_1_5.m:1122`, `sensor_2_value_for_apex_apf9_vacuum.m:23` — those files are **absent from the container snapshot** (it holds `decode_apex_2_{csv,nc}.m` etc. but not the `decode_data_apx_*` routines). The 07-28 audit's dispatch reference (`decode_apx_argos.m` case 1005/1010 with firmware comments) is also not in this snapshot; it was verified against a `/tmp/corio` clone per `DECODER_ROUTING_AUTHORITY.md`. Flagged: re-verify against the current Coriolis GitHub before treating those line numbers as ground truth.

## 5. Routing finding (verified, matches the briefing)

`docs/DECODER_ROUTING_AUTHORITY.md` (dated 2026-08-17 — newest doc in the workspace) + code `multi_csv_loader.py:87–92, 626–627, 703`:
- `Float subtype` (1010/1021) = Argo `DAC_FORMAT_ID`/`PR_VERSION` — **never** a routing key; wrong on 11/11 floats.
- Routing = `sensor-info.csv` `firmware revision number` → zero-padded → `FIRMWARE_TO_DECODER`: **061810→1005** (DIRECT + runtime-verified), **110613→1010** (DIRECT), **091515/091615→1010** (DERIVED + runtime-verified; absent from Coriolis), also 090413/102015/100410/020811→1010.
- `dac_format_id` is output-only (builder/models/metadata_file); unknown firmware fails closed (`decoder_id = 0`).
- Published `FIRMWARE_VERSION` (`firmware date/software date`, e.g. 020811 vs 061810) must never route.

## 6. Current APF9 fleet/parity status (reconstructed)

| Area | State |
|---|---|
| Floats | 10 decodable; **7 decodable in-repo** (2901304, 2901328, 2901339, 2902201/03/06/2222/2223); 2901305/2901350 raw missing; 2902224 metadata-only |
| Science | 48 993/48 993 shared valid cells, **0 mismatches**; 119 recovered levels; 0 lost (08-14 audit) |
| `_meta.nc` | 65/65 vars, sequence identical 10/10; FileChecker 10/10 accepted vs GDAC 10/10 rejected (`SENSOR_MAKER` DRUCK/KISTLER = approved divergence); START_DATE/END_MISSION_DATE/calib-precision = source gaps; FIRMWARE/MANUAL zero-padding = expected |
| `_tech.nc` 1005 | 14/14 names; 2901304 322/322 exact; 2901339 994/994 (fresh); 9 fleet-wide value cells (7 vacuum + 2 FLAG) pre-Part-A — **now 7 vacuum (1005) + 12 vacuum (1010, vs frozen −28.009) + 4 ABP ±1 + 2 FLAG** |
| `_tech.nc` 1010 | **14/14 names after Part A** (was 12/14 — the previously documented "parameter-count gap" is closed) |
| `_Rtraj.nc` | 102 vars v3.1; 2901304 536/536 exact incl. PRES/JULD; MC0 JULD = GDAC defect (2433282.5, not copied); C3 JULD anchor (first-fix vs ascent-end, 0.08–0.36 d) open on 1010; 2901305/2901328 GDAC files are legacy v2.2 |
| Profiles | 64 vars; DATA_MODE R vs D (expected); `*_ADJUSTED` fill required by UM §2.2.5; QC residuals all delayed-mode/fill-related |
| NC3 | 100 % everywhere (fresh 234/234; parity_fresh_nc3 336/336) |

## 7. Tests / lint / type-check / FileChecker — actual current state

| Check | Result this session | Notes |
|---|---|---|
| `pytest -q` | **1732 passed** | includes golden suite; ~82 s |
| `ruff check src tests scripts` | clean | |
| `ruff format --check src tests scripts` | clean (131 files) | |
| `mypy --strict src` | **4 errors** in `nc/admt.py:304`, `nc/multi_profile.py:442/447/463` | reproducible on **both** mypy 1.20.2 and 2.3.1 with the installed deps (numpy 2.5.2, xarray 2026.7.0); **files untouched by Part A**; the two Part A files are mypy-clean. Likely stub-version drift (no lockfile in repo); the previous agent's "clean" run is not reproducible in this environment. Not a Part A regression — but the repo's claimed baseline is stale |
| FileChecker | 10/10 `_meta.nc` FILE-ACCEPTED (committed reports, `-r1324`/`-r1181`) | jar not in workspace; tech/prof filecheck results absent |

## 8. NC3 status

Confirmed: all outputs are `NETCDF3_CLASSIC` (fresh 234/234 this session; parity_fresh_nc3 336/336 per 08-14 report; GDAC references checked are also NC3). The Part A change did not alter the format.

## 9. Open / closed issue register (reconstructed, with deltas from the briefing)

**OPEN:**
1. **1010 vacuum vs GDAC −28.009 (12 cells)** — GDAC's value is a frozen constant; **our values exactly match GDAC's own non-frozen values** on 4 floats. New lead for classification: `−28.009 = 6 counts × 0.293 − 29.767` exactly — i.e. GDAC's placeholder is the conversion of **counts = 6**. Whether 6 is a real byte occasionally transmitted or a processing default needs one targeted check.
2. **1010 ABP ±1 count (4 cells)** — copy-selection rule; GDAC's value is always one of the transmitted copies; class D (unknown DAC selection rule).
3. **1005 vacuum (7 cells)** — 2901328×6 (+44.655 vs −25.665; GDAC −25.665 implies counts 14, in none of the CRC-valid copies), 2901305×1. Irreducible from current telemetry; classified UNKNOWN.
4. **FLAG_ProfileTermination_hex copy-selection** — 2901304 cyc20 GDAC `61` unreachable (copies split 6×0x0601 / 4×0x0001; 0x0061 in none); 2901305 cyc27 genuine 0x0001-vs-0x0601 split; 1 cosmetic width (1D vs 01D). **Designated next major investigation in the briefing.**
5. **JULD / profile timestamp precedence** — C3 anchor (first Argos fix vs computed ascent end) on 1010; MC 600/700 ≤50 s reference-instant. Later.
6. **Battery tech-parameter naming** (4 names vs Coriolis 1005) — deferred, class D; no longer blocked on the manual (extracts now available) but still requires a deliberate spec-vs-GDAC decision.
7. **Calibration precision (3 s.f.)** — source-data limitation.
8. **END_MISSION_DATE (3 cells)** — operator/source-data limitation (Coriolis: database lookup, never derived).

**CLOSED / RULED OUT (verified):**
- START_DATE — investigated; not a decoder issue (2901304 exact; 5 floats empty by design, UM §2.4.9 not mandatory; needs operator `start date` column).
- C2 schedule chain — not a modelling error (0.0 s vs GDAC when cycle 1 present; `STATUS='9'` acceptable; Coriolis assigns 0 of 7 fields for this family).
- Part 1 LAT/LON "diffs" — comparison artefact; 266/266 fixes identical by timestamp.
- MC 0 JULD — GDAC defect (un-subtracted 1950 epoch), not copied.
- 480 h schedule chain on 2901304 — GDAC defect (single float), not copied.
- TEST014 sensitivity (4 cells) — INCOIS rule unknown; reproducing it costs 18 false positives; not a bug.
- `_tech.nc` 14-name restriction — required parity, confirmed NOT A BUG (assumption-audit Rev-2; Rev-1 recommendation withdrawn).

## 10. Contradictions / questionable previous conclusions (flagged)

1. **07-28 completion report says "Message 3 byte 3 on 1010 is ABP, not VAC"** — Part A supersedes this: msg3 payload byte 0 is **VAC** (matches GDAC's non-frozen vacuum exactly) and byte 1 is **ABP** (matches GDAC ABP). The earlier conclusion read only the ABP byte and mislabelled the pair. The 07-28 log entry and `APF9_COMPLETION_REPORT.md` §8 still describe the older, now-corrected reading.
2. **Stale state docs:** `APF9_PARITY_STATE.md` (08-14), `DECODER_ASSUMPTION_AUDIT.md` (08-14, "`_ABP_VERIFIED_DECODERS` gating"), `handoff.md` (08-12) and `OPEN_ISSUES_2901304.md` all predate Part A (1010 "12/14", "withheld") and must not be quoted as current.
3. **`IMPLEMENTATION_PROGRESS.md` has NO Part A entry** — the last entry is the SENSOR_MAKER fix; the append-only engineering log was not updated for Part A. Documentation debt to repair when the next change lands.
4. **mypy "clean" claim not reproducible** (see §7) — toolchain drift, files untouched by Part A.
5. **"20/20 FileChecker" not verifiable** — only 10/10 meta reports committed.
6. **In-repo GDAC fixtures are partial** — `_tech`/`_Rtraj` references exist for only 6 floats (2901339 + 5×1010); the 1005 vacuum/FLAG cells on 2901304/05/28/50 are only reproducible if GDAC is re-fetched (network) or the fixtures are committed.

## 11. Recommended next investigation (independent of the previous ordering)

**Priority 1 — close the 1010 vacuum question (small, high-value).** Verify the `−28.009 = 6 counts` lead: scan raw msg3 payload byte 0 across all 1010 archives for the value 6 (and 0xFF/absent patterns); check whether INCOIS's −28.009 appears on a cycle-boundary pattern (e.g. before/after some processing change). If counts=6 never appears in telemetry, GDAC's −28.009 is a processing-side placeholder → classify **PROVEN GDAC ERROR (approved divergence)** or **GDAC-side unknown algorithm (class D)** with a written decision, per the project rules.

**Priority 2 — ProfileTermination flag / copy-selection** (the briefing's designated next major investigation): 2901304 cyc20 (in-repo) is fully analysable now: 6×0x0601 vs 4×0x0001 CRC-valid copies; GDAC `61` (0x0061) in no copy. Determine whether any copy-selection rule over the full transmission set (not just message-1 copies) can produce `0x0061`; if not, document "unreachable, do not fabricate" and close.

**Priority 3 (data, not code):** commit GDAC `_tech/_Rtraj` for 2901304/2901305/2901328/2901350 so the 1005 vacuum/FLAG cells become reproducible in-repo; obtain 2901305 & 2901350 raw telemetry; obtain an early-life archive for one 091x15 float (closes C2/C3 + drift rate together).

**Maintenance (no behaviour change):** append the missing Part A entry to `IMPLEMENTATION_PROGRESS.md`; refresh the stale docstrings in `nc/technical.py` and the stale passages in `APF9_PARITY_STATE.md`/`DECODER_ASSUMPTION_AUDIT.md`.

---

*Nothing in `src/`, `config/`, or `tests/` was modified during this reconstruction.*

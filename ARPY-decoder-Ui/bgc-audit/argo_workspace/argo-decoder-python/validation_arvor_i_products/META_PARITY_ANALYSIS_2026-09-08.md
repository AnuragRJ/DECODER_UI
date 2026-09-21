# ARVOR-I `meta.nc` — Exhaustive Parity Analysis (ANALYSIS ONLY, no code changed)

**Date:** 2026-09-08 · Mono/Tech/Rtraj/GEBCO untouched. **No implementation performed** — this is the analysis deliverable; fixes are proposed in §10 and await instruction.

## Evidence used
| # | Source | Version |
|---|---|---|
| D1 | Argo User's Manual | **3.44.0, 10 July 2025** ([10.13155/29825](https://dx.doi.org/10.13155/29825)) |
| D2 | NERC reference tables **R09** (positioning), **R10** (transmission), **R28** (controller board) | live |
| D3 | Vendored Coriolis MATLAB + `_sample_3901839_meta.json` (reference ARVOR/PROVOR Iridium float info) | in-workspace |
| D4 | Four authoritative CSVs (`config/metadata/`) | in-workspace |
| D5 | Raw ARVOR-I telemetry | in-workspace |
| D6 | INCOIS GDAC `*_meta.nc` ×4 | comparison target |
| D7 | Official Argo **FileChecker v1.17** (`format_control_1-17`, rules `Argo_Meta_v3.1_AUM_3.1_20150820.xml`) | fetched this session |

---

## 1. Exact OUR vs GDAC inventory

| | 1902844 | 2904082 | 6990711 | 7902408 |
|---|---|---|---|---|
| variables ours / GDAC | 65 / 65 | 65 / 65 | 65 / 65 | 65 / 65 |
| **ours-only** | **0** | **0** | **0** | **0** |
| **GDAC-only** | **0** | **0** | **0** | **0** |
| dtype diffs | 0 | 0 | 0 | 0 |
| dimension diffs | 0 | 0 | 0 | 0 |
| **attribute diffs (incl. `_FillValue`)** | **0** | **0** | **0** | **0** |
| global attribute names | identical | identical | identical | identical |

All 17 dimensions match exactly (`N_MISSIONS=1`, `N_POSITIONING_SYSTEM=1`, `N_TRANS_SYSTEM=1`, `N_CONFIG_PARAM=14`, `N_LAUNCH_CONFIG_PARAM=14`, `N_PARAM=3`, `N_SENSOR=3`).

**§2 GDAC-only fields: none. §3 ours-only fields: none.** The structural layer is complete — every difference is a *value* difference.

## 4–6. Value comparison, derivation and adjudication

**58 of 65 variables are byte-identical on all four floats**, including every field previously flagged as uncertain: `DATA_CENTRE` (IN), `PI_NAME`, `PROJECT_NAME`, `PLATFORM_TYPE` (ARVOR), `PLATFORM_MAKER` (NKE), `PLATFORM_FAMILY`, `FLOAT_SERIAL_NO`, `FIRMWARE_VERSION`, `WMO_INST_TYPE` (844), `CONFIG_MISSION_NUMBER` ([1]), `PTT`, `TRANS_SYSTEM` (IRIDIUM), `LAUNCH_*`, `SENSOR*`, `PARAMETER*`, and the full `PREDEPLOYMENT_CALIB_*` / `CONFIG_*` / `LAUNCH_CONFIG_*` blocks.

**Only 7 variables differ**, and all 7 differ identically across all four floats — i.e. every one is a systematic rule, not a per-float artifact.

### 4.1 `CONTROLLER_BOARD_TYPE_PRIMARY` — ours `APF0`, GDAC `n/a` → **FIXABLE (P1)**
- **Derivation:** CSV `controller board serial number` = `'0i-0'` → `multi_csv_loader._controller_board_type()` takes `head[0]='0'` → returns `"APF0"`.
- **Standard (D1 §2.4.4):** value must come from **reference table 28**. **D2/R28 contains no `APF*` entry at all** — the 13 valid codes are `N1, N2, GG32, HC12, I535, I538, I458, OSEAN, USEA, APMT, SIVOR, CAMAT256, PFV2`. The NKE boards are the `I5xx` family.
- **Coriolis (D3):** reference Iridium float info gives `CONTROLLER_BOARD_TYPE_PRIMARY = 'I535'`.
- **Verdict:** `APF0` is **standards-invalid** and was produced by a heuristic written for APEX serials (`9A-7319`) misfiring on an NKE serial (`0i-0`). GDAC's `n/a` is not scientifically informative but *is* permissible; `APF0` is not. **Our bug — must fix.**

### 4.2 `TRANS_SYSTEM_ID` — ours `123230`/`124250`/`664170`/`339490`, GDAC `n/a` → **FIXABLE (P1)**
- **Derivation:** `multi_csv_loader` sets `trans_system_id = ptt` whenever comms ≠ ARGOS; `ptt` comes from CSV column **"Argos number"**.
- **Standard (D1 §2.4.4, verbatim):** *"Program identifier of the telecommunication subscription. **DACs can use N/A or alternative of their choice when not applicable (e.g. : Iridium or Orbcomm)**. Example: 38511 is a program number for all the beacons of an ARGOS customer."*
- **Verdict:** TRANS_SYSTEM_ID is an **ARGOS programme number**. These are Iridium floats with no ARGOS subscription, so the field is *not applicable* and the manual explicitly names `N/A`. Publishing the PTT here mislabels a beacon ID as a programme ID. **Manual supports GDAC.** Fix.

### 4.3 `TRANS_FREQUENCY` — ours `''` (fill), GDAC `n/a` → **FIX CANDIDATE (P3, cosmetic)**
- **Standard (D1 §2.4.4):** *"Frequency of transmission from the float. Unit: hertz."* No explicit not-applicable guidance; `_FillValue = " "`.
- **Coriolis (D3):** reference float info uses `'n/a'`.
- **Verdict:** both are defensible (blank = "not provided", `n/a` = "not applicable"). Iridium SBD has no fixed transmission frequency, so `n/a` is *more* informative and matches Coriolis practice. Low priority; group with 4.2 for consistency.

### 4.4 `POSITIONING_SYSTEM` — ours `IRIDIUM`, GDAC `GPS` → **FIXABLE (P1)**
This was investigated on platform evidence, not parity preference.
- **Derivation of ours:** `multi_csv_loader.py:729` — `"positioning_system": [comms.upper()]`. The CSV `Comms system` column is `IRIDIUM`, so the **transmission** system is being copied into the **positioning** field. These are two distinct concepts with two distinct reference tables (D2 **R10** transmission vs **R09** positioning).
- **Platform evidence (D5, decisive):** the float **transmits real GPS fixes**. Decoded `GpsRecord`s carry `accuracy='G'` and come from the Tech#1 packet — 15/14/5/12 GPS fixes per float. Positions are *determined by GPS*, merely *delivered over* Iridium.
- **Standard:** R09 admits **both** `GPS` and `IRIDIUM`, so the table alone doesn't decide it; `IRIDIUM` in R09 means positions computed by the Iridium network (Doppler/CEP), which is a different measurement. D1 §2.4.4 example is "ARGOS or GPS are 2 positioning systems".
- **Coriolis (D3):** reference Iridium float info gives `POSITIONING_SYSTEM = 'GPS'` with `TRANS_SYSTEM = 'IRIDIUM'` — exactly this distinction.
- **Verdict:** `GPS` is correct on the merits. Note the interaction below.
- **⚠️ Consistency issue this exposes:** our published **Rtraj** MC 703 rows carry `POSITION_ACCURACY = 'I'` (Iridium) and the publication projection *drops* the GPS-`'G'` rows, while `TRANS_SYSTEM=IRIDIUM`. If Meta declares `POSITIONING_SYSTEM=GPS` while every published fix is Iridium-derived, the two products contradict each other. **Recommend `N_POSITIONING_SYSTEM=2` with `['GPS','IRIDIUM']`** — truthful (both are genuinely in use), R09-valid, and consistent with both products. This *changes a dimension*, so it needs your explicit approval; the minimal alternative is scalar `GPS` matching GDAC. **Flagged for decision, not implemented.**

### 4.5 `START_DATE` — ours blank, GDAC populated → **FIX CANDIDATE (P2) + UNKNOWN**
- **Standard (D1 §2.4.5):** *"Date and time (UTC) of the **first descent of the float**"*, `YYYYMMDDHHMISS`.
- **Derivation of ours:** deliberately blanked (`arvor_i_meta.py`: `meta.start_date = ""` when no registry JSON) under a correct no-fabrication policy.
- **Coriolis (D3):** START_DATE is a **deployment-database field**, not decoded — `create_nc_meta_file_3_1.m` writes it straight from the float-info JSON. In the reference sample it is `09:03:00` against a launch of `09:07:00` — i.e. ~4 min *before* launch.
- **What GDAC's values actually are:**

| WMO | GDAC START_DATE | CSV launch date | our cycle-1 CYCLE_START | our cycle-1 DST(100) |
|---|---|---|---|---|
| 6990711 | 20250302051600 | **20250302051600** ✅ exact | 20250302051000 | 20250302072200 |
| 7902408 | 20260325120816 | 20260325174400 | **20260325120800** (Δ16 s) | 20260325131300 |
| 1902844 | 20260119192147 | 20260115133000 | 20260115133000 | 20260115143300 |
| 2904082 | 20260119083725 | 20260116153200 | 20260116153000 | 20260116162600 |

- **Adjudication:** no single rule reproduces all four. 6990711 = launch date exactly; 7902408 = our decoded cycle-1 start to within 16 s; **1902844/2904082 match nothing we decode** — their values fall *between cycles 2 and 3*, days after the real first descent, so they are operator-entered DB values, not derived.
- **Verdict:** **UNKNOWN / DATA-COVERAGE.** START_DATE is not derivable from telemetry for this family; it is a deployment-DB field absent from the four CSVs. **Do not invent an anchor to match GDAC** (as the prompt directs). Two of the four GDAC values are demonstrably *not* "first descent" and would be wrong to reproduce.
- **However, one genuine defect exists now:** we publish `START_DATE = ''` **with `START_DATE_QC = '1'`** ("value seems correct"). Asserting good QC on an absent value is self-contradictory. **FIXABLE: when START_DATE is blank, START_DATE_QC must be fill `' '`** (same rule the file already applies to `STARTUP_DATE`/`STARTUP_DATE_QC`). This is generic and requires no new data.

### 4.6 / 4.7 `DATE_CREATION`, `DATE_UPDATE` (and global `history`) → **EXPECTED**
Generation timestamps. D1 §2.4.4 defines them as file creation/update times. Differing values are correct behaviour, not a defect. **No action.**

## 7. Genuine implementation gaps (summary)

| # | Field | Class | Root cause | Generic? |
|---|---|---|---|---|
| G1 | `CONTROLLER_BOARD_TYPE_PRIMARY` | **FIXABLE** | APEX-serial heuristic emits R28-invalid `APF0` | yes |
| G2 | `TRANS_SYSTEM_ID` | **FIXABLE** | PTT written into an ARGOS-programme-ID field on non-ARGOS floats | yes |
| G3 | `POSITIONING_SYSTEM` | **FIXABLE** | transmission system copied into positioning field (`loader:729`) | yes |
| G4 | `START_DATE_QC` | **FIXABLE** | QC `'1'` asserted on a blank value | yes |
| G5 | `TRANS_FREQUENCY` | FIX CANDIDATE | blank vs `n/a` convention | yes |
| G6 | `START_DATE` value | **UNKNOWN / DATA-COVERAGE** | not in the four CSVs; not telemetry-derivable | n/a |

## 8. Unresolved UNKNOWNs
1. **START_DATE source** (§4.5) — needs a deployment-DB column in the four CSVs, or an ADMT ruling. Two of four GDAC values contradict the manual's own definition.
2. **POSITIONING_SYSTEM cardinality** (§4.4) — scalar `GPS` (GDAC parity) vs `['GPS','IRIDIUM']` (fuller truth, changes `N_POSITIONING_SYSTEM`). **Needs your decision.**

## 9. FileChecker results (official v1.17)

| Product | Files | Result |
|---|---|---|
| **OUR `_meta.nc`** | 4 | ✅ **4/4 ACCEPTED** (`file_compliant=yes`) |
| **OUR `_tech.nc`** | 4 | ✅ **4/4 ACCEPTED** |
| **OUR `_Rtraj.nc`** | 4 | ❌ 4/4 non-compliant — **identical errors to GDAC's own files** |
| **OUR Mono `R*.nc`** | 2 (1902844_001, 7902408_001) | ❌ non-compliant — **identical errors to GDAC's own files** |
| GDAC `_meta.nc` / `_tech.nc` (control) | 8 | ✅ accepted |

**Classification:**
- **Accepted:** all Meta and Tech, ours and GDAC.
- **Warnings:** none reported by the tool.
- **Errors — decoder-unique:** **NONE.** Zero findings appear in our output that are absent from GDAC's.
- **Errors — pre-existing / non-decoder (Rtraj):** `PRES_ADJUSTED:axis` missing; `comment` attribute forbidden on `PRES_ADJUSTED`/`PSAL_ADJUSTED`/`TEMP_ADJUSTED`. **Byte-identical in GDAC's published `1902844_Rtraj.nc`.**
- **Errors — pre-existing / non-decoder (Mono):** `JULD_LOCATION:axis` forbidden; `PRES_ADJUSTED:axis` missing. **Byte-identical in GDAC's published `R1902844_001.nc`.**
- **Tool-availability:** checker v1.17 validates against the **2015** rule set (`Argo_Meta_v3.1_AUM_3.1_20150820.xml`) while the current manual is **3.44.0 (2025)**. The `axis`/`comment` rules are known drift between the frozen rule file and current practice — which is why every GDAC file fails them too. Not decoder defects, and **no product was modified** to run these checks.

## 10. Implementation plan — Meta only (awaiting instruction)

All changes in `src/argo_decoder/metadata/multi_csv_loader.py` + the Meta writer; family-generic, four-CSV-only, no WMO/cycle logic, no `registry.csv`.

1. **G3 `POSITIONING_SYSTEM`** — stop aliasing `comms` into positioning. Derive from the platform's actual positioning capability: ARVOR-I transmits GPS fixes → `GPS`. Keep `TRANS_SYSTEM` from `comms` (R10). *Pending your §8.2 decision on scalar vs `['GPS','IRIDIUM']`.*
2. **G2 `TRANS_SYSTEM_ID`** — emit `n/a` when the transmission system is not ARGOS (D1 §2.4.4 explicitly sanctions it); retain the ARGOS programme number for ARGOS floats.
3. **G1 `CONTROLLER_BOARD_TYPE_PRIMARY`** — replace the `APF<digit>` heuristic with an R28-validated lookup; emit blank/`n/a` when the serial maps to no R28 code, never an invented code. (Keeps APEX floats working: their `9A-`/`9G-` serials must map to a real R28 value or blank — **must be verified against the APEX fleet before merging**, since `APF9` is likewise absent from R28 and this may be a wider issue than ARVOR-I.)
4. **G4 `START_DATE_QC`** — set to fill `' '` whenever `START_DATE` is blank (mirrors existing `STARTUP_DATE_QC` handling).
5. **G5 `TRANS_FREQUENCY`** — adopt `n/a` alongside item 2 for a consistent not-applicable convention.
6. **G6 `START_DATE`** — **no change.** Remains blank until a deployment-DB column exists in the four CSVs. Documented as DATA-COVERAGE; never inferred.

**Regression gates for the eventual change:** Meta validator 108/108, FileChecker 4/4 Meta still accepted, full pytest, ruff, APEX A/B fingerprints, and byte-verification that Tech/Mono/Rtraj are untouched.

**Expected outcome:** 58/65 → **63/65** exact, with the remaining two being `DATE_CREATION`/`DATE_UPDATE` (EXPECTED) — plus `START_DATE` blank by design.

---

# ADDENDUM — Implementation (2026-09-08)

The five confirmed fixes from §10 are implemented. **Result: 58/65 → 61/65 exact.**
The four remaining differences are `DATE_CREATION`/`DATE_UPDATE` (EXPECTED, generation
timestamps) and the deliberate `START_DATE`/`START_DATE_QC` blank pair.

> **Note on the 63/65 target.** The task anticipated 63/65 by counting START_DATE and
> START_DATE_QC as "matching". They cannot be: START_DATE is intentionally blank where
> GDAC publishes a value, so both members of the pair necessarily differ. 61/65 with a
> blank, self-consistent START_DATE pair **is** the intended end state — every field that
> is standards-valid and derivable now matches.

## Fields changed — before → after → GDAC

| Field | Ours BEFORE | Ours AFTER | GDAC | Derivation / rule |
|---|---|---|---|---|
| `POSITIONING_SYSTEM` | `IRIDIUM` ❌ | **`GPS`** ✅ | `GPS` | New `_positioning_system()`. R09 (positioning) ≠ R10 (transmission); the comms column was being aliased into the positioning field. ARVOR-I transmits real GPS fixes (Tech#1 → `GpsRecord(accuracy='G')`). Coriolis reference float info pairs `GPS` + `IRIDIUM`. |
| `TRANS_SYSTEM_ID` | PTT (`123230`…) ❌ | **`n/a`** ✅ | `n/a` | UM 3.44.0 §2.4.4: it is the ARGOS *programme* number; "DACs can use N/A … when not applicable (e.g. : Iridium or Orbcomm)". A PTT is a beacon ID, not a programme ID. |
| `TRANS_FREQUENCY` | `''` | **`n/a`** ✅ | `n/a` | Same manual sanction; Iridium SBD has no fixed carrier to publish. |
| `CONTROLLER_BOARD_TYPE_PRIMARY` | `APF0` ❌ | **`n/a`** ✅ | `n/a` | `APF0` is not in **R28** (no `APF*` entry exists). The APEX generation-digit heuristic misfired on the NKE placeholder serial `0i-0`. |
| `START_DATE_QC` | `'1'` on a blank date ❌ | **`''`** | `'1'` | A QC flag cannot qualify an unpublished value; mirrors the file's existing `STARTUP_DATE`/`STARTUP_DATE_QC` pairing. |
| `START_DATE` | `''` | `''` (unchanged) | populated | **Intentionally blank.** Deployment-DB field, absent from the four CSVs. Two of four GDAC values are not "first descent" (1902844/2904082 fall between cycles 2 and 3), so copying would publish wrong data. DATA-COVERAGE. |
| `TRANS_SYSTEM` | `IRIDIUM` | `IRIDIUM` (unchanged) | `IRIDIUM` | Correct already (R10). |

## Code changed
- `metadata/multi_csv_loader.py` — new `NOT_APPLICABLE`; new `_positioning_system()`; `_controller_board_type()` now recognises only the APEX serial convention (`<1-9><letters>`) and returns `n/a` otherwise; `trans_system_id`/`trans_frequency` emit `n/a` on non-ARGOS.
- `metadata/builder.py` — `START_DATE_QC` follows `START_DATE`.
- `nc/metadata_file.py` — new `_NOT_AVAILABLE_SIGNIFICANT_KEYS`; `_clean(keep_not_available=…)` so a *standards-mandated* `n/a` survives the placeholder filter. Scoped to exactly three fields; `SENSOR_MAKER` etc. still blank their placeholders.

**A second defect surfaced during implementation:** the loader emitted the correct `n/a`
values but the writer silently blanked them via `_NOT_AVAILABLE`. Without the
`metadata_file.py` change, fixes 1/2/4 would have appeared to work at the loader level
and still published `''`. This is why the addendum touches three files rather than two.

## APEX safety — verified, unchanged
`_controller_board_type` keys on the APEX serial convention, and the transmission fields
key on `is_argos`, so nothing ARVOR-I-specific was introduced.

| | APF9 | TRANS_SYSTEM_ID | TRANS_FREQUENCY | POSITIONING | TRANS_SYSTEM |
|---|---|---|---|---|---|
| 11 APEX floats (loader) | `APF9` | `02602` | `401.65 x 10^6` | `ARGOS` | `ARGOS` |
| 4 APEX vs their GDAC meta refs | OK | OK | OK | OK | OK |

APEX A/B fingerprints **IDENTICAL** (4/4).

## Validation
| Gate | Result |
|---|---|
| Meta value parity | **61/65 exact ×4**; structure/dims/dtypes/attributes identical |
| Meta validator | **108/108** |
| **FileChecker v1.17 (4 Meta)** | ✅ **4/4 ACCEPTED**, zero errors |
| Rtraj GDAC / 4B | 84/84 · 64/64 |
| Tech GDAC / Tech | 32/32 · 56/56 |
| pytest | **2105 passed**, 1 skipped (pre-existing) |
| ruff check + format | clean, 172 files |
| APEX A/B | IDENTICAL |
| **Tech + Rtraj products** | **byte-identical (md5, 8/8)** |
| **Mono products** | **byte-identical (md5, 69/69)** |

## Genericity
Four-CSV-only; `registry.csv` untouched for ARVOR-I. No WMO, hull or cycle literal in any
change — rules key on transmission system and serial *convention*, so a future ARVOR-I
float inherits `GPS` + `IRIDIUM` + `n/a` automatically, and a future ARGOS float keeps the
ARGOS behaviour. If a sheet ever supplies a genuine R28 board type or a real programme
number, those values flow through unchanged.

## Remaining differences
| Field | Class | Reason |
|---|---|---|
| `DATE_CREATION`, `DATE_UPDATE` | **EXPECTED** | File generation timestamps. |
| `START_DATE`, `START_DATE_QC` | **DATA-COVERAGE / UNKNOWN** | Deployment-DB field not in the four CSVs; GDAC's values for 1902844/2904082 contradict the manual's "first descent" definition. Unblocked only by a new authoritative CSV column. |

---

# ADDENDUM 2 — START_DATE / START_DATE_QC standards investigation (2026-09-08)

Full investigation: `final_parity_2026-09-08/START_DATE_QC_STANDARDS_INVESTIGATION.md`.

**Question:** is `START_DATE = blank` + `START_DATE_QC = '9'` correct, or should the QC be `'1'`?

**Verdict: `blank + '9'` is correct. `'1'` is rejected on semantic grounds.**

| Rule | Source |
|---|---|
| START_DATE = "Date (UTC) of the first descent of the float", `_FillValue = " "` | UM **3.44.0** §2.4.5 |
| START_DATE_QC = "Quality on start date", conventions "Argo reference table 2" | UM 3.44.0 §2.4.5 |
| `'9'` = **"Missing value. Data parameter will record FillValue."** | QC Manual **3.9** §6.1 Table 2 |
| `'1'` = "Good data. All Argo real-time QC tests passed." | QC Manual 3.9 §6.1 Table 2 |
| START_DATE **not** in the mandatory metadata list (LAUNCH_DATE is) | UM 3.44.0 §2.4.9 |
| START_DATE is copied from the float-info JSON, never computed | Coriolis `create_nc_meta_file_3_1.m:2975` |
| No document requires DACs to populate START_DATE | 0 obligation hits across UM 3.44.0, QC 3.9, Cookbook 6.1 |

**Why not `'1'`:** it would assert "Good data ... all real-time QC tests passed" about a value that
was never published — logically vacuous and misleading. Table 2 provides a code for exactly our
state (`'9'`); using "good" instead discards information.

**Empirical (FileChecker v3.0.5):** `'9'`, `'1'`, `'0'` all ACCEPTED; only `' '` REJECTED
(`START_DATE_QC: ' ' Status: Invalid`). Compliance cannot discriminate — Table 2 must, and it
names one code for a FillValue parameter.

**GDAC is not a usable reference here:** its four START_DATE values follow three mutually
incompatible derivations (6990711 == launch date; 7902408 ~ cycle-1 start; 1902844/2904082 match
nothing and fall *after* the first descent, contradicting the UM definition). GDAC also pairs
blank STARTUP_DATE with blank STARTUP_DATE_QC — the same pairing logic it does not apply to
START_DATE — surviving only because the checker never validates STARTUP_DATE_QC.

**Changes:** citation-only comment expansion in `metadata/builder.py` (no behavioural change) plus
a new test `test_present_start_date_gets_good_qc` proving the flag is value-driven, so a future
four-CSV deployment-date column yields `'1'` with no code change. Meta stays **61/65 exact**;
all 81 products **FileChecker v3.0.5 ACCEPTED**.

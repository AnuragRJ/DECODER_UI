# Decoder assumption audit — GDAC-parity reasoning

**Audit date:** 2026-08-14
**Revision 2** — reclassified after the project-goal clarification of
2026-08-14. Revision 1's Finding 1 recommendation was **wrong** and has
been withdrawn; see "Withdrawn recommendations" at the end.
**Phase:** 1 — investigation only. **No code was modified.**

**Revision 3 addendum (2026-08-17)** — this audit is a snapshot of
2026-08-14 (pre-Part A). Two statements in it are superseded; the body
is preserved as a historical record:

- The section-B entry "`_ABP_VERIFIED_DECODERS` gating" ("Withholds
  `PRESSURE_AirBladder_COUNT` on firmware 091x15 because it cannot be
  reproduced honestly") is **superseded**: Part A now reads ABP and VAC
  from Message-3 payload bytes 1 and 0 on decoder 1010
  (`_ABP_MSG3_DECODERS`, `_VACUUM_SOURCE_ATTRS` in `nc/technical.py`,
  `msg3_vacuum_offset` in `engineering.py`) and emits both parameters;
  1010 `_tech.nc` now carries 14/14 GDAC names.
- The 1010 `PRESSURE_InternalVacuum_inHg` discrepancy is **resolved and
  closed**: classified **NOT FIXABLE / approved GDAC-side divergence**.
  GDAC's `-28.009` equals the conversion of 6 counts; count 6 never
  occurs at the Message-3 VAC byte in 649 scanned copies across six 1010
  floats (CRC-valid and invalid); GDAC's own non-frozen values match our
  decode exactly. Origin established as GDAC-side / non-telemetry-
  derived; exact INCOIS mechanism unknown. Do not fabricate count 6.
  Full record: `docs/VACUUM_1010_REANALYSIS.md`.

**Baseline verified at audit time:** 1726 tests pass; `ruff` clean;
`mypy --strict` clean on 72 sources; 10/10 `_meta.nc` FileChecker
`FILE-ACCEPTED`.

---

## Project objective governing this audit

**GDAC INCOIS parity is a hard output requirement**, not a comparison
convenience. Parameter set, parameter count, ordering, structure, metadata
representation and values must match GDAC — including
`_meta.nc`, `_tech.nc`, `_Rtraj.nc` and the mono/multi-profile files.

Authority hierarchy for deciding *what is correct*:

```
1. Coriolis MATLAB decoder      (primary implementation reference)
2. Argo / instrument specs      (scientific + format authority)
3. INCOIS GDAC files            (parity target for the output)
```

**Default: make Python match GDAC.** Diverge only with strong evidence
that GDAC is demonstrably wrong, and record it as an approved divergence.

Every difference is classified:

- **A** Python bug → make Python match GDAC
- **B** GDAC representation difference → match GDAC if that is the
  required output representation
- **C** Proven GDAC error → document evidence, diverge intentionally
- **D** Insufficient evidence → **do not change yet**

---

## Scope inspected

`src/argo_decoder/` — 19,150 LOC across `metadata/` (8 files),
`platforms/` (14), `nc/` (8), `rtqc/` (7), plus `cli/`, `config/`,
`derived/`, `domain/`, `io/`, `pipeline/`, `sensors/`, `trajectory/`,
`util/`.

Searched for `*_CANONICAL` dicts, `DEFAULT_*`, `.get(x, <literal>)`,
`or "<literal>"`, hardcoded maker/model/sensor/parameter substitutions,
fallbacks, inferred metadata, WMO-specific branches, hardcoded QC and
`DATA_MODE`, timestamp assumptions, config defaults, and parity phrases
in comments.

---

## Summary

| # | Finding | Class | Severity | Action |
|---|---|---|---|---|
| 1 | `_tech.nc` publishes 14 of 32 derived params | **NOT A BUG** | — | **No change.** Already exact parity |
| 2 | `BATTERY_TYPE = "Alkaline"` vs sheet `4DD LI` | **D** | P2 | Investigate; do not change yet |
| 3 | 4 battery tech names differ from Coriolis 1005 | **D** | P2 | Blocked on APF9A manual |
| 4 | `PARAMETER_UNITS` ≠ reference table 3 | **B** | P3 | **No change.** GDAC representation |
| 5 | `INCOIS_DEFAULTS` bypasses `float "owner"` column | F | P4 | Optional robustness only |
| 6 | PROVOR `data_mode = "A"`, no adjustment applied | **D** | P2 | Non-INCOIS platform; needs a decode |
| 7 | `_RT_CALIB_DEFAULTS`, `INCOIS_DEFAULT_ACCURACY`, `ARGOS_TRANS_*` | F | P4 | No change |
| 8 | `PLATFORM_MAKER_CANONICAL`, `CTD mfg`→`SBE`, board type | F | P4 | No change |
| 9 | GROUNDED margin, RTQC thresholds, calib equations | C/D-confirmed | — | No change |

**Zero WMO-specific executable branches** exist in `src/` — every
`29xxxxx` match is a comment. Coriolis itself has
`if (floatNum == 3901639)` at `rename_argos_input_file.m:701`, so we are
cleaner than the reference here.

**No verified decoder bug was found in this audit.** Findings 2, 3 and 6
are class **D** — insufficient evidence — and must not be actioned yet.

---

# FINDING 1 — `_tech.nc` parameter restriction · **NOT A BUG**

**`nc/technical.py:217-253` · no change required**

## Revision 1 was wrong

Revision 1 called this a P1 decoder bug and proposed emitting 16–32
parameters, moving the 14-name restriction "into the comparison harness."
**That recommendation is withdrawn.** It would have broken a hard parity
requirement — turning a compliant product into a non-compliant one.

## What the evidence actually shows

Measured this session on WMO 2901304:

```
ours  rows 322   distinct 14
gdac  rows 322   distinct 14
same distinct set : True
IDENTICAL SEQUENCE: True
```

**`_tech.nc` is already at exact parameter, count and ordering parity.**
All 7 INCOIS reference floats publish exactly 14 distinct names
(2901304/05/28/39/50, 2902201, 2902222). The writer is doing precisely
what the project requires.

## Why 32 derived vs 14 published — answered

This is the question Revision 1 failed to ask. The answer is *not* that
GDAC is missing parameters:

| set | count | note |
|---|---|---|
| Our derived (`TECH_PARAMETER_ORDER`) | 32 | superset, internal |
| Coriolis decoder-1005 allow-list | 38 | `_tech_param_name_1005.json` |
| **GDAC INCOIS published** | **14** | consistent on 7/7 floats |
| In GDAC but **absent from Coriolis 1005** | **9** | see below |

The 9 GDAC names that Coriolis's 1005 list does **not** contain:

```
CURRENT_BatteryPark_mA              POSITION_PistonPark_COUNT
CURRENT_BatterySBEPump_mA           PRESSURE_InternalVacuum_inHg
FLAG_ProfileTermination_hex         TIME_PumpMotor_seconds
VOLTAGE_BatteryInitialAtProfileDepth_volts
VOLTAGE_BatteryParkNoLoad_volts     VOLTAGE_BatterySBEAscent_volts
```

This is decisive: **INCOIS did not produce these files with the Coriolis
decoder.** Their published vocabulary overlaps Coriolis's but is not a
subset of it. So "Coriolis exposes 38, therefore we should publish more
than 14" does not follow — the two DACs run different processing chains,
and our parity target is INCOIS.

Of the 18 we withhold, 17 appear in Coriolis's 1005 list and 1
(`FLAG_TelonicsPTTStatus_hex`) does not. They remain **derived and
available** via `DERIVED_NOT_PUBLISHED_TECH_PARAMETERS` and
`technical_records_for_cycle`, so nothing decoded is lost — only the
emission is scoped to the INCOIS vocabulary, which is correct.

## Correct reading of the code comment

The docstring's *"the goal is to match the GDAC reference… doubles the row
count (641 against 322)"* is **not** a parity-for-convenience smell. It is
an accurate statement of a hard product requirement. Revision 1
misread it.

The only defensible criticism is **wording**: it justifies the rule by
"row-wise comparison" rather than "the published product must carry the
INCOIS parameter set." Optional P4 docstring clarification; no behaviour
change.

---

# FINDING 2 — `BATTERY_TYPE = "Alkaline"` · **class D, do not change yet**

**`metadata/multi_csv_loader.py:114` · P2**

## The apparent contradiction

```python
DEFAULT_BATTERY_TYPE = "Alkaline"  # unconditional
```

The sheet distinguishes two chemistries:

| sheet `battery config` | implies | floats |
|---|---|---|
| `3D Alk + 1C Alk` | alkaline | 2901304 and others |
| `4DD LI` | **lithium** | 2902222, 2902223 |

Verified output for 2902222:

```
ours  BATTERY_TYPE='Alkaline'  BATTERY_PACKS='4DD LI'
gdac  BATTERY_TYPE='Alkaline'  BATTERY_PACKS='4DD LI'
```

We match GDAC exactly. The question is whether GDAC is wrong.

## What Coriolis does — SOURCE CONFIRMED

`generate_json_float_meta_apx_argos_.m:54` lists `BATTERY_TYPE` in
`mandatoryList1`, and line 1000 maps it **verbatim** from the operator
database field of the same name. Coriolis **derives nothing** — it copies
what the DAC's database says.

`update_meta_data.m:336-346` sets a default only when the field is
**empty** *and* the decoder is **NKE** (`SAFT Lithium 11 V` / `14.5 V`).
Never for APEX; never overwriting a populated value.

**Implication:** under Coriolis semantics `BATTERY_TYPE` is an
operator-declared fact, not a derived one. Deriving it from the pack
string — as Revision 1 proposed — has **no Coriolis basis**.

## What the specification requires — SOURCE CONFIRMED

FileChecker `CK_0147`/`CK_0148`/`CK_0150` parse `BATTERY_TYPE` as:

```java
pBatteryType = "\\s*(?<manufacturer>\\w+)\\s+(?<type>\\w+)\\s+(?<volts>\\d+\\.?\\d*)\\s+V\\s*"
```

- `manufacturer` → **R33** = `ELECTROCHEM` / `TADIRAN` / `SAFT`
- `type` → **R34** = **`Alk` / `Li` / `Hyb`**

So the required form is e.g. `SAFT Li 11 V`. Our `Alkaline`:

1. does not match the template at all (`CK_0147`), and
2. is not an R34 code even as a bare type — R34 says `Alk`, not `Alkaline`.

**GDAC's value is non-conformant to the current controlled vocabulary.**

Today `CK_0147`/`CK_0148`/`CK_0150` are all **warnings** with
`addError` commented out and marked *"WILL BECOME AN ERROR"*. Our file is
currently `FILE-ACCEPTED` with zero warnings on the 2.9.x jar — verified
this session.

## Why class D and not C

I can prove `Alkaline` is not the R34 spelling. I **cannot** yet produce
the correct value, because the template needs **manufacturer** and
**voltage**, and the sheets supply neither. `4DD LI` gives chemistry and
pack geometry only.

Emitting `Li` alone would still fail `CK_0147`. Inventing `SAFT` or a
voltage would fabricate provenance — forbidden.

There is also a real semantic question I have not resolved:
`BATTERY_PACKS = '4DD LI'` describes the *packs*; whether the INCOIS
`BATTERY_TYPE` for that hull is genuinely lithium, or whether the float
carries a mixed/alkaline main pack with a lithium sub-pack, is not
determinable from the sheet.

## Recommended action

**Do not change the decoder.** Two things are needed first:

1. **Ask the operator** for `BATTERY_TYPE` in template form
   (`<maker> <Alk|Li|Hyb> <volts> V`) for all floats — this is a
   **source-metadata gap (class B-source)**, and is exactly what Coriolis
   expects the database to provide.
2. **Confirm with INCOIS** whether `Alkaline` is intended on the `4DD LI`
   hulls, or a legacy DB artefact.

If INCOIS corrects the value, parity follows automatically. If they
confirm `Alkaline` is wrong *and* supply the real value, this becomes an
approved class-C divergence — documented, not assumed.

**Risk if left as-is:** when the temporary warnings become errors, every
INCOIS `_meta.nc` will fail `CK_0147`. That is a fleet-wide P0 *for
INCOIS*, not just for us — worth raising with them regardless.

---

# FINDING 3 — battery tech-parameter names · **class D, blocked**

**`nc/technical.py:94-98, 164-173` · P2**

## The discrepancy

We read message-1 payload bytes 18–21 and label them:

| byte | ours (= GDAC) | Coriolis `_tech_param_name_1005.json` |
|---|---|---|
| 18 | `VOLTAGE_BatteryParkNoLoad_volts` | `VOLTAGE_BatteryParkEnd_volts` — *"at end of Park phase"* |
| 19 | `CURRENT_BatteryPark_mA` | `CURRENT_BatteryParkEnd_mA` — *"at end of Park phase"* |
| 20 | `VOLTAGE_BatterySBEAscent_volts` | `VOLTAGE_BatterySBEParkEnd_volts` — *"while SBE41 sampling at end of Park phase"* |
| 21 | `CURRENT_BatterySBEPump_mA` | `CURRENT_BatterySBEParkEnd_mA` — *"while SBE41 sampling at end of Park phase"* |

Our four names appear in **zero** Coriolis files. Both sets are valid R14
entries (`T000532/T000533`, `T000505/T000506`), so there is **no
rejection risk** either way.

The semantic gap is real: *no-load* vs *end of park*, and
*ascent/pump* vs *park end*.

## Why this is class D, not a bug

Under the corrected framework this is the textbook case for *"do not
change merely because something appears more correct."*

- **GDAC publishes our names** — parity currently holds.
- **Coriolis is the implementation reference** and disagrees.
- **The instrument documentation would settle it — and is unavailable.**

The APF9A user manuals in
`Coriolis-…-container/decArgo_doc/float_user_manuals/APEX_floats/Argos/`
are **Git LFS pointer stubs**, not PDFs (`head -c 20` →
`version https://git-lfs.github.com/spec/v1`). `apf9_docs/` contains only
the Coriolis decoder manual and a spreadsheet; the APF9 firmware manuals
its README advertises are absent. The code cites "D4 p.23" for the
conversion constants, so the manual existed at some point.

**UNKNOWN — INSUFFICIENT EVIDENCE** on which physical instant bytes 18–21
sample.

## Recommended action

**No change.** Renaming would break parity on a field where GDAC may well
be right, on the strength of a naming convention alone.

**Blocker to clear:** obtain the real APF9A firmware manual (message-1
field table + D4 p.23). If it confirms Coriolis, this becomes a
documented class-C divergence decision to be taken explicitly — weighing
scientific correctness against parity, with INCOIS consulted.

---

# FINDING 4 — `PARAMETER_UNITS` ≠ reference table 3 · **class B, no change**

**`metadata/builder.py:118-124` · P3**

| | ours (= GDAC) | reference table 3 |
|---|---|---|
| PRES | `decibars` | `decibar` |
| TEMP | `deg C` | `degree_Celsius` |
| PSAL | `Siemens/meter` | `psu` |

Both of the code comment's factual claims verified this session:

- Table 3 (`argo-physical_params-spec-v3.1`) does specify
  `decibar` / `degree_Celsius` / `psu`.
- `CK_0130` (`ArgoMetadataFileValidator.java:923-931`) checks **only**
  `str.length() <= 0`. No table lookup, no rejection risk.

`PARAMETER_UNITS` is defined in the CDL as *"Units of accuracy and
resolution of the parameter"* — descriptive text, not a controlled field.

**Class B: a GDAC representation difference we must reproduce.** Changing
to table-3 units would break parity on 3 cells per float for no
conformance gain. **No change.**

Only the comment's phrasing (*"because the goal is INCOIS GDAC parity"*)
is worth revisiting — under the clarified objective that reasoning is
now correct as stated, so even the wording stands.

*(`PSAL` in `Siemens/meter` remains odd — practical salinity is
dimensionless. Worth mentioning to INCOIS as an observation; not our
divergence to make.)*

---

# FINDING 5 — `INCOIS_DEFAULTS` bypasses an existing sheet column

**`metadata/multi_csv_loader.py:102-108` · F · P4**

`meta.csv` **has** a `float "owner"` column containing `Incois`, but
`float_owner` is served from a hardcoded constant. `PI_NAME`,
`PROJECT_NAME`, `OPERATING_INSTITUTION` and `DATA_CENTRE` have no sheet
column, so those are legitimately configuration.

Output is correct and matches GDAC (`FLOAT_OWNER = INCOIS`). This is a
**robustness** point only: if a future float is co-owned or transferred,
the sheet would say so and we would not notice.

**Optional fix**, no output change today: read `float "owner"` when
present, fall back to the default.

---

# FINDING 6 — PROVOR `data_mode = "A"` · **class D**

**`platforms/provor_ir_sbd/profile.py:63` · P2**

`ProfileMeta.data_mode` defaults to `"A"` (adjusted) and is written
straight to `DATA_MODE` (`provor_ir_sbd/decoder.py:348`). It is never
overridden — `ProfileMeta(cycle_number=…)` is the only construction site.
APEX uses `"R"` and documents why.

`grep ADJUSTED` in the PROVOR decoder returns nothing. UM §2.2.5 requires
a `DATA_MODE='A'` profile to carry adjusted values.

**Class D.** PROVOR is not an INCOIS APEX product, has no GDAC parity
target in this project, and I did not decode a PROVOR file this session.
Needs a real decode before classification. Flagged so it is not
inherited as an assumption by future platforms.

---

# B. CORRECT EXISTING BEHAVIOUR — suspicious but justified

| Item | Why correct |
|---|---|
| **`_tech.nc` 14-parameter restriction** | Exact GDAC parity: 322 rows, identical sequence. **Required.** |
| **`GROUNDED_PRESSURE_MARGIN_DBAR = 100.0`** | Cookbook v6.1 §2.5 + Annex D §5.2 sanction the performance route and leave the margin to the DAC. 100 dbar measured, not assumed — error curve asymmetric about it (87@75, 78@100, 127@101, 165@150). Reproduces 2305/2315 published flags. |
| **`PARAMETER_UNITS` house style** | GDAC representation; field is descriptive; `CK_0130` checks non-empty only. |
| **`PLATFORM_MAKER_CANONICAL {"WEBB": "WRC"}`** | `WRC` is valid R24; sheet spells it `webb`. Formatting normalisation, no semantic change. |
| **`CTD mfg` → `SBE`** | Sheet says `SeaBird`; `SBE` is the R26 code and R27 binds `SBE41 → SBE`. |
| **`SBE41_CALIB_EQUATIONS`** | Sensor-model property, byte-identical across 11 floats (md5 verified); coefficients stay per-float. |
| **`_controller_board_type()`** | Derives `APF9` from the serial's leading digit; returns `""` rather than guessing. |
| **RTQC `cross_cycle` / `density_inversion`** | GDAC cited as corroboration for a reasoned fix (a test may only flag what it measured; a truncated dive must not be compared against a deeper one). Reasoning stands independently. |
| **`INCOIS_DEFAULT_ACCURACY`** | Sheet columns read first; default applies only when absent. |
| **`ARGOS_TRANS_SYSTEM_ID = "02602"`** | Argos *programme* number, not PTT; a genuine constant absent from the sheets. |
| **`_RT_CALIB_DEFAULTS`** | Lowest precedence; decoder values and `CALIB_RT_*` override. TEMP absent because no RT correction applies. |
| **`_ABP_VERIFIED_DECODERS` gating** | Withholds `PRESSURE_AirBladder_COUNT` on firmware 091x15 because it cannot be reproduced honestly. Correct restraint. |
| **Zero WMO-specific branches** | Confirmed; better than Coriolis. |

---

# C. APPROVED DIVERGENCES FROM GDAC (evidence-backed)

Only **one** currently stands, from the previous investigation:

| Field | GDAC | Ours | Evidence |
|---|---|---|---|
| `SENSOR_MAKER` on `CTD_PRES` | `SBE` | `DRUCK` / `KISTLER` | R27 SKOS `broader` binds model→maker; FileChecker `CK_0164` **rejects** GDAC's value on all 10 INCOIS floats; Coriolis `generate_prof_files_from_navis_csv_files.m:557` requires `DRUCK`/`KISTLER`; AOML/Coriolis/CSIRO/JMA all publish the transducer maker. Full record: `docs/SENSOR_MAKER_FILECHECKER_INVESTIGATION.md` |

This is the standard any future divergence must meet: source + Coriolis +
specification + an independent tool all agreeing against GDAC.

**Candidate divergences NOT approved:** Findings 2, 3 and 6 — all class
**D**, evidence incomplete.

---

# D. UNRESOLVED — insufficient evidence

| Question | Needed | Blocks |
|---|---|---|
| Do bytes 18–21 sample park-end or ascent/pump? | **APF9A firmware manual** — in-repo copies are LFS stubs | Finding 3 |
| Correct `BATTERY_TYPE` in `<maker> <Alk\|Li\|Hyb> <volts> V` form | Operator/INCOIS input — sheets carry no maker or voltage | Finding 2 |
| Is `Alkaline` intended on `4DD LI` hulls? | INCOIS confirmation | Finding 2 |
| Does PROVOR populate `*_ADJUSTED`? | A real PROVOR SBD decode | Finding 6 |

---

# Withdrawn recommendations (Revision 1 errors)

Recorded so the mistake is not repeated.

| Withdrawn | Why it was wrong |
|---|---|
| *"Emit 16 of the 18 withheld tech parameters"* | Would break `_tech.nc` parameter-count and ordering parity, which is a hard requirement. Output is already correct. |
| *"Move the 14-name restriction into the comparison harness"* | Treated parity as a test convenience. Parity belongs in the **product**; filtering at compare time is explicitly disallowed. |
| *"Finding 1 is a P1 decoder bug"* | It is **NOT A BUG**. Verified: 322 rows, identical sequence to GDAC. |
| *"Derive `BATTERY_TYPE` from the pack string"* | No Coriolis basis — Coriolis copies it verbatim from the operator DB and derives nothing. Would also still fail `CK_0147`. |
| *"Preserve valid telemetry even when GDAC has fill" as a blanket rule* | Applies to **values within the agreed parameter set**, not to adding parameters GDAC does not publish. |

---

## Architectural verdict

**The decoder is on the correct footing: it reproduces the INCOIS GDAC
product while sourcing its decoding decisions from Coriolis and the Argo
specifications.**

Re-examined under the clarified objective, the "GDAC-parity seam" that
Revision 1 flagged as a defect is largely the product requirement working
as intended. `_tech.nc` is at exact parity; `PARAMETER_UNITS` is a
required representation; the `_meta.nc` fleet is `FILE-ACCEPTED` 10/10.

The genuinely useful output of this audit is narrower than Revision 1
claimed but more actionable:

1. **One real conformance risk** — `BATTERY_TYPE` will fail `CK_0147`
   fleet-wide when the temporary warnings become errors. This affects
   INCOIS's own files, so it is worth raising with them rather than
   patching around locally.
2. **One documented open question** — the battery tech-parameter naming,
   blocked on instrument documentation that must come from outside the
   workspace.
3. **A validated inventory** of every hardcoded mapping, with its
   Coriolis and specification basis recorded, so future review does not
   have to re-derive it.

The `DRUCK → SBE` bug remains the only proven case where GDAC was wrong
and we were copying it — and the test that caught it (source + Coriolis +
specification + tool all agreeing against GDAC) is the right bar for any
future divergence.

---

## Phase 2 readiness

**No verified decoder bug requires fixing.** Recommended next steps are
**data and documentation requests**, not code:

1. Ask the operator for template-form `BATTERY_TYPE` (and raise the
   `CK_0147` risk with INCOIS).
2. Obtain the APF9A firmware manual to close Finding 3.
3. Optional P4: read the `float "owner"` column; clarify the
   `_tech.nc` docstring to cite the parity requirement rather than
   "row-wise comparison".

Nothing in this audit has been implemented.

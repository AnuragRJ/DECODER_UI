# `SENSOR_MODEL/SENSOR_MAKER[3]: Inconsistent: 'DRUCK'/'SBE'`

Investigation and fix for the GDAC FileChecker rejection of
`2901304_meta.nc`.

**Verdict: our decoder bug (class A, P1). Fixed. All 10 floats now
`FILE-ACCEPTED`.**

---

## 1. What `SENSOR_MODEL[3]` / `SENSOR_MAKER[3]` actually represent

The index is **1-based**, proven rather than assumed: corrupting
`SENSOR_MAKER` row 0 (0-based) makes the checker report `[1]`, and both
errors then appear together.

`N_SENSOR = 3`, so `[3]` is the last row — `CTD_PRES`, the Druck
strain-gauge pressure transducer inside the Sea-Bird SBE41 CTD.

Complete sensor-to-parameter mapping, our output **after** the fix:

| idx | SENSOR | MAKER | MODEL | SERIAL | PARAMETER | PARAMETER_SENSOR | UNITS | coherent |
|---|---|---|---|---|---|---|---|---|
| 1 | `CTD_TEMP` | `SBE` | `SBE41` | 5234 | `TEMP` | `CTD_TEMP` | deg C | yes |
| 2 | `CTD_CNDC` | `SBE` | `SBE41` | 5234 | `PSAL` | `CTD_CNDC` | Siemens/meter | yes |
| 3 | `CTD_PRES` | `DRUCK` | `DRUCK` | 3174705 | `PRES` | `CTD_PRES` | decibars | yes |

Before the fix, row 3 read `SBE`/`DRUCK`.

**There is no row-shift or alignment bug.** Rows 1 and 2 were already
physically coherent, `PARAMETER_SENSOR[i] == SENSOR[i]` on every row, and
the pressure serial (3174705) sits on the pressure row while the CTD
serial (5234) sits on both CTD rows. Checked on all 10 floats: **0
incoherent rows** after the fix, and the only defect before it was the
maker on `CTD_PRES`.

## 2. Where the values came from

| stage | value |
|---|---|
| `sensor-info.csv`, `Pressure sensor mfg` | `DRUCK` ✅ correct |
| `multi_csv_loader.SENSOR_MAKER_CANONICAL` | **`{"DRUCK": "SBE"}`** ❌ the bug |
| `_sensors_from_rows()` | `make=SBE`, `model=DRUCK` |
| `builder._sensor_vectors()` | pass-through |
| `nc/metadata_file.py` | pass-through |

The **source metadata is correct**. A single lookup entry at
`multi_csv_loader.py:131` rewrote the transducer's manufacturer to the
CTD integrator's. Its original comment justified this as *"published as
`SBE` on 11/11 sampled floats"* — GDAC-parity reasoning on a field where
GDAC is wrong.

`SENSOR_MODEL` was never wrong: `DRUCK` is a valid R27 model code.

## 3. What Coriolis does

Coriolis **agrees with the fix**.
`generate_prof_files_from_navis_csv_files.m:557` validates `CTD_PRES` and
errors unless `sensorInfo{idS,2}` — column 2 is `SENSOR_MAKER`, per the
assignment at lines 481-484 — is `DRUCK` or `KISTLER`:

```matlab
if (~strcmp(sensorInfo{idS, 2}, 'DRUCK') && ~strcmp(sensorInfo{idS, 2}, 'KISTLER'))
   fprintf('ERROR: ''DRUCK'' expected\n');
```

The adjacent `CTD_TEMP` block requires `SBE` for the same column, so
Coriolis explicitly models the transducer and the CTD module as
different manufacturers. Its APEX/APF9 JSON templates emit no `DRUCK`
model at all, so they neither support nor contradict the pairing.

## 4. What the Argo reference tables require

`SENSOR_MAKER` (table 26) names the firm that **built the sensor**, not
the firm that integrated it. Table 27 binds each model to exactly one
maker through SKOS `broader`:

| R27 `SENSOR_MODEL` | `skos:broader` → R26 `SENSOR_MAKER` |
|---|---|
| `DRUCK`, `DRUCK_2900PSIA`, `DRUCK_10153PSIA` | `DRUCK` |
| `KISTLER`, `KISTLER_2900PSIA` | `KISTLER` |
| `SBE41`, `SBE41CP`, `SBE` | `SBE` |
| `PAINE_*` / `AMETEK*` / `RBR_PRES` | `PAINE` / `AMETEK` / `RBR` |

**`SENSOR_MODEL = DRUCK` with `SENSOR_MAKER = SBE` is never valid.**

Both tokens are individually legal — `R26::DRUCK` = "Druck Inc.",
`R27::DRUCK` = "Druck pressure sensor with unknown pressure rating" —
which is precisely why only the cross-reference detects the error.

## 5. Why the historical GDAC file also fails

**Answer A — a historical INCOIS metadata error.** Not a legacy
convention, not a checker regression, not a false positive.

Contemporary floats from other DACs publish the transducer's own maker:

| float | DAC | platform | `CTD_PRES` maker/model |
|---|---|---|---|
| 6901234 | coriolis | APEX | `DRUCK`/`DRUCK_2900PSIA` |
| 5904471 | aoml | APEX | `DRUCK`/`DRUCK_2900PSIA` |
| 5905190 | csiro | NAVIS_EBR | `DRUCK`/`DRUCK` |
| 2903328 | jma | APEX | `KISTLER`/`KISTLER` |
| **2901304** | **incois** | APEX | **`SBE`/`DRUCK`** |

All 10 INCOIS floats carry the defect; 2901350 as `'KISTLER'/'SBE'`. It
is a systematic DAC-level error in files dated 2016, predating the
cross-reference check.

## 6. The FileChecker rule, and the 2.9.4 vs 3.0.5 question

Obtained and ran the real tool (`OneArgo/ArgoFormatChecker`). The user's
caution was well placed — **the mechanism did change between versions**,
even though the message is identical:

| | v2.9.4 | v3.0.5 |
|---|---|---|
| check id | `SENSOR_MODELxSENSOR_MAKER` | `CK_0164` |
| rule source | local `spec/ref_table-27` (col 1 vs col 2) | `NVS/R27.jsonld` `skos:broader` |
| implementation | `ArgoReferenceTable.SENSOR_MODELxSENSOR_MAKER.xrefContains(mdl, mkr)` | `sensorModelTableEntry.checkBroaderReference(makerId)` |
| verdict on `DRUCK`/`SBE` | **rejected** (`ref_table-27:99` = `DRUCK \| DRUCK`) | **rejected** (`R27::DRUCK broader R26::DRUCK`) |

v3.0.0 deleted **every** local `ref_table-*` file and switched to NVS
vocabulary snapshots — a real change in rule provenance. But for this
pair the two encode the same constraint, so the outcome is identical.
There is no version-specific behaviour to exploit and nothing to wait
for.

v3.0.5 source, `ArgoMetadataFileValidator.java:1032`:

```java
if (!sensorModelTableEntry.checkBroaderReference(sensorMakerTableEntry.getId())) {
    validationResult.addError(sensorModelName + "/" + sensorMakerName
        + "[" + (n + 1) + "]: " + "Inconsistent: '" + snsrModel + "'/'" + snsrMaker + "'");
```

The `(n + 1)` confirms the 1-based index independently.

Reproduced locally with `ValidateSubmit.jar` (FileChecker `-r1324`, spec
`-r1181`):

- historical INCOIS 2016 `2901304_meta.nc` → `FILE-REJECTED`, identical message
- **all 10** INCOIS reference `_meta.nc` → `FILE-REJECTED` on `[3]`
- our pre-fix output → `FILE-REJECTED`, identical message

## 7. The fix

`src/argo_decoder/metadata/multi_csv_loader.py` — stop rewriting the
maker; pass the sheet's manufacturer through.

```python
SENSOR_MAKER_CANONICAL = {
    "SEABIRD": "SBE",
    "SBE": "SBE",
    "DRUCK": "DRUCK",
    "KISTLER": "KISTLER",
}
...
pres_model = pres_maker_raw.upper() if pres_maker_raw else ""
pres_maker = SENSOR_MAKER_CANONICAL.get(pres_model, pres_model)
```

`.upper()` is load-bearing (mutation-tested) so a sheet spelling "Druck"
still emits the valid code. An unrecognised transducer is now passed
through rather than relabelled `SBE`, so the checker reports it instead
of us hiding it behind a plausible but wrong manufacturer.

No metadata edited, no value overridden, no reference value hardcoded.
The 4-CSV source needs **no** correction for this issue.

## 8. Result

| measure | before | after |
|---|---|---|
| `_meta.nc` FileChecker, 10 floats | 10 REJECTED | **10 ACCEPTED** |
| SENSOR errors across all 335 output files | 10 | **0** |
| incoherent sensor rows, fleet | 10 | **0** |
| tests | 1722 | **1726** |

`ruff check` clean · `ruff format` 131 files · `mypy --strict` clean on
72 sources.

**No unrelated output changed.** Full fleet re-decoded and compared
variable-by-variable against a same-run build with the fix reverted: for
all 24 files of 2901304 the only differences are `SENSOR_MAKER` and run
timestamps (`DATE_CREATION`, `DATE_UPDATE`, `SCIENTIFIC_CALIB_DATE`).
TECH, Rtraj and all 20 profiles are otherwise identical; the Part 2
science/QC/trajectory baseline is untouched.

(`END_MISSION_DATE` on 2901304 also changed, blank → `20110922051440`.
That is the newer operator sheet now supplying the column, **not** this
fix — confirmed by regenerating with the fix reverted.)

### Regression tests

4 new tests in `tests/unit/test_multi_csv_loader.py`, each
mutation-proven. Killed mutants: `DRUCK→SBE` (the original bug),
`KISTLER→SBE`, `SEABIRD→DRUCK`, `pres_maker = ctd_maker` (a simulated
row-alignment bug), an `SBE` fallback for unknown makers, and dropping
`.upper()`. One mutant — swapping `make` and `model` on `CTD_PRES` —
**survived and was proven equivalent**: model and maker are the same
token for every transducer in the sheets. A speculative
`PRESSURE_SENSOR_CANONICAL` table introduced to kill it was **reverted**,
since keeping it could only be justified by data we do not have.

`test_every_sensor_row_is_a_physically_coherent_instrument` guards the
whole `N_SENSOR` block for every float, not just the index the checker
happened to report first.

## 9. Other sensor entries

None. All 30 rows across the 10 floats are coherent, and no
`SENSOR`-related error remains anywhere in the 335 generated files.

## Remaining, unrelated

`_prof.nc` for all 10 floats still rejects with `D-mode: HISTORY_* not
set`. Pre-existing, unaffected by this change, separate issue — GDAC's
own `2901304_prof.nc` also fails, differently
(`VERTICAL_SAMPLING_SCHEME Not set`). Not addressed here.

## Corrections to earlier documentation

Two earlier claims were wrong and have been superseded:

- `docs/phase_reports/METADATA_MIGRATION_REPORT.md` accepted the error
  because it was *"produced identically by the official GDAC file"*.
  Matching a rejected file is not a pass.
- `APF9_PARITY_STATE.md` **M4** logged our `KISTLER` on 2901350 as a
  low-priority *metadata problem*. Our value was right; GDAC's was wrong.
  M4 is resolved.
